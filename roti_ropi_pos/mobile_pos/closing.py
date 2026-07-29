from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

import frappe
from frappe.utils import now_datetime, today

from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile, require_doc_permission
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import (
	_create_processing_request,
	_get_existing_request,
	_raise_if_hash_conflict,
	_request_in_progress,
	_scope_key,
	canonical_hash,
	complete_request,
	reject_request,
	replay_response,
	require_idempotency_key,
)
from roti_ropi_pos.mobile_pos.responses import success
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
_OPERATION = "v1.closing.submit"
_LEASE_SECONDS = 30
_KNOWN_SUBMIT_ERRORS = (
	frappe.ValidationError,
	frappe.PermissionError,
	frappe.TimestampMismatchError,
	frappe.MandatoryError,
	frappe.LinkValidationError,
)


def preview_closing(profile) -> dict:
	"""Return server-derived closing preview for the current cashier's opening."""
	opening = _require_opening(profile)
	invoices = _eligible_invoices(opening)
	total = sum((Decimal(str(inv.grand_total or 0)) for inv in invoices), Decimal())
	payment_map: dict[str, dict] = {}
	for row in opening.balance_details:
		opening_amount = Decimal(str(row.opening_amount or 0))
		payment_map[row.mode_of_payment] = {
			"mode_of_payment": row.mode_of_payment,
			"opening_amount": format(opening_amount, "f"),
			"expected_amount": opening_amount,
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
					"expected_amount": Decimal(),
				}
			payment_map[mop]["expected_amount"] += Decimal(str(pmt.amount or 0))

	for payment in payment_map.values():
		payment["expected_amount"] = format(payment["expected_amount"], "f")
	return {
		"opening_session": opening_dto(opening),
		"invoice_count": len(invoices),
		"grand_total": format(total, "f"),
		"expected_payments": list(payment_map.values()),
	}


def execute_closing_submit(profile, payload: dict) -> dict:
	key = require_idempotency_key()
	request_hash = canonical_hash(_OPERATION, payload)
	scope_key = _scope_key(key, _OPERATION)
	request = _get_existing_request(scope_key)
	if request:
		_raise_if_hash_conflict(request, request_hash, _OPERATION)
		if request.status in {"Completed", "Rejected"}:
			return replay_response(request)
		if request.lease_expires_at and request.lease_expires_at > now_datetime():
			raise _request_in_progress(_OPERATION)
		request = _claim_expired_request(scope_key, request_hash)
	else:
		savepoint = f"closing_reserve_{frappe.generate_hash(length=10)}"
		frappe.db.savepoint(savepoint)
		try:
			request = _create_processing_request(scope_key, key, _OPERATION, request_hash)
		except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
			frappe.db.rollback(save_point=savepoint)
			request = _get_existing_request(scope_key, for_update=True)
			_raise_if_hash_conflict(request, request_hash, _OPERATION)
			if request.status in {"Completed", "Rejected"}:
				return replay_response(request)
			raise _request_in_progress(_OPERATION)
		request.phase = "Reserved"
		request.lease_expires_at = _new_lease()
		request.save(ignore_permissions=True)
		frappe.db.commit()

	if not request.reference_name:
		closing = _create_closing_draft(profile, payload, key)
		request = _get_existing_request(scope_key, for_update=True)
		request.reference_doctype = "POS Closing Entry"
		request.reference_name = closing.name
		request.phase = "DraftCreated"
		frappe.db.set_value(
			"POS Opening Entry",
			closing.pos_opening_entry,
			"pos_closing_entry",
			closing.name,
			update_modified=False,
		)
		request.flags.ignore_links = True
		request.save(ignore_permissions=True)
		frappe.db.commit()
	else:
		closing = frappe.get_doc("POS Closing Entry", request.reference_name)

	if closing.docstatus == 0:
		request = _get_existing_request(scope_key, for_update=True)
		request.phase = "SubmitStarted"
		request.lease_expires_at = _new_lease()
		request.save(ignore_permissions=True)
		frappe.db.commit()
		try:
			_submit_persisted_closing(closing.name)
		except _KNOWN_SUBMIT_ERRORS as error:
			return _recover_submit_error(scope_key, error)

	return _complete_from_persisted(scope_key)


