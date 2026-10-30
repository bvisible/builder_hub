# //// Neoffice — added file (no upstream equivalent): from a page drawn in the Builder editor to a hub block, and back (block_compile.py).
"""Blocks are drawn in the hub's editor. What is pinned: the page of the editor gives the tree of the block (tokens named by role, slots, photographs,
the form, the grounds); what the editor cannot say (a variable of another palette, a component, a repeater, an image that is not a photograph of the
site) is an error that names the block; and the way back is exact: each seed block, turned into a page and compiled again, is the same tree, which
the linter still accepts. The editor is replaced by a few lines that store a tree the way the editor does. No Frappe."""

import copy
import unittest
from pathlib import Path

import yaml

from builder_hub import block_compile as C
from builder_hub import block_format

LIBRARY = Path(__file__).resolve().parent.parent / "block_library"
SEEDS = sorted(LIBRARY.glob("*.yaml"))


def stored_like_the_editor(node: dict, counter=None) -> dict:
	"""A node of the writer's format as the editor stores it: element, blockName, three style maps, attributes, innerHTML, children."""
	counter = counter if counter is not None else [0]
	counter[0] += 1
	block = {"blockId": f"b{counter[0]:08d}", "element": node["el"]}
	if node.get("name"):
		block["blockName"] = node["name"]
	if node.get("classes"):
		block["classes"] = list(node["classes"])
	for source, target in (("style", "baseStyles"), ("t_style", "tabletStyles"), ("m_style", "mobileStyles")):
		if node.get(source):
			block[target] = dict(node[source])
	if node.get("attrs"):
		block["attributes"] = {k: str(v) for k, v in node["attrs"].items()}
	if "text" in node:
		block["innerHTML"] = node["text"]
	if node.get("c"):
		block["children"] = [stored_like_the_editor(child, counter) for child in node["c"]]
	return block


def page_of(tree):
	"""The blocks of the page the editor would hold after `to_page_yaml(tree)`: the body and its one section."""
	body = yaml.safe_load(C.to_page_yaml(tree))
	return [stored_like_the_editor(body)]


def section(**over):
	block = {
		"blockId": "s1",
		"element": "section",
		"blockName": "band",
		"baseStyles": {"backgroundColor": "var(--hb-ground-background)", "padding": "4rem 0"},
		"children": [
			{
				"blockId": "h1",
				"element": "h2",
				"blockName": "heading",
				"baseStyles": {"fontFamily": "var(--hb-font-heading)", "color": "var(--hb-ground-ink)"},
				"innerHTML": "WRITE heading: 4 to 8 words",
			},
			{
				"blockId": "a1",
				"element": "a",
				"blockName": "button",
				"classes": ["u-btn", "u-btn--primary"],
				"attributes": {"href": "{{cta_href}}"},
				"innerHTML": "WRITE button: 2 to 4 words",
			},
		],
	}
	block.update(over)
	return block


def compiled(blocks):
	return C.compile_blocks(blocks if isinstance(blocks, list) else [blocks])


class TestThePalette(unittest.TestCase):
	def test_every_role_is_a_token_of_the_block_format_and_comes_back_from_its_variable(self):
		for role in C.ROLES:
			with self.subTest(role):
				self.assertEqual(role, C.role_of_token(C.token_key(role)))

	def test_a_variable_of_another_palette_has_no_role(self):
		for key in ("qgch-primary", "surface-color", "hb-brand-pink", "hb-", "primary"):
			with self.subTest(key):
				self.assertIsNone(C.role_of_token(key))

	def test_the_palette_names_each_role_once_with_a_known_type(self):
		roles = [role for role, _t, _v in C.PALETTE]
		self.assertEqual(len(roles), len(set(roles)))
		self.assertEqual({"Color", "Font", "Dimension"}, {t for _r, t, _v in C.PALETTE})


