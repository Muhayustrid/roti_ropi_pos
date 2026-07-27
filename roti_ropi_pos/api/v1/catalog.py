from __future__ import annotations

from decimal import Decimal

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile
from roti_ropi_pos.mobile_pos.catalog import quote_item as quote_item_service
from roti_ropi_pos.mobile_pos.catalog import scan_value, search_items
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import success
from roti_ropi_pos.mobile_pos.validation import decimal_string, require_json_object


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def search(pos_profile=None, q="", item_group=None, start=0, limit=20) -> dict:
	"""Return scoped catalog snapshots."""
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise _invalid("pos_profile", "Expected a POS Profile name.")
	if not isinstance(q, str):
		raise _invalid("q", "Expected a string.")
	if item_group is not None and (not isinstance(item_group, str) or not item_group.strip()):
		raise _invalid("item_group", "Expected an Item Group name.")
	profile = get_authorized_profile(pos_profile.strip())
	return success(
		search_items(
			profile,
			q=q.strip(),
			item_group=item_group.strip() if item_group else None,
			start=_integer(start, "start", minimum=0),
			limit=_integer(limit, "limit", minimum=1),
		)
	)


@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def scan(**kwargs) -> dict:
	"""Resolve barcode through current scanner override."""
	payload = _payload({"pos_profile", "value"})
	profile = get_authorized_profile(_name(payload, "pos_profile", "Expected a POS Profile name."))
	return success(scan_value(profile, _name(payload, "value", "Expected a scan value.")))


@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def quote_item(**kwargs) -> dict:
	"""Return ERPNext-calculated item quote snapshot."""
	payload = _payload({"pos_profile", "customer", "item_code", "qty", "uom", "batch_no"})
	profile = get_authorized_profile(_name(payload, "pos_profile", "Expected a POS Profile name."))
	customer = payload.get("customer")
	batch_no = payload.get("batch_no")
	if customer is not None and (not isinstance(customer, str) or not customer.strip()):
		raise _invalid("customer", "Expected a Customer name or null.")
	if batch_no is not None and (not isinstance(batch_no, str) or not batch_no.strip()):
		raise _invalid("batch_no", "Expected a Batch name or null.")
	qty = decimal_string(payload.get("qty"), field="qty")
	if qty <= Decimal("0"):
		raise _invalid("qty", "Expected a positive decimal string.")
	return success(
		quote_item_service(
			profile,
			customer=customer.strip() if customer else None,
			item_code=_name(payload, "item_code", "Expected an Item code."),
			qty=qty,
			uom=_name(payload, "uom", "Expected a UOM."),
			batch_no=batch_no.strip() if batch_no else None,
		)
	)


def _payload(fields: set[str]) -> dict:
	payload = dict(frappe.form_dict)
	payload.pop("cmd", None)
	payload = require_json_object(payload, field="payload")
	unknown = sorted(set(payload) - fields)
	if unknown:
		raise _invalid(unknown[0], "This field is not accepted.")
	return payload


def _name(payload: dict, field: str, reason: str) -> str:
	value = payload.get(field)
	if not isinstance(value, str) or not value.strip():
		raise _invalid(field, reason)
	return value.strip()


def _integer(value, field: str, *, minimum: int) -> int:
	if isinstance(value, bool):
		raise _invalid(field, "Expected an integer.")
	try:
		integer = int(value)
	except (TypeError, ValueError) as error:
		raise _invalid(field, "Expected an integer.") from error
	if integer < minimum:
		raise _invalid(field, f"Expected an integer greater than or equal to {minimum}.")
	return integer


def _invalid(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
