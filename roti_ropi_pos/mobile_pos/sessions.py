from __future__ import annotations

import frappe
from frappe.utils import getdate, now_datetime, today

from roti_ropi_pos.mobile_pos.authorization import require_doc_permission
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import MutationResult


def get_current_opening(profile):
	"""Return the cashier's submitted, Open, unclosed POS Opening Entry.

	The lookup applies no hard current-calendar-day filter; a prior-day shift
	remains current. ``require_doc_permission`` enforces POS Opening Entry read
	permission without ``ignore_permissions``.
	"""
	name = frappe.db.get_value(
		"POS Opening Entry",
		{
			"user": frappe.session.user,
			"pos_profile": profile.name,
			"company": profile.company,
			"docstatus": 1,
			"status": "Open",
			"pos_closing_entry": ["is", "not set"],
		},
		"name",
		order_by="period_start_date desc",
	)
	if not name:
		return None
	opening = frappe.get_doc("POS Opening Entry", name)
	require_doc_permission("POS Opening Entry", "read", doc=opening)
	return opening


def open_session(profile, balances: list[dict], transaction_id: str) -> MutationResult:
	"""Create and submit one POS Opening Entry under the cashier/profile locks."""
	require_doc_permission("POS Opening Entry", "create")
	require_doc_permission("POS Opening Entry", "submit")
	_lock_opening_scope(profile)
	_check_opening_conflicts(profile)
	normalized_balances = _normalize_balances(profile, balances)

	opening = frappe.get_doc(
		{
			"doctype": "POS Opening Entry",
			"period_start_date": now_datetime(),
			"posting_date": today(),
			"user": frappe.session.user,
			"pos_profile": profile.name,
			"company": profile.company,
			"balance_details": normalized_balances,
			"custom_mobile_pos_transaction_id": transaction_id,
		}
	)
	opening.insert()
	opening.submit()
	return MutationResult(
		data={"opening_session": opening_dto(opening)},
		reference_doctype="POS Opening Entry",
		reference_name=opening.name,
	)


def _lock_opening_scope(profile) -> None:
	"""Serialize same-profile and same-user opening decisions before creation."""
	frappe.db.get_value("POS Profile", profile.name, "name", for_update=True)
	frappe.db.get_value("User", frappe.session.user, "name", for_update=True)


def _check_opening_conflicts(profile) -> None:
	profile_conflict = frappe.db.get_value(
		"POS Opening Entry",
		{"pos_profile": profile.name, "status": "Open"},
		["name", "pos_profile"],
		as_dict=True,
		for_update=True,
	)
	if profile_conflict:
		_raise_session_already_open(profile_conflict)
	user_conflict = frappe.db.get_value(
		"POS Opening Entry",
		{"user": frappe.session.user, "status": "Open"},
		["name", "pos_profile"],
		as_dict=True,
		for_update=True,
	)
	if user_conflict:
		_raise_session_already_open(user_conflict)


def _raise_session_already_open(conflict) -> None:
	raise MobilePOSAPIError(
		"SESSION_ALREADY_OPEN",
		"An open POS session already exists.",
		status=409,
		details={"opening_entry": conflict.name, "pos_profile": conflict.pos_profile},
	)


def _normalize_balances(profile, balances: list[dict]) -> list[dict]:
	allowed_modes = {row.mode_of_payment for row in profile.payments}
	seen = set()
	normalized = []
	for row in balances:
		mode = row.get("mode_of_payment")
		if not mode or mode not in allowed_modes:
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				"opening_balances contains a mode not configured for this POS Profile.",
				details={"field": "opening_balances", "reason": "Unknown payment mode."},
			)
		if mode in seen:
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				"opening_balances contains a duplicate payment mode.",
				details={"field": "opening_balances", "reason": "Duplicate payment mode."},
			)
		seen.add(mode)
		normalized.append({"mode_of_payment": mode, "opening_amount": row["opening_amount"]})
	if not normalized:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"opening_balances must contain at least one payment mode.",
			details={"field": "opening_balances", "reason": "Expected at least one balance."},
		)
	return normalized


def opening_dto(doc) -> dict:
	"""Map a POS Opening Entry to the contract DTO, including stale warning."""
	warnings = []
	opening_date = getdate(doc.period_start_date)
	server_date = getdate(today())
	if opening_date < server_date:
		warnings.append(
			{
				"code": "STALE_OPENING",
				"message": "The current POS opening started on an earlier calendar day.",
				"details": {
					"opening_date": str(opening_date),
					"server_date": str(server_date),
				},
			}
		)
	return {
		"name": doc.name,
		"pos_profile": doc.pos_profile,
		"company": doc.company,
		"user": doc.user,
		"status": "open",
		"posting_date": str(doc.posting_date),
		"period_start_date": _iso(doc.period_start_date),
		"opening_balances": [
			{
				"mode_of_payment": row.mode_of_payment,
				"opening_amount": _decimal(row.opening_amount),
			}
			for row in doc.balance_details
		],
		"warnings": warnings,
	}


def _iso(value) -> str:
	"""Render a datetime as an ISO 8601 string with the site timezone offset."""
	dt = value if hasattr(value, "astimezone") else frappe.utils.get_datetime(value)
	if hasattr(dt, "astimezone"):
		return dt.astimezone().isoformat()
	return str(dt)


def _decimal(value) -> str:
	"""Render a monetary value as a decimal string without float artifacts."""
	if value is None:
		return "0"
	return str(value)
