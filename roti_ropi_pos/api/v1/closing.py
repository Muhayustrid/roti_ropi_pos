from __future__ import annotations

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile, require_doc_permission
from roti_ropi_pos.mobile_pos.closing import closing_status, execute_closing_submit, preview_closing
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import success
from roti_ropi_pos.mobile_pos.validation import decimal_string, require_json_object


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def preview(pos_profile=None) -> dict:
	"""Return server-derived closing preview for the current session."""
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"pos_profile is invalid.",
			details={"field": "pos_profile", "reason": "Expected a POS Profile name."},
		)
	profile = get_authorized_profile(pos_profile.strip())
	return success(preview_closing(profile))


@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def submit(**kwargs) -> dict:
	"""Submit one idempotent POS Closing Entry."""
	payload = _parse_closing_payload(dict(frappe.form_dict))
	profile = get_authorized_profile(payload["pos_profile"])
	require_doc_permission("POS Closing Entry", "create")
	require_doc_permission("POS Closing Entry", "submit")
	return execute_closing_submit(profile, payload)


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def status(name=None) -> dict:
	"""Return closing status for one POS Closing Entry (scoped to current user)."""
	if not isinstance(name, str) or not name.strip():
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"name is invalid.",
			details={"field": "name", "reason": "Expected a POS Closing Entry name."},
		)
	return success(closing_status(name.strip()))


def _parse_closing_payload(value: dict) -> dict:
	value.pop("cmd", None)
	payload = require_json_object(value, field="payload")
	_unknown(payload, {"pos_profile", "closing_balances"})
	pos_profile = payload.get("pos_profile")
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"pos_profile is invalid.",
			details={"field": "pos_profile", "reason": "Expected a POS Profile name."},
		)
	balances = payload.get("closing_balances")
	if not isinstance(balances, list) or not balances:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"closing_balances is invalid.",
			details={"field": "closing_balances", "reason": "Expected a non-empty array."},
		)
	parsed_balances = []
	for row in balances:
		if not isinstance(row, dict):
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				"closing_balances is invalid.",
				details={"field": "closing_balances", "reason": "Each row must be an object."},
			)
		_unknown(row, {"mode_of_payment", "closing_amount"})
		mop = row.get("mode_of_payment")
		if not isinstance(mop, str) or not mop.strip():
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				"mode_of_payment is invalid.",
				details={"field": "mode_of_payment", "reason": "Expected a payment mode name."},
			)
		amount = decimal_string(
			row.get("closing_amount"),
			field="closing_amount",
			allow_zero=True,
		)
		parsed_balances.append({"mode_of_payment": mop.strip(), "closing_amount": amount})
	return {
		"pos_profile": pos_profile.strip(),
		"closing_balances": parsed_balances,
	}


def _unknown(payload: dict, allowed: set[str]) -> None:
	unknown = sorted(set(payload) - allowed)
	if unknown:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{unknown[0]} is invalid.",
			details={"field": unknown[0], "reason": "This field is not accepted."},
		)
