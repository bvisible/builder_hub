# //// Neoffice — added file (no upstream equivalent): the hub's library of blocks (blocks.py, the Hub Block doctype, publish_block).
"""What is pinned: a published block is served with its tree, and one whose tree no longer lints is not; the seed files are read into
Hub Blocks, a seed block somebody edited in the hub is left alone, a seed whose file is gone is retired, an unchanged one is not saved
again; the form of a Hub Block derives its family, writes its lint report, refuses to be published with an error and counts its versions;
`publish_block` only ever writes a draft and never overwrites a published block. The database is replaced."""

import inspect
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
import yaml

from builder_hub import block_fit, blocks, publish
from builder_hub.builder_hub.doctype.hub_block import hub_block
from builder_hub.builder_hub.doctype.hub_block.hub_block import HubBlock

SEEDS = Path(blocks.__file__).resolve().parent / "block_library"

TREE = {
	"el": "section",
	"name": "band",
	"style": {"backgroundColor": "{{ground.background}}", "padding": "4rem 0"},
	"c": [
		{"el": "h2", "name": "heading", "text": "WRITE heading: 4 to 8 words"},
		{
			"el": "a",
			"name": "button",
			"attrs": {"href": "{{cta_href}}"},
			"text": "WRITE button: 2 to 4 words",
		},
	],
}


def row(**over):
	data = {
		"block_id": "cta.band-test",
		"title": "Test band",
		"family": "cta",
		"kinds": "cta",
		"look": "a band",
		"photos": 0,
		"form": 0,
		"ground": "plain",
		"motion": "None",
		"version": 3,
		"tree": yaml.safe_dump(TREE, sort_keys=False),
	}
	data.update(over)
	# a block is served only once it was measured as it is and held on every screen (block_fit.py): the rows here have
	data.setdefault("fit_hash", block_fit.fit_hash(data))
	data.setdefault("fit_report", "")
	return data


class TestWhatIsServed(unittest.TestCase):
	def test_a_published_block_is_served_with_its_tree_parsed(self):
		wire = blocks.serve(row())
		self.assertEqual("cta.band-test", wire["id"])
		self.assertEqual(["cta"], wire["kinds"])
		self.assertEqual(3, wire["version"])
		self.assertEqual(TREE, wire["tree"])

	def test_a_row_changed_behind_the_form_is_not_served_and_the_reason_is_logged(self):
		bad = yaml.safe_load(row()["tree"])
		bad["c"][0]["text"] = "Fixed words"
		with patch.object(blocks.frappe, "log_error") as log:
			self.assertIsNone(blocks.serve(row(tree=yaml.safe_dump(bad))))
		self.assertIn("fixed words", log.call_args.args[1])

	def test_a_tree_that_is_not_yaml_is_not_served(self):
		with patch.object(blocks.frappe, "log_error"):
			self.assertIsNone(blocks.serve(row(tree="el: [unclosed")))

	def test_the_catalogue_holds_the_published_blocks_that_lint_and_says_its_format(self):
		rows = [row(), row(block_id="cta.broken", tree="el: [unclosed")]
		with (
			patch.object(blocks.frappe, "get_all", return_value=rows) as get_all,
			patch.object(blocks.frappe, "log_error"),
		):
			result = blocks.published_blocks()
		self.assertEqual({"status": ("in", ("Published",))}, get_all.call_args.kwargs["filters"])
		self.assertEqual(blocks.block_format.FORMAT, result["format"])
		self.assertEqual(["cta.band-test"], [b["id"] for b in result["blocks"]])


