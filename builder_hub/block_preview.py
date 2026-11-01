# //// Neoffice — added file (no upstream equivalent): a block drawn as a page, with sample words and the look of a site.
"""A block is a template: the colours of a site, the words of a writer. To judge it before it is published, this module draws it as a plain
HTML page, so that the desk of the hub can show it in a frame at the width of a desktop, a tablet and a phone:

- the look is a PALETTE (the four colours and the two fonts a site brings); every other colour a block uses (the muted ink, the hairlines, the tint,
  the deep band) is derived from them with the generator's own formulas (builder/site_ai/nora/recipes.py, `Look`), so a block looks here as it
  will on a site with that palette; `test_block_preview` and the builder's `test_hub_blocks` pin the same numbers;
- the words are SAMPLE words, as long as the slot allows: `WRITE heading: 4 to 8 words, one accent word` is drawn with eight words, the longest
  case, which is where a layout breaks (the other choice is the middle of the range). A numeral counts up, a button says what a button says;
- photographs are neutral frames, the form is a mock form, a link goes nowhere.

It is not a promise of pixels: the utilities of a site (`u-card`, `u-btn`, `u-grid`…) are redrawn here in a few lines, and the fonts are system fonts
(no request leaves the page). It is a promise of structure: what overflows, collapses badly or reads badly here would do the same on a site.
No Frappe, no third party."""

import html
import re

from builder_hub import block_format

DARK = 0.2  # the generator's threshold between a dark colour and a light one
TABLET_MAX = 1023  # the Builder's breakpoints (builder_page.py)
MOBILE_MAX = 576
DEVICES = {"desktop": 1280, "tablet": 820, "phone": 390}
LANGUAGES = ("fr", "en")
LENGTHS = ("longest", "typical")

# the four colours and the two fonts a site brings; fonts are system stacks so that nothing is requested from anywhere
PALETTES = {
	"terracotta": {
		"label": "Terracotta (light, serif)",
		"primary": "#7a2e1d",
		"secondary": "#d9b26f",
		"background": "#faf5ee",
		"text": "#2b1810",
		"font_heading": "Georgia, 'Times New Roman', serif",
		"font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
	},
	"midnight": {
		"label": "Midnight and gold (dark)",
		"primary": "#101820",
		"secondary": "#c9a24b",
		"background": "#12161c",
		"text": "#f2efe8",
		"font_heading": "'Trebuchet MS', 'Segoe UI', sans-serif",
		"font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
	},
	"navy": {
		"label": "Navy and brass (light)",
		"primary": "#1f3a5f",
		"secondary": "#c9a24b",
		"background": "#faf8f4",
		"text": "#1d1d1b",
		"font_heading": "Georgia, 'Times New Roman', serif",
		"font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
	},
	"forest": {
		"label": "Forest and sand (light)",
		"primary": "#2f5d3a",
		"secondary": "#b08d57",
		"background": "#f6f4ee",
		"text": "#1d261f",
		"font_heading": "'Palatino Linotype', Palatino, serif",
		"font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
	},
	"plum": {
		"label": "Plum and amber (light)",
		"primary": "#5b2a4e",
		"secondary": "#e0a458",
		"background": "#fbf7fa",
		"text": "#2a1626",
		"font_heading": "'Trebuchet MS', 'Segoe UI', sans-serif",
		"font_body": "system-ui, -apple-system, 'Segoe UI', sans-serif",
	},
}
DEFAULT_PALETTE = "terracotta"


# ---------------------------------------------------------------- colours, as the generator computes them


def parse_colour(value: str) -> tuple[float, float, float, float] | None:
	value = (value or "").strip()
	hexa = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
	if hexa:
		digits = hexa.group(1)
		if len(digits) == 3:
			digits = "".join(c * 2 for c in digits)
		return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), 1.0)
	rgba = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", value)
	if rgba:
		return (float(rgba.group(1)), float(rgba.group(2)), float(rgba.group(3)), float(rgba.group(4) or 1))
	return None


