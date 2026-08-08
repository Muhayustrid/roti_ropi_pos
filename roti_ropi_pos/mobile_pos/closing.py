from __future__ import annotations

import hashlib
import json
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
	normalize_for_hash,
	reject_request,
	replay_response,
	require_idempotency_key,
)
from roti_ropi_pos.mobile_pos.responses import success
from roti_ropi_pos.mobile_pos.sessions import get_current_opening, opening_dto
from roti_ropi_pos.mobile_pos.validation import (
	closing_counted_amount_policy,
	closing_counted_amount_string,
)

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
_PREVIEW_VERSION = "closing-preview/v1"
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
	snapshot = _closing_snapshot(profile, opening)
	return {
		"opening_session": opening_dto(opening),
		"preview_id": _preview_id(snapshot),
		"preview_version": _PREVIEW_VERSION,
		"preview_binding": {
			"opening_entry": opening.name,
			"pos_profile": profile.name,
			"cashier": frappe.session.user,
			"invoice_count": snapshot["invoice_count"],
			"payment_modes": [row["mode_of_payment"] for row in snapshot["expected_payments"]],
		},
		"invoice_count": snapshot["invoice_count"],
		"grand_total": snapshot["grand_total"],
		"net_total": snapshot["net_total"],
		"total_quantity": snapshot["total_quantity"],
		"total_taxes_and_charges": snapshot["total_taxes_and_charges"],
		"expected_payments": snapshot["expected_payments"],
		"counted_amount_policy": snapshot["counted_amount_policy"],
	}


def execute_closing_submit(profile, payload: dict) -> dict:
	key = require_idempotency_key()
	request_hash = canonical_hash(_OPERATION, payload)
	scope_key = _scope_key(key, _OPERATION)
	request = _get_existing_request(scope_key)
	prevalidated = False
	if request:
		_raise_if_hash_conflict(request, request_hash, _OPERATION)
		if request.status in {"Completed", "Rejected"}:
			return replay_response(request)
		if request.lease_expires_at and request.lease_expires_at > now_datetime():
			raise _request_in_progress(_OPERATION)
		request = _claim_expired_request(scope_key, request_hash)
	else:
		_validate_submission(profile, payload)
		prevalidated = True
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
		try:
			if not prevalidated:
				_validate_submission(profile, payload)
			closing = _create_closing_draft(profile, payload, key)
		except MobilePOSAPIError as error:
			frappe.db.rollback()
			request = _get_existing_request(scope_key, for_update=True)
			response = reject_request(request, error)
			frappe.db.commit()
			return response
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
	opening = _require_opening(profile, for_submit=True, for_update=True)
	_lock_opening(opening.name)
	opening = frappe.get_doc("POS Opening Entry", opening.name, for_update=True)
	if opening.status != "Open" or opening.docstatus != 1 or opening.pos_closing_entry:
		_raise_closing_unavailable(profile, opening)
	validated = _validate_submission(profile, payload, opening=opening)
	snapshot = validated["snapshot"]
	balances = validated["balances"]
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
			"pos_invoices": [
				{
					"pos_invoice": inv["name"],
					"posting_date": inv["posting_date"],
					"grand_total": inv["grand_total"],
					"customer": inv["customer"],
					"is_return": inv["is_return"],
					"return_against": inv["return_against"],
				}
				for inv in snapshot["invoices"]
			],
			"taxes": snapshot["taxes"],
			"grand_total": snapshot["grand_total"],
			"net_total": snapshot["net_total"],
			"total_quantity": snapshot["total_quantity"],
			"total_taxes_and_charges": snapshot["total_taxes_and_charges"],
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
			details={"endpoint": _OPERATION, "retry_after_seconds": 1},
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
	payments = [
		{
			"mode_of_payment": row.mode_of_payment,
			"opening_amount": _decimal(row.opening_amount),
			"expected_amount": _decimal(row.expected_amount),
			"counted_amount": _decimal(row.closing_amount),
			"difference": _decimal(row.difference),
		}
		for row in doc.payment_reconciliation
	]
	expected_total = sum((Decimal(row["expected_amount"]) for row in payments), Decimal())
	counted_total = sum((Decimal(row["counted_amount"]) for row in payments), Decimal())
	return {
		"name": doc.name,
		"opening_entry": doc.pos_opening_entry,
		"pos_profile": doc.pos_profile,
		"status": status,
		"invoice_count": len(doc.pos_invoices),
		"grand_total": _decimal(doc.grand_total),
		"net_total": _decimal(doc.net_total),
		"total_quantity": _decimal(doc.total_quantity),
		"total_taxes_and_charges": _decimal(doc.total_taxes_and_charges),
		"payments": payments,
		"reconciliation": {
			"expected_total": format(expected_total, "f"),
			"counted_total": format(counted_total, "f"),
			"difference_total": format(counted_total - expected_total, "f"),
		},
		"failure": failure,
	}


