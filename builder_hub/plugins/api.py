"""Public JSON API and authenticated actions for Builder Hub plugins."""

from __future__ import annotations

import json
from datetime import UTC

import frappe
from frappe import _
from frappe.utils import get_datetime, get_url
from frappe.utils.caching import redis_cache

from builder_hub.plugins import publishing, submission, tasks
from builder_hub.plugins.protocol import (
	CATALOG_PAGE_SIZE,
	PLUGIN_NAME_PATTERN,
	SEMVER_PATTERN,
	semver_key,
)

PUBLIC_STATUSES = ("Published", "Deprecated")
RELEASE_SUMMARY_FIELDS = ("version", "protocol_version", "package_size", "package_sha256", "published_on")


@frappe.whitelist(allow_guest=True)
def get_catalog(protocol_version: int | str = 1, page: int | str = 1) -> dict:
	page = positive_integer(page, "page")
	items = get_catalog_items(positive_integer(protocol_version, "protocol_version"), get_url())
	start = (page - 1) * CATALOG_PAGE_SIZE
	return {
		"plugins": items[start : start + CATALOG_PAGE_SIZE],
		"page": page,
		"total_count": len(items),
		"has_more": start + CATALOG_PAGE_SIZE < len(items),
	}


@redis_cache(ttl=600)
def get_catalog_items(protocol_version: int, base_url: str) -> list[dict]:
	"""One cached list for every page, so a page request does not build the catalog again."""
	items = []
	for plugin in frappe.get_all(
		"Hub Plugin",
		filters={"status": ("in", PUBLIC_STATUSES)},
		fields=plugin_fields(),
		order_by="plugin_name asc",
		ignore_permissions=True,
	):
		publisher = get_publisher(plugin.publisher)
		if not publisher or publisher.status != "Active":
			continue
		releases = published_releases(plugin.name, protocol_version, RELEASE_SUMMARY_FIELDS)
		if releases:
			items.append(
				{**listing(plugin, publisher, base_url), "latest_release": release_summary(releases[0])}
			)
	return items


@frappe.whitelist(allow_guest=True)
def get_plugin(name: str, protocol_version: int | str = 1) -> dict:
	protocol_version = positive_integer(protocol_version, "protocol_version")
	plugin, publisher = public_listing(name)
	releases = published_releases(
		plugin.name, protocol_version, (*RELEASE_SUMMARY_FIELDS, "release_notes", "status")
	)
	return {
		"plugin": {**listing(plugin, publisher, get_url()), "readme": plugin.readme or ""},
		"releases": [
			{**release_summary(row), "release_notes": row.release_notes or "", "status": row.status}
			for row in releases
		],
	}


