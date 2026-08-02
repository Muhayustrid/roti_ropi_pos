from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

_DECIMAL_SYNTAX = re.compile(r"[0-9]+(?:\.[0-9]+)?\Z")


def opening_amount_string(
	value: Any,
	*,
	field: str,
	decimal_places: int,
	column_type: str | None = None,
) -> str:
	negative = isinstance(value, str) and value.startswith("-")
	syntax_value = value[1:] if negative else value
	if not isinstance(value, str) or not _DECIMAL_SYNTAX.fullmatch(syntax_value):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} is invalid.",
			details={"field": field, "reason": "Invalid decimal syntax."},
		)
	parsed = Decimal(value)
	if negative:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} is invalid.",
			details={"field": field, "reason": "Amount must be non-negative."},
		)
	if parsed < 0:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} is invalid.",
			details={"field": field, "reason": "Amount must be non-negative."},
		)
	allowed_fractional_digits = decimal_places
	if column_type:
		match = re.fullmatch(r"decimal\((\d+),(\d+)\)", column_type.lower())
		if not match:
			raise MobilePOSAPIError(
				"PROFILE_CONFIGURATION_INVALID",
				"Opening amount storage configuration is invalid.",
				status=422,
				details={"pos_profile": "", "field": field, "reason": "Invalid database capacity."},
			)
		precision, scale = map(int, match.groups())
		allowed_fractional_digits = min(decimal_places, scale)
		integer_digits = len(value.partition(".")[0].lstrip("0")) or 1
		if integer_digits > precision - scale:
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				f"{field} is invalid.",
				details={"field": field, "reason": "Amount exceeds database capacity."},
			)
	fractional_digits = len(value.partition(".")[2])
	if fractional_digits > allowed_fractional_digits:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} is invalid.",
			details={"field": field, "reason": "Too many fractional digits."},
		)
	return f"{parsed:.{decimal_places}f}"


def decimal_string(value: Any, *, field: str) -> Decimal:
	"""Strictly parse a monetary/quantity decimal from a string."""
	if not isinstance(value, str):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "Expected a decimal string."},
		)
	try:
		parsed = Decimal(value)
	except InvalidOperation as error:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "Invalid decimal syntax."},
		) from error
	if not parsed.is_finite():
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "Decimal value must be finite."},
		)
	return parsed


def reject_fields(payload: dict, blocked: set[str]) -> None:
	"""Reject client-supplied server-owned identity/account/total fields."""
	present = sorted(blocked.intersection(payload))
	if present:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"Server-owned fields are not accepted: {', '.join(present)}.",
			details={"field": present[0], "reason": "This field is server-owned."},
		)


def require_json_object(value: Any, *, field: str) -> dict:
	"""Ensure a decoded JSON payload is a dict object."""
	if not isinstance(value, dict):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a JSON object.",
			details={"field": field, "reason": "Expected a JSON object."},
		)
	return value
