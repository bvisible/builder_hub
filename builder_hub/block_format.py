# //// Neoffice — added file (no upstream equivalent): the format of a hub block and its linter.
"""A hub block is a section of a site, written once and drawn for every site that asks for it.

It is stored as a tree in the compact node format the Nora site generator writes pages in (`el`, `name`, `classes`, `style`,
`t_style`, `m_style`, `attrs`, `text`, `c`), with three additions that make it a template rather than a page:

- a colour, a font or a width is a TOKEN, `{{primary}}`, `{{ground.ink}}`, `{{font_heading}}`: the consumer fills it with the handles of
  the site it draws the block on, so the same block is blue on one site and green on another;
- a text the site's writer has to write is a SLOT, `WRITE <role>: <guidance>` (the writer replaces the whole text, in the language of the
  site); a block never carries words of its own, they would be the same on every site;
- a node may set `ground: plain|tint|deep`: its subtree is drawn on that ground (`{{ground.*}}` tokens follow it).

It says whether a tree is a well-formed block (`lint`) and nothing else, and imports nothing from Frappe, so the tests run it anywhere.

THIS FILE EXISTS TWICE, byte for byte: here (the hub lints a block when it is saved and again when it serves it) and in the `builder` app as
`builder/site_ai/nora/block_format.py` (a site generator lints what it fetched before it draws it: the hub is another server, and what a
block holds ends up in published pages). Change one, change the other in the same sitting; a change of what a tree may hold bumps `FORMAT`,
and a consumer refuses a format it does not know instead of guessing. Drift is safe: a block one side no longer accepts is left out.
"""

import re

import yaml

FORMAT = 1

GROUNDS = ("plain", "tint", "deep")
MOTIONS = ("None", "Calm", "Brisk")

# the node keys of the writer's format, plus `ground`
NODE_KEYS = {"el", "name", "classes", "style", "t_style", "m_style", "attrs", "text", "c", "ground"}

TAGS = {
	"section", "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6", "a", "img", "ul", "ol", "li", "hr", "blockquote", "figure",
	"figcaption", "em", "strong", "small", "header", "footer", "article", "aside", "br",
}  # fmt: skip

# what the consumer fills in: the look of the site, the ground the node sits on, the photographs and the live component
LOOK_TOKENS = {
	"primary", "secondary", "background", "text", "font_heading", "font_body", "container", "gutter", "gutter_phone", "muted", "hair",
	"tint", "frame", "deep", "ink_on_deep", "deep_muted", "deep_hair",
}  # fmt: skip
GROUND_TOKENS = {
	"ground.background",
	"ground.ink",
	"ground.muted",
	"ground.hair",
	"ground.accent",
	"ground.button",
}
PLAIN_TOKENS = {"cta_href", "include_component"}
PHOTO = re.compile(r"^photo\.(\d)$")
MAX_PHOTOS = 6