def luminance(colour) -> float:
	def channel(c: float) -> float:
		c = c / 255
		return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

	r, g, b = (channel(c) for c in colour[:3])
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def to_hex(colour) -> str:
	return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in colour[:3])


def rgba(colour, alpha: float) -> str:
	return f"rgba({round(colour[0])}, {round(colour[1])}, {round(colour[2])}, {alpha})"


def mix(colour, toward, share: float):
	return tuple(c + (t - c) * share for c, t in zip(colour[:3], toward, strict=False))


def look_of(palette: dict) -> dict:
	"""Every look token of block_format for a palette: the six the site brings, and what the generator derives from them (recipes.Look)."""
	p, s, b, t = (parse_colour(palette[k]) for k in ("primary", "secondary", "background", "text"))
	s = s or p
	look = {
		"primary": to_hex(p),
		"secondary": to_hex(s),
		"background": to_hex(b),
		"text": to_hex(t),
		"font_heading": palette["font_heading"],
		"font_body": palette["font_body"],
		"container": "1200px",
		"gutter": "48px",
		"gutter_phone": "24px",
		"muted": rgba(t, 0.72),
		"hair": rgba(t, 0.16),
		"tint": rgba(p or s, 0.08),
		"frame": rgba(s, 0.35),
	}
	if luminance(p) <= DARK:
		look["deep"] = look["primary"]
	elif luminance(t) <= DARK:
		look["deep"] = look["text"]
	else:
		look["deep"] = to_hex(mix(p, (0, 0, 0), 0.55))
	ink = b if luminance(b) > DARK else t
	look["ink_on_deep"] = to_hex(ink)
	look["deep_muted"] = rgba(ink, 0.8)
	look["deep_hair"] = rgba(ink, 0.25)
	return look


def grounds_of(look: dict) -> dict:
	return {
		"plain": {
			"background": look["background"],
			"ink": look["text"],
			"muted": look["muted"],
			"hair": look["hair"],
			"accent": look["secondary"],
		},
		"tint": {
			"background": look["tint"],
			"ink": look["text"],
			"muted": look["muted"],
			"hair": look["hair"],
			"accent": look["secondary"],
		},
		"deep": {
			"background": look["deep"],
			"ink": look["ink_on_deep"],
			"muted": look["deep_muted"],
			"hair": look["deep_hair"],
			"accent": look["secondary"],
		},
	}


# ---------------------------------------------------------------- sample words

BANK = {
	"fr": (
		"Une maison de famille installée dans la vallée depuis trois générations travaille chaque jour des produits de saison choisis chez des "
		"producteurs voisins. Nous prenons le temps d'écouter, de conseiller et de préparer ce qui convient vraiment à chacun, sans promesse en l'air "
		"ni détour. Chaque détail est pensé pour que l'accueil soit simple, chaleureux et fidèle à la région qui nous entoure, de l'atelier jusqu'au "
		"comptoir, avec le même soin pour les petites commandes que pour les grandes."
	),
	"en": (
		"A family house settled in the valley for three generations works every day with seasonal products chosen from neighbouring producers. We take "
		"the time to listen, to advise and to prepare what really suits each person, with no empty promise and no detour. Every detail is thought out "
		"so that the welcome is simple, warm and true to the region around us, from the workshop to the counter, with the same care for small orders "
		"as for large ones."
	),
}
FIXED = {
	"fr": {
		"label": "Notre maison",
		"button": "Nous écrire",
		"link": "En savoir plus",
		"initials": "AB",
		"price": "CHF 28",
		"who": "Prénom Nom",
		"figure": "25",
		"figure-label": "années d'expérience",
		"detail-label": "Adresse",
		"detail-value": "Rue du Exemple 1, 1950 Sion",
		"alt": "Une photographie du lieu",
	},
	"en": {
		"label": "Our house",
		"button": "Write to us",
		"link": "Learn more",
		"initials": "AB",
		"price": "CHF 28",
		"who": "First Last",
		"figure": "25",
		"figure-label": "years of experience",
		"detail-label": "Address",
		"detail-value": "1 Example Street, 1950 Sion",
		"alt": "A photograph of the place",
	},
}
RANGE = re.compile(r"(\d+)\s*(?:to|-|\u2013|à)\s*(\d+)\s*(?:words?|mots?)", re.IGNORECASE)
ONE_RANGE = re.compile(r"(\d+)\s*words?", re.IGNORECASE)
TITLE_ROLES = {"heading", "item-title", "question", "title", "phrase"}


