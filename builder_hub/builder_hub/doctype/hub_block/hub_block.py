# //// Neoffice — added file (no upstream equivalent): a block of the hub's library of sections.
import frappe
from frappe import _
from frappe.model.document import Document

from builder_hub import block_format


class HubBlock(Document):
	def validate(self):
		self.block_id = (self.block_id or "").strip()
		self.family = self.block_id.split(".")[0]
		self.kinds = ", ".join(self.kind_list())
		self.format = block_format.FORMAT
		errors, warnings = self.lint()
		self.lint_report = "\n".join([*(f"ERROR {e}" for e in errors), *(f"warning {w}" for w in warnings)])
		if errors and self.status == "Published":
			frappe.throw(_("A block with errors cannot be published:") + "<br>" + "<br>".join(errors))
		if not self.source:
			self.source = "edited in the hub"
		before = self.get_doc_before_save()
		if before and before.tree != self.tree:
			self.version = (before.version or 1) + 1
			if not self.flags.in_seed_sync and self.source == "seed":
				# a person changed a seed block: the files no longer overwrite it
				self.source = "edited in the hub"

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

	def on_update(self):
		from builder_hub.blocks import clear_block_cache

		clear_block_cache()

	def on_trash(self):
		from builder_hub.blocks import clear_block_cache

		clear_block_cache()