TOKEN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
SLOT = re.compile(r"^\s*WRITE\s+([\w-]+)\s*:\s*(\S.*)$", re.DOTALL)
BLOCK_ID = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
CLASS = re.compile(r"^[A-Za-z][\w-]*$")
CSS_KEY = re.compile(r"^[a-z][A-Za-z]*$")
# what a stylesheet value must never carry: a request to somewhere else, a script, markup
CSS_FORBIDDEN = re.compile(r"url\(|expression\(|javascript:|@import|[<>\\{}]", re.IGNORECASE)
COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\(", re.IGNORECASE)
SAFE_HREF = re.compile(r"^(?:/[^/\s]*|#\S*|tel:\S+|mailto:\S+)$")
MOTION_CLASSES = {"u-reveal", "u-marquee", "u-count"}

MAX_DEPTH = 10
MAX_NODES = 120
MAX_BYTES = 40_000


def parse_tree(text: str):
	"""The tree a block's source holds: YAML, one mapping. Raises ValueError for anything else."""
	try:
		tree = yaml.safe_load(text or "")
	except yaml.YAMLError as e:
		raise ValueError(f"the tree is not valid YAML: {str(e).splitlines()[0]}") from e
	if isinstance(tree, list) and len(tree) == 1:  # the writer's own form is a list of one item
		tree = tree[0]
	if not isinstance(tree, dict):
		raise ValueError("the tree must be one node (a mapping with `el`)")
	return tree


def lint(
	tree, *, block_id: str, kinds=(), photos: int = 0, form: bool = False, motion: str = "None"
) -> tuple[list[str], list[str]]:
	"""(errors, warnings) of a block. A block with an error is never served; a warning is shown to the person who edits it."""
	errors: list[str] = []
	warnings: list[str] = []
	if not BLOCK_ID.match(block_id or ""):
		errors.append(f"id `{block_id}` must be <family>.<variant>, lowercase letters, digits and hyphens")
	if not kinds:
		errors.append("kinds is empty: a block must say which section kinds it can carry")
	if motion not in MOTIONS:
		errors.append(f"motion `{motion}` must be one of {', '.join(MOTIONS)}")
	if not 0 <= photos <= MAX_PHOTOS:
		errors.append(f"photos must be between 0 and {MAX_PHOTOS}")
	if not isinstance(tree, dict):
		return [*errors, "the tree must be one node"], warnings

	state = {"nodes": 0, "photos": set(), "slots": 0, "include": False, "motion_class": False}
	_node(tree, "root", 1, errors, warnings, state)

	if tree.get("el") != "section":
		errors.append("the root node must be a `section`: a block is one section of a page")
	used = state["photos"]
	if used != set(range(photos)):
		errors.append(
			f"photos is {photos} but the tree uses {{{{photo.N}}}} for {sorted(used) or 'none'}: they must be 0..{photos - 1}"
		)
	if form and not state["include"]:
		errors.append("form is set but the tree never carries `{{include_component}}`")
	if state["include"] and not form:
		errors.append("the tree carries `{{include_component}}` but form is not set")
	if not state["slots"]:
		errors.append("the tree has no `WRITE <role>:` slot: a block with no words to write is a picture")
	if state["motion_class"] and motion == "None":
		errors.append("the tree uses a motion class (u-reveal, u-marquee, u-count) but motion is None")
	if len(yaml.safe_dump(tree)) > MAX_BYTES:
		errors.append(f"the tree is larger than {MAX_BYTES} bytes")
	return errors, warnings


def _token_ok(name: str, state: dict, where: str, errors: list[str]) -> None:
	if name in LOOK_TOKENS or name in GROUND_TOKENS or name in PLAIN_TOKENS:
		if name == "include_component":
			state["include"] = True
		return
	photo = PHOTO.match(name)
	if photo:
		state["photos"].add(int(photo.group(1)))
		return
	errors.append(f"{where}: unknown token {{{{{name}}}}}")


def _text(
	value, where: str, errors: list[str], warnings: list[str], state: dict, *, allow_slot: bool
) -> None:
	if not isinstance(value, str):
		errors.append(f"{where}: must be a string")
		return
	slot = SLOT.match(value)
	if slot:
		if not allow_slot:
			errors.append(f"{where}: a slot is not allowed here")
		else:
			state["slots"] += 1
		if TOKEN.search(value):
			errors.append(f"{where}: a slot holds guidance, not tokens")
		return
	for name in TOKEN.findall(value):
		_token_ok(name, state, where, errors)
	if re.search(r"\bWRITE\b", value):
		errors.append(f"{where}: `WRITE` must start the text and be followed by `<role>:` and its guidance")
	rest = TOKEN.sub("", value)
	if rest.strip() and re.search(r"[^\W\d_]", rest):
		errors.append(f"{where}: fixed words would be the same on every site: make it a `WRITE <role>:` slot")


def _style(value, where: str, errors: list[str], warnings: list[str], state: dict) -> None:
	if not isinstance(value, dict):
		errors.append(f"{where}: must be a mapping of CSS properties")
		return
	for key, item in value.items():
		if not isinstance(key, str) or not CSS_KEY.match(key):
			errors.append(f"{where}: `{key}` is not a camelCase CSS property")
			continue
		if isinstance(item, bool) or not isinstance(item, (str, int, float)):
			errors.append(f"{where}.{key}: must be a string or a number")
			continue
		text = str(item)
		if CSS_FORBIDDEN.search(TOKEN.sub("", text)):
			errors.append(f"{where}.{key}: `{text}` may not carry url(), a script, markup or an import")
			continue
		for name in TOKEN.findall(text):
			_token_ok(name, state, f"{where}.{key}", errors)
		if COLOUR_LITERAL.search(TOKEN.sub("", text)):
			warnings.append(
				f"{where}.{key}: a colour written out; use a handle ({{{{primary}}}}, {{{{ground.ink}}}}…) so the block follows the site"
			)


def _attrs(value, where: str, errors: list[str], warnings: list[str], state: dict) -> None:
	if not isinstance(value, dict):
		errors.append(f"{where}: must be a mapping")
		return
	for key, item in value.items():
		here = f"{where}.{key}"
		lowered = str(key).lower()
		if lowered.startswith("on") or lowered in {"style", "srcdoc", "formaction"}:
			errors.append(f"{here}: not allowed")
			continue
		if not isinstance(item, str):
			errors.append(f"{here}: must be a string")
			continue
		if lowered == "alt":
			_text(item, here, errors, warnings, state, allow_slot=True)
		elif lowered == "src":
			if not re.fullmatch(r"\{\{\s*photo\.\d\s*\}\}", item):
				errors.append(f"{here}: an image comes from `{{{{photo.N}}}}`, never from an address")
			else:
				_token_ok(TOKEN.search(item).group(1), state, here, errors)
		elif lowered == "href":
			if re.fullmatch(r"\{\{\s*cta_href\s*\}\}", item):
				continue
			if not SAFE_HREF.match(item):
				errors.append(
					f"{here}: `{item}` must be `{{{{cta_href}}}}`, a path of the site, an anchor, tel: or mailto:"
				)
		elif lowered in {"role", "aria-label", "aria-hidden", "title", "id"} or lowered.startswith("data-"):
			if TOKEN.search(item):
				errors.append(f"{here}: no token here")
		else:
			errors.append(f"{here}: attribute `{key}` is not allowed")


def _node(node, where: str, depth: int, errors: list[str], warnings: list[str], state: dict) -> None:
	state["nodes"] += 1
	if state["nodes"] > MAX_NODES:
		if state["nodes"] == MAX_NODES + 1:
			errors.append(f"the tree has more than {MAX_NODES} nodes")
		return
	if depth > MAX_DEPTH:
		errors.append(f"{where}: nested deeper than {MAX_DEPTH}")
		return
	if not isinstance(node, dict):
		errors.append(f"{where}: a node must be a mapping")
		return
	extra = set(node) - NODE_KEYS
	if extra:
		errors.append(f"{where}: unknown keys {sorted(extra)}")
	tag = node.get("el")
	if tag not in TAGS:
		errors.append(f"{where}: `el` must be one of the allowed tags, got `{tag}`")
	label = f"{where}>{node.get('name') or tag}"
	if "ground" in node and node["ground"] not in GROUNDS:
		errors.append(f"{label}: ground must be one of {', '.join(GROUNDS)}")
	classes = node.get("classes")
	if classes is not None:
		if not isinstance(classes, list) or not all(isinstance(c, str) and CLASS.match(c) for c in classes):
			errors.append(f"{label}: classes must be a list of class names")
		elif MOTION_CLASSES.intersection(classes):
			state["motion_class"] = True
	for key in ("style", "t_style", "m_style"):
		if key in node:
			_style(node[key], f"{label}.{key}", errors, warnings, state)
	if "attrs" in node:
		_attrs(node["attrs"], f"{label}.attrs", errors, warnings, state)
	if tag == "img" and not SLOT.match(str((node.get("attrs") or {}).get("alt") or "")):
		errors.append(
			f"{label}: an image needs an `alt` slot (`WRITE alt: …`), the alt text is also what the photograph is drawn from"
		)
	if "text" in node:
		_text(node["text"], f"{label}.text", errors, warnings, state, allow_slot=True)
		if node.get("c"):
			errors.append(f"{label}: a node has either `text` or children `c`, not both")
	children = node.get("c")
	if children is not None:
		if not isinstance(children, list):
			errors.append(f"{label}.c: must be a list")
		else:
			for index, child in enumerate(children):
				_node(child, f"{label}[{index}]", depth + 1, errors, warnings, state)
