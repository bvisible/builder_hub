from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase

from builder_hub.plugins import api
from builder_hub.plugins.protocol import ProtocolValidationError, expected_package_name
from builder_hub.plugins.submission import add_plugin, preview_plugin


class PublicationClient:
	def __init__(self, repository: dict, files: dict[str, bytes], release: dict, package: Path):
		self.repository = repository
		self.files = files
		self.release = release
		self.package = package

	def get_repository_by_name(self, owner: str, name: str) -> dict:
		return self.repository

	def get_repository_file(self, repository: dict, path: str) -> bytes:
		if path not in self.files:
			raise ProtocolValidationError("github_not_found", f"The repository has no {path} file.")
		if isinstance(self.files[path], ProtocolValidationError):
			raise self.files[path]
		return self.files[path]

	def get_release(self, repository: dict, version: str) -> dict:
		return self.release

	def download_asset(self, url: str) -> str:
		file_descriptor, filename = tempfile.mkstemp(suffix=".builderplugin")
		os.close(file_descriptor)
		shutil.copyfile(self.package, filename)
		return filename


class PublicationRequestTests(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.temporary = tempfile.TemporaryDirectory()
		self.publisher_id = f"public-{frappe.generate_hash(length=8).lower()}"
		self.plugin_name = f"{self.publisher_id}/icons"
		self.repository_id = frappe.generate_hash(length=12)
		self.owner_id = frappe.generate_hash(length=12)
		self.repository_url = f"https://github.com/{self.publisher_id}/builder-plugin-icons"
		self.manifest = {
			"v": 1,
			"name": self.plugin_name,
			"label": "Public icons",
			"description": "Insert public icons.",
			"version": "1.0.0",
			"entry": "main.js",
		}
		self.package = Path(self.temporary.name) / "plugin.builderplugin"
		with zipfile.ZipFile(self.package, "w", zipfile.ZIP_DEFLATED) as archive:
			archive.writestr("manifest.json", json.dumps(self.manifest))
			archive.writestr("main.js", "export const ready = true;")
		self.client = PublicationClient(
			self.github_repository(),
			{
				"manifest.json": json.dumps(self.manifest).encode(),
				"README.md": b"README <script>untrusted()</script>",
				"LICENSE": b"MIT License",
			},
			self.github_release(),
			self.package,
		)
		api.get_catalog_items.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Hub Plugin Release", {"plugin": self.plugin_name})
		frappe.db.delete("Hub Plugin", self.plugin_name)
		frappe.db.delete("Hub Publisher", self.publisher_id)
		api.get_catalog_items.clear_cache()
		self.temporary.cleanup()

	def test_preview_checks_the_repository_without_creating_records(self):
		summary = preview_plugin(self.repository_url, client=self.client)
		self.assertEqual(summary["plugin_name"], self.plugin_name)
		self.assertEqual(summary["version"], "1.0.0")
		self.assertEqual(summary["publisher_id"], self.publisher_id)
		self.assertEqual(len(summary["package_sha256"]), 64)
		self.assertFalse(frappe.db.exists("Hub Publisher", self.publisher_id))
		self.assertFalse(frappe.db.exists("Hub Plugin", self.plugin_name))

	def test_add_publishes_the_plugin(self):
		result = self.add_previewed_plugin()
		self.assertEqual(result["status"], "Published")
		self.assertEqual(frappe.db.get_value("Hub Publisher", self.publisher_id, "status"), "Active")
		self.assertEqual(frappe.db.get_value("Hub Plugin", self.plugin_name, "status"), "Published")
		catalog = api.get_catalog(1)
		self.assertIn(self.plugin_name, [item["name"] for item in catalog["plugins"]])

	def test_missing_required_file_is_named(self):
		del self.client.files["README.md"]
		with self.assertRaisesRegex(frappe.ValidationError, "no README.md file"):
			preview_plugin(self.repository_url, client=self.client)

	def test_github_failure_is_not_read_as_a_missing_required_file(self):
		self.client.files["README.md"] = ProtocolValidationError(
			"github_request_failed", "GitHub is unavailable (HTTP 502). Try again later."
		)
		with self.assertRaisesRegex(frappe.ValidationError, "HTTP 502"):
			preview_plugin(self.repository_url, client=self.client)

	def test_add_refuses_a_package_that_changed_after_the_preview(self):
		expected = preview_plugin(self.repository_url, client=self.client)
		with zipfile.ZipFile(self.package, "w") as archive:
			archive.writestr("manifest.json", json.dumps(self.manifest))
			archive.writestr("main.js", "export const ready = false;")
		with self.assertRaisesRegex(frappe.ValidationError, "changed after the check"):
			add_plugin(self.repository_url, expected, client=self.client)
		self.assertFalse(frappe.db.exists("Hub Plugin", self.plugin_name))

	def test_added_repository_cannot_be_added_again(self):
		self.add_previewed_plugin()
		with self.assertRaisesRegex(frappe.ValidationError, "already"):
			preview_plugin(self.repository_url, client=self.client)

	def test_existing_namespace_rejects_a_different_github_owner(self):
		frappe.get_doc(
			{
				"doctype": "Hub Publisher",
				"publisher_id": self.publisher_id,
				"display_name": "Existing Publisher",
				"github_owner": "another-owner",
				"github_account_id": "another-account",
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "different GitHub account"):
			add_plugin(self.repository_url, {}, client=self.client)

	def test_new_publisher_must_use_repository_owner_namespace(self):
		self.client.repository["owner"]["login"] = "actual-owner"
		with self.assertRaisesRegex(frappe.ValidationError, "actual-owner namespace"):
			add_plugin(self.repository_url, {}, client=self.client)

	def test_existing_github_account_keeps_its_publisher_namespace(self):
		frappe.get_doc(
			{
				"doctype": "Hub Publisher",
				"publisher_id": self.publisher_id,
				"display_name": "Existing Publisher",
				"github_owner": "previous-login",
				"github_account_id": self.owner_id,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		self.client.repository["owner"]["login"] = "current-login"
		summary = preview_plugin(self.repository_url, client=self.client)
		self.assertEqual(summary["publisher_id"], self.publisher_id)

	def test_only_a_maintainer_can_add_a_plugin(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			preview_plugin(self.repository_url, client=self.client)
		with self.assertRaises(frappe.PermissionError):
			add_plugin(self.repository_url, {}, client=self.client)

	def add_previewed_plugin(self) -> dict:
		return add_plugin(
			self.repository_url, preview_plugin(self.repository_url, client=self.client), client=self.client
		)

	def github_repository(self) -> dict:
		return {
			"id": self.repository_id,
			"name": "builder-plugin-icons",
			"private": False,
			"archived": False,
			"disabled": False,
			"default_branch": "main",
			"owner": {"id": self.owner_id, "login": self.publisher_id, "type": "User"},
			"license": {"spdx_id": "MIT"},
			"html_url": self.repository_url,
		}

	def github_release(self) -> dict:
		package_name = expected_package_name(self.plugin_name, "1.0.0")
		return {
			"id": frappe.generate_hash(length=12),
			"tag_name": "1.0.0",
			"html_url": f"{self.repository_url}/releases/tag/1.0.0",
			"draft": False,
			"prerelease": False,
			"body": "First release.",
			"assets": [
				{
					"id": frappe.generate_hash(length=12),
					"name": package_name,
					"state": "uploaded",
					"browser_download_url": f"{self.repository_url}/releases/download/1.0.0/{package_name}",
				}
			],
		}
