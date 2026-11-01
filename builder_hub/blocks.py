# //// Neoffice — added file (no upstream equivalent): the hub's library of blocks (sections a site generator draws from).
"""The block library of the Builder Hub.

A block is one section of a site (see `block_format` for what it is made of), stored as a `Hub Block`. The people who design blocks work in
the hub's desk (the form has the tree, the look and a lint report that says what is wrong before a block can be published); the site
generator (Nora, in the `builder` app of a client) asks `builder_hub.api.get_block_catalog` for the published ones and offers them to the
model that plans a site next to its own recipes. The hub never calls a model and never draws a page: it keeps designs and serves them.

Where blocks come from:
- `block_library/*.yaml` in this app: the seed blocks, versioned in git, synced into the database on install and migrate. A seed block that
  somebody edited in the hub (`source` no longer `seed`) is left as it is: the hub wins over the files.
- the desk of the hub (Hub Block list), by hand;
- `builder_hub.publish.publish_block`, for a tool that designs blocks elsewhere: it only ever writes a DRAFT, because a block ends up in every
  site that is generated, so a person publishes it.
"""

import frappe
import yaml

from builder_hub import block_compile, block_format, block_preview

SEED_SOURCE = "seed"
EDITED_SOURCE = "edited in the hub"
PUBLISHED_FIELDS = (
	"block_id", "title", "family", "kinds", "look", "photos", "form", "component", "ground", "motion", "version", "tree",
)  # fmt: skip
# the statuses of a block and who is offered it: Published goes to the site generator (which chooses alone, so a person has read the block) and to the
# editor; Editor goes to the editor only (a person builds a page there and chooses each block with their eyes)
GENERATOR_STATUSES = ("Published",)
EDITOR_STATUSES = ("Editor", "Published")

# the sections of the editor's insertion panel, in the order it lists them; the builder's Block Template offers exactly these as its `category`
# (and its blockTemplateStore lists them in this order), so a name changed here is changed there too
EDITOR_SECTIONS = (
	"Hero", "Features", "Steps", "Stats", "Testimonials", "Pricing", "Team", "FAQ", "Gallery", "Call to action", "Contact", "Shop", "Content",
)  # fmt: skip
# the section a family is listed under; a family not named here is listed under Content
EDITOR_CATEGORIES = {
	"hero": "Hero",
	"features": "Features",
	"steps": "Steps",
	"figures": "Stats",
	"testimonials": "Testimonials",
	"pricing": "Pricing",
	"team": "Team",
	"faq": "FAQ",
	"gallery": "Gallery",
	"cta": "Call to action",
	"contact": "Contact",
	"product-row": "Shop",
}
DEFAULT_CATEGORY = "Content"


def library_dir():
	from pathlib import Path

	return Path(frappe.get_app_path("builder_hub", "block_library"))


def clear_block_cache() -> None:
	try:
		from builder_hub.api import _block_catalog, _editor_block_catalog

		_block_catalog.clear_cache()
		_editor_block_catalog.clear_cache()
	except Exception:
		pass


def category_of(family: str) -> str:
	"""The section of the editor's insertion panel a block of this family is listed under."""
	return EDITOR_CATEGORIES.get((family or "").strip().lower(), DEFAULT_CATEGORY)


# the include a block names (Hub Block `component`): a block that carries a component but names none is from before the field, the contact form
DEFAULT_COMPONENT = "contact_form.html"


def component_of(row: dict) -> str:
	"""The file name of the site's include a block carries ("" when it carries none)."""
	if not row.get("form"):
		return ""
	return (row.get("component") or "").strip() or DEFAULT_COMPONENT


def serve(row: dict) -> dict | None:
	"""The wire form of a block row, or None when its tree no longer lints (a published block is linted again on the way out, so that a row
	changed behind the form's back is never served)."""
	try:
		tree = block_format.parse_tree(row["tree"])
	except ValueError:
		frappe.log_error(f"Block {row['block_id']} not served", "its tree is not valid YAML")
		return None
	kinds = [k.strip() for k in (row["kinds"] or "").split(",") if k.strip()]
	errors, _warnings = block_format.lint(
		tree,
		block_id=row["block_id"],
		kinds=kinds,
		photos=int(row["photos"] or 0),
		form=bool(row["form"]),
		motion=row["motion"] or "None",
	)
	if errors:
		frappe.log_error(f"Block {row['block_id']} not served", "\n".join(errors))
		return None
	return {
		"id": row["block_id"],
		"title": row["title"],
		"family": row["family"],
		"kinds": kinds,
		"look": row["look"],
		"photos": int(row["photos"] or 0),
		"form": bool(row["form"]),
		"component": component_of(row),
		"ground": row["ground"] or "plain",
		"motion": row["motion"] or "None",
		"version": int(row["version"] or 1),
		"tree": tree,
	}


# what a block must have been measured to hold on every screen to be served (block_fit.py): read with the row, never sent
FIT_FIELDS = ("fit_hash", "fit_report")


def published_blocks() -> dict:
	"""{"format": n, "blocks": [...]}: the blocks the generator may choose, those measured as they are and holding on every screen."""
	from builder_hub.block_fit import fits

	rows = frappe.get_all(
		"Hub Block",
		filters={"status": ("in", GENERATOR_STATUSES)},
		fields=[*PUBLISHED_FIELDS, *FIT_FIELDS],
		order_by="block_id asc",
		ignore_permissions=True,
	)
	return {"format": block_format.FORMAT, "blocks": [b for b in (serve(r) for r in rows if fits(r)) if b]}


