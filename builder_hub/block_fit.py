# //// Neoffice — added file (no upstream equivalent): whether a block of the hub holds on every screen, measured before it is offered.
"""A block the hub offers must hold on a phone, a tablet and a desktop. This module draws it as a page (block_preview.py, the page the preview
window shows: the Builder's own breakpoints, sample words of a typical length, at rest) and measures it with the headless browser the hub already
has, at five widths. It fails when something runs off the screen without a parent that clips it, when the page scrolls sideways, when a text is
under 12px, when a long text is squeezed into a column narrower than 150px on a phone, when a text is wider than its own box, or when a
photograph is flattened under 8px. Measured by hand on 2026-11-01, nine blocks of 161 failed this way (a nowrap row of 1200px, a fixed column,
a photograph of 8 by 4px…) and the editor offered them all.

A result belongs to a version of a block: `fit_hash` is the hash of what was measured (the tree, the ground, the version of this measure), and
`fit_report` says what failed, empty when nothing did. A block is served (to the generator and to the editor) only when it was measured as it
is and passed (blocks.py), and it cannot be set to Editor or Published while its measure says it fails (hub_block.py). It runs every hour for
the blocks that lack a current measure, and by hand: `bench --site <hub> execute builder_hub.block_fit.measure_blocks --kwargs "{'limit': 200}"`."""

import hashlib

import frappe

from builder_hub import block_format, block_preview

MEASURE = 1  # raise it when what is measured changes: every block is measured again
WIDTHS = (375, 600, 768, 1024, 1280)
HEIGHT = 900
FAILED = "x"
REPORT_LINES = 6

# runs in the page, for one width: what fails, as short lines
PROBE = r"""(W) => {
  const out = [];
  const clipped = (el) => { for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (['hidden', 'clip', 'auto', 'scroll'].includes(s.overflowX)) { const r = a.getBoundingClientRect(); if (r.right <= W + 1 && r.left >= -1) return true; } }
    return false; };
  const label = (el) => el.tagName.toLowerCase() + (el.textContent.trim() ? ' "' + el.textContent.trim().slice(0, 24) + '"' : '');
  if (document.documentElement.scrollWidth > W + 1 || document.body.scrollWidth > W + 1)
    out.push('the page scrolls sideways (' + Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) + 'px)');
  for (const el of document.body.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    if ((r.right > W + 1 || r.left < -1) && !clipped(el)) out.push('runs off the screen: ' + label(el) + ' ' + Math.round(r.left) + '..' + Math.round(r.right));
    if (el.tagName === 'IMG' && el.offsetParent !== null && (r.width < 8 || r.height < 8)) out.push('a flattened photograph: ' + Math.round(r.width) + 'x' + Math.round(r.height));
    const text = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!text) continue;
    if (parseFloat(cs.fontSize) < 12) out.push('a text under 12px: ' + label(el));
    if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2) out.push('a text wider than its box: ' + label(el) + ' ' + el.scrollWidth + '>' + el.clientWidth);
    if (W <= 400 && el.textContent.trim().length > 60 && r.width < 150) out.push('a long text in ' + Math.round(r.width) + 'px: ' + label(el));
  }
  return [...new Set(out)];
}"""


def fit_hash(row: dict) -> str:
	"""What a measure of this block measured: its tree, the ground it is drawn on, this measure's version."""
	text = "|".join([str(MEASURE), str(row.get("ground") or "plain"), str(row.get("tree") or "")])
	return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def measured(row: dict) -> bool:
	"""Whether the block has a measure of its current tree (passed, failed, or could not be drawn)."""
	have = row.get("fit_hash") or ""
	return have in (fit_hash(row), FAILED + fit_hash(row))


def fits(row: dict) -> bool:
	"""Whether the block was measured as it is and nothing failed: the only blocks the hub serves."""
	return (row.get("fit_hash") or "") == fit_hash(row) and not (row.get("fit_report") or "").strip()


def render(row: dict) -> str:
	"""The block as a page to measure: the preview window's page, sample words of a typical length, at rest."""
	tree = block_format.parse_tree(row["tree"])
	return block_preview.render_page(
		tree,
		palette=block_preview.DEFAULT_PALETTE,
		lang="fr",
		length="typical",
		ground=row.get("ground") or "plain",
		motion="None",
	)


