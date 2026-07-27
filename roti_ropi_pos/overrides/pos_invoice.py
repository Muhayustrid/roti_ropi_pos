import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import POSInvoice
from frappe import _


class MobilePOSInvoice(POSInvoice):
	def validate_pos_opening_entry(self):
		if not self.custom_mobile_pos_transaction_id:
			return super().validate_pos_opening_entry()
		opening_entries = frappe.get_all(
			"POS Opening Entry",
			fields=["name"],
			filters={
				"user": frappe.session.user,
				"pos_profile": self.pos_profile,
				"company": self.company,
				"docstatus": 1,
				"status": "Open",
				"pos_closing_entry": ["is", "not set"],
			},
		)
		if not opening_entries:
			frappe.throw(
				title=_("POS Opening Entry Missing"),
				msg=_("No open POS Opening Entry found for POS Profile {0}.").format(
					frappe.bold(self.pos_profile)
				),
			)
		if len(opening_entries) > 1:
			frappe.throw(
				title=_("Multiple POS Opening Entry"),
				msg=_(
					"POS Profile - {0} has multiple open POS Opening Entries. Please close or cancel the existing entries before proceeding."
				).format(self.pos_profile),
			)
