# //// Neoffice — added file (no upstream equivalent): a block drawn as a page with sample words and the look of a site (block_preview.py).
"""The preview is how a block is judged before it is published. What is pinned: the colours derived from a palette are the generator's own (the same
numbers are pinned in the builder's test_hub_blocks); a slot is filled with as many words as its guidance allows (the longest case is the point); a
numeral counts up and an accent word is wrapped as the writer wraps it; every seed block draws on every palette in every language with no token and
no slot left, nothing a page must not hold, the tablet and phone rules of the Builder's breakpoints, a dark palette on a dark page. No Frappe."""

import re
import unittest
from pathlib import Path

import yaml

from builder_hub import block_preview as P

LIBRARY = Path(__file__).resolve().parent.parent / "block_library"
SEEDS = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(LIBRARY.glob("*.yaml"))]


def plain_text(fragment: str) -> str:
	return re.sub(r"<[^>]+>", "", fragment)


class TestTheLookOfAPalette(unittest.TestCase):
	def test_the_colours_derived_from_a_light_site_are_the_generators(self):
		look = P.look_of(P.PALETTES["terracotta"])
		self.assertEqual("rgba(43, 24, 16, 0.72)", look["muted"])
		self.assertEqual("rgba(43, 24, 16, 0.16)", look["hair"])
		self.assertEqual("rgba(122, 46, 29, 0.08)", look["tint"])
		self.assertEqual("rgba(217, 178, 111, 0.35)", look["frame"])
		self.assertEqual("#7a2e1d", look["deep"])  # the primary is dark: it is the deep band
		self.assertEqual("#faf5ee", look["ink_on_deep"])
		self.assertEqual("rgba(250, 245, 238, 0.8)", look["deep_muted"])
		self.assertEqual("rgba(250, 245, 238, 0.25)", look["deep_hair"])

	def test_on_a_dark_site_the_ink_on_the_deep_band_is_the_text_colour(self):
		look = P.look_of(P.PALETTES["midnight"])
		self.assertEqual("#f2efe8", look["ink_on_deep"])
		self.assertEqual("rgba(242, 239, 232, 0.8)", look["deep_muted"])
		self.assertEqual("#101820", look["deep"])

	def test_a_light_primary_gets_a_deep_band_darker_than_itself(self):
		palette = {**P.PALETTES["terracotta"], "primary": "#e8c872", "text": "#f5f5f5"}
		look = P.look_of(palette)
		self.assertNotEqual(look["primary"], look["deep"])
		self.assertLessEqual(P.luminance(P.parse_colour(look["deep"])), P.DARK + 0.1)

	def test_the_grounds_follow_the_site(self):
		grounds = P.grounds_of(P.look_of(P.PALETTES["terracotta"]))
		self.assertEqual("#faf5ee", grounds["plain"]["background"])
		self.assertEqual("rgba(122, 46, 29, 0.08)", grounds["tint"]["background"])
		self.assertEqual(("#7a2e1d", "#faf5ee"), (grounds["deep"]["background"], grounds["deep"]["ink"]))
		self.assertTrue(all(g["accent"] == "#d9b26f" for g in grounds.values()))

	def test_a_colour_is_read_as_hex_short_hex_or_rgba(self):
		self.assertEqual((255, 0, 0, 1.0), P.parse_colour("#f00"))
		self.assertEqual((17, 34, 51, 1.0), P.parse_colour("#112233"))
		self.assertEqual((1.0, 2.0, 3.0, 0.5), P.parse_colour("rgba(1, 2, 3, 0.5)"))
		self.assertIsNone(P.parse_colour("var(--x)"))

	def test_every_palette_names_what_a_site_brings(self):
		for key, palette in P.PALETTES.items():
			with self.subTest(key):
				for needed in (
					"label",
					"primary",
					"secondary",
					"background",
					"text",
					"font_heading",
					"font_body",
				):
					self.assertIn(needed, palette)
				self.assertIsNotNone(P.parse_colour(palette["primary"]))


