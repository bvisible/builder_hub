# //// Neoffice — added file (no upstream equivalent): the design tokens of a published bundle land in the doctype the site has.
"""A publish failed on a current builder at its first design token: the hub wrote `Builder Variable`, which the builder renamed
`Builder Token` (and `variable_name` became `token_name`). Pinned here: the doctype is the one the site has, a bundle may carry either wire
name, an existing token is updated and a new one is inserted under the name it came with. The database is replaced."""

import unittest
from unittest.mock import MagicMock, patch

from builder_hub import publish


def run(has_token_doctype, existing, variables):
	db = MagicMock()
	db.exists.side_effect = lambda doctype, name=None: has_token_doctype if (doctype, name) == ("DocType", "Builder Token") else (doctype, name) in existing
	inserted = []
	doc = MagicMock()
	doc.insert.side_effect = lambda **kw: inserted.append(kw)
	with patch.object(publish.frappe, "db", db), patch.object(publish.frappe, "get_doc", return_value=doc) as get_doc:
		publish._upsert_variables(variables, [])
	return db, get_doc, inserted


class TestTheTokensOfABundle(unittest.TestCase):
	def test_a_current_site_writes_builder_token_with_its_new_name_field(self):
		_, get_doc, inserted = run(True, set(), [{"name": "u-1", "variable_name": "Primary", "type": "Color", "value": "#112233", "group": "g"}])
		self.assertEqual("Builder Token", get_doc.call_args.args[0]["doctype"])
		self.assertEqual("Primary", get_doc.call_args.args[0]["token_name"])
		self.assertNotIn("variable_name", get_doc.call_args.args[0])
		self.assertEqual([{"ignore_permissions": True, "set_name": "u-1"}], inserted)

	def test_an_older_site_keeps_the_old_doctype(self):
		_, get_doc, _ = run(False, set(), [{"name": "u-1", "variable_name": "Primary", "value": "#112233"}])
		self.assertEqual("Builder Variable", get_doc.call_args.args[0]["doctype"])
		self.assertEqual("Primary", get_doc.call_args.args[0]["variable_name"])

	def test_a_bundle_may_carry_the_new_name(self):
		_, get_doc, _ = run(True, set(), [{"name": "u-1", "token_name": "Primary", "value": "#112233"}])
		self.assertEqual("Primary", get_doc.call_args.args[0]["token_name"])

	def test_an_existing_token_is_updated_not_inserted(self):
		db, get_doc, inserted = run(True, {("Builder Token", "u-1")}, [{"name": "u-1", "variable_name": "Primary", "value": "#445566"}])
		db.set_value.assert_called_once()
		self.assertEqual(("Builder Token", "u-1"), db.set_value.call_args.args[:2])
		self.assertEqual("#445566", db.set_value.call_args.args[2]["value"])
		get_doc.assert_not_called()
		self.assertEqual([], inserted)

	def test_the_type_defaults_to_a_colour_and_a_row_without_a_name_is_skipped(self):
		_, get_doc, _ = run(True, set(), [{"variable_name": "Nameless"}, {"name": "u-2", "variable_name": "Accent", "value": "#fff"}])
		self.assertEqual(1, get_doc.call_count)
		self.assertEqual("Color", get_doc.call_args.args[0]["type"])


if __name__ == "__main__":
	unittest.main()
