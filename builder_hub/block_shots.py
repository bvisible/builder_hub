# //// Neoffice — added file (no upstream equivalent): the thumbnails of the hub's blocks, for the insertion panel of the Builder editor.
"""The editor offers a block as a card with a picture. This module makes the picture: the block drawn as a page (block_preview.py, a neutral
palette, sample words, a desktop width), photographed with the headless browser the hub already has (Playwright), cut to its first screen and
scaled down.

A thumbnail belongs to a version of a block: `preview_hash` is the hash of what the picture shows (the tree, the ground, the version of this
renderer), so a block whose tree changed is photographed again and one that did not is left alone. The pictures are public files of the hub
(`/files/hub-block-<id>-<hash>.png`); the old one of a block is deleted when its new one is made.

It runs every hour for the blocks the editor offers that lack a current picture (a few at a time: the hub also runs the fleet, and a browser
is a few hundred megabytes), and by hand for a backlog: `bench --site <hub> execute builder_hub.block_shots.make_previews --kwargs
"{'limit': 200}"`. A block that cannot be photographed gets a hash that says so and is not tried again until its tree changes."""

import hashlib
import io

import frappe

from builder_hub import block_format, block_preview
from builder_hub.blocks import EDITOR_STATUSES, clear_block_cache

RENDERER = 2  # raise it when the way a thumbnail is made changes: every picture is made again
SHOT_WIDTH = block_preview.DEVICES["desktop"]
SHOT_MAX_HEIGHT = 900  # a section taller than this shows its first 900 px: the card is a hint, not the page
THUMB_WIDTH = 640  # two pixels for each of the 320 the card gets
FAILED = "x"
FILE_PREFIX = "hub-block-"


def preview_hash(row: dict) -> str:
	"""What a thumbnail of this block shows: its tree, the ground it is drawn on, this renderer's version."""
	text = "|".join([str(RENDERER), str(row.get("ground") or "plain"), str(row.get("tree") or "")])
	return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def needs_a_picture(row: dict) -> bool:
	"""Whether the block has no picture of its current tree, and has not failed to get one."""
	current = preview_hash(row)
	have = row.get("preview_hash") or ""
	if have == FAILED + current:
		return False
	return not (have == current and row.get("preview"))


def thumb_size(height: int) -> tuple[int, int]:
	"""(width, height) of the thumbnail of a page `height` pixels tall at SHOT_WIDTH: the first screen, scaled."""
	shown = max(1, min(int(height), SHOT_MAX_HEIGHT))
	return THUMB_WIDTH, max(1, round(shown * THUMB_WIDTH / SHOT_WIDTH))


def file_name(block_id: str, digest: str) -> str:
	return f"{FILE_PREFIX}{block_id}-{digest}.png"


def render(row: dict) -> str:
	"""The block as a page for its thumbnail: sample words of a typical length; it is photographed at rest (see `shoot`)."""
	tree = block_format.parse_tree(row["tree"])
	return block_preview.render_page(
		tree,
		palette=block_preview.DEFAULT_PALETTE,
		lang="fr",
		length="typical",
		ground=row.get("ground") or "plain",
		motion="None",
	)


def shoot(pages: list[str]) -> list[bytes | None]:
	"""One PNG per HTML page, in order (None for a page that could not be photographed). One browser for all of them."""
	from PIL import Image
	from playwright.sync_api import sync_playwright

	out: list[bytes | None] = []
	with sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			# a reader whose system asks for less motion sees the page at rest (block_preview._motion): the thumbnail is that page, not the first frame
			# of a rise that has not played yet
			context = browser.new_context(
				viewport={"width": SHOT_WIDTH, "height": 800}, reduced_motion="reduce"
			)
			page = context.new_page()
			for html in pages:
				try:
					page.set_content(html, wait_until="load")
					height = min(page.evaluate("document.documentElement.scrollHeight"), SHOT_MAX_HEIGHT)
					raw = page.screenshot(
						clip={"x": 0, "y": 0, "width": SHOT_WIDTH, "height": height}, full_page=True
					)
					width, tall = thumb_size(height)
					image = Image.open(io.BytesIO(raw)).convert("RGB").resize((width, tall), Image.LANCZOS)
					buffer = io.BytesIO()
					image.save(buffer, "PNG", optimize=True)
					out.append(buffer.getvalue())
				except Exception as e:
					frappe.log_error("Block thumbnail not made", f"{type(e).__name__}: {e}"[:500])
					out.append(None)
		finally:
			browser.close()
	return out


def _keep(name: str, digest: str, png: bytes) -> str:
	"""Writes the picture of a block as a public file and deletes the one it replaces. Returns the file's URL.

	A picture identical to the one it replaces (a block the new renderer draws the same) is not a new file: Frappe answers with the file that is already
	there, and that one must not be deleted as the old picture."""
	old = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Hub Block",
			"attached_to_name": name,
			"file_name": ("like", f"{FILE_PREFIX}%"),
		},
		fields=["name", "file_url"],
	)
	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name(name, digest),
			"content": png,
			"is_private": 0,
			"attached_to_doctype": "Hub Block",
			"attached_to_name": name,
		}
	).insert(ignore_permissions=True)
	for stale in old:
		if stale["file_url"] != doc.file_url:
			frappe.delete_doc("File", stale["name"], ignore_permissions=True, force=True)
	return doc.file_url


def make_previews(limit: int = 25, only: str | None = None, force: bool = False) -> list[str]:
	"""Photographs up to `limit` of the blocks the editor offers that lack a current picture (`only`: one block id; `force`: even when it has
	one). Returns one line per block."""
	filters = {"status": ("in", EDITOR_STATUSES)}
	if only:
		filters["name"] = only
	rows = frappe.get_all(
		"Hub Block",
		filters=filters,
		fields=["name", "block_id", "tree", "ground", "preview", "preview_hash"],
		order_by="block_id asc",
		ignore_permissions=True,
	)
	todo = [r for r in rows if force or needs_a_picture(r)][: max(1, int(limit))]
	if not todo:
		return []
	pages, kept = [], []
	for row in todo:
		try:
			pages.append(render(row))
			kept.append(row)
		except Exception as e:
			frappe.db.set_value(
				"Hub Block", row["name"], "preview_hash", FAILED + preview_hash(row), update_modified=False
			)
			frappe.log_error(f"Block {row['block_id']} not photographed", f"{type(e).__name__}: {e}"[:500])
	lines = []
	for row, png in zip(kept, shoot(pages), strict=True):
		digest = preview_hash(row)
		if png is None:
			frappe.db.set_value(
				"Hub Block", row["name"], "preview_hash", FAILED + digest, update_modified=False
			)
			lines.append(f"{row['block_id']}: failed")
			continue
		url = _keep(row["name"], digest, png)
		frappe.db.set_value(
			"Hub Block", row["name"], {"preview": url, "preview_hash": digest}, update_modified=False
		)
		lines.append(f"{row['block_id']}: {url}")
	frappe.db.commit()
	clear_block_cache()
	return lines


def hourly() -> None:
	"""The scheduler's hook: a few thumbnails at a time, and never a failure that reaches the scheduler."""
	try:
		make_previews(limit=12)
	except Exception as e:
		frappe.log_error("Block thumbnails not made", f"{type(e).__name__}: {e}"[:500])