class TestTheEditorCatalogue(unittest.TestCase):
	def test_a_family_is_listed_under_its_section_and_an_unknown_one_under_content(self):
		self.assertEqual("Hero", blocks.category_of("hero"))
		self.assertEqual("Call to action", blocks.category_of("CTA"))
		self.assertEqual("Stats", blocks.category_of("figures"))
		self.assertEqual("Content", blocks.category_of("two-column"))
		self.assertEqual("Content", blocks.category_of(""))
		self.assertEqual("Content", blocks.category_of(None))

	def test_every_section_a_family_can_land_in_is_one_the_panel_lists(self):
		self.assertEqual(len(blocks.EDITOR_SECTIONS), len(set(blocks.EDITOR_SECTIONS)))
		self.assertLessEqual(
			{*blocks.EDITOR_CATEGORIES.values(), blocks.DEFAULT_CATEGORY}, set(blocks.EDITOR_SECTIONS)
		)
		self.assertEqual(
			set(blocks.EDITOR_SECTIONS), {*blocks.EDITOR_CATEGORIES.values(), blocks.DEFAULT_CATEGORY}
		)

	def test_the_seed_families_are_listed_under_a_section(self):
		for path in SEEDS.glob("*.yaml"):
			family = blocks.read_seed(path)["block_id"].split(".")[0]
			self.assertIn(blocks.category_of(family), blocks.EDITOR_SECTIONS, family)

	def test_a_block_is_served_to_the_editor_with_its_section_its_absolute_thumbnail_and_who_else_may_choose_it(
		self,
	):
		with patch.object(blocks.frappe.utils, "get_url", side_effect=lambda u: "https://hub.test" + u):
			made = blocks.serve_for_editor(row(status="Editor", preview="/files/hub-block-cta.png"))
			generator = blocks.serve_for_editor(row(status="Published", preview="/files/x.png"))
			absolute = blocks.serve_for_editor(row(status="Editor", preview="https://cdn.test/x.png"))
		self.assertEqual("Call to action", made["category"])
		self.assertEqual("https://hub.test/files/hub-block-cta.png", made["preview"])
		self.assertFalse(made["generator"])
		self.assertTrue(generator["generator"])
		self.assertEqual("https://cdn.test/x.png", absolute["preview"])
		self.assertEqual(TREE, made["tree"])

	def test_a_block_with_no_thumbnail_yet_or_that_no_longer_lints_is_not_offered(self):
		self.assertIsNone(blocks.serve_for_editor(row(status="Editor", preview="")))
		self.assertIsNone(blocks.serve_for_editor(row(status="Editor")))
		with patch.object(blocks.frappe, "log_error"):
			self.assertIsNone(
				blocks.serve_for_editor(row(status="Editor", preview="/f.png", tree="el: [unclosed"))
			)

	def test_the_editor_catalogue_asks_for_the_editor_and_published_blocks_only(self):
		rows = [row(status="Editor", preview="/a.png"), row(block_id="cta.none", status="Editor", preview="")]
		with (
			patch.object(blocks.frappe, "get_all", return_value=rows) as get_all,
			patch.object(blocks.frappe, "log_error"),
			patch.object(blocks.frappe.utils, "get_url", side_effect=lambda u: u),
		):
			result = blocks.editor_blocks()
		self.assertEqual({"status": ("in", ("Editor", "Published"))}, get_all.call_args.kwargs["filters"])
		self.assertIn("preview", get_all.call_args.kwargs["fields"])
		self.assertEqual(["cta.band-test"], [b["id"] for b in result["blocks"]])
		self.assertEqual(blocks.block_format.FORMAT, result["format"])
		self.assertEqual(list(blocks.EDITOR_SECTIONS), result["sections"])

	def test_the_site_generator_is_still_offered_the_published_blocks_only(self):
		self.assertEqual(("Published",), blocks.GENERATOR_STATUSES)


class TestTheSeedFiles(unittest.TestCase):
	def test_a_seed_file_becomes_the_values_of_a_hub_block(self):
		values = blocks.read_seed(SEEDS / "steps.rail.yaml")
		self.assertEqual("steps.rail", values["block_id"])
		self.assertEqual("steps", values["kinds"])
		self.assertEqual("None", values["motion"])
		self.assertEqual(0, values["form"])
		self.assertEqual("section", yaml.safe_load(values["tree"])["el"])

	def test_the_two_blocks_that_move_say_how_much_and_wear_the_classes_of_the_motion_layer(self):
		counters = blocks.read_seed(SEEDS / "figures.counters.yaml")
		ticker = blocks.read_seed(SEEDS / "statement.ticker.yaml")
		self.assertEqual(("figures", "Calm"), (counters["kinds"], counters["motion"]))
		self.assertEqual(("statement, intro", "Brisk"), (ticker["kinds"], ticker["motion"]))
		self.assertEqual(3, counters["tree"].count("u-count"))
		self.assertIn("u-reveal-group", counters["tree"])
		self.assertEqual(1, ticker["tree"].count("u-marquee__group"))
		self.assertEqual(1, ticker["tree"].count("- u-marquee\n"))

	def test_a_file_that_is_not_a_block_is_refused(self):
		with tempfile.TemporaryDirectory() as folder:
			path = Path(folder) / "x.yaml"
			path.write_text("title: nothing\n")
			with self.assertRaises(ValueError):
				blocks.read_seed(path)


