import frappe


def ensure_custom_field():
	if frappe.db.exists(
		"Custom Field",
		{"dt": "POS Payment Method", "fieldname": "custom_mobile_pos_suggested_opening_amount"},
	):
		return
	frappe.get_doc(
		{
			"doctype": "Custom Field",
			"dt": "POS Payment Method",
			"fieldname": "custom_mobile_pos_suggested_opening_amount",
			"fieldtype": "Data",
			"label": "Suggested Mobile POS Opening Amount",
			"description": "Canonical non-negative decimal string used as the mobile POS opening default.",
			"insert_after": "mode_of_payment",
			"module": "Roti Ropi Pos",
		}
	).insert(ignore_permissions=True)


def execute():
	if not frappe.db.has_column("POS Payment Method", "custom_mobile_pos_suggested_opening_amount"):
		return
	row = frappe.db.get_value(
		"POS Payment Method",
		{"parent": "POS Training", "mode_of_payment": "Cash"},
		"name",
	)
	if row:
		frappe.db.set_value(
			"POS Payment Method",
			row,
			"custom_mobile_pos_suggested_opening_amount",
			"200000.00",
			update_modified=False,
		)
