# //// Neoffice — added file (no upstream equivalent): tests of the thumbnails of the hub's blocks.
"""What is pinned: a thumbnail belongs to a version of a block (its tree, its ground, the renderer's), so a changed block is photographed again
and an unchanged one is not; a block that failed is not tried again until its tree changes; the thumbnail is the first screen, scaled; a run
makes at most `limit` pictures with one browser, writes the picture and its hash, remembers a failure, and clears the catalogue's cache. The
browser itself is not run here (the hub has it, the tests do not need it)."""

import unittest
from unittest.mock import MagicMock, patch

import yaml

from builder_hub import block_shots
from builder_hub.tests.test_blocks import TREE


def row(**over):
	data = {
		"name": "cta.band-test",
		"block_id": "cta.band-test",
		"tree": yaml.safe_dump(TREE, sort_keys=False),
		"ground": "plain",
		"preview": "",
		"preview_hash": "",
	}
	data.update(over)
	return data


class TestWhenABlockNeedsAPicture(unittest.TestCase):
	def test_the_hash_follows_the_tree_the_ground_and_the_renderer(self):
		base = block_shots.preview_hash(row())
		self.assertEqual(base, block_shots.preview_hash(row()))
		self.assertNotEqual(base, block_shots.preview_hash(row(tree=row()["tree"] + "\n# changed")))
		self.assertNotEqual(base, block_shots.preview_hash(row(ground="deep")))
		with patch.object(block_shots, "RENDERER", block_shots.RENDERER + 1):
			self.assertNotEqual(base, block_shots.preview_hash(row()))

	def test_the_component_a_block_carries_is_in_the_hash_and_one_without_keeps_its_hash(self):
		base = block_shots.preview_hash(row())
		self.assertEqual(base, block_shots.preview_hash(row(form=0, component="")))
		self.assertNotEqual(base, block_shots.preview_hash(row(form=1, component="opening_hours.html")))
		self.assertNotEqual(
			block_shots.preview_hash(row(form=1, component="opening_hours.html")),
			block_shots.preview_hash(row(form=1, component="product_carousel.html")),
		)

	def test_a_block_with_no_picture_needs_one(self):
		self.assertTrue(block_shots.needs_a_picture(row()))

	def test_a_block_with_a_picture_of_its_tree_does_not(self):
		current = block_shots.preview_hash(row())
		self.assertFalse(block_shots.needs_a_picture(row(preview="/files/a.png", preview_hash=current)))

	def test_a_block_whose_picture_is_missing_or_of_an_older_tree_needs_one(self):
		current = block_shots.preview_hash(row())
		self.assertTrue(block_shots.needs_a_picture(row(preview="", preview_hash=current)))
		self.assertTrue(block_shots.needs_a_picture(row(preview="/files/a.png", preview_hash="0123456789")))

	def test_a_block_that_failed_is_not_tried_again_until_its_tree_changes(self):
		current = block_shots.preview_hash(row())
		self.assertFalse(block_shots.needs_a_picture(row(preview_hash=block_shots.FAILED + current)))
		self.assertTrue(block_shots.needs_a_picture(row(preview_hash=block_shots.FAILED + "0123456789")))


class TestTheThumbnail(unittest.TestCase):
	def test_it_is_the_first_screen_scaled_to_the_width_of_the_card(self):
		self.assertEqual((640, 225), block_shots.thumb_size(450))
		self.assertEqual((640, 450), block_shots.thumb_size(block_shots.SHOT_MAX_HEIGHT))

	def test_a_tall_section_shows_its_first_900_pixels_only(self):
		self.assertEqual(block_shots.thumb_size(900), block_shots.thumb_size(4000))

	def test_an_empty_page_still_has_a_pixel(self):
		self.assertEqual(1, block_shots.thumb_size(0)[1])

	def test_the_file_is_named_after_the_block_and_the_hash_so_that_a_new_picture_has_a_new_address(self):
		self.assertEqual("hub-block-hero.a-1b2c.png", block_shots.file_name("hero.a", "1b2c"))

	def test_a_block_is_drawn_as_a_still_page_with_sample_words(self):
		html = block_shots.render(row())
		self.assertIn("<section", html)
		self.assertNotIn("WRITE ", html)


class TestKeepingAPicture(unittest.TestCase):
	def keep(self, old_files, new_url):
		frappe = MagicMock()
		frappe.get_all.return_value = old_files
		frappe.get_doc.return_value.insert.return_value = MagicMock(file_url=new_url)
		with patch.object(block_shots, "frappe", frappe):
			url = block_shots._keep("a.one", "abc", b"png")
		return url, frappe

	def test_the_picture_it_replaces_is_deleted(self):
		url, frappe = self.keep([{"name": "F1", "file_url": "/files/old.png"}], "/files/new.png")
		self.assertEqual("/files/new.png", url)
		frappe.delete_doc.assert_called_once_with("File", "F1", ignore_permissions=True, force=True)

	def test_a_picture_identical_to_the_old_one_is_the_old_file_and_it_is_not_deleted(self):
		url, frappe = self.keep([{"name": "F1", "file_url": "/files/same.png"}], "/files/same.png")
		self.assertEqual("/files/same.png", url)
		frappe.delete_doc.assert_not_called()

	def test_the_file_is_public_and_attached_to_its_block_under_a_name_that_changes_with_the_picture(self):
		_url, frappe = self.keep([], "/files/new.png")
		values = frappe.get_doc.call_args.args[0]
		self.assertEqual(0, values["is_private"])
		self.assertEqual(("Hub Block", "a.one"), (values["attached_to_doctype"], values["attached_to_name"]))
		self.assertEqual("hub-block-a.one-abc.png", values["file_name"])


