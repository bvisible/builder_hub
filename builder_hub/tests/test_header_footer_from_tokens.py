# //// Neoffice — added file (no upstream equivalent): the theme a promoted group brings to the site that installs it.
"""A generated site's pages name their own tokens, but its cards, buttons and header read the theme of the site: a group promoted without a
theme leaves the client who installs it with their own theme under another's pages. Pinned here: the theme is what the group's tokens say (the
colours and the fonts by their role), a font the theme does not offer is left out, a handle is not a value, and a group whose tokens are the
editor's (a uuid name) gets nothing. The database is replaced."""

import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict

from builder_hub import publish

FIELDS = {
	"heading_font": _dict(fieldtype="Select", options="Inter\nBebas Neue\nPlayfair Display"),
	"body_font": _dict(fieldtype="Select", options="Inter\nDM Sans"),
	"primary_color": _dict(fieldtype="Color", options=""),
	"secondary_color": _dict(fieldtype="Color", options=""),
	"background_color": _dict(fieldtype="Color", options=""),
	"text_color": _dict(fieldtype="Color", options=""),
}


def theme_of(rows):
	frappe = MagicMock()
	frappe.get_all.return_value = [_dict(name=n, value=v) for n, v in rows]
	frappe.get_meta.return_value.get_field.side_effect = lambda field: FIELDS.get(field)
	with (
		patch.object(publish, "frappe", frappe),
		patch.object(publish, "_token_doctype", return_value=("Builder Token", "token_name")),
	):
		return publish.header_footer_from_tokens("garage"), frappe


GARAGE = [
	("qtg-primary", "#1f2a36"),
	("qtg-secondary", "#e0792b"),
	("qtg-background", "#ffffff"),
	("qtg-text", "#1a1a1a"),
	("qtg-font-heading", "Bebas Neue"),
	("qtg-font-body", "DM Sans"),
	("qtg-container", "1200px"),
	("qtg-accent", "#e0792b"),
]


class TestTheThemeOfAGroup(unittest.TestCase):
	def test_the_colours_and_the_fonts_by_their_role(self):
		theme, frappe = theme_of(GARAGE)
		self.assertEqual(
			{
				"primary_color": "#1f2a36",
				"secondary_color": "#e0792b",
				"background_color": "#ffffff",
				"text_color": "#1a1a1a",
				"heading_font": "Bebas Neue",
				"body_font": "DM Sans",
			},
			theme,
		)
		self.assertEqual({"group": "garage"}, frappe.get_all.call_args.kwargs["filters"])

	def test_a_font_the_theme_does_not_offer_is_left_out_and_the_colours_stay(self):
		theme, _ = theme_of(
			[*GARAGE[:4], ("qtg-font-heading", "Cormorant Infant"), ("qtg-font-body", "DM Sans")]
		)
		self.assertNotIn("heading_font", theme)
		self.assertEqual("DM Sans", theme["body_font"])
		self.assertEqual("#1f2a36", theme["primary_color"])

	def test_a_token_that_is_only_a_handle_is_not_a_value(self):
		theme, _ = theme_of([("qtg-primary", "var(--other)"), ("qtg-text", "#1a1a1a")])
		self.assertEqual({"text_color": "#1a1a1a"}, theme)

	def test_a_group_of_the_editors_tokens_gets_no_theme(self):
		theme, _ = theme_of([("0824f62b-f051-48a6-b08b-283242b35aa7", "#383838")])
		self.assertEqual({}, theme)

	def test_a_group_with_no_tokens_gets_no_theme(self):
		self.assertEqual({}, theme_of([])[0])


if __name__ == "__main__":
	unittest.main()
