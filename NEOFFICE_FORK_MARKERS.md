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