def _require_opening(profile, *, for_submit: bool = False, for_update: bool = False):
	opening = get_current_opening(profile, for_update=for_update)
	if not opening:
		if for_submit:
			closing = frappe.db.get_value(
				"POS Closing Entry",
				{
					"user": frappe.session.user,
					"pos_profile": profile.name,
					"company": profile.company,
					"docstatus": 1,
				},
				["name", "pos_opening_entry", "status"],
				as_dict=True,
				order_by="creation desc",
			)
			if closing and closing.status == "Submitted":
				raise MobilePOSAPIError(
					"CLOSING_ALREADY_CLOSED",
					"The POS Opening has already been closed.",
					status=409,
					details={
						"pos_profile": profile.name,
						"opening_entry": closing.pos_opening_entry,
						"closing_entry": closing.name,
						"closing_status": "submitted",
						"status_endpoint": "v1.closing.status",
					},
				)
		raise MobilePOSAPIError(
			"NO_OPEN_SESSION",
			"No open POS session is available for this profile.",
			status=422,
			details={"pos_profile": profile.name},
		)
	if opening.pos_closing_entry:
		_raise_closing_unavailable(profile, opening)
	return opening


def _eligible_invoices(opening):
	"""Return submitted, unconsolidated POS Invoices for the cashier/opening period."""
	from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import build_invoice_query

	query = build_invoice_query(
		"POS Invoice",
		opening.user,
		opening.pos_profile,
		opening.period_start_date,
		now_datetime(),
	)
	return query.orderby(query.timestamp).orderby(query.name).run(as_dict=True)


def _closing_snapshot(profile, opening) -> dict:
	policy = closing_counted_amount_policy(profile.company)
	profile_modes = [row.mode_of_payment for row in profile.payments]
	if not profile_modes or len(profile_modes) != len(set(profile_modes)):
		raise MobilePOSAPIError(
			"PROFILE_CONFIGURATION_INVALID",
			"The POS Profile payment configuration is invalid.",
			status=422,
			details={"pos_profile": profile.name, "field": "payments"},
		)
	opening_amounts = {mode: Decimal() for mode in profile_modes}
	for row in opening.balance_details:
		if row.mode_of_payment not in opening_amounts:
			raise MobilePOSAPIError(
				"PROFILE_CONFIGURATION_INVALID",
				"The Opening payment modes do not match the POS Profile.",
				status=422,
				details={"pos_profile": profile.name, "field": "payments"},
			)
		opening_amounts[row.mode_of_payment] += Decimal(str(row.opening_amount or 0))

	invoices = _eligible_invoices(opening)
	invoice_names = [row.name for row in invoices]
	sales_amounts = {mode: Decimal() for mode in profile_modes}
	if invoice_names:
		for payment in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parenttype": "POS Invoice", "parent": ["in", invoice_names]},
			fields=["mode_of_payment", "account", "amount"],
		):
			if payment.mode_of_payment not in sales_amounts:
				raise MobilePOSAPIError(
					"PROFILE_CONFIGURATION_INVALID",
					"An invoice payment mode is not configured on the POS Profile.",
					status=422,
					details={"pos_profile": profile.name, "field": "payments"},
				)
			sales_amounts[payment.mode_of_payment] += Decimal(str(payment.amount or 0))
		change_by_account: dict[str, Decimal] = {}
		for invoice in invoices:
			if invoice.account_for_change_amount:
				change_by_account[invoice.account_for_change_amount] = change_by_account.get(
					invoice.account_for_change_amount, Decimal()
				) + Decimal(str(invoice.change_amount or 0))
		for payment in frappe.get_all(
			"Sales Invoice Payment",
			filters={"parenttype": "POS Invoice", "parent": ["in", invoice_names]},
			fields=["mode_of_payment", "account"],
			group_by="mode_of_payment, account",
		):
			sales_amounts[payment.mode_of_payment] -= change_by_account.get(payment.account, Decimal())

	taxes = []
	if invoice_names:
		tax_amounts: dict[str, Decimal] = {}
		for row in frappe.get_all(
			"Sales Taxes and Charges",
			filters={"parenttype": "POS Invoice", "parent": ["in", invoice_names]},
			fields=["account_head", "tax_amount_after_discount_amount"],
		):
			tax_amounts[row.account_head] = tax_amounts.get(row.account_head, Decimal()) + Decimal(
				str(row.tax_amount_after_discount_amount or 0)
			)
		taxes = [
			{"account_head": account, "amount": format(amount, "f")}
			for account, amount in sorted(tax_amounts.items())
		]

	expected_payments = [
		{
			"mode_of_payment": mode,
			"opening_amount": format(opening_amounts[mode], "f"),
			"expected_amount": format(opening_amounts[mode] + sales_amounts[mode], "f"),
		}
		for mode in profile_modes
	]
	invoice_rows = [
		{
			"name": row.name,
			"posting_date": str(row.posting_date),
			"grand_total": _decimal(row.grand_total),
			"net_total": _decimal(row.net_total),
			"total_quantity": _decimal(row.total_qty),
			"total_taxes_and_charges": _decimal(row.total_taxes_and_charges),
			"customer": row.customer,
			"is_return": int(row.is_return or 0),
			"return_against": row.return_against,
		}
		for row in invoices
	]
	return {
		"opening_entry": opening.name,
		"pos_profile": profile.name,
		"cashier": frappe.session.user,
		"company": profile.company,
		"currency": policy["currency"],
		"invoice_count": len(invoice_rows),
		"invoices": invoice_rows,
		"grand_total": _sum(invoice_rows, "grand_total"),
		"net_total": _sum(invoice_rows, "net_total"),
		"total_quantity": _sum(invoice_rows, "total_quantity"),
		"total_taxes_and_charges": _sum(invoice_rows, "total_taxes_and_charges"),
		"taxes": taxes,
		"expected_payments": expected_payments,
		"counted_amount_policy": policy,
	}


