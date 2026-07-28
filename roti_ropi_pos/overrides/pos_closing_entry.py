from __future__ import annotations

import frappe
from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

from roti_ropi_pos.mobile_pos.closing import ensure_committed_closing_job


class MobilePOSClosingEntry(POSClosingEntry):
	"""Override POS Closing Entry to defer consolidation until after DB commit.

	ERPNext's default on_submit calls consolidate_pos_invoices synchronously for
	any invoice count, which commits inside the submit transaction. For >= 10
	invoices we instead set status Queued, link invoices to the closing entry,
	and schedule consolidation via after_commit so the closing row is durable
	before the worker picks it up.
	"""

	def on_submit(self):
		if len(self.pos_invoices) < 10:
			return super().on_submit()
		self.set_status(update=True, status="Queued")
		self.update_sales_invoices_closing_entry()
		closing_name = self.name
		frappe.db.after_commit.add(lambda: ensure_committed_closing_job(closing_name))
		frappe.publish_realtime(
			f"poe_{self.pos_opening_entry}",
			message={"operation": "Closed", "doc": self},
			docname=f"POS Opening Entry/{self.pos_opening_entry}",
		)