class TestMakingThePictures(unittest.TestCase):
	def run_make(self, rows, pngs, **kwargs):
		frappe = MagicMock()
		frappe.get_all.return_value = rows
		with (
			patch.object(block_shots, "frappe", frappe),
			patch.object(block_shots, "render", side_effect=lambda r: f"<html>{r['block_id']}</html>"),
			patch.object(block_shots, "shoot", return_value=pngs) as shoot,
			patch.object(
				block_shots, "_keep", side_effect=lambda name, digest, png: f"/files/{name}-{digest}.png"
			),
			patch.object(block_shots, "clear_block_cache") as clear,
		):
			lines = block_shots.make_previews(**kwargs)
		return lines, frappe, shoot, clear

	def test_it_photographs_the_blocks_that_lack_a_picture_with_one_browser_and_remembers_what_it_made(self):
		rows = [row(name="a.one", block_id="a.one"), row(name="a.two", block_id="a.two")]
		lines, frappe, shoot, clear = self.run_make(rows, [b"png1", b"png2"])
		self.assertEqual(1, shoot.call_count)
		self.assertEqual(["<html>a.one</html>", "<html>a.two</html>"], shoot.call_args.args[0])
		self.assertEqual(2, len(lines))
		first = frappe.db.set_value.call_args_list[0]
		self.assertEqual(("Hub Block", "a.one"), first.args[:2])
		self.assertTrue(first.args[2]["preview"].startswith("/files/a.one-"))
		self.assertEqual(block_shots.preview_hash(rows[0]), first.args[2]["preview_hash"])
		frappe.db.commit.assert_called_once()
		clear.assert_called_once()

	def test_it_makes_at_most_the_limit(self):
		rows = [row(name=f"a.{i}", block_id=f"a.{i}") for i in range(5)]
		lines, _frappe, shoot, _clear = self.run_make(rows, [b"p", b"p"], limit=2)
		self.assertEqual(2, len(shoot.call_args.args[0]))
		self.assertEqual(2, len(lines))

	def test_a_block_that_is_up_to_date_is_left_alone_unless_forced(self):
		done = row(preview="/files/a.png", preview_hash=block_shots.preview_hash(row()))
		lines, frappe, shoot, clear = self.run_make([done], [])
		self.assertEqual([], lines)
		shoot.assert_not_called()
		frappe.db.commit.assert_not_called()
		clear.assert_not_called()
		lines, _frappe, shoot, _clear = self.run_make([done], [b"png"], force=True)
		self.assertEqual(1, len(lines))

	def test_a_block_that_could_not_be_photographed_is_marked_so_and_the_others_go_on(self):
		rows = [row(name="a.one", block_id="a.one"), row(name="a.two", block_id="a.two")]
		lines, frappe, _shoot, _clear = self.run_make(rows, [None, b"png2"])
		self.assertEqual("a.one: failed", lines[0])
		marked = frappe.db.set_value.call_args_list[0]
		self.assertEqual(
			("preview_hash", block_shots.FAILED + block_shots.preview_hash(rows[0])), marked.args[2:]
		)
		self.assertTrue(lines[1].startswith("a.two: /files/"))

	def test_a_block_that_cannot_be_drawn_is_marked_and_logged_and_does_not_stop_the_others(self):
		rows = [row(name="a.one", block_id="a.one"), row(name="a.two", block_id="a.two")]
		frappe = MagicMock()
		frappe.get_all.return_value = rows

		def draw(r):
			if r["block_id"] == "a.one":
				raise ValueError("no tree")
			return "<html></html>"

		with (
			patch.object(block_shots, "frappe", frappe),
			patch.object(block_shots, "render", side_effect=draw),
			patch.object(block_shots, "shoot", return_value=[b"png"]) as shoot,
			patch.object(block_shots, "_keep", return_value="/files/x.png"),
			patch.object(block_shots, "clear_block_cache"),
		):
			lines = block_shots.make_previews()
		self.assertEqual(1, len(shoot.call_args.args[0]))
		self.assertEqual(1, len(lines))
		self.assertTrue(frappe.log_error.call_args.args[0].startswith("Block a.one"))

	def test_the_hourly_hook_never_raises(self):
		with (
			patch.object(block_shots, "make_previews", side_effect=RuntimeError("no browser")),
			patch.object(block_shots, "frappe") as frappe,
		):
			block_shots.hourly()
		self.assertEqual("Block thumbnails not made", frappe.log_error.call_args.args[0])
