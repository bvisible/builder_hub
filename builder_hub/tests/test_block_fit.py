# //// Neoffice — added file (no upstream equivalent): tests of the responsive measure of the hub's blocks.
"""What is pinned: a measure belongs to a version of a block (its tree, its ground, the measure's version), so a changed block is measured again;
the catalogues of the generator and of the editor serve only the blocks measured as they are and holding on every screen; the form measures a
block it is about to offer when its tree has no measure, refuses one whose measure fails, lets a draft be, and does not stop on a browser that
does not start; a run measures at most `limit` blocks, the offered ones before the drafts. Then the browser itself, where the bench has it: a
block that holds passes, a nowrap line of 1200px fails at 375px with what ran off and the sideways scroll."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from builder_hub import block_fit, blocks
from builder_hub.builder_hub.doctype.hub_block import hub_block
from builder_hub.tests.test_blocks import form, row


class TestAMeasureBelongsToAVersion(unittest.TestCase):
	def test_the_hash_follows_the_tree_the_ground_and_the_measure(self):
		base = block_fit.fit_hash(row())
		self.assertEqual(base, block_fit.fit_hash(row()))
		self.assertNotEqual(base, block_fit.fit_hash(row(tree=row()["tree"] + "\n# changed")))
		self.assertNotEqual(base, block_fit.fit_hash(row(ground="deep")))
		with patch.object(block_fit, "MEASURE", block_fit.MEASURE + 1):
			self.assertNotEqual(base, block_fit.fit_hash(row()))

	def test_a_block_measured_as_it_is_and_holding_fits(self):
		self.assertTrue(block_fit.fits(row()))

	def test_a_block_whose_measure_failed_or_is_of_another_tree_or_missing_does_not(self):
		self.assertFalse(block_fit.fits(row(fit_report="375px: runs off the screen")))
		self.assertFalse(block_fit.fits(row(fit_hash="0123456789")))
		self.assertFalse(block_fit.fits(row(fit_hash="")))
		self.assertFalse(block_fit.fits(row(fit_hash=block_fit.FAILED + block_fit.fit_hash(row()), fit_report="")))

	def test_a_block_that_could_not_be_measured_is_not_measured_again_until_its_tree_changes(self):
		current = block_fit.fit_hash(row())
		self.assertTrue(block_fit.measured(row(fit_hash=block_fit.FAILED + current)))
		self.assertFalse(block_fit.measured(row(fit_hash=block_fit.FAILED + "0123456789")))

	def test_the_report_says_each_width_that_failed_and_stays_short(self):
		found = {375: ["a", "b", "c", "d"], 600: [], 1280: ["e"]}
		self.assertEqual("375px: a; b; c\n1280px: e", block_fit.report_of(found))
		self.assertEqual("", block_fit.report_of({w: [] for w in block_fit.WIDTHS}))
		many = {w: ["x"] for w in range(10)}
		self.assertEqual(block_fit.REPORT_LINES, len(block_fit.report_of(many).splitlines()))


class TestOnlyWhatHoldsIsServed(unittest.TestCase):
	def rows(self):
		return [
			row(status="Published", preview="/a.png"),
			row(block_id="cta.overflows", status="Published", preview="/b.png", fit_report="375px: runs off the screen"),
			row(block_id="cta.unmeasured", status="Published", preview="/c.png", fit_hash=""),
		]

	def test_the_generator_is_served_only_the_blocks_that_hold(self):
		with patch.object(blocks.frappe, "get_all", return_value=self.rows()) as get_all, patch.object(blocks.frappe, "log_error"):
			result = blocks.published_blocks()
		self.assertEqual(["cta.band-test"], [b["id"] for b in result["blocks"]])
		self.assertIn("fit_hash", get_all.call_args.kwargs["fields"])
		self.assertNotIn("fit_report", result["blocks"][0])

	def test_the_editor_is_served_only_the_blocks_that_hold(self):
		with (
			patch.object(blocks.frappe, "get_all", return_value=self.rows()),
			patch.object(blocks.frappe, "log_error"),
			patch.object(blocks.frappe.utils, "get_url", side_effect=lambda u: u),
		):
			result = blocks.editor_blocks()
		self.assertEqual(["cta.band-test"], [b["id"] for b in result["blocks"]])


class TestTheFormRefusesABlockThatDoesNotHold(unittest.TestCase):
	def validate(self, doc):
		with (
			patch.object(blocks.frappe, "throw", side_effect=frappe.ValidationError("refused")) as throw,
			patch.object(hub_block, "_", lambda text: text),
			patch.object(hub_block.frappe, "log_error"),
		):
			doc.validate()
		return throw

	def test_a_draft_is_never_measured(self):
		with patch.object(block_fit, "measure_row") as measure:
			self.validate(form(status="Draft", fit_hash=""))
		measure.assert_not_called()

	def test_a_block_offered_with_a_tree_that_has_no_measure_is_measured_now(self):
		with patch.object(block_fit, "measure_row", return_value=("h", "")) as measure:
			doc = form(status="Editor", fit_hash="")
			self.validate(doc)
		measure.assert_called_once()
		self.assertEqual(("h", ""), (doc.fit_hash, doc.fit_report))

	def test_one_measured_now_that_fails_is_refused_with_what_failed(self):
		def failing(fields):
			return block_fit.fit_hash(fields), "375px: runs off the screen: div 24..1230"

		with patch.object(block_fit, "measure_row", side_effect=failing), self.assertRaises(frappe.ValidationError):
			self.validate(form(status="Published", fit_hash=""))

	def test_one_whose_measure_already_failed_is_refused_without_measuring_again(self):
		doc = form(status="Editor")
		doc.fit_report = "375px: a flattened photograph: 8x4"
		with patch.object(block_fit, "measure_row") as measure, self.assertRaises(frappe.ValidationError):
			self.validate(doc)
		measure.assert_not_called()

	def test_one_that_holds_is_offered(self):
		with patch.object(block_fit, "measure_row") as measure:
			self.validate(form(status="Published"))
		measure.assert_not_called()

	def test_a_browser_that_does_not_start_does_not_stop_the_form(self):
		with patch.object(block_fit, "measure_row", side_effect=RuntimeError("no browser")):
			self.validate(form(status="Editor", fit_hash=""))

	def test_the_seed_sync_and_a_migrate_do_not_measure(self):
		doc = form(status="Published", fit_hash="")
		doc.flags.in_seed_sync = True
		with patch.object(block_fit, "measure_row") as measure:
			self.validate(doc)
		measure.assert_not_called()


class TestARun(unittest.TestCase):
	def test_it_measures_at_most_the_limit_the_offered_blocks_first_and_writes_each_result(self):
		rows = [
			row(name="a.draft", block_id="a.draft", status="Draft", fit_hash=""),
			row(name="b.offered", block_id="b.offered", status="Editor", fit_hash=""),
			row(name="c.done", block_id="c.done", status="Published"),
		]
		fake = MagicMock()
		fake.get_all.return_value = rows
		with (
			patch.object(block_fit, "frappe", fake),
			patch.object(block_fit, "render", return_value="<html></html>"),
			patch.object(block_fit, "measure", return_value=["375px: runs off the screen"]) as measure,
			patch("builder_hub.blocks.clear_block_cache") as cleared,
		):
			lines = block_fit.measure_blocks(limit=1)
		self.assertEqual(1, len(measure.call_args.args[0]))
		self.assertEqual(["b.offered: 375px: runs off the screen"], lines)
		name, values = fake.db.set_value.call_args.args[1], fake.db.set_value.call_args.args[2]
		self.assertEqual("b.offered", name)
		self.assertEqual("375px: runs off the screen", values["fit_report"])
		cleared.assert_called_once()


def browser_available() -> bool:
	try:
		import playwright.sync_api
	except ImportError:
		return False
	return True


@unittest.skipUnless(browser_available(), "no Playwright on this bench")
class TestTheBrowser(unittest.TestCase):
	HOLDS = "<html><body style='margin:0'><section style='padding:24px'><h2 style='font-size:28px'>Un titre</h2><p style='font-size:16px'>Une phrase qui passe à la ligne comme il faut sur un téléphone.</p></section></body></html>"
	RUNS_OFF = "<html><body style='margin:0'><section style='padding:24px'><p style='white-space:nowrap;font-size:16px'>" + "Une ligne qui ne passe jamais à la ligne " * 8 + "</p></section></body></html>"

	WIDE = "<html><body style='margin:0'><section><div style='width:900px;height:40px;background:#ccc'></div></section></body></html>"

	def test_a_page_that_holds_passes_and_a_nowrap_line_or_a_wide_box_fails_on_a_phone(self):
		holds, nowrap, wide = block_fit.measure([self.HOLDS, self.RUNS_OFF, self.WIDE])
		self.assertEqual("", holds)
		self.assertIn("375px:", nowrap)
		self.assertIn("a text wider than its box", nowrap)
		self.assertIn("the page scrolls sideways", nowrap)
		self.assertIn("runs off the screen: div", wide)
		self.assertNotIn("1280px", wide)


if __name__ == "__main__":
	unittest.main()
