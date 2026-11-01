# //// Neoffice — added file (no upstream equivalent): the complete sites of the catalogue, as a visitor walks through them on the hub.
"""The sites the hub shows to prospects; the gallery of neoffice.ch links to them.

A group published from a generated site leans on the chrome of the site it came from: the header and the footer, and, in the theme stylesheet the header
prints, every class its pages use (`u-btn`, `u-grid`, `u-card`) and the colours of its forms; its interior pages also get their title from the band
under the header. Builder's `webpage.html` leaves a template page without any of that, because upstream's groups ship their own navbar and their own
styles. Opened here, a page of ours was therefore stripped: buttons as bare text, cards stacked with no surface, light text on a light ground, a form
nobody could read, no title. Installed on a client's site the same page is right, which is why it went unseen. And its form sent a real message into
the hub on behalf of a business that does not exist.

So a response of these groups gets, on its way out, the real chrome of its site: the renderers of the Builder, fed with the settings the group brought
(`chrome` in its manifest) in an unsaved variant, with a menu made of the pages of the group, plus a note saying it is an example and forms that stop
before sending. This is done on the response and not on the pages: `get_template_bundle` hands the pages to the sites that install them, and those
have a chrome of their own.
"""

import re
import unicodedata

import frappe
from frappe import _
from frappe.utils import escape_html, get_url
from frappe.utils.caching import redis_cache

# what the gallery files a site under; each one has its label in the three languages of neoffice.ch (SiteExamples.sectors)
SECTORS = ("automotive", "beauty", "food", "health", "hospitality", "professional", "retail", "sport", "trades")

HEADER_STYLES = "builder/templates/includes/header_footer/header_styles.html"
FOOTER_STYLES = "builder/templates/includes/header_footer/footer_styles.html"
PAGE_BAND = "builder/templates/includes/header_footer/page_header.html"
NOTE = "builder_hub/templates/includes/showcase_footer.html"

GROUP_ROUTE = re.compile(r"^/templates/([^/]+)/")
BODY_OPENING = re.compile(r"<body\b[^>]*>", re.IGNORECASE)

# a group published before it could bring its chrome still gets a header that reads
DEFAULT_THEME = {"background_color": "#ffffff", "text_color": "#1a1a1a", "header_bg_color": "#ffffff", "header_text_color": "#1a1a1a"}


def showcase_group(name: str) -> dict | None:
	"""The catalogue entry of a group the gallery shows, None for any other (upstream's groups have their navbar)."""
	from builder_hub.api import _get_catalog

	return next((group for group in _get_catalog(get_url()) if group["name"] == name and group.get("showcase")), None)


def _slug(text: str) -> str:
	"""A route with nothing but its letters: the site said /reserver-une-table, the hub says réserver_une_table."""
	plain = unicodedata.normalize("NFKD", text.rsplit("/", 1)[-1]).encode("ascii", "ignore").decode()
	return re.sub(r"[^a-z0-9]", "", plain.lower())


def site_pages(group: dict) -> list[dict]:
	"""The pages of the site in the order of the manifest, the home page first."""
	return [
		{"name": page.get("name"), "title": page.get("page_title"), "url": f"/{page['route']}"}
		for page in group["pages"]
		if page.get("route")
	]


def site_config(group: dict, chrome: dict | None):
	"""The chrome of the site as an unsaved Website Header Footer Variant: its own settings, its links the pages of the group. The button keeps the page it
	led to, and leaves the menu as it did on the site; `website_profile` keeps the legal pages of the hub out of the footer of a site that is not the hub."""
	pages = site_pages(group)
	chrome = chrome or {}
	action = next((page for page in pages if _slug(page["url"]) == _slug(chrome.get("cta_url") or "")), None)
	settings = {
		**DEFAULT_THEME,
		**(group.get("header_footer") or {}),
		"logo_type": "Text",
		"logo_text": group["title"].split(" : ")[0],
		**chrome,
		"website_profile": group["name"],
		"show_newsletter": 0,
		"show_cta": 1 if action else 0,
		"cta_url": action["url"] if action else "",
		"footer_menu_source": "Custom links",
	}
	config = frappe.new_doc("Website Header Footer Variant")
	config.update(settings)
	for page in pages[1:]:
		if page is not action:
			config.append("menu_items", {"label": page["title"], "url": page["url"]})
	for page in pages:
		config.append("footer_links", {"label": page["title"], "url": page["url"], "column_name": _("Navigation")})
	return config