def word_count(guidance: str, length: str) -> int | None:
	"""How many words a slot's guidance allows: the top of its range (`4 to 8 words` is eight), or the middle for `typical`."""
	found = RANGE.search(guidance or "")
	if found:
		low, high = int(found.group(1)), int(found.group(2))
		return high if length == "longest" else (low + high) // 2
	found = ONE_RANGE.search(guidance or "")
	return int(found.group(1)) if found else None


class Words:
	"""The sample words of one preview: a counter per role, so that two headings are not the same sentence and the numerals count up."""

	def __init__(self, lang: str, length: str, accent: str):
		self.lang = lang if lang in LANGUAGES else "fr"
		self.length = length if length in LENGTHS else "longest"
		self.accent = accent
		self.seen: dict[str, int] = {}
		bank = BANK[self.lang]
		self.sentences = [s.strip() for s in re.split(r"(?<=\.)\s+", bank) if s.strip()]
		self.fragments = [f.strip() for f in re.split(r"[.,]", bank) if len(f.split()) >= 3]

	def _text(self, count: int, index: int) -> str:
		"""`count` words of running prose, from the sentence `index`, ending on a full stop."""
		words: list[str] = []
		cursor = index
		while len(words) < count:
			words += self.sentences[cursor % len(self.sentences)].split()
			cursor += 1
		return " ".join(words[:count]).rstrip(",;:.") + "."

	def _title(self, count: int, index: int) -> list[str]:
		"""`count` words of a title: a phrase of the bank, then the next one if it is too short, without punctuation."""
		words: list[str] = []
		cursor = index
		while len(words) < count:
			words += self.fragments[cursor % len(self.fragments)].split()
			cursor += 1
		return words[:count]

	def slot(self, role: str, guidance: str) -> str:
		"""The HTML (escaped, with the accent word wrapped as the writer wraps it) that fills a slot."""
		index = self.seen.get(role, 0)
		self.seen[role] = index + 1
		if role == "numeral":
			return f"{index + 1:02d}"
		fixed = FIXED[self.lang]
		count = word_count(guidance, self.length)
		if role in fixed and (role != "label" or count is None):
			return html.escape(fixed[role])
		shift = index + sum(map(ord, role)) % 5
		if role in TITLE_ROLES or role == "label":
			words = self._title(count or 6, shift)
			words[0] = words[0][:1].upper() + words[0][1:]
			if "accent" in (guidance or "").lower() and len(words) > 1:
				words = [html.escape(w) for w in words[:-1]] + [
					f'<em style="font-style: italic; color: {self.accent}">{html.escape(words[-1])}</em>'
				]
			else:
				words = [html.escape(w) for w in words]
			return " ".join(words)
		return html.escape(self._text(count or 24, shift))


# ---------------------------------------------------------------- the page

UNITLESS = {
	"lineHeight",
	"fontWeight",
	"opacity",
	"flex",
	"flexGrow",
	"flexShrink",
	"zIndex",
	"order",
	"aspectRatio",
	"scale",
}
VOID = {"img", "hr", "br"}
SAFE_ATTR = re.compile(r"^(?:role|title|id|aria-[\w-]+|data-[\w-]+)$")


def _css(styles: dict, look: dict, ground: dict) -> str:
	out = []
	for key, value in styles.items():
		prop = re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key)
		if isinstance(value, (int, float)) and not isinstance(value, bool):
			value = f"{value}" if key in UNITLESS or value == 0 else f"{value}px"
		out.append(f"{prop}: {_fill(str(value), look, ground)}")
	return "; ".join(out)


