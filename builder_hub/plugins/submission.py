"""Maintainer action that adds and publishes a plugin from its GitHub repository."""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _

from builder_hub.plugins.github import (
	GitHubClient,
	get_repository_contract,
	get_repository_license,
	get_validated_repository_url,
	parse_repository_url,
	validate_public_repository,
)
from builder_hub.plugins.protocol import ProtocolValidationError
from builder_hub.plugins.publishing import (
	ValidatedReleaseImport,
	approve_first_release,
	import_validated_release,
	require_maintainer,
	validate_release_source,
)


@dataclass(frozen=True)
class ValidatedPublication:
	repository: dict
	publisher_id: str
	publisher_name: str
	license_id: str
	release: ValidatedReleaseImport

	@property
	def summary(self) -> dict:
		manifest = self.release.package.manifest
		return {
			"plugin_name": manifest["name"],
			"version": manifest["version"],
			"publisher_id": self.publisher_id,
			"package_sha256": self.release.package.package_sha256,
		}


def preview_plugin(repository_url: str, *, client: GitHubClient | None = None) -> dict:
	"""Validate the repository and return what add_plugin would publish."""
	require_maintainer()
	return get_available_publication(repository_url, client).summary


def add_plugin(repository_url: str, expected: dict, *, client: GitHubClient | None = None) -> dict:
	"""Publish the plugin only if it still matches the summary the maintainer confirmed."""
	require_maintainer()
	publication = get_available_publication(repository_url, client)
	if publication.summary != expected:
		frappe.throw(_("The repository changed after the check. Check it again."))
	create_or_update_publisher(publication)
	plugin = create_listing(publication)
	release = import_validated_release(plugin.name, publication.release, first_release=True)
	if release.status != "Pending Review":
		frappe.throw(_("The first release could not be prepared for publication."))
	return approve_first_release(release.name)


def get_available_publication(repository_url: str, client: GitHubClient | None) -> ValidatedPublication:
	try:
		publication = validate_publication(repository_url, client=client)
		assert_identity_available(publication)
	except ProtocolValidationError as error:
		frappe.throw(_(error.message))
	return publication


def validate_publication(repository_url: str, *, client: GitHubClient | None = None) -> ValidatedPublication:
	client = client or GitHubClient()
	owner_name, repository_name = parse_repository_url(repository_url)
	repository = client.get_repository_by_name(owner_name, repository_name)
	owner = repository.get("owner") or {}
	owner_id = str(owner.get("id") or "")
	owner_login = owner.get("login") or ""
	if not owner_id or not owner_login:
		raise ProtocolValidationError("invalid_repository", "GitHub returned an invalid repository owner.")
	validate_public_repository(repository)

	license_id = get_repository_license(repository)
	contract = get_repository_contract(client, repository, license_id)
	manifest = contract["manifest"]
	publisher_id, publisher_name = resolve_publisher(owner_id, owner_login)
	if manifest["name"].split("/", 1)[0] != publisher_id:
		raise ProtocolValidationError(
			"publisher_owner_mismatch",
			f"Manifest name must use the repository owner's {publisher_id} namespace.",
		)
	release = validate_release_source(
		client,
		repository,
		contract,
		manifest["name"],
		manifest["version"],
	)
	return ValidatedPublication(
		repository=repository,
		publisher_id=publisher_id,
		publisher_name=publisher_name,
		license_id=license_id,
		release=release,
	)


def create_or_update_publisher(publication: ValidatedPublication):
	owner = publication.repository["owner"]
	if frappe.db.exists("Hub Publisher", publication.publisher_id):
		publisher = frappe.get_doc("Hub Publisher", publication.publisher_id)
		publisher.github_owner = owner["login"]
		publisher.verified = 1
		publisher.status = "Active"
		publisher.save(ignore_permissions=True)
		return publisher
	return frappe.get_doc(
		{
			"doctype": "Hub Publisher",
			"publisher_id": publication.publisher_id,
			"display_name": publication.publisher_name,
			"github_owner": owner["login"],
			"github_account_id": str(owner["id"]),
			"verified": 1,
			"status": "Active",
		}
	).insert(ignore_permissions=True)


def create_listing(publication: ValidatedPublication):
	manifest = publication.release.package.manifest
	return frappe.get_doc(
		{
			"doctype": "Hub Plugin",
			"plugin_name": manifest["name"],
			"publisher": publication.publisher_id,
			"label": manifest["label"],
			"description": manifest["description"],
			"readme": publication.release.contract["readme"],
			"repository_url": get_validated_repository_url(publication.repository),
			"github_repository_id": str(publication.repository["id"]),
			"license": publication.license_id,
			"categories": frappe.as_json([]),
			"status": "Pending Review",
		}
	).insert(ignore_permissions=True)


def assert_identity_available(publication: ValidatedPublication) -> None:
	if frappe.db.exists("Hub Plugin", publication.summary["plugin_name"]):
		raise ProtocolValidationError("plugin_exists", "This plugin name has already been used.")
	if frappe.db.exists("Hub Plugin", {"github_repository_id": str(publication.repository["id"])}):
		raise ProtocolValidationError(
			"repository_exists", "This GitHub repository has already been published."
		)


def resolve_publisher(owner_id: str, owner_login: str) -> tuple[str, str]:
	publisher_id = frappe.db.get_value("Hub Publisher", {"github_account_id": owner_id}, "publisher_id")
	if not publisher_id:
		publisher_id = owner_login.lower()
		if frappe.db.exists("Hub Publisher", publisher_id):
			raise ProtocolValidationError(
				"publisher_owner_mismatch",
				"The repository owner belongs to a different GitHub account.",
			)
		return publisher_id, owner_login

	publisher = frappe.get_doc("Hub Publisher", publisher_id)
	if publisher.status == "Blocked":
		raise ProtocolValidationError("publisher_blocked", "This publisher is blocked.")
	return publisher.publisher_id, publisher.display_name