def page_band(page: dict, home: str, config) -> str:
	"""The title band of an interior page, as builder.page_header draws it on the site: that function reads the chrome of the hub, whose band is off."""
	from builder import page_header

	template = config.get("page_header_template") or "Standard"
	if page["url"] == home or template == "None":
		return ""
	doc = frappe.get_cached_doc("Builder Page", page["name"])
	blocks = page_header._rendered_blocks(doc)
	if doc.get("hide_page_header") or page_header._opens_with_own_title(blocks):
		return ""
	subtitle = doc.get("page_header_subtitle") or ""
	description = doc.get("meta_description") or ""
	if not subtitle and description and not page_header._page_prints(blocks, description):
		subtitle = description
	background = config.get("page_header_background") or "None"
	title = escape_html(page["title"])
	crumbs = [{"label": escape_html(_("Home")), "url": home}, {"label": title, "url": ""}]
	return page_header._CSS + frappe.render_template(
		PAGE_BAND,
		{
			"template": "Standard" if template == "Builder" else template,
			"background": background,
			"fill": page_header._fill(background, config),
			"crumbs_below": page_header._trail_below(config),
			"on_dark": background in page_header._DARK_BACKGROUNDS,
			"fonts": page_header._page_fonts(blocks),
			"title": title,
			"subtitle": escape_html(subtitle),
			"breadcrumbs": crumbs if config.get("show_breadcrumbs") else [],
		},
	)


@redis_cache(ttl=3600)
def chrome_parts(name: str, path: str, lang: str) -> tuple[str, str] | None:
	"""(what opens the body, what closes it) for a page of a site. `lang` is here for the key: the chrome is written in the language of the request."""
	from builder.hf_utils.header_footer import render_footer, render_header
	from builder.template_sync import get_group_manifest

	group = showcase_group(name)
	if not group:
		return None
	pages = site_pages(group)
	page = next((page for page in pages if page["url"] == path), None)
	if not page:
		return None
	config = site_config(group, (get_group_manifest(name, app="builder_hub") or {}).get("chrome"))
	home = pages[0]["url"]
	# the logo and the home links of the renderers lead to /, which on the hub is the hub
	here = lambda html: html.replace('href="/"', f'href="{escape_html(home)}"')  # noqa: E731
	top = frappe.render_template(HEADER_STYLES, {"colors": config.get_header_colors(), "hf_config": config}) + render_header(config)
	end = frappe.render_template(FOOTER_STYLES, {"footer_colors": config.get_footer_colors(), "hf_config": config}) + render_footer(config)
	return here(top) + page_band(page, home, config), here(end) + frappe.render_template(NOTE, {})


def dress(html: str, top: str, end: str) -> str:
	"""The page inside its chrome. A document without a body is left as it came."""
	opening = BODY_OPENING.search(html)
	closing = html.rfind("</body>")
	if not opening or closing < opening.end():
		return html
	return html[: opening.end()] + top + html[opening.end() : closing] + end + html[closing:]


def dress_template_page(response=None, request=None):
	"""after_request: only the HTML page of a group the gallery shows is touched, and a chrome that fails leaves the page as it was."""
	if request is None or response is None or request.method != "GET" or response.status_code != 200:
		return
	route = GROUP_ROUTE.match(request.path)
	if not route or response.mimetype != "text/html" or not showcase_group(route.group(1)):
		return
	try:
		parts = chrome_parts(route.group(1), request.path, frappe.local.lang)
	except Exception:
		frappe.log_error("Showcase chrome failed", frappe.get_traceback())
		return
	if parts:
		response.set_data(dress(response.get_data(as_text=True), *parts))