def _fill(text: str, look: dict, ground: dict) -> str:
	def swap(match):
		name = match.group(1)
		if name.startswith("ground."):
			return ground.get(name.split(".", 1)[1], "")
		return look.get(name, "")

	return block_format.TOKEN.sub(swap, text)


def _photo(index: int, look: dict) -> str:
	"""A neutral frame for the photograph N: a soft gradient of the site's own colours, as a data URI (no request)."""
	a, b = (look["secondary"], look["primary"]) if index % 2 == 0 else (look["primary"], look["secondary"])
	svg = (
		"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 300' preserveAspectRatio='none'>"
		f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='{a}' stop-opacity='.55'/>"
		f"<stop offset='1' stop-color='{b}' stop-opacity='.75'/></linearGradient></defs>"
		"<rect width='400' height='300' fill='url(#g)'/>"
		"<path d='M0 235 L90 150 L150 205 L240 110 L400 250 L400 300 L0 300 Z' fill='#fff' fill-opacity='.22'/>"
		"<circle cx='300' cy='80' r='28' fill='#fff' fill-opacity='.3'/></svg>"
	)
	return "data:image/svg+xml;utf8," + svg.replace("<", "%3C").replace(">", "%3E").replace("#", "%23")


MOCK_FORM = (
	'<div style="display:grid;gap:14px">'
	'<div style="height:44px;border:1px solid var(--border-color);border-radius:var(--radius);background:rgba(255,255,255,.4)"></div>'
	'<div style="height:44px;border:1px solid var(--border-color);border-radius:var(--radius);background:rgba(255,255,255,.4)"></div>'
	'<div style="height:110px;border:1px solid var(--border-color);border-radius:var(--radius);background:rgba(255,255,255,.4)"></div>'
	'<div class="u-btn u-btn--primary" style="justify-self:start">Envoyer</div></div>'
)


# //// Neoffice — what each live component of a site looks like in the preview (2026-11-01): a block names the component it carries (Hub
# //// Block `component`), and its thumbnail and its responsive measure must show that component, not a form. Neutral boxes of the size the
# //// real component takes, laid out the way it lays itself out (auto-fit grids that wrap on a phone). The file names are the site's includes.
_BOX = "border:1px solid var(--border-color);border-radius:var(--radius);background:rgba(255,255,255,.45)"
_GRID = "display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax({min},1fr))"


def _cards(count: int, minimum: str, picture: str, lines: tuple[str, ...]) -> str:
	card = (
		f'<div style="display:grid;gap:8px"><div style="{_BOX};{picture}"></div>'
		+ "".join(f"<div>{line}</div>" for line in lines)
		+ "</div>"
	)
	return f'<div style="{_GRID.format(min=minimum)}">' + card * count + "</div>"


_DAYS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
COMPONENT_MOCKS = {
	"contact_form.html": MOCK_FORM,
	"site_form.html": MOCK_FORM,
	"opening_hours.html": '<div style="display:grid;gap:6px;max-width:28rem">'
	+ "".join(
		f'<div style="display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-color)">'
		f"<span>{day}</span><span>{'Fermé' if day == 'Dimanche' else '08:00 &ndash; 18:00'}</span></div>"
		for day in _DAYS
	)
	+ "</div>",
	"product_carousel.html": _cards(4, "160px", "aspect-ratio:1/1", ("Un produit", "<strong>CHF 49.&ndash;</strong>")),
	"brand_carousel.html": _cards(5, "120px", "height:72px", ()),
	"google_map.html": f'<div style="{_BOX};height:320px;display:grid;place-items:center">Carte</div>',
	"team_grid.html": _cards(3, "160px", "aspect-ratio:1/1;border-radius:50%", ("Prénom Nom", "Rôle")),
	"company_timeline.html": '<div style="display:grid;gap:18px">'
	+ "".join(f'<div style="display:grid;gap:4px;padding-left:16px;border-left:2px solid var(--border-color)"><strong>{y}</strong><span>Une étape de l&rsquo;entreprise.</span></div>' for y in (1998, 2008, 2020))
	+ "</div>",
	"blog_listing.html": _cards(3, "220px", "aspect-ratio:16/10", ("<strong>Le titre d&rsquo;un article</strong>", "12 octobre")),
	"contact_info.html": '<div style="display:grid;gap:8px"><div>Rue du Marché 12, 1950 Sion</div><div>027 123 45 67</div><div>bonjour@exemple.ch</div></div>',
}