def _claim_expired_request(scope_key: str, request_hash: str):
	request = _get_existing_request(scope_key, for_update=True)
	_raise_if_hash_conflict(request, request_hash, _OPERATION)
	if request.status in {"Completed", "Rejected"}:
		return request
	if request.lease_expires_at and request.lease_expires_at > now_datetime():
		raise _request_in_progress(_OPERATION)
	request.lease_expires_at = _new_lease()
	request.save(ignore_permissions=True)
	frappe.db.commit()
	return request


def _create_closing_draft(profile, payload: dict, transaction_id: str):
	opening = _require_opening(profile)
	_lock_opening(opening.name)
	opening = frappe.get_doc("POS Opening Entry", opening.name)
	if opening.status != "Open" or opening.docstatus != 1 or opening.pos_closing_entry:
		raise MobilePOSAPIError("NO_ACTIVE_SESSION", "No open session for this profile.")
	invoices = _eligible_invoices(opening)
	balances = _normalize_closing_balances(profile, payload["closing_balances"], opening)
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
	closing.insert()
	return closing


def _submit_persisted_closing(closing_name: str) -> None:
	cashier = frappe.session.user
	frappe.set_user("Administrator")
	try:
		frappe.get_doc("POS Closing Entry", closing_name).submit()
	finally:
		frappe.set_user(cashier)


def _complete_from_persisted(scope_key: str) -> dict:
	request = _get_existing_request(scope_key, for_update=True)
	closing = frappe.get_doc("POS Closing Entry", request.reference_name)
	if closing.docstatus == 1 and closing.status in {None, "Draft"}:
		closing.status = "Submitted"
	if closing.docstatus != 1 or closing.status not in {"Queued", "Submitted", "Failed"}:
		raise MobilePOSAPIError(
			"REQUEST_IN_PROGRESS",
			"Closing is still being processed.",
			status=409,
			retryable=True,
		)
	if closing.custom_mobile_pos_transaction_id != request.idempotency_key:
		raise MobilePOSAPIError("IDEMPOTENCY_INVARIANT", "Closing reference mismatch.", status=500)
	response = success({"closing": closing_dto(closing)}, http_status=201)
	complete_request(
		request,
		response,
		reference_doctype="POS Closing Entry",
		reference_name=closing.name,
		http_status=201,
		audit_reference_written=True,
	)
	frappe.db.commit()
	if closing.status == "Queued":
		ensure_committed_closing_job(closing.name)
	return response


def _recover_submit_error(scope_key: str, error: Exception) -> dict:
	frappe.db.rollback()
	request = _get_existing_request(scope_key, for_update=True)
	closing = frappe.get_doc("POS Closing Entry", request.reference_name, for_update=True)
	if closing.docstatus == 1 and closing.status in {"Queued", "Submitted", "Failed"}:
		return _complete_from_persisted(scope_key)
	mapped = MobilePOSAPIError(
		"INVALID_REQUEST",
		"Closing could not be submitted.",
		status=422,
		details={"reason": error.__class__.__name__},
	)
	response = reject_request(request, mapped, reference_name=closing.name)
	if (
		frappe.db.get_value("POS Opening Entry", closing.pos_opening_entry, "pos_closing_entry")
		== closing.name
	):
		frappe.db.set_value(
			"POS Opening Entry",
			closing.pos_opening_entry,
			"pos_closing_entry",
			None,
			update_modified=False,
		)
	frappe.db.commit()
	return response


def _new_lease():
	return now_datetime() + timedelta(seconds=_LEASE_SECONDS)


def closing_status(name: str) -> dict:
	"""Return scoped closing DTO for one POS Closing Entry."""
	closing = frappe.get_doc("POS Closing Entry", name)
	profile = get_authorized_profile(closing.pos_profile)
	require_doc_permission("POS Closing Entry", "read", doc=closing)
	if closing.user != frappe.session.user or closing.company != profile.company:
		raise MobilePOSAPIError(
			"PERMISSION_DENIED",
			"The operation is not permitted.",
			status=403,
		)
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
		result.append(
			{
				"mode_of_payment": mop,
				"opening_amount": opening_amounts.get(mop, 0),
				"closing_amount": row["closing_amount"],
			}
		)
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
	cashier = frappe.session.user
	frappe.set_user("Administrator")
	try:
		consolidate_pos_invoices(closing_entry=closing)
	finally:
		frappe.set_user(cashier)
