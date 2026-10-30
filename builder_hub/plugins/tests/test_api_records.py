from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from builder_hub.plugins import api, publishing


class PluginAPIRecordTests(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.publisher_id = f"test-{frappe.generate_hash(length=8).lower()}"
		self.plugin_name = f"{self.publisher_id}/icons"
		self.readme = "README <script>bad()</script> [bad](javascript:alert(1))"
		frappe.get_doc(
			{
				"doctype": "Hub Publisher",
				"publisher_id": self.publisher_id,
				"display_name": "Test Publisher",
				"github_owner": self.publisher_id,
				"github_account_id": frappe.generate_hash(length=12),
				"verified": 1,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Hub Plugin",
				"plugin_name": self.plugin_name,
				"publisher": self.publisher_id,
				"label": "Icon Library",
				"description": "Add icons.",
				"readme": self.readme,
				"repository_url": f"https://github.com/{self.publisher_id}/icons",
				"github_repository_id": frappe.generate_hash(length=12),
				"license": "MIT",
				"categories": frappe.as_json(["design"]),
				"icon": "/files/plugin-icons/" + ("a" * 64) + ".svg",
				"status": "Published",
			}
		).insert(ignore_permissions=True)
		self.release_120 = self.insert_release("1.2.0", 1)
		self.release_1100 = self.insert_release("1.10.0", 1)
		self.release_protocol_2 = self.insert_release("2.0.0", 2, manifest=None)
		api.get_catalog_items.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Hub Plugin Release", {"plugin": self.plugin_name})
		frappe.db.delete("Hub Plugin", self.plugin_name)
		frappe.db.delete("Hub Publisher", self.publisher_id)
		api.get_catalog_items.clear_cache()

	def insert_release(self, version, protocol_version, manifest="default"):
		manifest_value = (
			{
				"v": 1,
				"name": self.plugin_name,
				"label": "Icon Library",
				"description": "Add icons.",
				"version": version,
				"entry": "main.js",
			}
			if manifest == "default"
			else manifest
		)
		return frappe.get_doc(
			{
				"doctype": "Hub Plugin Release",
				"plugin": self.plugin_name,
				"version": version,
				"protocol_version": protocol_version,
				"manifest": frappe.as_json(manifest_value) if manifest_value is not None else None,
				"github_release_id": frappe.generate_hash(length=12),
				"github_release_url": f"https://github.com/{self.publisher_id}/icons/releases/tag/{version}",
				"github_asset_id": frappe.generate_hash(length=12),
				"package_url": f"https://github.com/{self.publisher_id}/icons/releases/download/{version}/{self.publisher_id}-icons-{version}.builderplugin",
				"package_sha256": "b" * 64,
				"package_size": 1234,
				"release_notes": f"Release {version}",
				"published_on": now_datetime(),
				"status": "Published",
			}
		).insert(ignore_permissions=True)

	def test_catalog_shape_chooses_latest_compatible_semver(self):
		catalog = api.get_catalog(1)
		item = next(item for item in catalog["plugins"] if item["name"] == self.plugin_name)
		self.assertEqual(item["latest_release"]["version"], "1.10.0")
		self.assertNotIn("package_url", json.dumps(item))
		self.assertTrue(item["icon"].endswith("/files/plugin-icons/" + ("a" * 64) + ".svg"))

	def test_catalog_paginates_and_reports_total_count(self):
		items = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
		with (
			patch.object(api, "get_catalog_items", return_value=items),
			patch.object(api, "CATALOG_PAGE_SIZE", 2),
		):
			first_page = api.get_catalog(1, page=1)
			second_page = api.get_catalog(1, page=2)

		self.assertEqual(first_page["plugins"], items[:2])
		self.assertEqual(first_page["total_count"], 3)
		self.assertTrue(first_page["has_more"])
		self.assertEqual(second_page["plugins"], items[2:])
		self.assertEqual(second_page["page"], 2)
		self.assertEqual(second_page["total_count"], 3)
		self.assertFalse(second_page["has_more"])

	def test_detail_has_readme_and_compatible_history_without_package_urls(self):
		detail = api.get_plugin(self.plugin_name, 1)
		self.assertEqual(detail["plugin"]["readme"], self.readme)
		self.assertEqual([row["version"] for row in detail["releases"]], ["1.10.0", "1.2.0"])
		self.assertNotIn("package_url", json.dumps(detail))

	def test_exact_release_is_only_response_with_package_url(self):
		response = api.get_plugin_release(self.plugin_name, "1.10.0")
		self.assertIn("package_url", response["release"])
		self.assertEqual(response["release"]["manifest"]["version"], "1.10.0")

	def test_status_reports_yanked_and_blocked_states(self):
		self.release_120.db_set("status", "Yanked")
		response = api.get_release_status([{"plugin_name": self.plugin_name, "version": "1.2.0"}])
		self.assertTrue(response["releases"][0]["found"])
		self.assertEqual(response["releases"][0]["release_status"], "Yanked")
		frappe.db.set_value("Hub Publisher", self.publisher_id, "status", "Blocked")
		response = api.get_release_status([{"plugin_name": self.plugin_name, "version": "1.2.0"}])
		self.assertEqual(response["releases"][0]["plugin_status"], "Blocked")

	def test_block_ignores_a_stored_manifest_that_fails_current_checks(self):
		self.release_120.db_set("manifest", frappe.as_json({"v": 1}))
		publishing.block_plugin(self.plugin_name)
		self.assertEqual(
			frappe.db.get_value("Hub Plugin Release", self.release_120.name, "status"), "Blocked"
		)

	def test_published_release_metadata_is_immutable_but_status_can_change(self):
		release = frappe.get_doc("Hub Plugin Release", self.release_120.name)
		release.package_url += "?changed=1"
		with self.assertRaises(frappe.ValidationError):
			release.save(ignore_permissions=True)
		release.reload()
		release.status = "Yanked"
		release.save(ignore_permissions=True)
		self.assertEqual(release.status, "Yanked")