def mock_of(component: str | None) -> str:
	"""What the preview draws where a block carries its live component: the component's mock, the form when it names none."""
	return COMPONENT_MOCKS.get((component or "").rsplit("/", 1)[-1], MOCK_FORM)


# the copies of a strip of words the preview draws (the site's footer script repeats the group until it fills the widest screen: here three are
# enough for the widest preview, and the track slides by one of them)
MARQUEE_COPIES = 3
YEARS = range(1900, 2101)
FIRST_NUMBER = re.compile(r"\d{1,9}")


class Page:
	def __init__(self, look: dict, grounds: dict, words: Words, component: str = ""):
		self.look, self.grounds, self.words = look, grounds, words
		self.component = component
		self.base: list[str] = []
		self.tablet: list[str] = []
		self.mobile: list[str] = []
		self.count = 0

	def node(self, node: dict, ground_name: str) -> str:
		ground_name = node.get("ground") or ground_name
		ground = self.grounds[ground_name]
		self.count += 1
		cls = f"b{self.count}"
		for source, bucket in (("style", self.base), ("t_style", self.tablet), ("m_style", self.mobile)):
			if node.get(source):
				bucket.append(f".{cls} {{ {_css(node[source], self.look, ground)} }}")
		tag = node["el"]
		named = list(node.get("classes") or [])
		# a strip that moves in the site is drawn moving here (the class the site's script adds once it has repeated the group)
		classes = " ".join([cls, *named, *(["is-moving"] if "u-marquee" in named else [])])
		attrs = [f'class="{html.escape(classes)}"']
		if "u-marquee__track" in named:
			attrs.append(f'style="--marquee-shift: {100 / MARQUEE_COPIES:.4f}%"')
		for key, value in (node.get("attrs") or {}).items():
			value = str(value)
			if key == "href":
				attrs.append('href="#"')
			elif key == "src":
				photo = re.fullmatch(r"\{\{\s*photo\.(\d)\s*\}\}", value)
				attrs.append(f'src="{_photo(int(photo.group(1)) if photo else 0, self.look)}"')
			elif key == "alt":
				slot = block_format.SLOT.match(value)
				attrs.append(
					f'alt="{html.escape(self.words.slot("alt", slot.group(2)) if slot else value, quote=True)}"'
				)
			elif SAFE_ATTR.match(key):
				attrs.append(
					f'{html.escape(key)}="{html.escape(_fill(value, self.look, ground), quote=True)}"'
				)
		if tag in VOID:
			return f"<{tag} {' '.join(attrs)}>"
		inner = ""
		if "text" in node:
			text = str(node["text"])
			slot = block_format.SLOT.match(text)
			if slot:
				inner = self.words.slot(slot.group(1), slot.group(2))
				if "u-count" in named:
					inner = FIRST_NUMBER.sub(self._counting, inner, count=1)
			elif text.strip() == "{{include_component}}":
				inner = mock_of(self.component)
			else:
				inner = html.escape(_fill(text, self.look, ground))
		elif node.get("c"):
			children = [self.node(child, ground_name) for child in node["c"]]
			# the first of the folding questions of a list is open, so that the preview shows an answer too
			first_fold = next((i for i, kid in enumerate(node["c"]) if kid.get("el") == "details"), None)
			if first_fold is not None:
				children[first_fold] = children[first_fold].replace("<details ", "<details open ", 1)
			if "u-marquee__track" in named and children:
				# the words are written once; the copies are the same group, hidden from a reader of the page
				group = children[0].replace(" class=", ' aria-hidden="true" class=', 1)
				children = [children[0], *([group] * (MARQUEE_COPIES - 1))]
			inner = "".join(children)
		return f"<{tag} {' '.join(attrs)}>{inner}</{tag}>"

	@staticmethod
	def _counting(match: re.Match) -> str:
		"""The first number of a figure that counts, as the site's script reads it: a year is a name and stays written. The number itself is drawn by
		the stylesheet (a counter over a registered custom property), so the preview needs no script."""
		if int(match.group(0)) in YEARS or match.group(0).startswith("0"):
			return match.group(0)
		return f'<span class="pv-n" style="--target: {int(match.group(0))}"></span>'


