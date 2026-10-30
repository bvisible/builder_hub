from __future__ import annotations

import re
from urllib.parse import urlparse

import frappe
from frappe import _
from frappe.model.document import Document

from builder_hub.plugins.publishing import is_maintainer

PUBLISHER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class HubPublisher(Document):
	def validate(self):
		if not PUBLISHER_ID_PATTERN.fullmatch(self.publisher_id or ""):
			frappe.throw(_("Publisher ID must contain lowercase letters, numbers, and hyphens only."))
		if self.website:
			url = urlparse(self.website)
			if url.scheme != "https" or not url.netloc or url.username or url.password:
				frappe.throw(_("Publisher website must be a public HTTPS URL."))
		self.validate_protected_changes()

	def validate_protected_changes(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if before.publisher_id != self.publisher_id:
			frappe.throw(_("Publisher IDs are permanent."))
		protected = ("github_owner", "github_account_id", "verified", "status")
		if (
			any(before.get(fieldname) != self.get(fieldname) for fieldname in protected)
			and not is_maintainer()
		):
			frappe.throw(_("A Builder Hub maintainer must review publisher ownership changes."))

	def on_trash(self):
		frappe.throw(_("Publisher records are permanent and cannot be deleted."))
