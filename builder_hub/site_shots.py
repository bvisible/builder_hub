# //// Neoffice — added file (no upstream equivalent): the picture of a whole site, for the cards of the gallery of neoffice.ch.
"""A card of the gallery shows the first screen of a site; hovered, it runs down the whole home page. This module makes that second picture: the home page as a
visitor gets it, its chrome included (showcase.py), photographed from top to bottom with the headless browser the hub already has and scaled to the width a card needs.

It sits beside the preview of the page (`/builder_assets/<group>/<page>/whole-<hash>.webp`). `picture_hash` is the hash of what it shows, so a site whose home page,
chrome or menu changed is photographed again and one that did not is left alone, and the address changes with the picture: neoffice.ch keeps its images for a day.

It runs every hour for the sites of the catalogue that lack a current picture, so a site promoted to the catalogue gets its picture without anybody asking. By hand:
`bench --site <hub> execute builder_hub.site_shots.make_pictures --kwargs "{'only': 'garage', 'force': True}"`. A site that could not be photographed keeps its card
without the movement and is tried again the next hour."""

import hashlib
import io
import json
from pathlib import Path

import frappe
from frappe.utils import get_url

from builder_hub.assets import resolve_asset_path

RENDERER = 1  # raise it when the way a picture is made changes: every site is photographed again
SHOT_SIZE = {"width": 1280, "height": 800}  # the viewport of the previews, so that the top of this picture is the first screen the card already shows
SHOT_MAX_HEIGHT = 12000  # past this a page is cut: the movement is a hint of the site, and a browser and WEBP have limits
PICTURE_WIDTH = 800  # two pixels for each of the 400 a card gets
PICTURE_QUALITY = 74
PICTURE_PREFIX = "whole-"

# The photos of a page load as they come into view: it is walked down once, and back to the top where a sticky header is at rest.
WALK_DOWN = """async () => {
	for (let y = 0; y < document.documentElement.scrollHeight; y += window.innerHeight) {
		window.scrollTo(0, y);
		await new Promise((done) => setTimeout(done, 150));
	}
	window.scrollTo(0, 0);
}"""


def home_of(pages: list[dict]) -> dict | None:
	"""The page the gallery opens: the first one with an address."""
	return next((page for page in pages if page.get("live_url")), None)


def picture_hash(group: dict, page_name: str) -> str:
	"""What the picture of a site shows: its home page, the chrome it brought, the menu its pages make, this renderer's version."""
	from builder.template_sync import get_group_manifest

	blocks = frappe.db.get_value("Builder Page", page_name, "blocks") or ""
	chrome = (get_group_manifest(group["name"], app="builder_hub") or {}).get("chrome") or {}
	titles = [page.get("page_title") or "" for page in group["pages"]]
	text = "|".join([str(RENDERER), blocks, json.dumps(chrome, sort_keys=True), *titles])
	return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def picture_size(width: int, height: int) -> tuple[int, int]:
	"""(width, height) of the picture of a page of that size."""
	return PICTURE_WIDTH, max(1, round(height * PICTURE_WIDTH / width))


def _folder(page_name: str) -> Path | None:
	"""Where the preview of a page is; a page without one has no card in the gallery."""
	preview = resolve_asset_path(frappe.db.get_value("Builder Page", page_name, "preview"))
	return preview.parent if preview else None


def scroll_picture(pages: list[dict]) -> dict | None:
	"""The picture of a site for the catalogue: its address, and its size, which tells the gallery how long the page takes to run by. None until it is made."""
	from PIL import Image

	from builder_hub.api import abs_url

	home = home_of(pages)
	folder = _folder(home["name"]) if home else None
	path = next(folder.glob(f"{PICTURE_PREFIX}*.webp"), None) if folder else None
	if not path:
		return None
	with Image.open(path) as image:
		width, height = image.size
	folder_url = frappe.db.get_value("Builder Page", home["name"], "preview").split("?", 1)[0].rsplit("/", 1)[0]
	return {"url": abs_url(f"{folder_url}/{path.name}"), "width": width, "height": height}


def shoot(urls: list[str]) -> list[bytes | None]:
	"""One WEBP per page, in order (None for a page that could not be photographed). One browser for all of them."""
	from PIL import Image
	from playwright.sync_api import sync_playwright

	out: list[bytes | None] = []
	with sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			# a reader whose system asks for less motion sees every section at rest, not waiting for a scroll; French, the language the sites are written in
			context = browser.new_context(viewport=SHOT_SIZE, locale="fr-CH", reduced_motion="reduce")
			for url in urls:
				page = context.new_page()
				try:
					page.goto(url, wait_until="networkidle", timeout=60000)
					page.evaluate(WALK_DOWN)
					page.wait_for_load_state("networkidle")
					page.wait_for_timeout(600)
					height = min(page.evaluate("document.documentElement.scrollHeight"), SHOT_MAX_HEIGHT)
					raw = page.screenshot(
						clip={"x": 0, "y": 0, "width": SHOT_SIZE["width"], "height": height}, full_page=True
					)
					image = Image.open(io.BytesIO(raw)).convert("RGB")
					image = image.resize(picture_size(*image.size), Image.LANCZOS)
					buffer = io.BytesIO()
					image.save(buffer, "WEBP", quality=PICTURE_QUALITY, method=6)
					out.append(buffer.getvalue())
				except Exception as e:
					frappe.log_error("Site picture not made", f"{url}: {type(e).__name__}: {e}"[:500])
					out.append(None)
				finally:
					page.close()
		finally:
			browser.close()
	return out


def _keep(target: Path, picture: bytes) -> None:
	"""Writes a picture and drops the one it replaces. Written aside and renamed, so that a request never gets a partial file."""
	partial = target.with_name(f".{target.name}.{frappe.generate_hash(length=6)}")
	partial.write_bytes(picture)
	partial.replace(target)
	for old in target.parent.glob(f"{PICTURE_PREFIX}*.webp"):
		if old != target:
			old.unlink(missing_ok=True)


def make_pictures(only: str | None = None, force: bool = False) -> list[str]:
	"""Photographs the sites of the catalogue that lack a current picture (`only`: one group; `force`: even when it has one). Returns one line per site."""
	from builder_hub.api import _get_catalog
	from builder_hub.publish import _clear_catalog_caches

	todo = []
	for group in _get_catalog(get_url()):
		if not group.get("showcase") or (only and group["name"] != only):
			continue
		home = home_of(group["pages"])
		folder = _folder(home["name"]) if home else None
		if not folder:
			continue
		target = folder / f"{PICTURE_PREFIX}{picture_hash(group, home['name'])}.webp"
		if force or not target.exists():
			todo.append((group["name"], home["live_url"], target))
	if not todo:
		return []
	lines = []
	for (name, _url, target), picture in zip(todo, shoot([row[1] for row in todo]), strict=True):
		if picture is None:
			lines.append(f"{name}: failed")
			continue
		_keep(target, picture)
		lines.append(f"{name}: {target.name}, {len(picture) // 1024} KB")
	_clear_catalog_caches()
	return lines


def hourly() -> None:
	"""The scheduler's hook: never a failure that reaches the scheduler."""
	try:
		make_pictures()
	except Exception as e:
		frappe.log_error("Site pictures not made", f"{type(e).__name__}: {e}"[:500])