class TestTheSampleWords(unittest.TestCase):
	def test_a_slot_takes_the_top_of_its_range_or_its_middle(self):
		for guidance, longest, typical in (
			("4 to 8 words, one accent word", 8, 6),
			("one sentence of 15 to 25 words saying what", 25, 20),
			("two sentences, 30 to 45 words, from the facts", 45, 37),
			("2 to 4 words naming the subject", 4, 3),
		):
			with self.subTest(guidance):
				self.assertEqual(longest, P.word_count(guidance, "longest"))
				self.assertEqual(typical, P.word_count(guidance, "typical"))
		self.assertIsNone(P.word_count("a short invitation", "longest"))

	def test_a_text_has_exactly_the_words_it_may_have_and_ends_on_a_full_stop(self):
		words = P.Words("fr", "longest", "#d9b26f")
		text = plain_text(words.slot("text", "two sentences, 30 to 45 words, from the facts"))
		self.assertEqual(45, len(text.split()))
		self.assertTrue(text.endswith("."))

	def test_a_title_has_no_full_stop_and_the_accent_word_is_wrapped_as_the_writer_wraps_it(self):
		words = P.Words("en", "longest", "#d9b26f")
		heading = words.slot("heading", "4 to 8 words, one accent word")
		self.assertEqual(8, len(plain_text(heading).split()))
		self.assertFalse(plain_text(heading).endswith("."))
		self.assertRegex(heading, r'<em style="font-style: italic; color: #d9b26f">\w+</em>$')

	def test_a_title_with_no_accent_is_left_plain(self):
		self.assertNotIn(
			"<em", P.Words("fr", "longest", "#000").slot("item-title", "2 to 5 words naming the step")
		)

	def test_the_numerals_count_up_and_two_headings_are_not_the_same_sentence(self):
		words = P.Words("fr", "longest", "#000")
		self.assertEqual(["01", "02", "03"], [words.slot("numeral", "the step number") for _ in range(3)])
		self.assertNotEqual(
			words.slot("item-title", "2 to 5 words"), words.slot("item-title", "2 to 5 words")
		)

	def test_what_a_button_or_a_label_says_is_fixed_and_follows_the_language(self):
		self.assertEqual(
			"Nous écrire", P.Words("fr", "longest", "#000").slot("button", "a short invitation, 2 to 4 words")
		)
		self.assertEqual("Write to us", P.Words("en", "longest", "#000").slot("button", "a short invitation"))
		self.assertEqual("Notre maison", P.Words("fr", "longest", "#000").slot("label", "the subject"))

	def test_a_language_or_length_it_does_not_know_falls_back(self):
		words = P.Words("klingon", "enormous", "#000")
		self.assertEqual(("fr", "longest"), (words.lang, words.length))

	def test_the_words_are_escaped(self):
		words = P.Words("fr", "longest", "#000")
		words.sentences = ["<script>alert(1)</script> & more words here."]
		self.assertNotIn("<script", words.slot("text", "3 to 6 words"))


