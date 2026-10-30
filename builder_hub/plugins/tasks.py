"""Scheduled and maintainer-requested GitHub release checks."""

from __future__ import annotations

import hashlib

import frappe
from frappe.utils import now_datetime

from builder_hub.plugins.github import GitHubClient, get_repository_contract, validate_repository
from builder_hub.plugins.protocol import ProtocolValidationError, semver_key, version_from_tag
from builder_hub.plugins.publishing import import_release, increment_metric, require_maintainer


def check_releases() -> None:
	"""Hourly scheduler entry: queue one deduplicated job for each active listing."""
	for plugin in frappe.get_all(
		"Hub Plugin",
		filters={"status": ("in", ["Published", "Deprecated"])},
		fields=["name", "github_repository_id"],
		ignore_permissions=True,
	):
		enqueue_repository_check(plugin.name, plugin.github_repository_id)


def enqueue_repository_check(plugin_name: str, repository_id: str | None = None):
	repository_id = repository_id or frappe.db.get_value("Hub Plugin", plugin_name, "github_repository_id")
	if not repository_id:
		return None
	job_suffix = hashlib.sha256(str(repository_id).encode()).hexdigest()[:24]
	return frappe.enqueue(
		"builder_hub.plugins.tasks.check_repository",
		queue="short",
		timeout=180,
		job_id=f"builder-hub-plugin-{job_suffix}",
		deduplicate=True,
		plugin_name=plugin_name,
	)


def check_repository(plugin_name: str, *, client: GitHubClient | None = None) -> dict:
	"""Check one stable repository ID and import every new declared release."""
	increment_metric("checks")
	plugin = frappe.get_doc("Hub Plugin", plugin_name)
	if plugin.status not in {"Published", "Deprecated"}:
		return {"plugin": plugin.name, "checked": False, "reason": "inactive_listing"}
	publisher = frappe.get_doc("Hub Publisher", plugin.publisher)
	if publisher.status != "Active":
		return {"plugin": plugin.name, "checked": False, "reason": "inactive_publisher"}

	client = client or GitHubClient()
	try:
		repository = client.get_repository(plugin.github_repository_id)
		validate_repository(repository, publisher.github_account_id)
		response = client.get_releases(repository, plugin.github_etag)
		if response.status_code == 304:
			plugin.db_set("last_checked_on", now_datetime(), update_modified=False)
			return {"plugin": plugin.name, "checked": True, "unchanged": True, "imported": []}

		imported = import_new_releases(plugin, client, repository, response.data or [])
		# a stored ETag would turn the retry of a Validating release into a 304
		needs_retry = any(item["status"] == "Validating" for item in imported)
		plugin.db_set(
			{"last_checked_on": now_datetime(), "github_etag": None if needs_retry else response.etag},
			update_modified=False,
		)
		return {"plugin": plugin.name, "checked": True, "unchanged": False, "imported": imported}
	except ProtocolValidationError as error:
		increment_metric("github_rate_limits" if error.code == "github_rate_limited" else "check_failures")
		plugin.db_set("last_checked_on", now_datetime(), update_modified=False)
		frappe.logger("builder_hub.plugins").warning(
			"Plugin release check failed for %s: %s (%s)", plugin.name, error.message, error.code
		)
		return {"plugin": plugin.name, "checked": False, "error": error.as_dict()}


def import_new_releases(plugin, client: GitHubClient, repository: dict, releases: list[dict]) -> list[dict]:
	contract = get_repository_contract(client, repository, plugin.license)
	imported = []
	for version, release_data in get_release_index(releases).items():
		existing_status = frappe.db.get_value("Hub Plugin Release", f"{plugin.name}@{version}", "status")
		if existing_status in {"Published", "Pending Review", "Yanked", "Blocked"}:
			continue
		release = import_release(
			plugin.name,
			version,
			client=client,
			repository=repository,
			contract=contract,
			release_data=release_data,
		)
		imported.append({"version": version, "status": release.status})
	return imported


def get_release_index(releases: list[dict]) -> dict[str, dict]:
	"""Index published GitHub releases with valid SemVer tags in precedence order."""
	available = {}
	# a bare tag wins when a version has both forms
	for release in sorted(releases, key=lambda release: str(release.get("tag_name")).startswith("v")):
		version = version_from_tag(release.get("tag_name"))
		if version and not release.get("draft") and not release.get("prerelease"):
			available.setdefault(version, release)
	return {version: available[version] for version in sorted(available, key=semver_key)}


def request_release_check(plugin_name: str) -> dict:
	require_maintainer()
	plugin = frappe.get_doc("Hub Plugin", plugin_name)
	enqueue_repository_check(plugin.name, plugin.github_repository_id)
	return {"plugin": plugin.name, "queued": True}