def library(folder, **files):
	for name, tree in files.items():
		data = {"id": name, "title": name, "kinds": ["cta"], "look": "a band", "tree": tree}
		(Path(folder) / f"{name}.yaml").write_text(yaml.safe_dump(data))


class Docs:
	"""A few Hub Blocks the database holds: {name: doc}."""

	def __init__(self, **docs):
		self.docs = docs
		self.saved, self.deleted = [], []

	def exists(self, doctype, name=None):
		return name in self.docs

	def get_doc(self, doctype, name):
		return self.docs[name]

	def new_doc(self, doctype):
		doc = MagicMock()
		doc.get.side_effect = lambda k, d=None: getattr(doc, k, d)
		doc.update.side_effect = lambda values: [setattr(doc, k, v) for k, v in values.items()]
		doc.save.side_effect = lambda **kw: (setattr(doc, "name", doc.block_id), self.saved.append(doc))
		return doc

	def get_all(self, doctype, filters=None, pluck=None, **kw):
		return [n for n, d in self.docs.items() if d.source == filters["source"]]

	def delete_doc(self, doctype, name, **kw):
		self.deleted.append(name)


def seed_doc(name, source, values):
	doc = MagicMock()
	doc.name, doc.source = name, source
	doc.get.side_effect = lambda k, d=None: values.get(k, d)
	doc.save.side_effect = lambda **kw: None
	return doc


class TestSyncingTheLibrary(unittest.TestCase):
	def sync(self, folder, docs):
		with (
			patch.object(blocks, "library_dir", return_value=Path(folder)),
			patch.object(blocks.frappe, "db", MagicMock(exists=docs.exists, commit=MagicMock())),
			patch.object(blocks.frappe, "get_doc", docs.get_doc),
			patch.object(blocks.frappe, "new_doc", docs.new_doc),
			patch.object(blocks.frappe, "get_all", docs.get_all),
			patch.object(blocks.frappe, "delete_doc", docs.delete_doc),
			patch.object(blocks, "clear_block_cache") as clear,
			patch.object(blocks.frappe, "log_error"),
		):
			changes = blocks.sync_block_library()
		return changes, clear

	def test_a_new_seed_is_added_as_published_with_its_source_set(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE})
			docs = Docs()
			changes, clear = self.sync(folder, docs)
		self.assertEqual(["cta.one: added"], changes)
		saved = docs.saved[0]
		self.assertEqual(("Published", "seed"), (saved.status, saved.source))
		self.assertTrue(saved.flags.in_seed_sync)
		clear.assert_called_once()

	def test_a_seed_that_has_not_changed_is_not_saved_again(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE})
			values = blocks.read_seed(Path(folder) / "cta.one.yaml")
			docs = Docs(**{"cta.one": seed_doc("cta.one", "seed", values)})
			changes, clear = self.sync(folder, docs)
		self.assertEqual([], changes)
		docs.docs["cta.one"].save.assert_not_called()
		clear.assert_not_called()

	def test_a_seed_whose_file_changed_is_updated(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE})
			values = blocks.read_seed(Path(folder) / "cta.one.yaml")
			docs = Docs(**{"cta.one": seed_doc("cta.one", "seed", {**values, "look": "an older look"})})
			changes, _ = self.sync(folder, docs)
		self.assertEqual(["cta.one: updated"], changes)
		docs.docs["cta.one"].save.assert_called_once()

	def test_a_block_a_person_edited_in_the_hub_is_left_alone(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE})
			docs = Docs(**{"cta.one": seed_doc("cta.one", "edited in the hub", {})})
			changes, _ = self.sync(folder, docs)
		self.assertEqual(["cta.one: edited in the hub, kept"], changes)
		docs.docs["cta.one"].save.assert_not_called()

	def test_a_seed_whose_file_is_gone_is_retired_but_one_a_person_took_over_stays(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE})
			values = blocks.read_seed(Path(folder) / "cta.one.yaml")
			docs = Docs(
				**{
					"cta.one": seed_doc("cta.one", "seed", values),
					"cta.old": seed_doc("cta.old", "seed", {}),
					"cta.mine": seed_doc("cta.mine", "edited in the hub", {}),
				}
			)
			changes, _ = self.sync(folder, docs)
		self.assertEqual(["cta.old: retired"], changes)
		self.assertEqual(["cta.old"], docs.deleted)

	def test_an_app_with_no_library_folder_retires_nothing(self):
		with tempfile.TemporaryDirectory() as folder:
			docs = Docs(**{"cta.old": seed_doc("cta.old", "seed", {})})
			changes, _ = self.sync(Path(folder) / "missing", docs)
		self.assertEqual([], changes)
		self.assertEqual([], docs.deleted)

	def test_a_seed_that_does_not_validate_is_said_and_the_others_go_on(self):
		with tempfile.TemporaryDirectory() as folder:
			library(folder, **{"cta.one": TREE, "cta.two": TREE})
			docs = Docs()
			original = docs.new_doc

			def refuse_first(doctype):
				doc = original(doctype)
				if not docs.saved and not getattr(refuse_first, "done", False):
					refuse_first.done = True
					doc.save.side_effect = frappe.ValidationError("a block with errors")
				return doc

			docs.new_doc = refuse_first
			changes, _ = self.sync(folder, docs)
		self.assertEqual(["cta.one: REFUSED", "cta.two: added"], changes)


