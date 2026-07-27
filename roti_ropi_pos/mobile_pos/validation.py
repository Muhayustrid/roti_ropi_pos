from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError


def decimal_string(value: Any, *, field: str) -> Decimal:
	"""Strictly parse a monetary/quantity decimal from a string.

	Floats are rejected to preserve exact precision; clients must send decimal
	strings. Invalid syntax is mapped to ``INVALID_REQUEST``.
	"""
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
