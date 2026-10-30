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
	"block_id", "title", "family", "kinds", "look", "photos", "form", "ground", "motion", "version", "tree",
)  # fmt: skip


def library_dir():
	from pathlib import Path

	return Path(frappe.get_app_path("builder_hub", "block_library"))


def clear_block_cache() -> None:
	try:
		from builder_hub.api import _block_catalog

		_block_catalog.clear_cache()
	except Exception:
		pass


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
		"ground": row["ground"] or "plain",
		"motion": row["motion"] or "None",
		"version": int(row["version"] or 1),
		"tree": tree,
	}


def published_blocks() -> dict:
	rows = frappe.get_all(
		"Hub Block",
		filters={"status": "Published"},
		fields=list(PUBLISHED_FIELDS),
		order_by="block_id asc",
		ignore_permissions=True,
	)
	return {"format": block_format.FORMAT, "blocks": [b for b in (serve(r) for r in rows) if b]}


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