class TestWhatTheEditorGives(unittest.TestCase):
	def test_a_section_becomes_the_tree_with_roles_for_tokens_and_slots_kept(self):
		result = compiled(section())
		self.assertEqual("", result.report())
		tree = result.tree
		self.assertEqual("section", tree["el"])
		self.assertEqual("{{ground.background}}", tree["style"]["backgroundColor"])
		self.assertEqual("{{font_heading}}", tree["c"][0]["style"]["fontFamily"])
		self.assertEqual("WRITE heading: 4 to 8 words", tree["c"][0]["text"])
		self.assertEqual({"href": "{{cta_href}}"}, tree["c"][1]["attrs"])
		self.assertEqual(["u-btn", "u-btn--primary"], tree["c"][1]["classes"])

	def test_a_link_marked_as_the_call_to_action_goes_where_the_site_sends_its_visitors(self):
		link = {
			"blockId": "l",
			"element": "a",
			"attributes": {"href": "/somewhere", "data-cta": "true"},
			"innerHTML": "WRITE button: 2 words",
		}
		self.assertEqual({"href": "{{cta_href}}"}, compiled(section(children=[link])).tree["c"][0]["attrs"])
		other = {"blockId": "d", "element": "div", "attributes": {"data-cta": "true"}}
		self.assertTrue(
			any("data-cta is for a link" in e for e in compiled(section(children=[other])).errors)
		)

	def test_a_link_typed_with_the_token_itself_is_still_read(self):
		link = {
			"blockId": "l",
			"element": "a",
			"attributes": {"href": "{{cta_href}}"},
			"innerHTML": "WRITE button: 2 words",
		}
		self.assertEqual({"href": "{{cta_href}}"}, compiled(section(children=[link])).tree["c"][0]["attrs"])

	def test_the_first_section_of_a_page_is_the_block_and_a_second_is_said(self):
		body = {
			"blockId": "b",
			"element": "div",
			"children": [section(blockName="first"), section(blockName="second")],
		}
		result = compiled(body)
		self.assertEqual("first", result.tree["name"])
		self.assertIn("2 sections", result.warnings[0])

	def test_a_page_with_no_section_is_an_error(self):
		result = compiled({"blockId": "b", "element": "div"})
		self.assertIsNone(result.tree)
		self.assertIn("no section", result.errors[0])

	def test_a_photograph_is_an_image_with_its_number_and_gets_an_alt_to_write(self):
		image = {
			"blockId": "i",
			"element": "img",
			"attributes": {"src": "/files/sample.png", "data-photo": "0"},
		}
		result = compiled(section(children=[image]))
		node = result.tree["c"][0]
		self.assertEqual("{{photo.0}}", node["attrs"]["src"])
		self.assertTrue(node["attrs"]["alt"].startswith("WRITE alt:"))
		self.assertNotIn("data-photo", node["attrs"])
		self.assertEqual(1, result.photos)

	def test_an_alt_the_designer_wrote_as_a_slot_is_kept(self):
		image = {
			"blockId": "i",
			"element": "img",
			"attributes": {"data-photo": "0", "alt": "WRITE alt: the dish, 10 words"},
		}
		self.assertEqual(
			"WRITE alt: the dish, 10 words", compiled(section(children=[image])).tree["c"][0]["attrs"]["alt"]
		)

	def test_an_image_that_is_not_a_photograph_of_the_site_is_an_error(self):
		result = compiled(
			section(children=[{"blockId": "i", "element": "img", "attributes": {"src": "/files/logo.png"}}])
		)
		self.assertTrue(any("set data-photo" in e for e in result.errors))

	def test_data_photo_on_something_else_or_not_a_number_is_an_error(self):
		bad = section(
			children=[
				{"blockId": "d", "element": "div", "attributes": {"data-photo": "0"}},
				{"blockId": "i", "element": "img", "attributes": {"data-photo": "first"}},
			]
		)
		errors = compiled(bad).errors
		self.assertTrue(any("data-photo is for an image" in e for e in errors))
		self.assertTrue(any("must be a number" in e for e in errors))

	def test_a_ground_set_on_a_block_is_the_ground_of_its_subtree(self):
		band = {
			"blockId": "g",
			"element": "div",
			"blockName": "band",
			"attributes": {"data-ground": "deep"},
			"baseStyles": {"backgroundColor": "var(--hb-ground-background)"},
			"children": [{"blockId": "p", "element": "p", "innerHTML": "WRITE text: a line"}],
		}
		node = compiled(section(children=[band])).tree["c"][0]
		self.assertEqual("deep", node["ground"])
		self.assertNotIn("attrs", node)

	def test_the_block_that_holds_the_form_is_empty_and_becomes_the_include(self):
		form = {
			"blockId": "f",
			"element": "div",
			"blockName": "form",
			"customAttributes": {"data-include": "component"},
		}
		result = compiled(section(children=[form]))
		self.assertTrue(result.form)
		self.assertEqual("{{include_component}}", result.tree["c"][0]["text"])
		full = {**form, "children": [{"blockId": "x", "element": "p", "innerHTML": "no"}]}
		self.assertTrue(any("must be empty" in e for e in compiled(section(children=[full])).errors))

	def test_the_attributes_typed_by_hand_are_read_as_well_as_the_standard_ones(self):
		heading = {
			"blockId": "h",
			"element": "h2",
			"attributes": {"href": ""},
			"customAttributes": {"aria-label": "x", "data-ground": "tint"},
			"innerHTML": "WRITE heading: a",
		}
		node = compiled(section(children=[heading])).tree["c"][0]
		self.assertEqual("tint", node["ground"])
		self.assertEqual({"aria-label": "x"}, node["attrs"])

	def test_empty_style_values_are_dropped_and_numbers_kept(self):
		block = section(baseStyles={"margin": 0, "color": "", "padding": "1rem"})
		self.assertEqual({"margin": 0, "padding": "1rem"}, compiled(block).tree["style"])

	def test_a_variable_inside_a_shorthand_is_replaced_in_place(self):
		block = section(baseStyles={"border": "1px solid var(--hb-ground-accent)"})
		self.assertEqual("1px solid {{ground.accent}}", compiled(block).tree["style"]["border"])


