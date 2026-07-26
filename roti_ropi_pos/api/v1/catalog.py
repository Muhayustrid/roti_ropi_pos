from __future__ import annotations

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile
from roti_ropi_pos.mobile_pos.catalog import quote_item as quote_item_service
from roti_ropi_pos.mobile_pos.catalog import scan_value, search_items
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import api_endpoint, success


@frappe.whitelist(methods=["GET"])
@api_endpoint
@mobile_pos_endpoint
def search(pos_profile=None, q="", item_group=None, start=0, limit=20) -> dict:
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise _invalid_request("pos_profile", "Expected a POS Profile name.")
	if not isinstance(q, str):
		raise _invalid_request("q", "Expected a string.")
	if item_group is not None and not isinstance(item_group, str):
		raise _invalid_request("item_group", "Expected an Item Group name.")
	profile = get_authorized_profile(pos_profile.strip())
	return success(
		search_items(
			profile,
			q=q.strip(),
			item_group=item_group.strip() if item_group else None,
			start=_integer(start, "start"),
			limit=_integer(limit, "limit"),
		)
	)


@frappe.whitelist(methods=["POST"])
@api_endpoint
@mobile_pos_endpoint
def scan(**kwargs) -> dict:
	payload = _payload(kwargs, {"pos_profile", "value"})
	profile = get_authorized_profile(_required_text(payload, "pos_profile"))
	return success(scan_value(profile, _required_text(payload, "value")))


@frappe.whitelist(methods=["POST"])
@api_endpoint
@mobile_pos_endpoint
def quote_item(**kwargs) -> dict:
	payload = _payload(kwargs, {"pos_profile", "customer", "walk_in_customer_name", "item_code", "qty", "uom", "batch_no"})
	profile = get_authorized_profile(_required_text(payload, "pos_profile"))
	return success(
		quote_item_service(
			profile,
			item_code=_required_text(payload, "item_code"),
			qty=payload.get("qty"),
			customer=payload.get("customer"),
			walk_in_customer_name=payload.get("walk_in_customer_name"),
			uom=payload.get("uom"),
			batch_no=payload.get("batch_no"),
		)
	)


def _payload(kwargs: dict, allowed: set[str]) -> dict:
	payload = dict(frappe.form_dict) if frappe.form_dict else dict(kwargs)
	payload.pop("cmd", None)
	unknown = sorted(set(payload) - allowed)
	if unknown:
		raise _invalid_request(unknown[0], "This field is not accepted.")
	return payload


def _required_text(payload: dict, field: str) -> str:
	value = payload.get(field)
	if not isinstance(value, str) or not value.strip():
		raise _invalid_request(field, "Expected a non-empty string.")
	return value.strip()


def _integer(value, field: str) -> int:
	if isinstance(value, bool):
		raise _invalid_request(field, "Expected an integer.")
	try:
		return int(value)
	except (TypeError, ValueError) as error:
		raise _invalid_request(field, "Expected an integer.") from error


def _invalid_request(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
