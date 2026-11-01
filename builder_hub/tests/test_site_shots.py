# //// Neoffice — added file (no upstream equivalent): tests of the picture of a whole site for the gallery of neoffice.ch.
"""What is pinned: a site is photographed when what the picture shows changed and not otherwise, so that a new site gets its picture by itself and an unchanged one
costs nothing; the page photographed is the one the gallery opens; a site that fails keeps its card and does not stop the others; the picture replaces the old one
under a new address; the catalogue serves it for the sites of the gallery only. The browser itself is not run here (the hub has it, the tests do not need it)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from builder_hub import api, publish, site_shots


def group(name="garage", showcase=True, **overrides):
	return {
		"name": name,
		"showcase": showcase,
		"pages": [
			{"name": "no-address", "page_title": "Brouillon", "live_url": None},
			{"name": f"{name}-home", "page_title": "Accueil", "live_url": f"https://hub.test/templates/{name}/accueil"},
			{"name": f"{name}-about", "page_title": "À propos", "live_url": f"https://hub.test/templates/{name}/a_propos"},
		],
		**overrides,
	}


class TestWhenASiteIsPhotographedAgain(unittest.TestCase):
	def digest(self, blocks="[]", chrome=None, site=None):
		with (
			patch.object(site_shots.frappe, "db", MagicMock(**{"get_value.return_value": blocks})),
			patch("builder.template_sync.get_group_manifest", return_value={"chrome": chrome or {}}),
		):
			return site_shots.picture_hash(site or group(), "garage-home")

	def test_an_unchanged_site_keeps_its_picture(self):
		self.assertEqual(self.digest(), self.digest())

	def test_its_home_page_its_chrome_and_its_menu_each_make_a_new_picture(self):
		self.assertNotEqual(self.digest(), self.digest(blocks='[{"a": 1}]'))
		self.assertNotEqual(self.digest(), self.digest(chrome={"header_bg_color": "#000000"}))
		longer = group()
		longer["pages"].append({"name": "x", "page_title": "Contact", "live_url": "https://hub.test/x"})
		self.assertNotEqual(self.digest(), self.digest(site=longer))

	def test_the_order_of_the_chrome_settings_is_not_a_change(self):
		self.assertEqual(self.digest(chrome={"a": 1, "b": 2}), self.digest(chrome={"b": 2, "a": 1}))


class TestTheSizeOfThePicture(unittest.TestCase):
	def test_a_page_is_scaled_to_the_width_of_a_card_at_two_pixels(self):
		self.assertEqual((800, 3000), site_shots.picture_size(1280, 4800))

	def test_an_empty_page_still_has_a_pixel(self):
		self.assertEqual(1, site_shots.picture_size(1280, 0)[1])


class Folder(unittest.TestCase):
	def setUp(self):
		tmp = tempfile.TemporaryDirectory()
		self.addCleanup(tmp.cleanup)
		self.folder = Path(tmp.name)
		self.db = MagicMock(**{"get_value.return_value": "/builder_assets/garage/garage-home/preview.webp?v=2"})
		for patcher in (
			patch.object(site_shots, "resolve_asset_path", return_value=self.folder / "preview.webp"),
			patch.object(site_shots.frappe, "db", self.db),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def picture(self, name, size=(800, 3000)):
		Image.new("RGB", size).save(self.folder / name, "WEBP")


class TestThePictureInTheCatalogue(Folder):
	def test_it_is_served_beside_the_preview_with_its_size(self):
		self.picture("whole-abc.webp")
		with patch.object(api, "get_url", return_value="https://hub.test"):
			self.assertEqual(
				{"url": "https://hub.test/builder_assets/garage/garage-home/whole-abc.webp", "width": 800, "height": 3000},
				site_shots.scroll_picture(group()["pages"]),
			)

	def test_a_site_not_photographed_yet_has_none_and_keeps_its_card(self):
		self.assertIsNone(site_shots.scroll_picture(group()["pages"]))

	def test_the_preview_and_its_thumbnails_are_not_taken_for_it(self):
		self.picture("preview.webp")
		self.picture("preview-thumb-12345678.webp")
		self.assertIsNone(site_shots.scroll_picture(group()["pages"]))

	def test_a_group_with_no_page_to_open_has_none(self):
		self.assertIsNone(site_shots.scroll_picture([{"name": "a", "live_url": None}]))


class TestKeepingAPicture(Folder):
	def test_it_replaces_the_old_one_and_nothing_else(self):
		self.picture("whole-old.webp")
		self.picture("preview.webp")
		with patch.object(site_shots.frappe, "generate_hash", return_value="abc123"):
			site_shots._keep(self.folder / "whole-new.webp", b"picture")
		self.assertEqual(["preview.webp", "whole-new.webp"], sorted(path.name for path in self.folder.iterdir()))
		self.assertEqual(b"picture", (self.folder / "whole-new.webp").read_bytes())


class TestMakingThePictures(Folder):
	def make(self, groups, pictures, **kwargs):
		with (
			patch.object(api, "_get_catalog", return_value=groups),
			patch.object(site_shots, "get_url", return_value="https://hub.test"),
			patch.object(site_shots, "picture_hash", return_value="abc"),
			patch.object(site_shots, "shoot", return_value=pictures) as shoot,
			patch.object(site_shots.frappe, "generate_hash", return_value="abc123"),
			patch.object(publish, "_clear_catalog_caches") as clear,
		):
			lines = site_shots.make_pictures(**kwargs)
		return lines, shoot, clear

	def test_a_new_site_is_photographed_by_itself_on_the_page_the_gallery_opens(self):
		lines, shoot, clear = self.make([group()], [b"picture"])
		shoot.assert_called_once_with(["https://hub.test/templates/garage/accueil"])
		self.assertTrue((self.folder / "whole-abc.webp").exists())
		self.assertEqual(1, len(lines))
		clear.assert_called_once()

	def test_a_site_that_has_its_picture_costs_no_browser(self):
		self.picture("whole-abc.webp")
		lines, shoot, clear = self.make([group()], [])
		self.assertEqual([], lines)
		shoot.assert_not_called()
		clear.assert_not_called()

	def test_force_photographs_it_again(self):
		self.picture("whole-abc.webp")
		_lines, shoot, _clear = self.make([group()], [b"picture"], force=True)
		shoot.assert_called_once()

	def test_the_sites_the_gallery_does_not_show_are_left_alone(self):
		_lines, shoot, _clear = self.make([group(showcase=False)], [])
		shoot.assert_not_called()

	def test_one_site_can_be_named(self):
		_lines, shoot, _clear = self.make([group("garage"), group("salon")], [b"picture"], only="salon")
		shoot.assert_called_once_with(["https://hub.test/templates/salon/accueil"])

	def test_a_site_without_a_preview_has_no_card_and_no_picture(self):
		with patch.object(site_shots, "resolve_asset_path", return_value=None):
			_lines, shoot, _clear = self.make([group()], [])
		shoot.assert_not_called()

	def test_a_site_that_fails_writes_nothing_and_does_not_stop_the_next(self):
		with patch.object(site_shots, "_keep") as keep:
			lines, _shoot, _clear = self.make([group("garage"), group("salon")], [None, b"picture"])
		self.assertEqual("garage: failed", lines[0])
		keep.assert_called_once()


class TestTheHook(unittest.TestCase):
	def test_a_failure_never_reaches_the_scheduler(self):
		with (
			patch.object(site_shots, "make_pictures", side_effect=RuntimeError("no browser")),
			patch.object(site_shots.frappe, "log_error") as log,
		):
			site_shots.hourly()
		self.assertEqual("Site pictures not made", log.call_args.args[0])

	def test_the_scheduler_runs_it(self):
		from builder_hub import hooks

		self.assertIn("builder_hub.site_shots.hourly", hooks.scheduler_events["hourly"])