def form(**over):
	"""A HubBlock form without a database: the fields as plain attributes."""
	doc = HubBlock.__new__(HubBlock)
	doc.flags = frappe._dict()
	values = {
		"block_id": " cta.band-test ",
		"title": "Test band",
		"status": "Draft",
		"kinds": "cta , cta",
		"photos": 0,
		"form": 0,
		"ground": "plain",
		"motion": "None",
		"look": "a band",
		"tree": yaml.safe_dump(TREE, sort_keys=False),
		"version": 1,
		"source": "",
		"family": "",
		"lint_report": "",
		"format": 0,
	}
	values.update(over)
	# measured as it is and holding on every screen, unless the test says otherwise (block_fit.py)
	values.setdefault("fit_hash", block_fit.fit_hash(values))
	values.setdefault("fit_report", "")
	for key, value in values.items():
		setattr(doc, key, value)
	doc.get_doc_before_save = lambda: over.get("_before")
	return doc


class TestTheForm(unittest.TestCase):
	@staticmethod
	@contextmanager
	def throwing():
		with (
			patch.object(blocks.frappe, "throw", side_effect=frappe.ValidationError("refused")),
			patch.object(hub_block, "_", lambda text: text),
		):
			yield

	def test_saving_derives_the_family_and_tidies_the_id_and_kinds(self):
		doc = form()
		with self.throwing():
			doc.validate()
		self.assertEqual("cta.band-test", doc.block_id)
		self.assertEqual("cta", doc.family)
		self.assertEqual("cta", doc.kinds)
		self.assertEqual(blocks.block_format.FORMAT, doc.format)
		self.assertEqual("", doc.lint_report)
		self.assertEqual("edited in the hub", doc.source)

	def test_a_draft_with_an_error_is_saved_with_the_report_but_cannot_be_published(self):
		bad = yaml.safe_load(yaml.safe_dump(TREE))
		bad["c"][0]["text"] = "Fixed words"
		doc = form(tree=yaml.safe_dump(bad))
		with self.throwing():
			doc.validate()
		self.assertIn("ERROR", doc.lint_report)
		self.assertIn("fixed words", doc.lint_report)
		doc.status = "Published"
		with self.throwing(), self.assertRaises(frappe.ValidationError):
			doc.validate()

	def test_a_block_kept_for_the_editor_is_refused_with_an_error_as_a_published_one_is(self):
		bad = yaml.safe_load(yaml.safe_dump(TREE))
		bad["c"][0]["text"] = "Fixed words"
		doc = form(tree=yaml.safe_dump(bad), status="Editor")
		with self.throwing(), self.assertRaises(frappe.ValidationError):
			doc.validate()
		doc = form(status="Editor")
		with self.throwing():
			doc.validate()
		self.assertEqual("", doc.lint_report)

	def test_a_tree_that_is_not_yaml_is_reported_not_raised_for_a_draft(self):
		doc = form(tree="el: [unclosed")
		with self.throwing():
			doc.validate()
		self.assertIn("not valid YAML", doc.lint_report)

	def test_a_changed_tree_counts_a_new_version(self):
		before = MagicMock(tree="el: section", version=4)
		doc = form(_before=before)
		with self.throwing():
			doc.validate()
		self.assertEqual(5, doc.version)

	def test_a_person_changing_a_seed_block_takes_it_over_from_the_files(self):
		before = MagicMock(tree="el: section", version=1)
		doc = form(_before=before, source="seed")
		with self.throwing():
			doc.validate()
		self.assertEqual("edited in the hub", doc.source)

	def test_the_sync_changing_a_seed_block_keeps_it_a_seed(self):
		before = MagicMock(tree="el: section", version=1)
		doc = form(_before=before, source="seed")
		doc.flags.in_seed_sync = True
		with self.throwing():
			doc.validate()
		self.assertEqual("seed", doc.source)


