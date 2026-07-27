from __future__ import annotations

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import execute_idempotent
from roti_ropi_pos.mobile_pos.responses import api_endpoint, success
from roti_ropi_pos.mobile_pos.sessions import get_current_opening, open_session, opening_dto
from roti_ropi_pos.mobile_pos.validation import decimal_string, require_json_object


@frappe.whitelist(methods=["GET"])
@api_endpoint
@mobile_pos_endpoint
def current(pos_profile: str | None = None) -> dict:
	"""Return the selected profile's shared current-opening projection or null."""
	if not isinstance(pos_profile, str) or not pos_profile:
		raise _invalid("pos_profile", "Expected a POS Profile name.")
	profile = get_authorized_profile(pos_profile)
	opening = get_current_opening(profile)
	return success({"opening_session": opening_dto(opening) if opening else None})


@frappe.whitelist(methods=["POST"])
@api_endpoint
@mobile_pos_endpoint
def open(**kwargs) -> dict:
	"""Open one POS session through the durable idempotency executor."""
	payload_data = dict(frappe.form_dict)
	# Frappe api.v1.handle_rpc_call injects this routing metadata for every
	# /api/method request; it is not part of the Mobile POS request body.
	payload_data.pop("cmd", None)
	payload = _parse_open_payload(payload_data)
	profile = get_authorized_profile(payload["pos_profile"])
	return execute_idempotent(
		"v1.sessions.open",
		payload,
		lambda transaction_id: open_session(profile, payload["opening_balances"], transaction_id),
	)


def _parse_open_payload(value) -> dict:
	payload = require_json_object(value, field="payload")
	unknown = sorted(set(payload) - {"pos_profile", "opening_balances"})
	if unknown:
		raise _invalid(unknown[0], "This field is not accepted.")
	pos_profile = payload.get("pos_profile")
	if not isinstance(pos_profile, str) or not pos_profile:
		raise _invalid("pos_profile", "Expected a POS Profile name.")
	balances = payload.get("opening_balances")
	if not isinstance(balances, list):
		raise _invalid("opening_balances", "Expected an array of balances.")
	normalized = []
	for index, row in enumerate(balances):
		if not isinstance(row, dict):
			raise _invalid("opening_balances", f"Row {index} must be an object.")
		unknown_row = sorted(set(row) - {"mode_of_payment", "amount"})
		if unknown_row:
			raise _invalid(unknown_row[0], "This field is not accepted.")
		mode = row.get("mode_of_payment")
		if not isinstance(mode, str) or not mode:
			raise _invalid("mode_of_payment", "Expected a payment mode name.")
		normalized.append(
			{
				"mode_of_payment": mode,
				"opening_amount": decimal_string(row.get("amount"), field="amount"),
			}
		)
	return {"pos_profile": pos_profile, "opening_balances": normalized}


def _invalid(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
