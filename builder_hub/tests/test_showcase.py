# //// Neoffice — added file (no upstream equivalent): what a visitor gets on a site of the catalogue, and what stays untouched.
"""A site of the catalogue opened on the hub lacked the chrome its pages lean on: no theme stylesheet, so buttons as bare text and cards with no surface,
no title band, no footer, and a form that sent a real message for a business that does not exist. Pinned here: a page of ours is dressed with the settings
of its site and the pages of its group, on the response only; upstream's groups and everything that is not the page of a group are left as they came;
a chrome that fails leaves the page served; a search engine is told to stay out. The database and the Builder's renderers are replaced."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jinja2 import Environment, FileSystemLoader

from builder_hub import api, publish, showcase

ROOT = Path(showcase.__file__).parent
PAGE = '<!doctype html><html><head></head><body class="x"><main>page</main><script>1</script></body></html>'


def group(**overrides):
	return {
		"name": "garage",
		"title": "Garage : atelier indépendant",
		"showcase": True,
		"header_footer": {"background_color": "#102030", "text_color": "#f0f0f0"},
		"pages": [
			{"name": "p1", "page_title": "Accueil", "route": "templates/garage/accueil"},
			{"name": "p2", "page_title": "Prestations", "route": "templates/garage/prestations"},
			{"name": "p3", "page_title": "Réserver une table", "route": "templates/garage/réserver_une_table"},
			{"name": "p4", "page_title": "L'atelier", "route": "templates/garage/l'atelier"},
			{"name": "p5", "page_title": "Sans route", "route": None},
		],
		**overrides,
	}


class Variant(dict):
	"""What the renderers read of an unsaved Website Header Footer Variant."""

	def update(self, values):
		super().update(values)

	def append(self, table, row):
		self.setdefault(table, []).append(row)


def config_for(chrome=None, **overrides):
	with patch.object(showcase.frappe, "new_doc", return_value=Variant()), patch.object(showcase, "_", side_effect=lambda text: text):
		return showcase.site_config(group(**overrides), chrome)


class TestTheChromeOfASite(unittest.TestCase):
	def test_it_is_the_chrome_of_the_site_it_came_from(self):
		config = config_for({"logo_text": "Garage du Centre", "radius_style": "Subtle", "token_prefix": "qtg", "header_bg_color": "#1f2a36"})
		self.assertEqual("Garage du Centre", config["logo_text"])
		self.assertEqual("qtg", config["token_prefix"])
		self.assertEqual("Subtle", config["radius_style"])
		self.assertEqual("#1f2a36", config["header_bg_color"])
		self.assertEqual("#102030", config["background_color"])

	def test_a_group_that_brought_no_chrome_is_named_after_its_trade(self):
		config = config_for(None, header_footer=None)
		self.assertEqual("Garage", config["logo_text"])
		self.assertEqual("#ffffff", config["background_color"])
		self.assertEqual(0, config["show_cta"])

	def test_the_button_keeps_its_page_whatever_the_hub_calls_it_and_leaves_the_menu(self):
		config = config_for({"cta_text": "Réserver", "cta_url": "/reserver-une-table"})
		self.assertEqual("/templates/garage/réserver_une_table", config["cta_url"])
		self.assertEqual(1, config["show_cta"])
		self.assertEqual(["Prestations", "L'atelier"], [row["label"] for row in config["menu_items"]])

	def test_the_footer_lists_every_page_and_nothing_leads_off_the_site(self):
		config = config_for({"cta_url": "/jobs"})
		self.assertEqual(0, config["show_cta"])
		self.assertEqual("", config["cta_url"])
		self.assertEqual(["Accueil", "Prestations", "Réserver une table", "L'atelier"], [row["label"] for row in config["footer_links"]])
		self.assertTrue(all(row["url"].startswith("/templates/garage/") for row in config["footer_links"]))

	def test_no_newsletter_and_no_legal_page_of_the_hub_on_a_site_that_does_not_exist(self):
		config = config_for({"show_newsletter": 1})
		self.assertEqual(0, config["show_newsletter"])
		self.assertEqual("garage", config["website_profile"])


class TestTheTitleOfAnInteriorPage(unittest.TestCase):
	def band(self, page, opens_itself=False, doc=None, printed=False):
		builder = MagicMock()
		builder._opens_with_own_title.return_value = opens_itself
		builder._page_prints.return_value = printed
		builder._DARK_BACKGROUNDS = ("Image", "Solid")
		builder._CSS = "<style/>"
		builder._page_fonts.return_value = ""
		builder._fill.return_value = ""
		document = {"meta_description": "Une ligne.", **(doc or {})}
		render = MagicMock(return_value="<band/>")
		with (
			patch.dict("sys.modules", {"builder.page_header": builder}),
			patch("builder.page_header", builder, create=True),
			patch.object(showcase.frappe, "get_cached_doc", return_value=document),
			patch.object(showcase.frappe, "render_template", render),
			patch.object(showcase, "_", side_effect=lambda text: text),
		):
			html = showcase.page_band(page, "/home", {"page_header_template": "Standard", "show_breadcrumbs": 1})
		return html, render

	def test_an_interior_page_gets_its_title_and_a_way_home(self):
		html, render = self.band({"name": "p2", "title": "Prestations", "url": "/p2"})
		self.assertEqual("<style/><band/>", html)
		context = render.call_args.args[1]
		self.assertEqual("Prestations", context["title"])
		self.assertEqual("Une ligne.", context["subtitle"])
		self.assertEqual("/home", context["breadcrumbs"][0]["url"])

	def test_the_home_page_keeps_its_hero(self):
		self.assertEqual("", self.band({"name": "p1", "title": "Accueil", "url": "/home"})[0])

	def test_a_page_that_opens_on_its_own_title_keeps_it(self):
		self.assertEqual("", self.band({"name": "p2", "title": "Prestations", "url": "/p2"}, opens_itself=True)[0])

	def test_a_line_the_page_prints_is_not_said_twice(self):
		_html, render = self.band({"name": "p2", "title": "Prestations", "url": "/p2"}, printed=True)
		self.assertEqual("", render.call_args.args[1]["subtitle"])


class Response:
	def __init__(self, html=PAGE, status_code=200, mimetype="text/html"):
		self.html, self.status_code, self.mimetype = html, status_code, mimetype
		self.headers = {}

	def get_data(self, as_text=False):
		return self.html

	def set_data(self, value):
		self.html = value


def dressed(path="/templates/garage/accueil", response=None, is_ours=True, method="GET", parts=("<top/>", "<end/>")):
	response = response or Response()
	chrome = MagicMock(return_value=parts)
	showcase.frappe.local.lang = "fr"
	with patch.object(showcase, "showcase_group", return_value={"name": "garage"} if is_ours else None), patch.object(showcase, "chrome_parts", chrome):
		showcase.dress_template_page(response=response, request=SimpleNamespace(path=path, method=method))
	return response.html


class TestThePageOnItsWayOut(unittest.TestCase):
	def test_the_chrome_opens_and_closes_the_body(self):
		html = dressed()
		self.assertLess(html.index('<body class="x">'), html.index("<top/>"))
		self.assertLess(html.index("<top/>"), html.index("<main>"))
		self.assertLess(html.index("<script>1</script>"), html.index("<end/>"))
		self.assertLess(html.index("<end/>"), html.index("</body>"))

	def test_a_group_of_upstream_keeps_its_own_navbar(self):
		self.assertEqual(PAGE, dressed(is_ours=False))

	def test_anything_but_the_page_of_a_group(self):
		self.assertEqual(PAGE, dressed("/about"))
		self.assertEqual(PAGE, dressed(response=Response(status_code=404)))
		self.assertEqual(PAGE, dressed(response=Response(mimetype="application/json")))
		self.assertEqual(PAGE, dressed(method="POST"))

	def test_a_page_the_group_does_not_list(self):
		self.assertEqual(PAGE, dressed(parts=None))

	def test_a_document_without_a_body(self):
		self.assertEqual("<p>x</p>", dressed(response=Response(html="<p>x</p>")))

	def test_a_chrome_that_fails_leaves_the_page_served_and_says_so(self):
		response = Response()
		with (
			patch.object(showcase, "showcase_group", return_value={"name": "garage"}),
			patch.object(showcase, "chrome_parts", side_effect=ValueError("no")),
			patch.object(showcase.frappe, "log_error") as logged,
			patch.object(showcase.frappe, "get_traceback", return_value="trace"),
		):
			showcase.dress_template_page(response=response, request=SimpleNamespace(path="/templates/garage/accueil", method="GET"))
		self.assertEqual(PAGE, response.html)
		self.assertEqual("Showcase chrome failed", logged.call_args.args[0])


class TestTheNote(unittest.TestCase):
	def note(self):
		env = Environment(loader=FileSystemLoader(ROOT), autoescape=False)
		env.globals["_"] = lambda text: text
		return env.get_template("templates/includes/showcase_footer.html").render({})

	def test_the_forms_stop_before_their_own_listener(self):
		html = self.note()
		self.assertIn("stopImmediatePropagation", html)
		self.assertRegex(html, r'addEventListener\(\s*"submit"[\s\S]*?true\s*\)')

	def test_it_says_it_is_an_example_and_leaves_in_a_new_tab(self):
		html = self.note()
		self.assertIn("Example site made with Neoffice", html)
		self.assertIn('target="_blank"', html)


class TestTheCatalogueSaysWhatTheGalleryNeeds(unittest.TestCase):
	def catalogue(self, manifest):
		page = showcase.frappe._dict(name="p", page_title="Accueil", preview=None, route="templates/g/accueil", template_group="g")
		with (
			patch.object(api.frappe, "get_all", return_value=[page]),
			patch("builder.template_sync.get_all_group_manifests", return_value={"g": manifest}),
			patch.object(api, "get_url", return_value="https://hub.test"),
			patch.object(api, "get_thumbnail_url", return_value=None),
			patch("builder_hub.site_shots.scroll_picture", return_value={"url": "https://hub.test/whole.webp"}),
		):
			return api._get_catalog.__wrapped__("https://hub.test")[0]

	def test_a_group_we_published_shows_up_by_itself(self):
		entry = self.catalogue({"source": publish.PROTECTED_GROUPS_MARKER})
		self.assertTrue(entry["showcase"])
		self.assertEqual("", entry["sector"])
		self.assertEqual({}, entry["translations"])
		self.assertEqual("https://hub.test/whole.webp", entry["scroll_picture"]["url"])

	def test_its_sector_and_its_translations_are_served(self):
		entry = self.catalogue({"source": publish.PROTECTED_GROUPS_MARKER, "sector": "trades", "translations": {"en": {"title": "Electrician"}}})
		self.assertEqual("trades", entry["sector"])
		self.assertEqual("Electrician", entry["translations"]["en"]["title"])

	def test_a_group_of_upstream_does_not(self):
		entry = self.catalogue({"title": "Fronds"})
		self.assertFalse(entry["showcase"])
		self.assertIsNone(entry["scroll_picture"])


class TestThePromotion(unittest.TestCase):
	def test_a_sector_the_gallery_has_no_label_for_is_refused(self):
		with patch.object(publish.frappe, "throw", side_effect=ValueError) as throw, self.assertRaises(ValueError):
			publish._validate_sector("plumbing")
		self.assertIn("plumbing", throw.call_args.args[0])

	def test_a_page_added_to_a_site_comes_after_the_pages_it_has(self):
		manifest = {"pages": [{"name": "home"}, {"name": "services"}]}
		staged = [showcase.frappe._dict(name="services"), showcase.frappe._dict(name="about")]
		self.assertEqual(["home", "services", "about"], publish._group_pages(manifest, staged))

	def test_a_new_group_takes_its_pages_as_they_come(self):
		self.assertEqual(["home"], publish._group_pages({}, [showcase.frappe._dict(name="home")]))

	def test_no_sector_is_allowed(self):
		publish._validate_sector(None)
		publish._validate_sector("")
		publish._validate_sector("trades")


class TestAGroupWithAMissingPicture(unittest.TestCase):
	PAGE = showcase.frappe._dict(name="p1", page_title="Accueil")

	def promote(self, draft, blocks):
		db = MagicMock()
		db.get_value.side_effect = lambda doctype, name, field: {"draft_blocks": draft, "blocks": blocks}[field]
		with patch.object(publish.frappe, "db", db), patch.object(publish.frappe, "throw", side_effect=ValueError) as throw:
			try:
				publish._refuse_empty_photos([self.PAGE])
			except ValueError:
				return throw.call_args.args[0]

	def test_it_stays_in_the_inbox_and_the_page_is_named(self):
		self.assertIn("Accueil", self.promote(None, '[{"attributes": {"src": "data:image/svg+xml;utf8,<svg/>"}}]'))

	def test_the_draft_is_what_will_be_published(self):
		self.assertIn("Accueil", self.promote('[{"src": "data:image/svg+xml;utf8,<svg/>"}]', "[]"))

	def test_real_pictures_pass(self):
		self.assertIsNone(self.promote(None, '[{"attributes": {"src": "/files/photo.jpg"}}]'))


class TestTheChromeWaitsForThePromotion(unittest.TestCase):
	def test_what_the_publish_kept_reaches_the_promotion(self):
		with tempfile.TemporaryDirectory() as folder, patch.object(publish, "_chrome_path", return_value=f"{folder}/inbox/garage.json"):
			publish._keep_chrome("garage", {"logo_text": "Garage du Centre"})
			self.assertEqual({"logo_text": "Garage du Centre"}, publish._kept_chrome("garage"))

	def test_a_publish_that_brought_none_leaves_nothing_to_read(self):
		with tempfile.TemporaryDirectory() as folder, patch.object(publish, "_chrome_path", return_value=f"{folder}/inbox/garage.json"):
			publish._keep_chrome("garage", None)
			self.assertEqual({}, publish._kept_chrome("garage"))


class TestTheSearchEngines(unittest.TestCase):
	def test_they_are_kept_out_of_the_examples_and_nowhere_else(self):
		page, other = Response(), Response()
		api.allow_template_embedding(response=page, request=SimpleNamespace(path="/templates/electrician/accueil"))
		api.allow_template_embedding(response=other, request=SimpleNamespace(path="/about"))
		self.assertEqual("noindex", page.headers["X-Robots-Tag"])
		self.assertNotIn("X-Robots-Tag", other.headers)
