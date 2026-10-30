# //// Neoffice — added file (no upstream equivalent): what makes a tree a block of the hub's library (block_format.py).
"""A block ends up in every site that is generated, so the linter is the gate. Pinned here: the four seed blocks pass it; each way a tree can
be wrong (a token nobody fills, words fixed for every site, an image from an address, a script, a photograph count that does not match, a
form with no place for it) is an error with a message that says what to change; a colour written out is only a warning. No Frappe."""

import copy
import unittest
from pathlib import Path

import yaml

from builder_hub import block_format

LIBRARY = Path(__file__).resolve().parent.parent / "block_library"


def seed(name):
	return yaml.safe_load((LIBRARY / name).read_text(encoding="utf-8"))


def lint_seed(data, **over):
	args = {
		"block_id": data["id"],
		"kinds": data["kinds"],
		"photos": data.get("photos", 0),
		"form": data.get("form", False),
		"motion": data.get("motion", "None"),
	}
	args.update(over)
	return block_format.lint(data["tree"], **args)


def minimal():
	return {
		"el": "section",
		"name": "s",
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


def check(tree, **over):
	args = {"block_id": "cta.test", "kinds": ["cta"], "photos": 0, "form": False, "motion": "None"}
	args.update(over)
	return block_format.lint(tree, **args)


class TestTheSeedBlocks(unittest.TestCase):
	def test_every_seed_block_lints_clean_without_a_warning(self):
		files = sorted(p.name for p in LIBRARY.glob("*.yaml"))
		self.assertGreaterEqual(len(files), 4)
		for name in files:
			with self.subTest(name):
				errors, warnings = lint_seed(seed(name))
				self.assertEqual(([], []), (errors, warnings))

	def test_a_seed_file_is_named_after_its_id(self):
		for path in LIBRARY.glob("*.yaml"):
			with self.subTest(path.name):
				self.assertEqual(path.stem, yaml.safe_load(path.read_text(encoding="utf-8"))["id"])

	def test_the_ids_are_unique_and_each_kind_is_a_kind_of_the_plan(self):
		ids = [seed(p.name)["id"] for p in LIBRARY.glob("*.yaml")]
		self.assertEqual(len(ids), len(set(ids)))


class TestAWellFormedBlock(unittest.TestCase):
	def test_the_minimal_block_passes(self):
		self.assertEqual(([], []), check(minimal()))

	def test_parse_tree_takes_a_mapping_or_a_list_of_one(self):
		one = yaml.safe_dump(minimal())
		self.assertEqual(minimal(), block_format.parse_tree(one))
		self.assertEqual(minimal(), block_format.parse_tree(yaml.safe_dump([minimal()])))

	def test_parse_tree_refuses_what_is_not_a_node(self):
		for text in ("", "just words", "- a\n- b", "el: [unclosed"):
			with self.subTest(text), self.assertRaises(ValueError):
				block_format.parse_tree(text)


class TestWhatIsRefused(unittest.TestCase):
	def errors(self, tree, **over):
		return check(tree, **over)[0]

	def test_an_id_without_a_family_is_refused(self):
		self.assertTrue(
			any("must be <family>.<variant>" in e for e in self.errors(minimal(), block_id="nofamily"))
		)

	def test_a_block_with_no_kinds_is_refused(self):
		self.assertTrue(any("kinds is empty" in e for e in self.errors(minimal(), kinds=[])))

	def test_the_root_must_be_a_section(self):
		tree = minimal()
		tree["el"] = "div"
		self.assertTrue(any("must be a `section`" in e for e in self.errors(tree)))

	def test_a_tag_that_runs_a_script_or_loads_a_page_is_refused(self):
		for tag in ("script", "iframe", "style", "form", "input", "object"):
			tree = minimal()
			tree["c"].append({"el": tag, "text": "WRITE text: x"})
			with self.subTest(tag):
				self.assertTrue(any("allowed tags" in e for e in self.errors(tree)))

	def test_an_unknown_token_is_refused(self):
		tree = minimal()
		tree["style"]["color"] = "{{brand_pink}}"
		self.assertTrue(any("unknown token {{brand_pink}}" in e for e in self.errors(tree)))

	def test_words_fixed_for_every_site_are_refused_but_signs_are_fine(self):
		tree = minimal()
		tree["c"].append({"el": "p", "name": "x", "text": "Nos services"})
		self.assertTrue(any("fixed words" in e for e in self.errors(tree)))
		tree["c"][-1]["text"] = "→"
		self.assertEqual([], self.errors(tree))

	def test_a_block_with_no_slot_is_a_picture(self):
		tree = {"el": "section", "c": [{"el": "hr"}]}
		self.assertTrue(any("no `WRITE" in e for e in self.errors(tree)))

	def test_a_write_that_is_not_a_slot_is_refused(self):
		tree = minimal()
		tree["c"][0]["text"] = "WRITE heading 4 to 8 words"
		self.assertTrue(any("`WRITE` must start" in e or "fixed words" in e for e in self.errors(tree)))

	def test_a_slot_with_a_token_inside_is_refused(self):
		tree = minimal()
		tree["c"][0]["text"] = "WRITE heading: in {{primary}}"
		self.assertTrue(any("guidance, not tokens" in e for e in self.errors(tree)))

	def test_an_image_comes_from_a_photograph_slot_never_from_an_address(self):
		img = {"el": "img", "attrs": {"src": "https://example.org/a.jpg", "alt": "WRITE alt: a scene"}}
		tree = minimal()
		tree["c"].append(img)
		self.assertTrue(any("never from an address" in e for e in self.errors(tree, photos=0)))

	def test_photos_declared_must_match_photos_used(self):
		img = {"el": "img", "attrs": {"src": "{{photo.0}}", "alt": "WRITE alt: a scene"}}
		tree = minimal()
		tree["c"].append(img)
		self.assertEqual([], self.errors(tree, photos=1))
		self.assertTrue(any("photos is 0" in e for e in self.errors(tree, photos=0)))
		self.assertTrue(any("photos is 2" in e for e in self.errors(tree, photos=2)))

	def test_an_image_needs_an_alt_slot(self):
		tree = minimal()
		tree["c"].append({"el": "img", "attrs": {"src": "{{photo.0}}"}})
		self.assertTrue(any("needs an `alt` slot" in e for e in self.errors(tree, photos=1)))

	def test_a_link_goes_to_the_site_an_anchor_a_phone_or_a_mail_never_a_script(self):
		for href, ok in (
			("javascript:alert(1)", False),
			("https://evil.example", False),
			("/contact", True),
			("#top", True),
			("tel:+41000", True),
			("mailto:a@b.ch", True),
			("{{cta_href}}", True),
		):
			tree = minimal()
			tree["c"][1]["attrs"]["href"] = href
			with self.subTest(href):
				self.assertEqual(ok, not self.errors(tree))

	def test_an_event_handler_or_inline_style_attribute_is_refused(self):
		for attr in ("onclick", "onload", "style", "srcdoc"):
			tree = minimal()
			tree["c"][1]["attrs"][attr] = "x"
			with self.subTest(attr):
				self.assertTrue(any("not allowed" in e for e in self.errors(tree)))

	def test_a_stylesheet_value_cannot_reach_out_or_carry_markup(self):
		for value in (
			"url(https://x.test/a.png)",
			"expression(alert(1))",
			"red; } body { display: none",
			"<b>",
			"@import 'x'",
		):
			tree = minimal()
			tree["style"]["backgroundImage"] = value
			with self.subTest(value):
				self.assertTrue(any("may not carry" in e for e in self.errors(tree)))

	def test_a_property_that_is_not_camel_case_is_refused(self):
		tree = minimal()
		tree["style"]["background-color"] = "red"
		self.assertTrue(any("camelCase" in e for e in self.errors(tree)))

	def test_a_form_block_needs_the_include_and_only_a_form_block_may_carry_it(self):
		tree = minimal()
		self.assertEqual([], self.errors(tree))
		self.assertTrue(any("never carries" in e for e in self.errors(tree, form=True)))
		tree["c"].append({"el": "div", "name": "form", "text": "{{include_component}}"})
		self.assertEqual([], self.errors(tree, form=True))
		self.assertTrue(any("form is not set" in e for e in self.errors(tree, form=False)))

	def test_a_motion_class_needs_a_motion_style(self):
		tree = minimal()
		tree["c"][0]["classes"] = ["u-reveal"]
		self.assertTrue(any("motion is None" in e for e in self.errors(tree, motion="None")))
		self.assertEqual([], self.errors(tree, motion="Calm"))

	def test_every_part_of_the_motion_layer_is_a_motion_class_and_the_rest_is_not(self):
		for name in ("u-reveal", "u-reveal-group", "u-marquee", "u-marquee__track", "u-marquee__group", "u-count"):
			tree = minimal()
			tree["c"][0]["classes"] = [name]
			with self.subTest(name):
				self.assertTrue(any("motion is None" in e for e in self.errors(tree, motion="None")))
				self.assertEqual([], self.errors(tree, motion="Brisk"))
		tree = minimal()
		tree["c"][0]["classes"] = ["u-card", "u-grid", "u-grid--3", "u-media"]
		self.assertEqual([], self.errors(tree, motion="None"))

	def warnings(self, tree, **kw):
		args = {"block_id": "cta.test", "kinds": ["cta"], "photos": 0, "form": False, "motion": "Calm"}
		return block_format.lint(tree, **{**args, **kw})[1]

	def test_a_reveal_under_a_box_that_clips_is_warned_it_never_plays(self):
		for clipping in ("hidden", "auto", "scroll"):
			tree = minimal()
			tree["style"] = {"overflow": clipping}
			tree["c"][0]["classes"] = ["u-reveal"]
			with self.subTest(clipping):
				self.assertTrue(any("never play" in w for w in self.warnings(tree)), clipping)
		tree = minimal()
		tree["m_style"] = {"overflowX": "hidden"}  # on a phone only, still a scroll container there
		tree["c"][0]["classes"] = ["u-reveal"]
		self.assertTrue(any("never play" in w for w in self.warnings(tree)))

	def test_overflow_clip_or_the_reveal_on_the_clipping_box_itself_is_fine(self):
		tree = minimal()
		tree["style"] = {"overflow": "clip"}
		tree["c"][0]["classes"] = ["u-reveal"]
		self.assertEqual([], self.warnings(tree))
		tree = minimal()
		tree["classes"] = ["u-reveal"]  # the box that clips is the subject: it is not inside itself
		tree["style"] = {"overflow": "hidden"}
		self.assertEqual([], self.warnings(tree))

	def test_the_children_of_a_group_follow_the_group_if_it_clips(self):
		tree = minimal()
		tree["c"][0]["classes"] = ["u-reveal-group"]
		tree["c"][0]["style"] = {"overflow": "hidden"}
		self.assertTrue(any("never play" in w for w in self.warnings(tree)))
		tree["c"][0]["style"] = {"overflow": "clip"}
		self.assertEqual([], self.warnings(tree))

	def test_a_sibling_of_a_clipping_box_is_not_inside_it(self):
		tree = minimal()
		tree["c"][0]["style"] = {"overflow": "hidden"}
		tree["c"].append({"el": "p", "name": "later", "classes": ["u-reveal"], "text": "WRITE text: x"})
		self.assertEqual([], self.warnings(tree))

	def test_a_node_has_text_or_children_not_both(self):
		tree = minimal()
		tree["c"][0]["c"] = [{"el": "span", "text": "WRITE text: x"}]
		self.assertTrue(any("not both" in e for e in self.errors(tree)))

	def test_a_tree_nested_too_deep_or_too_large_is_refused(self):
		tree = minimal()
		node = tree
		for _ in range(block_format.MAX_DEPTH + 1):
			child = {"el": "div", "c": []}
			node.setdefault("c", []).append(child)
			node = child
		self.assertTrue(any("nested deeper" in e for e in self.errors(tree)))
		wide = minimal()
		wide["c"] += [{"el": "span", "text": "WRITE text: x"} for _ in range(block_format.MAX_NODES)]
		self.assertTrue(any("more than" in e for e in self.errors(wide)))

	def test_an_unknown_key_or_ground_is_refused(self):
		tree = minimal()
		tree["colour"] = "red"
		tree["c"][0]["ground"] = "neon"
		errors = self.errors(tree)
		self.assertTrue(any("unknown keys" in e for e in errors))
		self.assertTrue(any("ground must be" in e for e in errors))

	def test_a_motion_or_photo_count_out_of_range_is_refused(self):
		self.assertTrue(any("motion `Wild`" in e for e in self.errors(minimal(), motion="Wild")))
		self.assertTrue(any("photos must be" in e for e in self.errors(minimal(), photos=9)))


class TestWhatIsOnlyWarned(unittest.TestCase):
	def test_a_colour_written_out_is_a_warning_not_an_error(self):
		tree = minimal()
		tree["style"]["color"] = "#112233"
		errors, warnings = check(tree)
		self.assertEqual([], errors)
		self.assertTrue(any("a colour written out" in w for w in warnings))

	def test_a_colour_inside_a_token_is_not_flagged(self):
		tree = copy.deepcopy(minimal())
		tree["style"]["color"] = "{{ground.ink}}"
		self.assertEqual(([], []), check(tree))


if __name__ == "__main__":
	unittest.main()
