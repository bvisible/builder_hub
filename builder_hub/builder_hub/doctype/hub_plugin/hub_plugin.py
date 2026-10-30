from __future__ import annotations

from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document

from builder_hub.plugins.protocol import PLUGIN_NAME_PATTERN
from builder_hub.plugins.publishing import is_maintainer


class HubPlugin(Document):
	def validate(self):
		if not PLUGIN_NAME_PATTERN.fullmatch(self.plugin_name or ""):
			frappe.throw(_("Plugin name must use the lowercase publisher/name format."))
		if self.publisher and self.plugin_name.split("/", 1)[0] != self.publisher:
			frappe.throw(_("Plugin name must start with its publisher ID."))
		url = urlparse(self.repository_url or "")
		if url.scheme != "https" or url.hostname != "github.com" or len(url.path.strip("/").split("/")) != 2:
			frappe.throw(_("Repository URL must identify one public GitHub repository."))
		if self.replacement == self.name:
			frappe.throw(_("A plugin cannot replace itself."))
		if not self.is_new():
			before = self.get_doc_before_save()
			if before and before.plugin_name != self.plugin_name:
				frappe.throw(_("Plugin names are permanent."))
			protected = (
				"publisher",
				"repository_url",
				"github_repository_id",
				"license",
				"icon",
				"replacement",
				"status",
			)
			if (
				before
				and any(before.get(fieldname) != self.get(fieldname) for fieldname in protected)
				and not is_maintainer()
			):
				frappe.throw(_("A Builder Hub maintainer must review protected listing changes."))

	def on_trash(self):
		frappe.throw(_("Plugin records are permanent. Set the listing to Removed instead."))
