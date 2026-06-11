"""Authenticated publish API of the Builder Hub (bvisible extension).

Upstream builder_hub is read-only for consumers: templates enter the hub via
developer-mode fixtures committed to git. This module adds the missing upward
flow for the Neoservice fleet:

1. A client instance (Administrator only, via builder.hub_publish) uploads the
   group's assets then POSTs the page bundles here.
2. Bundles land in a STAGING area: regular, editable Builder Pages (no
   is_template flag, published=0) grouped in a "Hub Inbox — <group>" project
   folder, so the team can depersonalize client content directly in the hub's
   builder editor.
3. `promote_to_catalog` converts the staged pages into a proper template group
   (is_template + template_group + published), writes the disk manifest +
   fixtures via builder.template_sync.export_template_group, and clears the
   catalog caches — the group then appears in every instance's template picker.

Auth: dedicated service user carrying the "Hub Publisher" role, called with
standard Frappe token auth (Authorization: token key:secret). Keys are
distributed to client instances by neoffice-devops' SiteConfigPhase.
"""

import json
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from builder.template_sync import safe_segment

PUBLISHER_ROLES = ("Hub Publisher", "System Manager")

# Group slugs of the official Frappe templates (and any group whose manifest
# lacks our marker) can never be overwritten through this API.
PROTECTED_GROUPS_MARKER = "hub_publish"

STAGING_FOLDER_PREFIX = "Hub Inbox — "

MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB of JSON per publish call
MAX_ASSET_BYTES = 15 * 1024 * 1024  # 15 MB per uploaded asset

GROUP_SLUG_RE = re.compile(r"^[a-z0-9_]{2,60}$")


def _check_publisher():
    if frappe.session.user == "Administrator":
        return
    roles = set(frappe.get_roles())
    if not roles.intersection(PUBLISHER_ROLES):
        frappe.throw(_("Not permitted to publish to the hub"), frappe.PermissionError)


def _staging_folder_name(group: str) -> str:
    return f"{STAGING_FOLDER_PREFIX}{group}"


def _validate_group_slug(group: str) -> str:
    group = (group or "").strip().lower()
    safe_segment(group)
    if not GROUP_SLUG_RE.match(group):
        frappe.throw(_("Invalid group slug {0} — use [a-z0-9_], 2-60 chars").format(group))
    return group


def _assert_group_not_protected(group: str):
    """A group that already ships from disk fixtures can only be overwritten if
    its manifest carries our marker (i.e. it was created by this flow)."""
    from builder.template_sync import get_group_manifest

    manifest = get_group_manifest(group, app="builder_hub")
    if manifest and manifest.get("source") != PROTECTED_GROUPS_MARKER:
        frappe.throw(
            _("Template group {0} is a protected shipped group").format(group),
            frappe.PermissionError,
        )


@frappe.whitelist()
@rate_limit(limit=120, seconds=60)
def upload_template_asset(group: str):
    """Receive one asset file (multipart field `file`) for a group being
    published. Saved as a public File; returns its hub-local file_url.
    Content-hash dedup keeps re-publishes from piling up identical files."""
    _check_publisher()
    group = _validate_group_slug(group)

    files = frappe.request.files
    if not files or "file" not in files:
        frappe.throw(_("No file in request"))
    file_storage = files["file"]
    content = file_storage.stream.read()
    if len(content) > MAX_ASSET_BYTES:
        frappe.throw(_("Asset exceeds the {0} MB limit").format(MAX_ASSET_BYTES // (1024 * 1024)))

    filename = safe_segment(file_storage.filename or "asset")
    prefixed = f"hubpub-{group}-{filename}"

    # Dedup: same name + same content hash → reuse the existing file
    import hashlib

    content_hash = hashlib.md5(content).hexdigest()
    existing = frappe.db.get_value(
        "File",
        {"file_name": prefixed, "content_hash": content_hash, "is_private": 0},
        "file_url",
    )
    if existing:
        return {"file_url": existing}

    # File doctype (not legacy file_manager.save_file): get_max_file_size()
    # cint()s frappe.conf.max_file_size, which fleet site_configs carry as a
    # string — the legacy path compares int > str and crashes.
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": prefixed,
            "is_private": 0,
            "content": content,
        }
    ).insert(ignore_permissions=True)
    return {"file_url": file_doc.file_url}


