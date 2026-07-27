from __future__ import annotations

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile
from roti_ropi_pos.mobile_pos.customers import search_customers
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import api_endpoint, success


@frappe.whitelist(methods=["GET"])
@api_endpoint
@mobile_pos_endpoint
def search(pos_profile=None, q="", start=0, limit=20) -> dict:
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise _invalid("pos_profile", "Expected a POS Profile name.")
	if not isinstance(q, str):
		raise _invalid("q", "Expected a string.")
	profile = get_authorized_profile(pos_profile.strip())
	return success(search_customers(profile, q.strip(), _integer(start, "start"), _integer(limit, "limit")))


def _integer(value, field: str) -> int:
	if isinstance(value, bool):
		raise _invalid(field, "Expected an integer.")
	try:
		return int(value)
	except (TypeError, ValueError) as error:
		raise _invalid(field, "Expected an integer.") from error


def _invalid(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