class TestWhatTheEditorCannotSay(unittest.TestCase):
	def errors(self, block):
		return compiled(block).errors

	def test_a_variable_that_is_not_of_the_palette_is_an_error_that_says_where(self):
		errors = self.errors(section(baseStyles={"color": "var(--surface-color)"}))
		self.assertEqual(1, len(errors))
		self.assertIn("band.style.color", errors[0])
		self.assertIn("not a token of the Hub blocks palette", errors[0])

	def test_a_component_a_repeater_data_a_script_are_errors(self):
		for key, value in (
			("extendedFromComponent", "hero"),
			("isRepeaterBlock", True),
			("dynamicValues", [{"property": "innerHTML", "key": "x"}]),
			("visibilityCondition", "x"),
			("clientScript", {"js": "x"}),
		):
			with self.subTest(key):
				child = {"blockId": "c", "element": "div", "blockName": "oops", key: value}
				self.assertTrue(any("oops" in e for e in self.errors(section(children=[child]))))


class TestTheWayBack(unittest.TestCase):
	def test_a_block_is_opened_in_the_editor_with_the_variables_of_the_palette(self):
		text = C.to_page_yaml(yaml.safe_load(SEEDS[0].read_text())["tree"])
		self.assertIn("var(--hb-", text)
		self.assertNotIn("{{ground.", text)
		self.assertEqual("body", yaml.safe_load(text)["name"])

	def test_with_no_block_the_editor_opens_a_starting_section_that_compiles_and_lints(self):
		result = compiled(page_of(None))
		self.assertEqual([], result.errors)
		errors, _ = block_format.lint(
			result.tree, block_id="cta.start", kinds=["cta"], photos=result.photos, form=result.form
		)
		self.assertEqual([], errors)

	def test_every_seed_block_comes_back_as_the_same_tree_after_the_editor(self):
		self.assertGreaterEqual(len(SEEDS), 4)
		for path in SEEDS:
			data = yaml.safe_load(path.read_text())
			with self.subTest(path.name):
				result = compiled(page_of(copy.deepcopy(data["tree"])))
				self.assertEqual([], result.errors)
				self.assertEqual(data["tree"], result.tree)
				errors, warnings = block_format.lint(
					result.tree,
					block_id=data["id"],
					kinds=data["kinds"],
					photos=result.photos,
					form=result.form,
					motion=data["motion"],
				)
				self.assertEqual(([], []), (errors, warnings))

	def test_a_block_with_a_photograph_a_ground_and_a_form_survives_the_editor(self):
		tree = {
			"el": "section",
			"name": "mix",
			"c": [
				{"el": "img", "name": "photo", "attrs": {"src": "{{photo.0}}", "alt": "WRITE alt: a scene"}},
				{
					"el": "div",
					"name": "band",
					"ground": "deep",
					"style": {"color": "{{ground.ink}}"},
					"c": [{"el": "p", "text": "WRITE text: a line"}],
				},
				{"el": "div", "name": "form", "text": "{{include_component}}"},
			],
		}
		result = compiled(page_of(copy.deepcopy(tree)))
		self.assertEqual([], result.errors)
		self.assertEqual(tree, result.tree)
		self.assertEqual((1, True), (result.photos, result.form))


if __name__ == "__main__":
	unittest.main()
