from __future__ import annotations

import logging

import frappe
from frappe.utils import now_datetime, today

from roti_ropi_pos.mobile_pos.authorization import require_doc_permission
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import MutationResult
from roti_ropi_pos.mobile_pos.sessions import get_current_opening, opening_dto
_log = logging.getLogger(__name__)

# Maps core POS Closing Entry status to mobile API status strings.
_STATUS_MAP = {
	"Draft": "draft",
	"Submitted": "submitted",
	"Queued": "queued",
	"Failed": "failed",
	"Cancelled": "cancelled",
}

_FAILURE_RESPONSE = {
	"code": "CLOSING_FAILED",
	"message": "Closing failed. A manager must review it in ERPNext.",
}


def preview_closing(profile) -> dict:
	"""Return server-derived closing preview for the current cashier's opening."""
	opening = _require_opening(profile)
	invoices = _eligible_invoices(opening)
	total = sum(inv.grand_total for inv in invoices)
	payment_map: dict[str, dict] = {}
	for row in opening.balance_details:
		payment_map[row.mode_of_payment] = {
			"mode_of_payment": row.mode_of_payment,
			"opening_amount": str(row.opening_amount or 0),
			"expected_amount": str(row.opening_amount or 0),
		}
	for inv in invoices:
		for pmt in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parent": inv.name, "parenttype": "POS Invoice"},
			fields=["mode_of_payment", "amount"],
		):
			mop = pmt.mode_of_payment
			if mop not in payment_map:
				payment_map[mop] = {
					"mode_of_payment": mop,
					"opening_amount": "0",
					"expected_amount": "0",
				}
			current = float(payment_map[mop]["expected_amount"])
			payment_map[mop]["expected_amount"] = str(current + float(pmt.amount or 0))

	return {
		"opening_session": opening_dto(opening),
		"invoice_count": len(invoices),
		"grand_total": str(total),
		"expected_payments": list(payment_map.values()),
	}


def submit_closing(payload: dict, transaction_id: str) -> MutationResult:
	"""Create and submit one POS Closing Entry using the closing exception protocol."""
	profile_name = payload["pos_profile"]
	profile = frappe.get_doc("POS Profile", profile_name, ignore_permissions=True)
	opening = _require_opening(profile)
	invoices = _eligible_invoices(opening)
	balances = _normalize_closing_balances(profile, payload["closing_balances"], opening)

	_lock_opening(opening.name)

	closing = frappe.get_doc(
		{
			"doctype": "POS Closing Entry",
			"period_start_date": opening.period_start_date,
			"period_end_date": now_datetime(),
			"posting_date": today(),
			"user": frappe.session.user,
			"pos_profile": profile.name,
			"company": profile.company,
			"pos_opening_entry": opening.name,
			"payment_reconciliation": balances,
			"pos_invoices": [{"pos_invoice": inv.name} for inv in invoices],
			"custom_mobile_pos_transaction_id": transaction_id,
		}
	)
	# Consolidation triggered by on_submit requires elevated ERPNext perms
	# (GL entries, Sales Invoice). Run as Administrator for insert+submit only.
	cashier = frappe.session.user
	frappe.set_user("Administrator")
	try:
		closing.insert()
		closing.submit()
	finally:
		frappe.set_user(cashier)

	return MutationResult(
		data={"closing": closing_dto(closing)},
		reference_doctype="POS Closing Entry",
		reference_name=closing.name,
	)


def closing_status(name: str) -> dict:
	"""Return scoped closing DTO for one POS Closing Entry."""
	closing = frappe.get_doc("POS Closing Entry", name)
	# Scope: cashier must own the entry.
	if closing.user != frappe.session.user:
		raise MobilePOSAPIError("PERMISSION_ERROR", "Access denied.")
	return {"closing": closing_dto(closing)}


def closing_dto(doc) -> dict:
	status = _STATUS_MAP.get(doc.status, doc.status.lower() if doc.status else "draft")
	failure = _FAILURE_RESPONSE if status == "failed" else None
	return {
		"name": doc.name,
		"opening_entry": doc.pos_opening_entry,
		"pos_profile": doc.pos_profile,
		"status": status,
		"invoice_count": len(doc.pos_invoices),
		"failure": failure,
	}


def _require_opening(profile):
	opening = get_current_opening(profile)
	if not opening:
		raise MobilePOSAPIError("NO_ACTIVE_SESSION", "No open session for this profile.")
	return opening


def _eligible_invoices(opening):
	"""Return submitted, unconsolidated POS Invoices for the cashier/opening period."""
	return frappe.get_all(
		"POS Invoice",
		filters={
			"owner": opening.user,
			"pos_profile": opening.pos_profile,
			"company": opening.company,
			"docstatus": 1,
			"consolidated_invoice": ["is", "not set"],
			"posting_date": [">=", str(opening.posting_date)],
		},
		fields=["name", "grand_total"],
	)


def _normalize_closing_balances(profile, balances: list[dict], opening) -> list[dict]:
	"""Build payment_reconciliation rows with opening_amount from Opening Entry balance_details."""
	profile_modes = {p.mode_of_payment for p in profile.payments}
	opening_amounts = {row.mode_of_payment: row.opening_amount for row in opening.balance_details}
	result = []
	for row in balances:
		mop = row["mode_of_payment"]
		if mop not in profile_modes:
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				f"mode_of_payment {mop!r} not in profile.",
				details={"field": "closing_balances"},
			)
		result.append({
			"mode_of_payment": mop,
			"opening_amount": opening_amounts.get(mop, 0),
			"closing_amount": row["closing_amount"],
		})
	return result


def _lock_opening(opening_name: str) -> None:
	frappe.db.sql(
		"SELECT name FROM `tabPOS Opening Entry` WHERE name = %s FOR UPDATE",
		opening_name,
	)


def ensure_committed_closing_job(closing_name: str) -> None:
	"""Enqueue consolidation after DB commit if entry is still Queued."""
	from erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log import (
		consolidate_pos_invoices,
	)

	closing = frappe.get_doc("POS Closing Entry", closing_name)
	if closing.docstatus != 1 or closing.status != "Queued":
		return
	consolidate_pos_invoices(closing_entry=closing)
