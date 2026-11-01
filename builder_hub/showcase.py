# //// Neoffice — added file (no upstream equivalent): the complete sites of the catalogue, as a visitor walks through them on the hub.
"""The sites the hub shows to prospects; the gallery of neoffice.ch links to them.

A group published from a generated site has no navigation of its own: on a client's site its pages wear the chrome of that site, and builder's
`webpage.html` leaves a template page bare because upstream's groups ship their own navbar. Opened here, such a page was a lone page with no way to
the next one, and its form sent a real message into the hub on behalf of a business that does not exist. So a response of these groups gets, on its
way out: a menu of the pages of the group in the colours of the group, a footer saying it is an example, and forms that stop before sending.

This is done on the response and not on the pages: `get_template_bundle` hands the pages to the sites that install them, and those have a chrome.
"""

import re

import frappe
from frappe.utils import get_url

# what the gallery files a site under; each one has its label in the three languages of neoffice.ch (SiteExamples.sectors)
SECTORS = ("automotive", "beauty", "food", "health", "hospitality", "professional", "retail", "sport", "trades")

HEADER = "builder_hub/templates/includes/showcase_header.html"
FOOTER = "builder_hub/templates/includes/showcase_footer.html"

GROUP_ROUTE = re.compile(r"^/templates/([^/]+)/")
BODY_OPENING = re.compile(r"<body\b[^>]*>", re.IGNORECASE)

DEFAULT_THEME = {"background_color": "#ffffff", "text_color": "#1a1a1a", "primary_color": "#1a1a1a"}


def showcase_group(name: str) -> dict | None:
	"""The catalogue entry of a group the gallery shows, None for any other (upstream's groups have their navbar)."""
	from builder_hub.api import _get_catalog

	return next((group for group in _get_catalog(get_url()) if group["name"] == name and group.get("showcase")), None)


def chrome_context(group: dict, path: str) -> dict:
	"""What the two templates need: the short name of the site, its pages in the order of the manifest, and its theme."""
	pages = [
		{"title": page.get("page_title"), "url": f"/{page['route']}", "current": f"/{page['route']}" == path}
		for page in group["pages"]
		if page.get("route")
	]
	return {
		"name": group["title"].split(" : ")[0],
		"pages": pages,
		"home": pages[0]["url"] if pages else "",
		"theme": {**DEFAULT_THEME, **(group.get("header_footer") or {})},
	}


def dress(html: str, group: dict, path: str) -> str:
	"""The page with the menu at the top of its body and the note at the end of it. A document without a body is left as it came."""
	opening = BODY_OPENING.search(html)
	closing = html.rfind("</body>")
	if not opening or closing < opening.end():
		return html
	context = chrome_context(group, path)
	header = frappe.render_template(HEADER, context)
	footer = frappe.render_template(FOOTER, context)
	return html[: opening.end()] + header + html[opening.end() : closing] + footer + html[closing:]


def dress_template_page(response=None, request=None):
	"""after_request: only the HTML page of a group the gallery shows is touched."""
	if request is None or response is None or request.method != "GET" or response.status_code != 200:
		return
	route = GROUP_ROUTE.match(request.path)
	if not route or response.mimetype != "text/html":
		return
	group = showcase_group(route.group(1))
	if group:
		response.set_data(dress(response.get_data(as_text=True), group, request.path))
