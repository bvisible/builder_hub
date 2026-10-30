# //// Neoffice — added file (no upstream equivalent): from a page drawn in the Builder editor to a hub block, and back.
"""A block is drawn where pages are drawn: in the hub's Builder editor. This module is the two-way bridge between that editor and the
block of the library (block_format.py), so that nobody has to write the YAML of a block by hand.

THE CONVENTIONS of a page that is going to be a block (the editor needs no change for them):
- the page holds ONE section (the first one is the block);
- a colour, a font or a width comes from a token of the palette `Hub blocks` (the tokens are named `hb-<role>`: `hb-primary`,
  `hb-font-heading`, `hb-ground-ink`…; they are created on the hub, and their values only serve the preview in the editor), never typed;
- a text the writer has to write is typed as `WRITE <role>: <guidance>` (`WRITE heading: 4 to 8 words, one accent word`); a text in
  plain words is refused, it would be the same on every site;
- the attributes below are set in the editor's Attributes panel:
    `data-photo`   = 0, 1, 2…   on an image: it is the photograph number N of the block (the picture shown in the editor is only a
                                placeholder; its alt is `WRITE alt: …` by default, written for the photograph);
    `data-ground`  = plain | tint | deep   on any block: it and what is under it are drawn on that ground (`hb-ground-*` tokens follow it);
    `data-include` = component   on an empty block: the live contact form goes there;
    `data-cta`     = true   on a link: it goes where the site sends its visitors to act (its contact or booking page), whatever its href says
                                in the editor; any other link goes to a path of the site, an anchor, tel: or mailto:.

`compile_blocks` reads such a page and gives the tree of the block (with a report of what is wrong, in the words of the editor);
`to_page_yaml` does the opposite, so that a block of the library (a seed, one written by hand) can be opened in the editor and changed there.
Neither imports Frappe: the tests run anywhere."""

import copy
import re
from dataclasses import dataclass, field

import yaml

from builder_hub import block_format

TOKEN_PREFIX = "hb-"
TOKEN_GROUP = "Hub blocks"

# (role, type, the value the editor previews with): the palette of the blocks. The roles are the tokens of block_format; `ground.*` are the
# plain ground (a block drawn in the editor shows the plain ground whatever its data-ground: the real one is drawn by the site).
PALETTE = [
	("primary", "Color", "#1f3a5f"),
	("secondary", "Color", "#c9a24b"),
	("background", "Color", "#faf8f4"),
	("text", "Color", "#1d1d1b"),
	("muted", "Color", "rgba(29, 29, 27, 0.72)"),
	("hair", "Color", "rgba(29, 29, 27, 0.16)"),
	("tint", "Color", "rgba(31, 58, 95, 0.08)"),
	("frame", "Color", "rgba(201, 162, 75, 0.35)"),
	("deep", "Color", "#1f3a5f"),
	("ink_on_deep", "Color", "#faf8f4"),
	("deep_muted", "Color", "rgba(250, 248, 244, 0.8)"),
	("deep_hair", "Color", "rgba(250, 248, 244, 0.25)"),
	("ground.background", "Color", "#faf8f4"),
	("ground.ink", "Color", "#1d1d1b"),
	("ground.muted", "Color", "rgba(29, 29, 27, 0.72)"),
	("ground.hair", "Color", "rgba(29, 29, 27, 0.16)"),
	("ground.accent", "Color", "#c9a24b"),
	("font_heading", "Font", "Georgia"),
	("font_body", "Font", "Arial"),
	("container", "Dimension", "1200px"),
	("gutter", "Dimension", "48px"),
	("gutter_phone", "Dimension", "24px"),
]
ROLES = {role for role, _type, _value in PALETTE}
assert ROLES <= block_format.LOOK_TOKENS | block_format.GROUND_TOKENS, (
	"the palette names a role the block format does not know"
)