def _utilities(look: dict) -> str:
	primary, secondary, background = (
		parse_colour(look["primary"]),
		parse_colour(look["secondary"]),
		parse_colour(look["background"]),
	)

	def on(colour) -> str:
		"""White or near-black, whichever reads better on the colour (as the theme picks the label of a button)."""

		def ratio(other) -> float:
			a, b = luminance(colour), luminance(other)
			return (max(a, b) + 0.05) / (min(a, b) + 0.05)

		return "#ffffff" if ratio((255, 255, 255)) >= ratio((26, 26, 26)) else "#1a1a1a"

	# a card is a little lighter than the page it sits on: nearly white on a light site, a shade lighter on a dark one
	surface = to_hex(mix(background, (255, 255, 255), 0.55 if luminance(background) > DARK else 0.06))
	return f"""
:root {{ --primary-color: {look["primary"]}; --secondary-color: {look["secondary"]}; --surface-color: {surface}; --border-color: {look["hair"]}; --radius: 8px; --radius-lg: 13px; }}
.u-card {{ background: var(--surface-color); border: 1px solid var(--border-color); border-radius: var(--radius-lg); box-shadow: 0 1px 3px rgba(0,0,0,.05); padding: 24px; }}
.u-btn {{ display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 12px 24px; border-radius: var(--radius); border: 1px solid transparent; font-size: .95rem; font-weight: 500; line-height: 1; text-decoration: none; }}
.u-btn--primary {{ background: {look["primary"]}; color: {on(primary)}; }}
.u-btn--secondary {{ background: {look["secondary"]}; color: {on(secondary)}; }}
.u-btn--outline {{ background: transparent; color: inherit; border-color: currentColor; }}
.u-btn--ghost {{ background: transparent; color: inherit; padding-left: 0; padding-right: 0; }}
.u-media {{ border-radius: var(--radius-lg); overflow: hidden; display: block; width: 100%; }}
.u-faq > details {{ border-top: 1px solid color-mix(in srgb, currentColor 18%, transparent); }}
.u-faq > details:last-child {{ border-bottom: 1px solid color-mix(in srgb, currentColor 18%, transparent); }}
.u-faq summary {{ display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; padding: 1.25rem 0; cursor: pointer; list-style: none; }}
.u-faq summary::-webkit-details-marker {{ display: none; }}
.u-faq summary::after {{ content: "+"; flex: none; font-weight: 400; line-height: 1; }}
.u-faq details[open] > summary::after {{ content: "\\2212"; }}
.u-faq details > :not(summary) {{ margin: 0 0 1.25rem; }}
.u-grid {{ display: grid; gap: 24px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.u-grid--3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
.u-grid--4 {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
@media (max-width: 1024px) {{ .u-grid--3, .u-grid--4 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
@media (max-width: 640px) {{ .u-grid, .u-grid--3, .u-grid--4 {{ grid-template-columns: minmax(0, 1fr); }} }}
"""