@frappe.whitelist(allow_guest=True)
def get_plugin_release(plugin_name: str, version: str) -> dict:
	validate_identity(plugin_name, version)
	public_listing(plugin_name)
	name = f"{plugin_name}@{version}"
	if not frappe.db.exists("Hub Plugin Release", name):
		not_found()
	release = frappe.get_doc("Hub Plugin Release", name)
	if release.status != "Published":
		frappe.throw(_("This release is not available for installation."), frappe.PermissionError)
	return {
		"release": {
			"plugin_name": release.plugin,
			"version": release.version,
			"protocol_version": release.protocol_version,
			"manifest": parse_json_value(release.manifest, {}),
			"github_release_url": release.github_release_url,
			"package_url": release.package_url,
			"package_size": release.package_size,
			"package_sha256": release.package_sha256,
			"status": release.status,
			"published_on": iso(release.published_on),
		},
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def get_release_status(releases: list[dict] | str) -> dict:
	releases = parse_json_value(releases, None)
	if not isinstance(releases, list):
		frappe.throw(_("releases must be a JSON list."))
	if len(releases) > 100:
		frappe.throw(_("At most 100 release identities can be checked at once."))
	return {
		"releases": [get_release_identity_status(identity) for identity in releases],
	}


def get_release_identity_status(identity) -> dict:
	if not isinstance(identity, dict):
		frappe.throw(_("Each release identity must be an object."))
	plugin_name = identity.get("plugin_name")
	version = identity.get("version")
	validate_identity(plugin_name, version)
	plugin = frappe.db.get_value(
		"Hub Plugin", plugin_name, ["name", "publisher", "status", "replacement"], as_dict=True
	)
	release_status = frappe.db.get_value("Hub Plugin Release", f"{plugin_name}@{version}", "status")
	plugin_status = plugin.status if plugin else None
	if plugin and frappe.db.get_value("Hub Publisher", plugin.publisher, "status") == "Blocked":
		plugin_status = "Blocked"
	return {
		"plugin_name": plugin_name,
		"version": version,
		"found": bool(plugin and release_status),
		"plugin_status": plugin_status,
		"release_status": release_status,
		"replacement": plugin.replacement if plugin else None,
	}


@frappe.whitelist(methods=["POST"])
def preview_plugin(repository_url: str) -> dict:
	return submission.preview_plugin(repository_url)


@frappe.whitelist(methods=["POST"])
def add_plugin(repository_url: str, expected: dict | str) -> dict:
	return submission.add_plugin(repository_url, frappe.parse_json(expected))


@frappe.whitelist()
def approve_first_release(release_name: str) -> dict:
	return publishing.approve_first_release(release_name)


@frappe.whitelist()
def reject_first_release(release_name: str, reason: str) -> dict:
	return publishing.reject_first_release(release_name, reason)


@frappe.whitelist()
def request_release_check(plugin_name: str) -> dict:
	return tasks.request_release_check(plugin_name)


@frappe.whitelist()
def yank_release(release_name: str) -> dict:
	return publishing.yank_release(release_name)


@frappe.whitelist()
def block_release(release_name: str) -> dict:
	return publishing.block_release(release_name)


@frappe.whitelist()
def block_plugin(plugin_name: str) -> dict:
	return publishing.block_plugin(plugin_name)


@frappe.whitelist()
def block_publisher(publisher_id: str) -> dict:
	return publishing.block_publisher(publisher_id)


def public_listing(plugin_name: str):
	if not isinstance(plugin_name, str) or not PLUGIN_NAME_PATTERN.fullmatch(plugin_name):
		not_found()
	plugin = frappe.db.get_value("Hub Plugin", plugin_name, [*plugin_fields(), "readme"], as_dict=True)
	if not plugin or plugin.status not in PUBLIC_STATUSES:
		not_found()
	publisher = get_publisher(plugin.publisher)
	if not publisher or publisher.status != "Active":
		not_found()
	return plugin, publisher


def published_releases(plugin_name: str, protocol_version: int, fields) -> list:
	"""Published releases the client can install, newest first."""
	releases = frappe.get_all(
		"Hub Plugin Release",
		filters={
			"plugin": plugin_name,
			"status": "Published",
			"protocol_version": ("<=", protocol_version),
		},
		fields=list(fields),
		ignore_permissions=True,
	)
	return sorted(releases, key=lambda row: semver_key(row.version), reverse=True)


def listing(plugin, publisher, base_url: str) -> dict:
	return {
		"name": plugin.plugin_name,
		"label": plugin.label,
		"description": plugin.description,
		"publisher": {
			"id": publisher.publisher_id,
			"name": publisher.display_name,
			"verified": bool(publisher.verified),
		},
		"repository_url": plugin.repository_url,
		"license": plugin.license,
		"categories": parse_json_value(plugin.categories, []),
		"icon": absolute_url(plugin.icon, base_url),
		"status": plugin.status,
		"replacement": plugin.replacement or None,
	}


def release_summary(release) -> dict:
	return {
		**{fieldname: release[fieldname] for fieldname in RELEASE_SUMMARY_FIELDS},
		"published_on": iso(release.published_on),
	}


def get_publisher(name: str):
	return frappe.db.get_value(
		"Hub Publisher",
		name,
		["publisher_id", "display_name", "verified", "status"],
		as_dict=True,
	)


def plugin_fields() -> list[str]:
	return [
		"name",
		"plugin_name",
		"publisher",
		"label",
		"description",
		"repository_url",
		"license",
		"categories",
		"icon",
		"status",
		"replacement",
	]


def positive_integer(value, fieldname: str) -> int:
	try:
		value = int(value)
	except (TypeError, ValueError):
		value = 0
	if value < 1 or value > 2_147_483_647:
		frappe.throw(_("{0} must be a positive integer.").format(fieldname))
	return value


def validate_identity(plugin_name, version) -> None:
	if not isinstance(plugin_name, str) or not PLUGIN_NAME_PATTERN.fullmatch(plugin_name):
		frappe.throw(_("Invalid plugin name."))
	if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
		frappe.throw(_("Invalid release version."))


def absolute_url(path: str | None, base_url: str) -> str | None:
	if path and path.startswith("/"):
		return base_url.rstrip("/") + path
	return path


def iso(value) -> str | None:
	if not value:
		return None
	date = get_datetime(value)
	if date.tzinfo is None:
		date = date.replace(tzinfo=UTC)
	return date.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_json_value(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except json.JSONDecodeError:
			return default
	return value


def not_found():
	frappe.throw(_("Plugin or release not found."), frappe.DoesNotExistError)