@frappe.whitelist()
@rate_limit(limit=30, seconds=60)
def publish_template_group():
    """Receive a full template-group bundle and stage it for editorial review.

    JSON body:
    {
      "group": "client_xyz_portfolio",
      "title": "...", "description": "...",
      "replace": true,
      "pages": [ { "page": {...}, "components": [...], "variables": [...],
                   "client_scripts": [...], "fonts": [...] } ]
    }
    Page/component/preview asset URLs must already be hub-local (/files/...),
    uploaded beforehand via upload_template_asset.
    """
    _check_publisher()

    raw = frappe.request.get_data() or b"{}"
    if len(raw) > MAX_PAYLOAD_BYTES:
        frappe.throw(_("Payload exceeds the {0} MB limit").format(MAX_PAYLOAD_BYTES // (1024 * 1024)))
    payload = frappe.parse_json(raw.decode("utf-8"))

    group = _validate_group_slug(payload.get("group"))
    _assert_group_not_protected(group)
    pages = payload.get("pages") or []
    if not pages:
        frappe.throw(_("No pages in payload"))

    _reject_foreign_asset_urls(payload)

    warnings = []
    folder = _ensure_staging_folder(group)

    # Shared records first (variables/components/scripts/fonts), then pages
    for bundle in pages:
        _upsert_variables(bundle.get("variables") or [], warnings)
        _upsert_components(group, bundle.get("components") or [], warnings)
        _upsert_client_scripts(group, bundle.get("client_scripts") or [], warnings)
        _upsert_fonts(bundle.get("fonts") or [], warnings)

    created = []
    seen_titles = []
    for bundle in pages:
        page = bundle.get("page") or {}
        name = _upsert_staged_page(group, folder, page, bundle, warnings)
        created.append(name)
        seen_titles.append(page.get("page_title"))

    if payload.get("replace", True):
        _drop_stale_staged_pages(folder, keep=created)

    frappe.db.commit()
    return {
        "group": group,
        "staging_folder": folder,
        "pages": created,
        "warnings": warnings,
        "next_step": "Edit the staged pages in the builder, then call "
        "builder_hub.publish.promote_to_catalog",
    }


@frappe.whitelist()
def promote_to_catalog(group: str, title: str | None = None, description: str | None = None):
    """Turn the staged pages of a group into a published template group.

    Administrator action on the hub, after editorial cleanup. Sets the
    template invariants, writes the manifest + disk fixtures (git-committable)
    and clears the catalog caches.
    """
    _check_publisher()
    group = _validate_group_slug(group)
    _assert_group_not_protected(group)

    folder = _staging_folder_name(group)
    staged = frappe.get_all(
        "Builder Page",
        filters={"project_folder": folder},
        fields=["name", "page_title"],
        order_by="creation",
    )
    if not staged:
        frappe.throw(_("No staged pages found for group {0}").format(group))

    import os

    from frappe.utils import now

    from builder.template_sync import (
        export_template_group,
        get_templates_root,
        update_template_manifest,
    )

    frappe.flags.in_import = True  # bypass the template read-only guard
    try:
        for page in staged:
            route = f"templates/{group}/{frappe.scrub(str(page.page_title or page.name))}"
            frappe.db.set_value(
                "Builder Page",
                page.name,
                {
                    "is_template": 1,
                    "template_group": group,
                    "published": 1,
                    "published_at": now(),
                    "project_folder": None,
                    "route": route,
                },
                update_modified=False,
            )

        # Seed the manifest with editorial metadata + our ownership marker
        group_path = os.path.join(get_templates_root("builder_hub"), safe_segment(group))
        os.makedirs(group_path, exist_ok=True)
        manifest_path = os.path.join(group_path, "template.json")
        manifest = {}
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                try:
                    manifest = json.load(f)
                except ValueError:
                    manifest = {}
        manifest["source"] = PROTECTED_GROUPS_MARKER
        if title:
            manifest["title"] = title
        if description:
            manifest["description"] = description
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(frappe.as_json(manifest, ensure_ascii=False))

        update_template_manifest(group_path, [p.name for p in staged], title=title or group)

        # Disk fixtures (pages + components + variables + scripts + fonts +
        # assets copied under www/builder_assets/<group>/)
        export_template_group(group, target_app="builder_hub")
    finally:
        frappe.flags.in_import = False

    _delete_staging_folder(folder)
    frappe.db.commit()
    _clear_catalog_caches()

    return {
        "group": group,
        "pages": [p.name for p in staged],
        "fixture_path": f"builder_hub/builder_templates/{group}",
        "note": "Fixtures written on the hub server are untracked — commit them "
        "to git from the hub checkout to make them durable.",
    }


@frappe.whitelist()
def unpublish_from_catalog(group: str):
    """Remove a promoted group from the catalog (pages survive as drafts back
    in the staging folder, fixtures are deleted)."""
    _check_publisher()
    group = _validate_group_slug(group)
    _assert_group_not_protected(group)

    import os
    import shutil

    from builder.template_sync import get_group_assets_root, get_templates_root

    pages = frappe.get_all(
        "Builder Page", filters={"is_template": 1, "template_group": group}, pluck="name"
    )
    folder = _ensure_staging_folder(group)
    frappe.flags.in_import = True
    try:
        for name in pages:
            frappe.db.set_value(
                "Builder Page",
                name,
                {
                    "is_template": 0,
                    "template_group": None,
                    "published": 0,
                    "published_at": None,
                    "project_folder": folder,
                },
                update_modified=False,
            )
    finally:
        frappe.flags.in_import = False

    for path in (
        os.path.join(get_templates_root("builder_hub"), safe_segment(group)),
        get_group_assets_root(safe_segment(group), "builder_hub"),
    ):
        if os.path.isdir(path):
            shutil.rmtree(path)

    frappe.db.commit()
    _clear_catalog_caches()
    return {"group": group, "pages": pages, "staging_folder": folder}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _reject_foreign_asset_urls(payload: dict):
    """Every asset reference must be hub-local (/files/... or /builder_assets/...).
    Absolute URLs pointing elsewhere mean the client skipped the upload step —
    rejecting them doubles as an SSRF/content guard."""
    blob = frappe.as_json(payload, indent=0)
    for match in re.finditer(r'"(https?://[^"]+)"', blob):
        url = match.group(1)
        if not url.startswith(frappe.utils.get_url()):
            frappe.throw(
                _("Foreign asset URL in payload: {0} — upload assets via upload_template_asset first").format(
                    url[:120]
                )
            )


def _ensure_staging_folder(group: str) -> str:
    name = _staging_folder_name(group)
    if not frappe.db.exists("Builder Project Folder", name):
        frappe.get_doc({"doctype": "Builder Project Folder", "folder_name": name}).insert(
            ignore_permissions=True
        )
    return name


def _delete_staging_folder(name: str):
    if frappe.db.exists("Builder Project Folder", name):
        frappe.delete_doc("Builder Project Folder", name, force=True, ignore_permissions=True)


def _upsert_variables(variables: list, warnings: list):
    for var in variables:
        name = var.get("name")
        if not name:
            continue
        values = {
            "variable_name": var.get("variable_name"),
            "type": var.get("type") or "Color",
            "value": var.get("value"),
            "dark_value": var.get("dark_value"),
            "group": var.get("group"),
        }
        if frappe.db.exists("Builder Variable", name):
            frappe.db.set_value("Builder Variable", name, values, update_modified=False)
        else:
            frappe.get_doc({"doctype": "Builder Variable", "name": name, **values}).insert(
                ignore_permissions=True, set_name=name
            )


def _upsert_components(group: str, components: list, warnings: list):
    import hashlib

    for comp in components:
        component_id = comp.get("component_id") or comp.get("name")
        if not component_id:
            continue
        block_json = comp.get("block") or "{}"
        if frappe.db.exists("Builder Component", component_id):
            existing_block = frappe.db.get_value("Builder Component", component_id, "block") or "{}"

            def _h(s):
                return hashlib.md5(json.dumps(json.loads(s), sort_keys=True).encode()).hexdigest()

            try:
                same = _h(existing_block) == _h(block_json)
            except Exception:
                same = existing_block == block_json
            if same:
                continue
            frappe.throw(
                _(
                    "Component {0} already exists on the hub with different content — "
                    "rename the component on the source site and re-publish"
                ).format(component_id),
                exc=frappe.DuplicateEntryError,
            )
        else:
            frappe.get_doc(
                {
                    "doctype": "Builder Component",
                    "name": component_id,
                    "component_id": component_id,
                    "component_name": comp.get("component_name") or component_id,
                    "block": block_json,
                }
            ).insert(ignore_permissions=True, set_name=component_id)


def _upsert_client_scripts(group: str, scripts: list, warnings: list):
    for script in scripts:
        base = script.get("name") or "script"
        name = base if base.startswith(f"{group}-") else f"{group}-{base}"
        values = {
            "script_type": script.get("script_type") or "JavaScript",
            "script": script.get("script") or "",
        }
        if frappe.db.exists("Builder Client Script", name):
            frappe.db.set_value("Builder Client Script", name, values, update_modified=False)
        else:
            doc = frappe.get_doc({"doctype": "Builder Client Script", "name": name, **values})
            doc.insert(ignore_permissions=True, set_name=name)
        script["_hub_name"] = name


def _upsert_fonts(fonts: list, warnings: list):
    for font in fonts:
        font_name = font.get("font_name")
        if not font_name:
            continue
        if frappe.db.exists("User Font", {"font_name": font_name}):
            continue
        try:
            frappe.get_doc(
                {
                    "doctype": "User Font",
                    "font_name": font_name,
                    "font_file": font.get("font_file"),
                }
            ).insert(ignore_permissions=True)
        except Exception as e:
            warnings.append(f"font {font_name}: {e}")


def _upsert_staged_page(group: str, folder: str, page: dict, bundle: dict, warnings: list) -> str:
    title = page.get("page_title") or "Untitled"
    blocks = page.get("blocks")
    blocks_json = blocks if isinstance(blocks, str) else frappe.as_json(blocks, indent=0)

    existing = frappe.db.get_value(
        "Builder Page", {"project_folder": folder, "page_title": title}, "name"
    )

    values = {
        "page_title": title,
        "blocks": blocks_json,
        "draft_blocks": None,
        "published": 0,
        "preview": page.get("preview"),
        "page_data_script": page.get("page_data_script"),
        "head_html": page.get("head_html"),
        "body_html": page.get("body_html"),
        "meta_description": page.get("meta_description"),
        "project_folder": folder,
    }

    if existing:
        doc = frappe.get_doc("Builder Page", existing)
        doc.update(values)
        doc.client_scripts = []
        for script in bundle.get("client_scripts") or []:
            if script.get("_hub_name"):
                doc.append("client_scripts", {"builder_script": script["_hub_name"]})
        doc.save(ignore_permissions=True)
        return doc.name

    doc = frappe.get_doc({"doctype": "Builder Page", **values})
    for script in bundle.get("client_scripts") or []:
        if script.get("_hub_name"):
            doc.append("client_scripts", {"builder_script": script["_hub_name"]})
    doc.insert(ignore_permissions=True)
    return doc.name


def _drop_stale_staged_pages(folder: str, keep: list):
    for name in frappe.get_all(
        "Builder Page", filters={"project_folder": folder, "name": ("not in", keep)}, pluck="name"
    ):
        frappe.delete_doc("Builder Page", name, force=True, ignore_permissions=True)


def _clear_catalog_caches():
    from builder_hub.api import _get_catalog, _get_template_bundle

    try:
        _get_catalog.clear_cache()
        _get_template_bundle.clear_cache()
    except Exception:
        frappe.cache().delete_keys("builder_hub*")


def ensure_publisher_role():
    """Idempotently create the Hub Publisher role (called on install/migrate)."""
    if not frappe.db.exists("Role", "Hub Publisher"):
        frappe.get_doc(
            {"doctype": "Role", "role_name": "Hub Publisher", "desk_access": 0}
        ).insert(ignore_permissions=True)
        frappe.db.commit()
