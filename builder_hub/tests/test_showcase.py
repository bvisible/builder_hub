# //// Neoffice — added file (no upstream equivalent): what a visitor gets on a site of the catalogue, and what stays untouched.
"""A site of the catalogue opened on the hub had no menu, and its form sent a real message for a business that does not exist. Pinned here: a group
of ours gets its menu, its note and its stopped forms, on the response only; upstream's groups, which ship their own navbar, and everything that is
not the page of a group are left as they came; a search engine is told to stay out. The templates are rendered for real, the database is not read."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader

from builder_hub import api, publish, showcase

ROOT = Path(showcase.__file__).parent
PAGE = '<!doctype html><html><head></head><body class="x"><main>page</main><script>1</script></body></html>'


def render(path, context):
	env = Environment(loader=FileSystemLoader(ROOT), autoescape=False)
	env.globals["_"] = lambda text: text
	return env.get_template(path.split("/", 1)[1]).render(context)


def group(**overrides):
	return {
		"name": "electrician",
		"title": "Électricien : installations et dépannage",
		"showcase": True,
		"header_footer": {"background_color": "#102030", "text_color": "#f0f0f0", "body_font": "Inter", "heading_font": "Outfit"},
		"pages": [
			{"page_title": "Accueil", "route": "templates/electrician/accueil"},
			{"page_title": "L'entreprise", "route": "templates/electrician/l'entreprise"},
			{"page_title": "Sans route", "route": None},
		],
		**overrides,
	}


class Response:
	def __init__(self, html=PAGE, status_code=200, mimetype="text/html"):
		self.html, self.status_code, self.mimetype = html, status_code, mimetype
		self.headers = {}

	def get_data(self, as_text=False):
		return self.html

	def set_data(self, value):
		self.html = value


def dressed(path="/templates/electrician/accueil", response=None, catalogue=None, method="GET"):
	response = response or Response()
	with (
		patch.object(showcase.frappe, "render_template", render),
		patch("builder_hub.api._get_catalog", return_value=[group()] if catalogue is None else catalogue),
		patch.object(showcase, "get_url", return_value="https://hub.test"),
	):
		showcase.dress_template_page(response=response, request=SimpleNamespace(path=path, method=method))
	return response.html


class TestASiteOfTheCatalogue(unittest.TestCase):
	def test_the_menu_opens_the_body_with_the_pages_of_the_group_in_their_order(self):
		html = dressed()
		self.assertLess(html.index('<body class="x">'), html.index("hub-showcase-header__menu"))
		self.assertLess(html.index("hub-showcase-header__menu\""), html.index("<main>"))
		self.assertLess(html.index(">Accueil<"), html.index("L&#39;entreprise"))
		self.assertNotIn("Sans route", html)

	def test_the_name_of_the_site_is_the_trade_and_the_current_page_is_marked(self):
		html = dressed("/templates/electrician/l'entreprise")
		self.assertIn(">Électricien</a>", html)
		self.assertNotIn("dépannage", html)
		self.assertEqual(1, html.count('aria-current="page">'))
		self.assertIn('l&#39;entreprise" aria-current="page">', html)

	def test_the_menu_wears_the_colours_of_the_group(self):
		html = dressed()
		self.assertIn("background: #102030", html)
		self.assertIn("color: #f0f0f0", html)
		self.assertIn('"Outfit"', html)

	def test_a_group_without_a_theme_still_reads(self):
		html = dressed(catalogue=[group(header_footer=None)])
		self.assertIn("background: #ffffff", html)
		self.assertIn("color: #1a1a1a", html)

	def test_the_note_closes_the_body_and_the_forms_stop_before_their_own_listener(self):
		html = dressed()
		self.assertLess(html.index("<script>1</script>"), html.index("hub-showcase-note\""))
		self.assertLess(html.index("hub-showcase-note\""), html.index("</body>"))
		self.assertIn("stopImmediatePropagation", html)
		self.assertRegex(html, r'addEventListener\(\s*"submit"[\s\S]*?true\s*\)')


class TestWhatIsLeftAlone(unittest.TestCase):
	def test_a_group_of_upstream_keeps_its_own_navbar(self):
		self.assertEqual(PAGE, dressed(catalogue=[group(showcase=False)]))

	def test_a_group_the_catalogue_does_not_know(self):
		self.assertEqual(PAGE, dressed(catalogue=[]))

	def test_anything_but_the_page_of_a_group(self):
		self.assertEqual(PAGE, dressed("/about"))
		self.assertEqual(PAGE, dressed(response=Response(status_code=404)))
		self.assertEqual(PAGE, dressed(response=Response(mimetype="application/json")))
		self.assertEqual(PAGE, dressed(method="POST"))

	def test_a_document_without_a_body(self):
		self.assertEqual("<p>x</p>", dressed(response=Response(html="<p>x</p>")))


class TestTheCatalogueSaysWhatTheGalleryNeeds(unittest.TestCase):
	def catalogue(self, manifest):
		page = showcase.frappe._dict(name="p", page_title="Accueil", preview=None, route="templates/g/accueil", template_group="g")
		with (
			patch.object(api.frappe, "get_all", return_value=[page]),
			patch("builder.template_sync.get_all_group_manifests", return_value={"g": manifest}),
			patch.object(api, "get_url", return_value="https://hub.test"),
			patch.object(api, "get_thumbnail_url", return_value=None),
		):
			return api._get_catalog.__wrapped__("https://hub.test")[0]

	def test_a_group_we_published_shows_up_by_itself(self):
		entry = self.catalogue({"source": publish.PROTECTED_GROUPS_MARKER})
		self.assertTrue(entry["showcase"])
		self.assertEqual("", entry["sector"])
		self.assertEqual({}, entry["translations"])

	def test_its_sector_and_its_translations_are_served(self):
		entry = self.catalogue({"source": publish.PROTECTED_GROUPS_MARKER, "sector": "trades", "translations": {"en": {"title": "Electrician"}}})
		self.assertEqual("trades", entry["sector"])
		self.assertEqual("Electrician", entry["translations"]["en"]["title"])

	def test_a_group_of_upstream_does_not(self):
		self.assertFalse(self.catalogue({"title": "Fronds"})["showcase"])


class TestThePromotion(unittest.TestCase):
	def test_a_sector_the_gallery_has_no_label_for_is_refused(self):
		with patch.object(publish.frappe, "throw", side_effect=ValueError) as throw, self.assertRaises(ValueError):
			publish._validate_sector("plumbing")
		self.assertIn("plumbing", throw.call_args.args[0])

	def test_no_sector_is_allowed(self):
		publish._validate_sector(None)
		publish._validate_sector("")
		publish._validate_sector("trades")


class TestTheSearchEngines(unittest.TestCase):
	def test_they_are_kept_out_of_the_examples_and_nowhere_else(self):
		page, other = Response(), Response()
		api.allow_template_embedding(response=page, request=SimpleNamespace(path="/templates/electrician/accueil"))
		api.allow_template_embedding(response=other, request=SimpleNamespace(path="/about"))
		self.assertEqual("noindex", page.headers["X-Robots-Tag"])
		self.assertNotIn("X-Robots-Tag", other.headers)