def serve_for_editor(row: dict) -> dict | None:
	"""The wire form of a block for the editor's insertion panel: the block (as `serve` gives it, so linted again), the section it is listed under,
	its thumbnail (absolute: a site shows it from here) and whether the site generator may also choose it. None when it cannot be served or has
	no thumbnail yet (a card without a picture is no use to somebody who chooses with their eyes)."""
	wire = serve(row)
	if wire is None or not row.get("preview"):
		return None
	preview = row["preview"]
	wire["category"] = category_of(row.get("family"))
	wire["preview"] = frappe.utils.get_url(preview) if preview.startswith("/") else preview
	wire["generator"] = row.get("status") in GENERATOR_STATUSES
	return wire


def editor_blocks() -> dict:
	"""{"format": n, "blocks": [...]}: the blocks the editor offers (those with a thumbnail, measured as they are and holding on every screen), by
	id."""
	from builder_hub.block_fit import fits

	rows = frappe.get_all(
		"Hub Block",
		filters={"status": ("in", EDITOR_STATUSES)},
		fields=[*PUBLISHED_FIELDS, *FIT_FIELDS, "status", "preview"],
		order_by="block_id asc",
		ignore_permissions=True,
	)
	served = [b for b in (serve_for_editor(r) for r in rows if fits(r)) if b]
	return {"format": block_format.FORMAT, "sections": list(EDITOR_SECTIONS), "blocks": served}


# ---------------------------------------------------------------- the seed blocks


def read_seed(path) -> dict:
	"""A seed file as the field values of a Hub Block."""
	data = yaml.safe_load(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or "tree" not in data or "id" not in data:
		raise ValueError(f"{path.name}: a seed block holds `id` and `tree`")
	kinds = data.get("kinds") or []
	return {
		"block_id": data["id"],
		"title": data.get("title") or data["id"],
		"kinds": ", ".join(kinds) if isinstance(kinds, list) else str(kinds),
		"look": data.get("look") or "",
		"photos": int(data.get("photos") or 0),
		"form": 1 if data.get("form") else 0,
		"ground": data.get("ground") or "plain",
		"motion": data.get("motion") or "None",
		"notes": data.get("notes") or "",
		"tree": yaml.safe_dump(
			data["tree"], sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False
		),
	}


def sync_block_library() -> list[str]:
	"""Brings the seed blocks of this app into the database. Returns one line per change."""
	folder = library_dir()
	files = sorted(folder.glob("*.yaml")) if folder.is_dir() else []
	changes: list[str] = []
	seen: set[str] = set()
	for path in files:
		try:
			values = read_seed(path)
		except (ValueError, yaml.YAMLError) as e:
			frappe.log_error(f"Seed block {path.name} skipped", str(e))
			continue
		seen.add(values["block_id"])
		if frappe.db.exists("Hub Block", values["block_id"]):
			doc = frappe.get_doc("Hub Block", values["block_id"])
			if doc.source != SEED_SOURCE:
				changes.append(f"{doc.name}: edited in the hub, kept")
				continue
			current = {k: doc.get(k) for k in values}
			if all(str(current[k] or "") == str(values[k] or "") for k in values):
				continue
			doc.update(values)
			verb = "updated"
		else:
			doc = frappe.new_doc("Hub Block")
			doc.update(values)
			doc.source = SEED_SOURCE
			verb = "added"
		doc.status = "Published"
		doc.flags.in_seed_sync = True
		try:
			doc.save(ignore_permissions=True)
		except frappe.ValidationError as e:
			frappe.log_error(f"Seed block {path.name} not synced", str(e))
			changes.append(f"{values['block_id']}: REFUSED")
			continue
		changes.append(f"{doc.name}: {verb}")
	if files:
		# a seed block whose file is gone is retired (one a person took over is theirs and stays)
		for name in frappe.get_all("Hub Block", filters={"source": SEED_SOURCE}, pluck="name"):
			if name not in seen:
				frappe.delete_doc("Hub Block", name, ignore_permissions=True, force=True)
				changes.append(f"{name}: retired")
	if changes:
		frappe.db.commit()
		clear_block_cache()
	return changes


# ---------------------------------------------------------------- what the editor needs to draw a block


PAGE_FOLDER = "Hub blocks"


def ensure_page_folder() -> str:
	"""The project folder of the Builder editor that holds the pages where the blocks are drawn."""
	if not frappe.db.exists("Builder Project Folder", PAGE_FOLDER):
		frappe.get_doc({"doctype": "Builder Project Folder", "folder_name": PAGE_FOLDER}).insert(
			ignore_permissions=True
		)
	return PAGE_FOLDER


def ensure_block_tokens() -> list[str]:
	"""The palette of the blocks (block_compile.PALETTE) as design tokens of the editor, named `hb-<role>`. A token that exists is never changed
	(somebody may have tuned the colours the editor previews with). Returns the keys it created."""
	from builder_hub.publish import _token_doctype

	doctype, name_field = _token_doctype()
	made = []
	for role, kind, value in block_compile.PALETTE:
		key = block_compile.token_key(role)
		if frappe.db.exists(doctype, key):
			continue
		label = "Block · " + role.replace("_", " ").replace(".", " ")
		frappe.get_doc(
			{
				"doctype": doctype,
				"name": key,
				name_field: label,
				"type": kind,
				"value": value,
				"group": block_compile.TOKEN_GROUP,
			}
		).insert(ignore_permissions=True, set_name=key)
		made.append(key)
	if made:
		frappe.db.commit()
	return made


@frappe.whitelist()
def preview_options() -> dict:
	"""What the preview window of a block offers: the palettes, the languages of the sample words, their lengths, the widths of the devices."""
	return block_preview.options()