class TestPublishingABlock(unittest.TestCase):
	def run_publish(self, payload, existing=None):
		db = MagicMock()
		db.exists.side_effect = lambda doctype, name=None: existing is not None and name == existing.name
		doc = existing or MagicMock()
		saved = MagicMock()
		doc.save = saved
		doc.name = payload["id"] if existing is None else existing.name
		doc.version, doc.lint_report = 1, ""
		request = MagicMock()
		request.get_data.return_value = yaml_bytes(payload)
		with (
			patch.object(publish, "_check_publisher"),
			patch.object(publish.frappe, "db", db),
			patch.object(publish.frappe, "request", request),
			patch.object(publish.frappe, "get_doc", return_value=doc),
			patch.object(publish.frappe, "new_doc", return_value=doc),
			patch.object(publish.frappe, "session", MagicMock(user="designer@example.org")),
			patch.object(publish.frappe, "throw", side_effect=frappe.ValidationError("refused")),
			patch.object(publish, "_", lambda text: text),
		):
			result = inspect.unwrap(publish.publish_block)()
		return result, doc

	def test_a_new_block_is_kept_as_a_draft_with_its_publisher_named(self):
		result, doc = self.run_publish(
			{"id": "cta.new", "title": "New", "kinds": ["cta"], "look": "a band", "tree": TREE}
		)
		self.assertEqual("Draft", doc.status)
		self.assertEqual("published by designer@example.org", doc.source)
		doc.save.assert_called_once()
		self.assertEqual("Draft", result["status"])

	def test_a_published_block_is_not_overwritten(self):
		existing = MagicMock(status="Published")
		existing.name = "cta.live"
		with self.assertRaises(frappe.ValidationError):
			self.run_publish(
				{"id": "cta.live", "title": "x", "kinds": ["cta"], "look": "x", "tree": TREE}, existing
			)
		existing.save.assert_not_called()

	def test_a_draft_is_replaced_by_the_new_revision_and_stays_a_draft(self):
		existing = MagicMock(status="Draft")
		existing.name = "cta.draft"
		_, doc = self.run_publish(
			{"id": "cta.draft", "title": "x", "kinds": ["cta"], "look": "x", "tree": TREE}, existing
		)
		self.assertEqual("Draft", doc.status)
		doc.update.assert_called_once()
		self.assertEqual("cta.draft", doc.update.call_args.args[0]["block_id"])

	def test_the_fields_of_a_payload_take_a_tree_as_a_mapping_or_as_text(self):
		as_mapping = publish._block_fields({"id": "cta.x", "kinds": ["cta", "steps"], "tree": TREE})
		as_text = publish._block_fields({"id": "cta.x", "kinds": "cta, steps", "tree": yaml.safe_dump(TREE)})
		self.assertEqual("cta, steps", as_mapping["kinds"])
		self.assertEqual(yaml.safe_load(as_mapping["tree"]), yaml.safe_load(as_text["tree"]))


def yaml_bytes(payload):
	import json

	return json.dumps(payload).encode("utf-8")


if __name__ == "__main__":
	unittest.main()
