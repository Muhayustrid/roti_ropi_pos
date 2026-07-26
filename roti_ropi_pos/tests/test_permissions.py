import json
from collections import Counter
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import cint, cstr
from frappe.utils.fixtures import sync_fixtures

from roti_ropi_pos.tests.helpers import make_cashier

APPROVED_DOCTYPES = (
	"POS Profile",
	"POS Opening Entry",
	"POS Invoice",
	"POS Closing Entry",
	"Customer",
	"Item",
)
CASHIER_ROLE = "Mobile POS Cashier"
STANDARD_ROW_COUNT = 30
TOTAL_ROW_COUNT = STANDARD_ROW_COUNT + len(APPROVED_DOCTYPES)

PERMISSION_FIELDS = (
	"read",
	"write",
	"create",
	"submit",
	"cancel",
	"delete",
	"amend",
	"mask",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"select",
	"impersonate",
	"apply_user_permissions",
)
EXPECTED_CHECK_FIELDS = {
	"if_owner",
	"read",
	"write",
	"create",
	"submit",
	"cancel",
	"delete",
	"amend",
	"mask",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"select",
	"impersonate",
}
CASHIER_NAMES = {
	"POS Profile": "mobile-pos-cdp-pos-profile",
	"POS Opening Entry": "mobile-pos-cdp-pos-opening-entry",
	"POS Invoice": "mobile-pos-cdp-pos-invoice",
	"POS Closing Entry": "mobile-pos-cdp-pos-closing-entry",
	"Customer": "mobile-pos-cdp-customer",
	"Item": "mobile-pos-cdp-item",
}
WRITE_DOCTYPES = {
	"POS Opening Entry",
	"POS Invoice",
	"POS Closing Entry",
}
STANDARD_DRIFT_MESSAGE = (
	"ERPNext standard permission matrix drifted; review the upstream change and intentionally "
	"regenerate the snapshot."
)


def _canonical(row):
	return (
		cstr(row.get("parent")),
		cstr(row.get("role")),
		cint(row.get("permlevel")),
		cint(row.get("if_owner")),
		*(cint(row.get(field)) for field in PERMISSION_FIELDS),
	)


def _standard_fixture_name(row):
	parent = frappe.scrub(row.get("parent")).replace("_", "-")
	role = frappe.scrub(row.get("role")).replace("_", "-")
	return f"mobile-pos-cdp-standard-{parent}-{role}-p{cint(row.get('permlevel'))}-o{cint(row.get('if_owner'))}"


def _fixture_rows():
	path = Path(frappe.get_app_path("roti_ropi_pos", "fixtures", "custom_docperm.json"))
	return json.loads(path.read_text(encoding="utf-8"))


def _database_snapshot():
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": ["in", APPROVED_DOCTYPES]},
		fields=["*"],
		order_by="name asc",
	)
	return tuple(sorted((row.name, _canonical(row)) for row in rows))


class TestCustomDocPermFixture(IntegrationTestCase):
	maxDiff = None

	def test_fixture_preserves_standard_permission_matrix(self):
		fixture_rows = _fixture_rows()
		self.assertEqual({row["parent"] for row in fixture_rows}, set(APPROVED_DOCTYPES))

		for doctype in ("DocPerm", "Custom DocPerm"):
			meta = frappe.get_meta(doctype)
			check_fields = {field.fieldname for field in meta.fields if field.fieldtype == "Check"}
			self.assertEqual(
				check_fields,
				EXPECTED_CHECK_FIELDS,
				f"{doctype} permission-field schema drifted; review the snapshot before regeneration.",
			)
			self.assertIsNone(meta.get_field("apply_user_permissions"))

		standard_rows = frappe.get_all(
			"DocPerm",
			filters={"parent": ["in", APPROVED_DOCTYPES]},
			fields=["*"],
		)
		fixture_standard_rows = [row for row in fixture_rows if row.get("role") != CASHIER_ROLE]
		self.assertEqual(len(standard_rows), STANDARD_ROW_COUNT, STANDARD_DRIFT_MESSAGE)
		self.assertEqual(
			Counter(_canonical(row) for row in fixture_standard_rows),
			Counter(_canonical(row) for row in standard_rows),
			STANDARD_DRIFT_MESSAGE,
		)
		self.assertTrue(all(row["name"] == _standard_fixture_name(row) for row in fixture_standard_rows))
		names = [row["name"] for row in fixture_rows]
		self.assertEqual(len(names), len(set(names)), "Fixture contains duplicate document names.")
		self.assertTrue(all(len(name) <= 140 for name in names))

	def test_mobile_cashier_matrix_is_exact(self):
		fixture_rows = _fixture_rows()
		cashier_rows = [row for row in fixture_rows if row.get("role") == CASHIER_ROLE]
		self.assertEqual(len(cashier_rows), len(APPROVED_DOCTYPES))
		self.assertEqual(
			{row["parent"]: row["name"] for row in cashier_rows},
			CASHIER_NAMES,
		)

		expected = []
		for doctype in APPROVED_DOCTYPES:
			row = {"parent": doctype, "role": CASHIER_ROLE, "read": 1}
			if doctype in WRITE_DOCTYPES:
				row.update({"write": 1, "create": 1, "submit": 1})
			expected.append(_canonical(row))

		self.assertEqual(Counter(_canonical(row) for row in cashier_rows), Counter(expected))
		identities = [canonical[:4] for canonical in map(_canonical, fixture_rows)]
		self.assertEqual(len(identities), len(set(identities)), "Fixture contains duplicate permission identities.")

	def test_cashier_effective_permissions_are_exact(self):
		cashier = make_cashier(f"permissions-{frappe.generate_hash(length=10)}@example.com")
		self.assertEqual(frappe.db.get_value("User", cashier, "user_type"), "Website User")

		roles = set(frappe.get_roles(cashier))
		self.assertIn(CASHIER_ROLE, roles)
		self.assertIn("All", roles)
		self.assertNotIn("Desk User", roles)
		self.assertEqual(frappe.db.get_value("Role", CASHIER_ROLE, "desk_access"), 0)

		for doctype in APPROVED_DOCTYPES:
			permissions = frappe.permissions.get_role_permissions(doctype, user=cashier)
			expected = {field: 0 for field in PERMISSION_FIELDS}
			expected["read"] = 1
			if doctype in WRITE_DOCTYPES:
				expected.update({"write": 1, "create": 1, "submit": 1})
			self.assertEqual(
				{field: cint(permissions.get(field)) for field in PERMISSION_FIELDS},
				expected,
				doctype,
			)

	def test_fixture_import_is_idempotent(self):
		sync_fixtures("roti_ropi_pos")
		frappe.clear_cache()
		first = _database_snapshot()

		sync_fixtures("roti_ropi_pos")
		frappe.clear_cache()
		second = _database_snapshot()

		fixture = tuple(sorted((row["name"], _canonical(row)) for row in _fixture_rows()))
		self.assertEqual(first, fixture)
		self.assertEqual(second, first)
		self.assertEqual(len(second), TOTAL_ROW_COUNT)
		identities = [canonical[:4] for _, canonical in second]
		self.assertEqual(len(identities), len(set(identities)), "Repeated fixture import created duplicates.")
