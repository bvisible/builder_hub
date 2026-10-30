"""Plugin import, publication, moderation, and immutable state changes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import now_datetime

from builder_hub.plugins.github import (
	GitHubClient,
	get_repository_contract,
	validate_repository,
)
from builder_hub.plugins.icons import store_catalog_icon
from builder_hub.plugins.package import ValidatedPackage, validate_package
from builder_hub.plugins.protocol import (
	ProtocolValidationError,
	expected_package_name,
	version_from_tag,
)

TRANSIENT_ERROR_CODES = frozenset(
	{
		"github_not_found",
		"github_rate_limited",
		"github_request_failed",
		"github_response_too_large",
		"invalid_github_response",
		"package_download_failed",
	}
)


@dataclass(frozen=True)
class ValidatedReleaseImport:
	release_data: dict
	asset: dict
	package: ValidatedPackage
	contract: dict


def import_release(
	plugin_name: str,
	version: str,
	*,
	first_release: bool = False,
	client: GitHubClient | None = None,
	repository: dict | None = None,
	contract: dict | None = None,
	release_data: dict | None = None,
):
	"""Idempotently validate and record one exact GitHub release."""
	plugin = frappe.get_doc("Hub Plugin", plugin_name)
	publisher = frappe.get_doc("Hub Publisher", plugin.publisher)
	release = get_or_create_release(plugin.name, version)
	if release.status in {"Published", "Yanked", "Blocked"}:
		return reuse_immutable_release(release, release_data)

	client = client or GitHubClient()
	try:
		validated_import = validate_release_import(
			plugin,
			publisher,
			release,
			version,
			client,
			repository,
			contract,
			release_data,
		)
		return store_validated_release(plugin, release, validated_import, first_release)
	except ProtocolValidationError as error:
		return record_import_failure(release, error)


def validate_release_source(
	client: GitHubClient,
	repository: dict,
	contract: dict,
	plugin_name: str,
	version: str,
	*,
	release_data: dict | None = None,
) -> ValidatedReleaseImport:
	"""Validate one repository release without creating registry records."""
	release_data = release_data or client.get_release(repository, version)
	asset = validate_release(release_data, plugin_name, version)
	package = download_and_validate_package(client, asset, plugin_name, version)
	validate_current_manifest(package, contract)
	return ValidatedReleaseImport(release_data, asset, package, contract)


def import_validated_release(
	plugin_name: str,
	validated_import: ValidatedReleaseImport,
	*,
	first_release: bool = False,
):
	"""Store a release that was validated in the current request."""
	plugin = frappe.get_doc("Hub Plugin", plugin_name)
	release = get_or_create_release(plugin.name, validated_import.package.manifest["version"])
	if release.status in {"Published", "Yanked", "Blocked"}:
		return release
	return store_validated_release(plugin, release, validated_import, first_release)


def reuse_immutable_release(release, release_data: dict | None):
	if release_data:
		asset = validate_release(release_data, release.plugin, release.version)
		assert_unchanged_asset(release, release_data, asset)
	return release


def validate_release_import(
	plugin,
	publisher,
	release,
	version: str,
	client: GitHubClient,
	repository: dict | None,
	contract: dict | None,
	release_data: dict | None,
) -> ValidatedReleaseImport:
	repository = repository or client.get_repository(plugin.github_repository_id)
	validate_repository(repository, publisher.github_account_id)
	if str(repository.get("id")) != str(plugin.github_repository_id):
		raise ProtocolValidationError(
			"repository_mismatch", "GitHub returned a different repository identity."
		)
	contract = contract or get_repository_contract(client, repository, plugin.license)
	validated_import = validate_release_source(
		client,
		repository,
		contract,
		plugin.name,
		version,
		release_data=release_data,
	)
	assert_unchanged_asset(release, validated_import.release_data, validated_import.asset)
	return validated_import


def store_validated_release(plugin, release, validated_import, first_release: bool):
	apply_validated_release(release, validated_import, first_release)
	if validated_import.package.icon_content:
		icon_url = store_catalog_icon(validated_import.package.icon_content)
		if plugin.icon != icon_url:
			plugin.db_set("icon", icon_url, update_modified=False)
	update_listing_from_contract(plugin, validated_import.contract)
	return release.reload()


def download_and_validate_package(
	client: GitHubClient, asset: dict, plugin_name: str, version: str
) -> ValidatedPackage:
	temporary_path = Path(client.download_asset(asset["browser_download_url"]))
	try:
		return validate_package(temporary_path, expected_name=plugin_name, expected_version=version)
	finally:
		temporary_path.unlink(missing_ok=True)


def validate_current_manifest(package: ValidatedPackage, contract: dict) -> None:
	if (
		package.manifest["version"] == contract["manifest"]["version"]
		and package.manifest != contract["manifest"]
	):
		raise ProtocolValidationError(
			"root_manifest_mismatch", "The package manifest does not match the root manifest.json."
		)


def record_import_failure(release, error: ProtocolValidationError):
	transient = error.code in TRANSIENT_ERROR_CODES
	increment_metric(failure_metric(error.code, transient))
	if not release.published_on:
		release.status = "Validating" if transient else "Rejected"
		release.validation_errors = frappe.as_json([error.as_dict()])
		release.save(ignore_permissions=True)
	return release


def failure_metric(error_code: str, transient: bool) -> str:
	if error_code == "github_rate_limited":
		return "github_rate_limits"
	return "check_failures" if transient else "validation_failures"


def approve_first_release(release_name: str) -> dict:
	require_maintainer()
	release = frappe.get_doc("Hub Plugin Release", release_name)
	plugin = frappe.get_doc("Hub Plugin", release.plugin)
	if release.status != "Pending Review" or plugin.status != "Pending Review":
		frappe.throw(_("Only a pending first release can be published."))
	set_status(plugin, "Published")
	release.published_on = now_datetime()
	set_status(release, "Published", save=True)
	clear_public_caches()
	return {"plugin": plugin.name, "release": release.name, "status": "Published"}


def reject_first_release(release_name: str, reason: str) -> dict:
	require_maintainer()
	if not reason or not reason.strip():
		frappe.throw(_("A rejection reason is required."))
	release = frappe.get_doc("Hub Plugin Release", release_name)
	if release.status != "Pending Review":
		frappe.throw(_("Only a pending release can be rejected."))
	release.validation_errors = frappe.as_json([{"code": "maintainer_rejected", "message": reason.strip()}])
	set_status(release, "Rejected", save=True)
	return {"release": release.name, "status": release.status}


def yank_release(release_name: str) -> dict:
	require_maintainer()
	release = frappe.get_doc("Hub Plugin Release", release_name)
	if release.status != "Published":
		frappe.throw(_("Only a published release can be yanked."))
	set_status(release, "Yanked")
	clear_public_caches()
	return {"release": release.name, "status": release.status}


def block_release(release_name: str) -> dict:
	require_maintainer()
	release = frappe.get_doc("Hub Plugin Release", release_name)
	set_status(release, "Blocked")
	clear_public_caches()
	return {"release": release.name, "status": release.status}


def block_plugin(plugin_name: str) -> dict:
	require_maintainer()
	plugin = frappe.get_doc("Hub Plugin", plugin_name)
	set_status(plugin, "Blocked")
	frappe.db.set_value("Hub Plugin Release", {"plugin": plugin.name}, "status", "Blocked")
	clear_public_caches()
	return {"plugin": plugin.name, "status": plugin.status}


def block_publisher(publisher_id: str) -> dict:
	require_maintainer()
	publisher = frappe.get_doc("Hub Publisher", publisher_id)
	set_status(publisher, "Blocked")
	for plugin_name in frappe.get_all("Hub Plugin", filters={"publisher": publisher.name}, pluck="name"):
		block_plugin(plugin_name)
	clear_public_caches()
	return {"publisher": publisher.name, "status": publisher.status}


def clear_public_caches() -> None:
	frappe.cache.delete_keys("builder_hub.plugins.api.get_catalog_items")


def is_maintainer() -> bool:
	roles = set(frappe.get_roles())
	return frappe.session.user == "Administrator" or bool(
		roles.intersection({"System Manager", "Builder Hub Maintainer"})
	)


def apply_validated_release(release, validated_import: ValidatedReleaseImport, first_release: bool) -> None:
	release_data, asset, package = (
		validated_import.release_data,
		validated_import.asset,
		validated_import.package,
	)
	release.protocol_version = package.manifest["v"]
	release.manifest = frappe.as_json(package.manifest)
	release.github_release_id = str(release_data["id"])
	release.github_release_url = release_data["html_url"]
	release.github_asset_id = str(asset["id"])
	release.package_url = asset["browser_download_url"]
	release.package_sha256 = package.package_sha256
	release.package_size = package.package_size
	release.release_notes = release_data.get("body") or ""
	release.validation_errors = frappe.as_json([])
	if first_release:
		release.status = "Pending Review"
	else:
		plugin_status = frappe.db.get_value("Hub Plugin", release.plugin, "status")
		if plugin_status not in {"Published", "Deprecated"}:
			raise ProtocolValidationError(
				"listing_not_published", "Later releases require a published listing."
			)
		release.status = "Published"
		release.published_on = now_datetime()
	release.save(ignore_permissions=True)
	if release.status == "Published":
		clear_public_caches()


def update_listing_from_contract(plugin, contract: dict) -> None:
	manifest = contract["manifest"]
	plugin.label = manifest["label"]
	plugin.description = manifest["description"]
	plugin.readme = contract["readme"]
	plugin.save(ignore_permissions=True)


def validate_release(release: dict, plugin_name: str, version: str) -> dict:
	if version_from_tag(release.get("tag_name")) != version:
		raise ProtocolValidationError(
			"release_tag_mismatch",
			"GitHub release tag must equal the SemVer version, with or without a leading v.",
		)
	if release.get("draft") or release.get("prerelease"):
		raise ProtocolValidationError(
			"unpublished_release", "Draft and prerelease GitHub releases are not accepted."
		)
	expected = expected_package_name(plugin_name, version)
	assets = [asset for asset in release.get("assets") or [] if asset.get("name") == expected]
	if len(assets) != 1:
		raise ProtocolValidationError(
			"invalid_release_asset", f"The release must contain exactly one {expected} asset."
		)
	asset = assets[0]
	if asset.get("state") not in {None, "uploaded"} or not asset.get("browser_download_url"):
		raise ProtocolValidationError(
			"invalid_release_asset", "The GitHub release asset is not ready for download."
		)
	return asset


def assert_unchanged_asset(release, release_data: dict, asset: dict) -> None:
	if not release.github_asset_id:
		return
	values = {
		"github_release_id": str(release_data["id"]),
		"github_asset_id": str(asset["id"]),
		"package_url": asset["browser_download_url"],
	}
	for fieldname, value in values.items():
		if release.get(fieldname) and release.get(fieldname) != value:
			raise ProtocolValidationError(
				"release_asset_changed", "An existing release asset cannot be replaced."
			)


def get_or_create_release(plugin_name: str, version: str):
	name = f"{plugin_name}@{version}"
	if frappe.db.exists("Hub Plugin Release", name):
		release = frappe.get_doc("Hub Plugin Release", name)
		if not release.published_on:
			release.status = "Validating"
			release.validation_errors = frappe.as_json([])
			release.save(ignore_permissions=True)
		return release
	return frappe.get_doc(
		{
			"doctype": "Hub Plugin Release",
			"plugin": plugin_name,
			"version": version,
			"protocol_version": 1,
			"status": "Validating",
		}
	).insert(ignore_permissions=True)


def set_status(doc, status: str, *, save: bool = False) -> None:
	doc.status = status
	if save:
		doc.save(ignore_permissions=True)
	else:
		doc.db_set("status", status)


def require_maintainer() -> None:
	if not is_maintainer():
		frappe.throw(_("A Builder Hub maintainer must perform this action."), frappe.PermissionError)


def increment_metric(name: str) -> None:
	try:
		frappe.cache.incrby(f"builder_hub:plugins:metrics:{name}", 1)
	except Exception:
		frappe.logger("builder_hub.plugins").debug("Could not increment plugin metric", exc_info=True)