def _preview_id(snapshot: dict) -> str:
	body = json.dumps(
		{"version": _PREVIEW_VERSION, "snapshot": normalize_for_hash(snapshot)},
		sort_keys=True,
		separators=(",", ":"),
		ensure_ascii=True,
	)
	return hashlib.sha256(body.encode()).hexdigest()


def _validate_submission(profile, payload: dict, *, opening=None) -> dict:
	opening = opening or _require_opening(profile, for_submit=True)
	snapshot = _closing_snapshot(profile, opening)
	current_preview_id = _preview_id(snapshot)
	if payload["preview_id"] != current_preview_id:
		raise MobilePOSAPIError(
			"CLOSING_PREVIEW_STALE",
			"The Closing preview is no longer current.",
			status=409,
			details={
				"pos_profile": profile.name,
				"opening_entry": opening.name,
				"current_preview_id": current_preview_id,
				"refresh_endpoint": "v1.closing.preview",
			},
		)
	expected = [row["mode_of_payment"] for row in snapshot["expected_payments"]]
	received = [row["mode_of_payment"] for row in payload["closing_balances"]]
	duplicate = next((mode for mode in received if received.count(mode) > 1), None)
	if duplicate:
		_raise_payment_error("CLOSING_PAYMENT_MODE_DUPLICATE", "duplicate", duplicate, expected)
	unknown = next((mode for mode in received if mode not in expected), None)
	if unknown:
		_raise_payment_error("CLOSING_PAYMENT_MODE_UNKNOWN", "unknown", unknown, expected)
	missing = next((mode for mode in expected if mode not in received), None)
	if missing:
		_raise_payment_error("CLOSING_PAYMENT_MODE_MISSING", "missing", missing, expected)
	policy = snapshot["counted_amount_policy"]
	counted = {
		row["mode_of_payment"]: closing_counted_amount_string(
			row["closing_amount"], policy=policy, mode_of_payment=row["mode_of_payment"]
		)
		for row in payload["closing_balances"]
	}
	payments = {row["mode_of_payment"]: row for row in snapshot["expected_payments"]}
	balances = []
	for mode in expected:
		expected_amount = Decimal(payments[mode]["expected_amount"])
		counted_amount = Decimal(counted[mode])
		balances.append(
			{
				"mode_of_payment": mode,
				"opening_amount": payments[mode]["opening_amount"],
				"expected_amount": payments[mode]["expected_amount"],
				"closing_amount": counted[mode],
				"difference": format(counted_amount - expected_amount, "f"),
			}
		)
	return {"snapshot": snapshot, "balances": balances}


def _raise_payment_error(code: str, reason: str, mode: str, expected: list[str]) -> None:
	raise MobilePOSAPIError(
		code,
		"Closing payment modes must exactly match the preview.",
		status=422,
		details={
			"field": "closing_balances",
			"reason": reason,
			"mode_of_payment": mode,
			"expected_modes": expected,
		},
	)


def _raise_closing_unavailable(profile, opening) -> None:
	closing = frappe.get_doc("POS Closing Entry", opening.pos_closing_entry)
	status = _STATUS_MAP.get(closing.status, "draft")
	code = "CLOSING_ALREADY_CLOSED" if status == "submitted" else "CLOSING_IN_PROGRESS"
	raise MobilePOSAPIError(
		code,
		"Closing has already been accepted for this Opening.",
		status=409,
		details={
			"pos_profile": profile.name,
			"opening_entry": opening.name,
			"closing_entry": closing.name,
			"closing_status": status,
			"status_endpoint": "v1.closing.status",
		},
	)


def _sum(rows: list[dict], field: str) -> str:
	return format(sum((Decimal(row[field]) for row in rows), Decimal()), "f")


def _decimal(value) -> str:
	return format(Decimal(str(value or 0)), "f")


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