VAR = re.compile(r"var\(--([\w-]+)\)")
PLACEHOLDER_PHOTO = "/assets/builder/images/fallback.png"
ALT_SLOT = "WRITE alt: a photographic description of the scene, 10 to 20 words, specific to this business"
STARTER = """el: section
name: block
style: {backgroundColor: "{{ground.background}}", width: 100%, padding: 6rem 0}
m_style: {padding: 4rem 0}
c:
  - el: div
    name: container
    style: {maxWidth: "{{container}}", width: 100%, margin: 0 auto, paddingLeft: "{{gutter}}", paddingRight: "{{gutter}}"}
    m_style: {paddingLeft: "{{gutter_phone}}", paddingRight: "{{gutter_phone}}"}
    c:
      - el: h2
        name: heading
        style: {fontFamily: "{{font_heading}}", fontSize: 3rem, fontWeight: "700", lineHeight: "1.15", color: "{{ground.ink}}", margin: 0 0 1.25rem}
        m_style: {fontSize: 1.75rem}
        text: "WRITE heading: 4 to 8 words, one accent word"
      - el: p
        name: text
        style: {fontFamily: "{{font_body}}", fontSize: 1.0625rem, lineHeight: "1.7", color: "{{ground.muted}}", margin: 0, maxWidth: 34rem}
        text: "WRITE text: two or three sentences, 40 to 60 words, from the business's own facts"
"""

# what a block cannot carry, and what to say to the person who drew it
UNSUPPORTED = {
	"extendedFromComponent": "is a component: ungroup it (a block is drawn in plain blocks)",
	"isRepeaterBlock": "is a repeater: a block holds the items it shows, one block each",
	"dynamicValues": "is bound to data: a block holds no data",
	"visibilityCondition": "has a visibility condition: a block shows everything it holds",
	"clientScript": "carries a script: a block holds none",
	"blockClientScript": "carries a script: a block holds none",
}


def role_of_token(key: str) -> str | None:
	"""The role of a palette token (`hb-ground-ink` is `ground.ink`), or None for any other variable."""
	if not key.startswith(TOKEN_PREFIX):
		return None
	role = key[len(TOKEN_PREFIX) :].replace("-", "_")
	if role.startswith("ground_"):
		role = "ground." + role[len("ground_") :]
	return role if role in ROLES else None


def token_key(role: str) -> str:
	"""`ground.ink` is the token `hb-ground-ink`."""
	return TOKEN_PREFIX + role.replace(".", "-").replace("_", "-")


@dataclass
class Compiled:
	tree: dict | None = None
	photos: int = 0
	form: bool = False
	errors: list = field(default_factory=list)
	warnings: list = field(default_factory=list)

	def report(self) -> str:
		return "\n".join([*(f"ERROR {e}" for e in self.errors), *(f"warning {w}" for w in self.warnings)])


def _first_section(blocks):
	"""(the first section in reading order, how many there are)."""
	found = []

	def walk(nodes):
		for node in nodes or []:
			if isinstance(node, dict):
				if str(node.get("element") or "").lower() == "section":
					found.append(node)
				walk(node.get("children"))

	walk(blocks if isinstance(blocks, list) else [blocks])
	return (found[0] if found else None), len(found)


def _styles(raw, where: str, role_of, errors: list) -> dict:
	out = {}
	for key, value in (raw or {}).items():
		if isinstance(value, str):

			def swap(match, key=key):
				role = role_of(match.group(1))
				if role is None:
					errors.append(
						f"{where}.{key}: `{match.group(0)}` is not a token of the Hub blocks palette: pick the colour, font or width from the palette"
					)
					return match.group(0)
				return "{{" + role + "}}"

			value = VAR.sub(swap, value)
		if value in ("", None):
			continue
		out[key] = value
	return out


