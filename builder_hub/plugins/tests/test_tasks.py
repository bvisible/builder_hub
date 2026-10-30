from frappe.tests import UnitTestCase

from builder_hub.plugins.tasks import get_release_index


class ReleaseDiscoveryTests(UnitTestCase):
	def test_indexes_only_published_semver_releases(self):
		releases = [
			{"tag_name": "1.1.0"},
			{"tag_name": "documentation"},
			{"tag_name": "2.0.0", "draft": True},
			{"tag_name": "3.0.0", "prerelease": True},
			{"tag_name": "1.0.0"},
		]

		self.assertEqual(list(get_release_index(releases)), ["1.0.0", "1.1.0"])

	def test_indexes_a_v_prefixed_tag_by_its_version(self):
		releases = [{"tag_name": "v1.1.0"}, {"tag_name": "v1.0.0", "id": 1}, {"tag_name": "1.0.0", "id": 2}]

		index = get_release_index(releases)

		self.assertEqual(list(index), ["1.0.0", "1.1.0"])
		self.assertEqual(index["1.0.0"]["id"], 2)
