<!-- //// Neoffice — added file (no upstream equivalent): where the divergences of this fork that no comment can reach are written down. -->
# Neoffice fork markers

What in this repository is **ours** and not `frappe/builder_hub`'s. Every hunk of code we changed carries a `//// Neoffice` comment
saying what upstream did, what we do instead and why: `grep -rn "////" .` is the map. This file holds what a comment cannot reach, files
with no comment syntax (JSON).

Checked with `fork_markers.py` from `bvisible/neoffice-ci`.

## Files with no comment syntax

| Path | What it is | Why |
|---|---|---|
| `builder_hub/builder_hub/doctype/hub_block/hub_block.json` | the Hub Block doctype, the hub's library of blocks (`builder_hub/blocks.py`, `builder_hub/block_format.py`) | added file: no upstream equivalent. A block is a section of a site designed once, edited in the hub's desk and served to the site generators of the Neoservice fleet |
| `builder_hub/builder_templates/cabinet_dentaire/template.json` | the manifest of the dental practice site, a group published from a generated site | added file: no upstream equivalent. `sector` and `translations` are what the gallery of neoffice.ch reads through `get_catalog` (`builder_hub/showcase.py`) |
| `builder_hub/builder_templates/electricien/template.json` | the manifest of the electrician site, a group published from a generated site | added file: no upstream equivalent. `sector` and `translations` are what the gallery of neoffice.ch reads through `get_catalog` (`builder_hub/showcase.py`) |
| `builder_hub/builder_templates/garage/template.json` | the manifest of the garage site, a group published from a generated site | added file: no upstream equivalent. `sector` and `translations` are what the gallery of neoffice.ch reads through `get_catalog` (`builder_hub/showcase.py`) |
| `builder_hub/builder_templates/restaurant/template.json` | the manifest of the restaurant site, a group published from a generated site | added file: no upstream equivalent. `sector` and `translations` are what the gallery of neoffice.ch reads through `get_catalog` (`builder_hub/showcase.py`) |
| `builder_hub/builder_templates/salon_de_coiffure/template.json` | the manifest of the hair salon site, a group published from a generated site | added file: no upstream equivalent. `sector` and `translations` are what the gallery of neoffice.ch reads through `get_catalog` (`builder_hub/showcase.py`) |