def _node(block: dict, role_of, state: dict, path: str) -> dict:
	errors = state["errors"]
	tag = str(block.get("element") or "").lower()
	name = block.get("blockName") or ""
	here = f"{path}>{name or tag}"
	for key, why in UNSUPPORTED.items():
		if block.get(key):
			errors.append(f"{here}: it {why}")
	node: dict = {"el": tag}
	if name:
		node["name"] = name
	if block.get("classes"):
		node["classes"] = [c for c in block["classes"] if isinstance(c, str) and c.strip()]
	for source, target in (("baseStyles", "style"), ("tabletStyles", "t_style"), ("mobileStyles", "m_style")):
		styles = _styles(block.get(source), f"{here}.{target}", role_of, errors)
		if styles:
			node[target] = styles

	attrs = {**(block.get("attributes") or {}), **(block.get("customAttributes") or {})}
	ground = attrs.pop("data-ground", None)
	photo = attrs.pop("data-photo", None)
	include = attrs.pop("data-include", None)
	cta = attrs.pop("data-cta", None)
	if ground not in (None, ""):
		node["ground"] = str(ground)
	if photo not in (None, ""):
		if tag != "img":
			errors.append(f"{here}: data-photo is for an image")
		else:
			try:
				index = int(photo)
			except ValueError:
				errors.append(f"{here}: data-photo must be a number (0, 1, 2…), got `{photo}`")
			else:
				state["photos"].add(index)
				attrs["src"] = "{{photo." + str(index) + "}}"
				if not block_format.SLOT.match(str(attrs.get("alt") or "")):
					attrs["alt"] = ALT_SLOT
	elif tag == "img":
		errors.append(
			f"{here}: an image of a block is a photograph of the site: set data-photo (0, 1, 2…) in the Attributes panel"
		)
	if str(cta or "").lower() in ("true", "1", "yes"):
		if tag != "a":
			errors.append(f"{here}: data-cta is for a link")
		else:
			attrs["href"] = "{{cta_href}}"
	attrs = {k: v for k, v in attrs.items() if v not in ("", None)}
	if attrs:
		node["attrs"] = attrs

	children = [c for c in block.get("children") or [] if isinstance(c, dict)]
	if include not in (None, ""):
		state["form"] = True
		node["text"] = "{{include_component}}"
		if children:
			errors.append(f"{here}: the block that holds the form must be empty")
		return node
	text = block.get("innerHTML")
	if children:
		if isinstance(text, str) and text.strip() and tag not in ("svg",):
			state["warnings"].append(f"{here}: it holds blocks, so its own text is not kept")
		node["c"] = [_node(child, role_of, state, here) for child in children]
	elif isinstance(text, str) and text.strip():
		node["text"] = text.strip()
	return node


def compile_blocks(blocks, role_of=role_of_token) -> Compiled:
	"""The block (tree, photograph count, form) a page drawn in the editor holds, and what is wrong with it. `role_of(variable)` says which role of
	the palette a CSS variable is (None for any other)."""
	result = Compiled()
	section, count = _first_section(blocks)
	if section is None:
		result.errors.append("the page holds no section: a block is one section")
		return result
	if count > 1:
		result.warnings.append(f"the page holds {count} sections: only the first one is the block")
	state = {"errors": result.errors, "warnings": result.warnings, "photos": set(), "form": False}
	result.tree = _node(section, role_of, state, "page")
	result.photos = len(state["photos"])
	result.form = state["form"]
	return result


# ---------------------------------------------------------------- the other way: a block, to be opened in the editor


def _to_editor(value):
	if isinstance(value, str):
		return block_format.TOKEN.sub(
			lambda m: f"var(--{token_key(m.group(1))})" if m.group(1) in ROLES else m.group(0), value
		)
	return value


def _page_node(node: dict) -> dict:
	out = copy.deepcopy(node)
	attrs = dict(out.get("attrs") or {})
	ground = out.pop("ground", None)
	if ground:
		attrs["data-ground"] = ground
	if str(attrs.get("href") or "").strip() == "{{cta_href}}":
		# braces in an attribute are read by the editor as data: the link is marked, and shows the page it will usually go to
		attrs["data-cta"] = "true"
		attrs["href"] = "/contact"
	src = str(attrs.get("src") or "")
	photo = re.fullmatch(r"\{\{\s*photo\.(\d)\s*\}\}", src)
	if photo:
		attrs["data-photo"] = photo.group(1)
		attrs["src"] = PLACEHOLDER_PHOTO
	if str(out.get("text") or "").strip() == "{{include_component}}":
		attrs["data-include"] = "component"
		out["text"] = "The contact form goes here"
	for key in ("style", "t_style", "m_style"):
		if key in out:
			out[key] = {k: _to_editor(v) for k, v in out[key].items()}
	if attrs:
		out["attrs"] = {k: (str(v) if isinstance(v, int) else v) for k, v in attrs.items()}
	if "c" in out:
		out["c"] = [_page_node(child) for child in out["c"]]
	return out


def to_page_yaml(tree: dict | None) -> str:
	"""The block as the writer's own YAML for a page (a body holding the section; builder.ai.page_writer.expand_page_yaml reads it), tokens turned
	into the variables of the palette, so that the editor shows it with the colours of the palette and `compile_blocks` gives the same tree back.
	With no tree, a starting section."""
	if not tree:
		tree = yaml.safe_load(STARTER)
	body = {
		"el": "div",
		"name": "body",
		"style": {"display": "flex", "flexDirection": "column"},
		"c": [_page_node(tree)],
	}
	return yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False)