def report_of(found: dict) -> str:
	"""{width: [what failed]} as the report a person reads on the block: one line per width that failed, empty when none did."""
	lines = [f"{width}px: " + "; ".join(issues[:3]) for width, issues in sorted(found.items()) if issues]
	return "\n".join(lines[:REPORT_LINES])


def measure(pages: list[str]) -> list[str | None]:
	"""One report per HTML page, in order ("" when it holds everywhere, None when it could not be measured). One browser for all of them."""
	from playwright.sync_api import sync_playwright

	out: list[str | None] = []
	with sync_playwright() as p:
		browser = p.chromium.launch()
		try:
			contexts = {
				width: browser.new_context(viewport={"width": width, "height": HEIGHT}, reduced_motion="reduce")
				for width in WIDTHS
			}
			tabs = {width: context.new_page() for width, context in contexts.items()}
			for html in pages:
				try:
					found = {}
					for width, tab in tabs.items():
						tab.set_content(html, wait_until="load")
						found[width] = tab.evaluate(PROBE, width)
					out.append(report_of(found))
				except Exception as e:
					frappe.log_error("Block not measured", f"{type(e).__name__}: {e}"[:500])
					out.append(None)
		finally:
			browser.close()
	return out


def measure_row(row: dict) -> tuple[str, str]:
	"""(fit_hash, fit_report) for one block, measured now: FAILED + hash and the reason when it cannot be drawn or measured."""
	digest = fit_hash(row)
	try:
		page = render(row)
	except Exception as e:
		return FAILED + digest, f"the block could not be drawn: {type(e).__name__}"
	report = measure([page])[0]
	if report is None:
		return FAILED + digest, "the block could not be measured"
	return digest, report


def measure_blocks(limit: int = 25, only: str | None = None, force: bool = False, drafts: bool = True) -> list[str]:
	"""Measures up to `limit` blocks that lack a measure of their current tree (`only`: one block id; `force`: even when they have one): the
	blocks offered first, then the drafts a person may offer next. Returns one line per block."""
	from builder_hub.blocks import EDITOR_STATUSES, clear_block_cache  # blocks.py reads `fits` from here

	statuses = [*EDITOR_STATUSES, *(["Draft"] if drafts else [])]
	filters = {"status": ("in", statuses)}
	if only:
		filters["name"] = only
	rows = frappe.get_all(
		"Hub Block",
		filters=filters,
		fields=["name", "block_id", "status", "tree", "ground", "fit_hash", "fit_report"],
		order_by="block_id asc",
		ignore_permissions=True,
	)
	rows.sort(key=lambda r: r["status"] == "Draft")
	todo = [r for r in rows if force or not measured(r)][: max(1, int(limit))]
	if not todo:
		return []
	pages, kept, lines = [], [], []
	for row in todo:
		try:
			pages.append(render(row))
			kept.append(row)
		except Exception as e:
			frappe.db.set_value(
				"Hub Block",
				row["name"],
				{"fit_hash": FAILED + fit_hash(row), "fit_report": f"the block could not be drawn: {type(e).__name__}"},
				update_modified=False,
			)
			lines.append(f"{row['block_id']}: not drawn")
	for row, report in zip(kept, measure(pages), strict=True):
		digest = fit_hash(row)
		if report is None:
			values = {"fit_hash": FAILED + digest, "fit_report": "the block could not be measured"}
		else:
			values = {"fit_hash": digest, "fit_report": report}
		frappe.db.set_value("Hub Block", row["name"], values, update_modified=False)
		lines.append(f"{row['block_id']}: " + ("holds" if report == "" else (values["fit_report"].splitlines() or ["?"])[0]))
	frappe.db.commit()
	clear_block_cache()
	return lines


def hourly() -> None:
	"""The scheduler's hook: a few measures at a time, and never a failure that reaches the scheduler."""
	try:
		measure_blocks(limit=12)
	except Exception as e:
		frappe.log_error("Blocks not measured", f"{type(e).__name__}: {e}"[:500])