def _motion(motion: str) -> str:
	"""The motion layer of a site (theme_variables.html, "The motion layer"), drawn in time: the preview does not scroll, so what a site drives by the
	scroll (the rise of u-reveal) plays once when the preview opens, and "Replay" in the window plays it again. The strip drifts, the figures count. All
	of it stays inside `prefers-reduced-motion: no-preference`, as on a site: a reader whose system asks for less motion sees the page at rest."""
	brisk = motion == "Brisk"
	rise, count, drift, step = ("0.5s", "0.9s", "24s", 0.08) if brisk else ("0.9s", "1.6s", "40s", 0.14)
	delays = "\n".join(
		f".u-reveal-group > :nth-child({n}) {{ animation-delay: {(n - 1) * step:.2f}s; }}"
		for n in range(2, 7)
	)
	return f"""
@property --pv-n {{ syntax: "<integer>"; inherits: false; initial-value: 0; }}
.u-count {{ font-variant-numeric: tabular-nums; }}
.pv-n {{ --pv-n: var(--target); counter-reset: pv var(--pv-n); }}
.pv-n::before {{ content: counter(pv); }}
.u-marquee__track {{ display: flex; flex-wrap: wrap; justify-content: center; }}
.u-marquee__group {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: .75rem 3rem; }}
@media (prefers-reduced-motion: no-preference) {{
@keyframes pv-rise {{ from {{ opacity: 0; translate: 0 1.5rem; }} }}
@keyframes pv-count {{ from {{ --pv-n: 0; }} }}
@keyframes pv-drift {{ to {{ translate: calc(var(--marquee-shift, 33.333%) * -1) 0; }} }}
.u-reveal, .u-reveal-group > * {{ animation: pv-rise {rise} ease-out backwards; }}
{delays}
.pv-n {{ animation: pv-count {count} cubic-bezier(.2, .7, .2, 1) backwards; }}
.u-marquee.is-moving {{ overflow: hidden; -webkit-mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent); mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent); }}
.u-marquee.is-moving .u-marquee__track {{ flex-wrap: nowrap; justify-content: flex-start; width: max-content; animation: pv-drift {drift} linear infinite; }}
.u-marquee.is-moving .u-marquee__group {{ flex: none; flex-wrap: nowrap; justify-content: flex-start; gap: 3rem; padding-right: 3rem; }}
}}
"""


def render_page(
	tree: dict,
	*,
	palette: str = DEFAULT_PALETTE,
	lang: str = "fr",
	length: str = "longest",
	ground: str = "plain",
	motion: str = "Calm",
	component: str = "",
) -> str:
	"""The block as a whole HTML page, for the palette (a key of PALETTES, or a dict of the six values), in the language and with the length of text
	given, with the mock of the live component it carries (`component`, a file name of the site's includes). The tree must be one that
	block_format.lint accepts."""
	colours = PALETTES[palette] if isinstance(palette, str) else palette
	look = look_of(colours)
	grounds = grounds_of(look)
	page = Page(look, grounds, Words(lang, length, look["secondary"]), component)
	body = page.node(tree, ground if ground in grounds else "plain")
	css = "\n".join(
		[
			_utilities(look),
			_motion(motion),
			*page.base,
			f"@media (max-width: {TABLET_MAX}px) {{\n" + "\n".join(page.tablet) + "\n}"
			if page.tablet
			else "",
			f"@media (max-width: {MOBILE_MAX}px) {{\n" + "\n".join(page.mobile) + "\n}"
			if page.mobile
			else "",
		]
	)
	return (
		f'<!doctype html><html lang="{page.words.lang}"><head><meta charset="utf-8">'
		'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Block preview</title><style>'
		"*, *::before, *::after { box-sizing: border-box; } html { -webkit-text-size-adjust: 100%; }"
		f"body {{ margin: 0; background: {look['background']}; color: {look['text']}; font-family: {look['font_body']}; line-height: 1.5; }}"
		"h1, h2, h3, h4, h5, h6, p, ul, ol, figure, blockquote, hr { margin: 0; } a { color: inherit; text-decoration: none; } img { max-width: 100%; }"
		f"{css}</style></head><body>{body}</body></html>"
	)


def options() -> dict:
	"""What the desk offers in its preview window."""
	return {
		"palettes": [{"value": key, "label": value["label"]} for key, value in PALETTES.items()],
		"languages": list(LANGUAGES),
		"lengths": list(LENGTHS),
		"devices": DEVICES,
		"default_palette": DEFAULT_PALETTE,
	}