class TestTheSeedBlocksOnEveryLook(unittest.TestCase):
	def test_each_seed_draws_on_each_palette_in_each_language_with_nothing_left_over(self):
		self.assertGreaterEqual(len(SEEDS), 4)
		for data in SEEDS:
			for palette in P.PALETTES:
				for lang in P.LANGUAGES:
					for length in P.LENGTHS:
						with self.subTest(block=data["id"], palette=palette, lang=lang, length=length):
							page = P.render_page(
								data["tree"], palette=palette, lang=lang, length=length, ground=data["ground"]
							)
							self.assertTrue(page.startswith("<!doctype html>") and page.endswith("</html>"))
							for leftover in (
								"{{",
								"}}",
								"WRITE ",
								"<script",
								"javascript:",
								"onclick",
								"http://",
								"https://",
							):
								self.assertNotIn(leftover, page)

	def test_the_classes_of_the_nodes_are_unique(self):
		page = P.render_page(SEEDS[0]["tree"])
		ids = re.findall(r'class="(b\d+)', page)
		self.assertEqual(len(ids), len(set(ids)))

	def test_a_block_with_tablet_and_phone_styles_gets_the_builders_breakpoints(self):
		page = P.render_page(next(d for d in SEEDS if d["id"] == "features.bento")["tree"])
		self.assertIn(f"@media (max-width: {P.TABLET_MAX}px)", page)
		self.assertIn(f"@media (max-width: {P.MOBILE_MAX}px)", page)
		self.assertEqual(1023, P.TABLET_MAX)
		self.assertEqual(576, P.MOBILE_MAX)

	def test_a_dark_palette_draws_a_dark_page_and_a_light_one_a_light_page(self):
		tree = SEEDS[0]["tree"]
		self.assertIn("background: #12161c", P.render_page(tree, palette="midnight"))
		self.assertIn("background: #faf5ee", P.render_page(tree, palette="terracotta"))

	def test_a_palette_can_be_given_as_a_dictionary_of_the_values_a_site_brings(self):
		palette = {**P.PALETTES["forest"], "primary": "#123456"}
		self.assertIn("#123456", P.render_page(SEEDS[0]["tree"], palette=palette))

	def test_a_node_with_a_ground_is_drawn_on_that_ground(self):
		tree = {
			"el": "section",
			"name": "mix",
			"style": {"backgroundColor": "{{ground.background}}"},
			"c": [
				{
					"el": "div",
					"name": "band",
					"ground": "deep",
					"style": {"backgroundColor": "{{ground.background}}"},
					"c": [{"el": "p", "text": "WRITE text: 3 to 6 words"}],
				}
			],
		}
		page = P.render_page(tree, palette="terracotta")
		self.assertIn("background-color: #faf5ee", page)
		self.assertIn("background-color: #7a2e1d", page)

	def test_a_photograph_is_a_frame_made_of_the_site_colours_and_asks_for_nothing(self):
		tree = {
			"el": "section",
			"c": [
				{
					"el": "img",
					"attrs": {"src": "{{photo.0}}", "alt": "WRITE alt: a scene"},
					"style": {"aspectRatio": "4/3", "width": "100%"},
				}
			],
		}
		page = P.render_page(tree)
		self.assertIn('src="data:image/svg+xml', page)
		for request in ('src="http', 'href="http', "url(http", "@import"):
			self.assertNotIn(request, page)
		self.assertIn("aspect-ratio: 4/3", page)

	def test_the_form_of_a_block_is_a_mock_form_never_an_include(self):
		tree = {
			"el": "section",
			"c": [
				{"el": "div", "name": "form", "text": "{{include_component}}"},
				{"el": "h2", "text": "WRITE heading: 3 to 6 words"},
			],
		}
		page = P.render_page(tree)
		self.assertIn("u-btn--primary", page)
		self.assertNotIn("{%", page)

	def test_a_link_goes_nowhere_and_an_attribute_that_is_not_safe_is_not_written(self):
		tree = {
			"el": "section",
			"c": [
				{
					"el": "a",
					"attrs": {"href": "{{cta_href}}", "onclick": "alert(1)", "data-x": 'a"b'},
					"text": "WRITE button: 2 to 4 words",
				}
			],
		}
		page = P.render_page(tree)
		self.assertIn('href="#"', page)
		self.assertNotIn("onclick", page)
		self.assertIn('data-x="a&quot;b"', page)

	def test_numbers_get_units_except_where_a_number_is_a_number(self):
		tree = {
			"el": "section",
			"style": {"padding": 24, "margin": 0, "lineHeight": 1.5, "fontWeight": 700, "opacity": 1},
			"c": [{"el": "p", "text": "WRITE text: 3 to 6 words"}],
		}
		page = P.render_page(tree)
		for expected in ("padding: 24px", "margin: 0;", "line-height: 1.5", "font-weight: 700", "opacity: 1"):
			self.assertIn(expected, page)

	def test_the_label_of_a_button_is_the_colour_that_reads_on_it(self):
		page = P.render_page(SEEDS[0]["tree"], palette="terracotta")
		self.assertIn(".u-btn--primary { background: #7a2e1d; color: #ffffff; }", page)  # white on a dark red
		self.assertIn(
			".u-btn--secondary { background: #d9b26f; color: #1a1a1a; }", page
		)  # dark on a light gold

	def test_the_options_of_the_window_name_every_palette_and_the_three_widths(self):
		options = P.options()
		self.assertEqual(set(P.PALETTES), {p["value"] for p in options["palettes"]})
		self.assertEqual({"desktop", "tablet", "phone"}, set(options["devices"]))
		self.assertIn(options["default_palette"], P.PALETTES)


if __name__ == "__main__":
	unittest.main()
