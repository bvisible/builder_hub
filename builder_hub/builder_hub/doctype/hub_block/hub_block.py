# //// Neoffice — added file (no upstream equivalent): a block of the hub's library of sections.
import frappe
from frappe import _
from frappe.model.document import Document

from builder_hub import block_compile, block_format, block_preview


class HubBlock(Document):
	def validate(self):
		self.block_id = (self.block_id or "").strip()
		self.family = self.block_id.split(".")[0]
		self.kinds = ", ".join(self.kind_list())
		self.format = block_format.FORMAT
		errors, warnings = self.lint()
		lint_lines = [*(f"ERROR {e}" for e in errors), *(f"warning {w}" for w in warnings)]
		# what compiling the page of the editor said comes first: it names the blocks of the page, the lint names those of the tree
		self.lint_report = "\n".join([*(self.flags.get("compile_report") or []), *lint_lines])
		if errors and self.status in ("Editor", "Published"):
			frappe.throw(_("A block with errors cannot be offered:") + "<br>" + "<br>".join(errors))
		self.check_fit()
		if not self.source:
			self.source = "edited in the hub"
		before = self.get_doc_before_save()
		if before and before.tree != self.tree:
			self.version = (before.version or 1) + 1
			if not self.flags.in_seed_sync and self.source == "seed":
				# a person changed a seed block: the files no longer overwrite it
				self.source = "edited in the hub"

	def check_fit(self):
		"""A block is offered only if it holds on a phone, a tablet and a desktop (block_fit.py): measured now when its tree has no measure yet,
		refused when its measure says it fails. A block that could not be measured is not refused here; it is not served until it is."""
		if self.status not in ("Editor", "Published"):
			return
		if self.flags.in_seed_sync or _installing():
			return
		from builder_hub import block_fit

		row = {"tree": self.tree, "ground": self.ground, "fit_hash": self.fit_hash, "fit_report": self.fit_report}
		if not block_fit.measured(row):
			try:
				self.fit_hash, self.fit_report = block_fit.measure_row(row)
			except Exception as e:
				frappe.log_error("Block not measured", f"{type(e).__name__}: {e}"[:500])
				return
		if self.fit_hash == block_fit.fit_hash(row) and (self.fit_report or "").strip():
			frappe.throw(
				_("This block does not hold on every screen, so it cannot be offered:")
				+ "<br>"
				+ "<br>".join(frappe.utils.escape_html(line) for line in self.fit_report.splitlines())
			)

	def kind_list(self) -> list[str]:
		return list(dict.fromkeys(k.strip() for k in (self.kinds or "").split(",") if k.strip()))

	def parsed_tree(self) -> dict:
		return block_format.parse_tree(self.tree)

	def lint(self) -> tuple[list[str], list[str]]:
		try:
			tree = self.parsed_tree()
		except ValueError as e:
			return [str(e)], []
		return block_format.lint(
			tree,
			block_id=self.block_id,
			kinds=self.kind_list(),
			photos=int(self.photos or 0),
			form=bool(self.form),
			motion=self.motion or "None",
		)

	@frappe.whitelist()
	def draw_page(self) -> str:
		"""The page of the Builder editor where this block is drawn: made from the tree (or a starting section) when there is none. Returns its name."""
		self.check_permission("write")
		if self.source_page and frappe.db.exists("Builder Page", self.source_page):
			return self.source_page
		from builder.ai.page_writer import expand_page_yaml

		from builder_hub.blocks import ensure_block_tokens, ensure_page_folder

		ensure_block_tokens()
		try:
			tree = self.parsed_tree() if (self.tree or "").strip() else None
		except ValueError:
			tree = None
		blocks, _script = expand_page_yaml(block_compile.to_page_yaml(tree))
		if not blocks:
			frappe.throw(_("The block could not be turned into a page of the editor"))
		blocks_json = frappe.as_json(blocks, indent=0)
		page = frappe.get_doc(
			{
				"doctype": "Builder Page",
				"page_title": f"Block {self.block_id}",
				"project_folder": ensure_page_folder(),
				"published": 0,
				"blocks": blocks_json,
				"draft_blocks": blocks_json,
			}
		)
		page.insert(ignore_permissions=True)
		self.db_set("source_page", page.name)
		return page.name

	@frappe.whitelist()
	def preview_html(
		self, palette: str = block_preview.DEFAULT_PALETTE, lang: str = "fr", length: str = "longest"
	) -> str:
		"""The block as a page, with the look of a palette and sample words (block_preview.py). It draws the tree as it is on the form, saved or
		not, and only a tree that passes the lint."""
		self.check_permission("read")
		errors, _warnings = self.lint()
		if errors:
			frappe.throw(
				_("The block has errors, there is nothing to preview:") + "<br>" + "<br>".join(errors)
			)
		if palette not in block_preview.PALETTES:
			palette = block_preview.DEFAULT_PALETTE
		return block_preview.render_page(
			self.parsed_tree(),
			palette=palette,
			lang=lang,
			length=length,
			ground=self.ground or "plain",
			motion=self.motion if self.motion in ("Calm", "Brisk") else "Calm",
		)

	@frappe.whitelist()
	def compile_from_page(self) -> dict:
		"""Rewrites the tree (and the photographs and the form) from the page of the editor, and lints it. Returns what it said."""
		self.check_permission("write")
		if not self.source_page or not frappe.db.exists("Builder Page", self.source_page):
			frappe.throw(_("Draw the block in the editor first (Editor > Draw in the editor)"))
		page = frappe.get_doc("Builder Page", self.source_page)
		result = block_compile.compile_blocks(frappe.parse_json(page.draft_blocks or page.blocks or "[]"))
		if result.tree is None:
			frappe.throw("<br>".join(result.errors))
		import yaml

		self.tree = yaml.safe_dump(
			result.tree, sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False
		)
		self.photos = result.photos
		self.form = 1 if result.form else 0
		self.flags.compile_report = [
			*(f"ERROR {e}" for e in result.errors),
			*(f"warning {w}" for w in result.warnings),
		]
		self.save()
		return {"report": self.lint_report or "", "version": self.version, "status": self.status}

	def on_update(self):
		from builder_hub.blocks import clear_block_cache

		clear_block_cache()

	def on_trash(self):
		from builder_hub.blocks import clear_block_cache

		clear_block_cache()


def _installing() -> bool:
	"""Whether an install, a migrate or an import is saving the block: no browser is started from one."""
	try:
		return bool(frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_import)
	except RuntimeError:  # no site bound (a test that builds the form by hand)
		return False
