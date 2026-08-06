from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import frappe

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


_SIGNED_DECIMAL_SYNTAX = re.compile(r"\A-?[0-9]+(?:\.[0-9]+)?\Z")


def decimal_string(
	value: Any,
	*,
	field: str,
	currency: str | None = None,
	positive: bool = True,
	allow_zero: bool = False,
) -> Decimal:
	"""Strictly parse a monetary/quantity decimal from a string.

	Syntax and scale are validated against the original string representation
	before the value is converted to ``Decimal``. The function rejects:

	* non-string input (``Expected a decimal string.``)
	* leading-signed input when ``positive`` is ``True``
	  (``negative_amount``); leading-positive input when ``positive`` is
	  ``False`` (``non_negative_amount``)
	* malformed input (exponent, grouping, whitespace, missing fraction)
	  (``malformed_decimal``)
	* fractional digits beyond the policy's ``decimal_places`` when a
	  ``currency`` is supplied (``excessive_scale``)
	* zero when ``allow_zero`` is ``False`` (``zero_amount``)
	* values that lose precision when represented as a ``Decimal`` (NaN/Inf)
	  (``Decimal value must be finite.``)

	The returned ``Decimal`` preserves the exact parsed value; no quantize
	rounding or truncation is applied.
	"""
	if not isinstance(value, str):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "Expected a decimal string."},
		)
	syntax = _SIGNED_DECIMAL_SYNTAX if not positive else _DECIMAL_SYNTAX
	if positive and value.startswith("-"):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "negative_amount"},
		)
	if not positive and not value.startswith("-"):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "non_negative_amount"},
		)
	if not syntax.fullmatch(value):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "malformed_decimal"},
		)
	if currency is not None:
		decimal_places = frappe_get_currency_precision(currency)
		fractional = value.partition(".")[2]
		if len(fractional) > decimal_places:
			raise MobilePOSAPIError(
				"INVALID_REQUEST",
				f"{field} must be a decimal string.",
				details={"field": field, "reason": "excessive_scale"},
			)
	try:
		parsed = Decimal(value)
	except InvalidOperation as error:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "malformed_decimal"},
		) from error
	if not allow_zero and parsed == 0:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			f"{field} must be a decimal string.",
			details={"field": field, "reason": "zero_amount"},
		)
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


_SALE_DECIMAL_SYNTAX = _DECIMAL_SYNTAX


def sale_payment_amount_policy(currency: str) -> dict:
	"""Return the server-projected policy for sale payment amounts.

	Currency decimal places are server-derived through ERPNext's precision
	utility, with a validated fallback from ``Currency.fraction_units``. The
	contract exposes the same shape as ``opening_amount_policy`` so Android
	treats the two as the same kind of object.
	"""
	if not isinstance(currency, str) or not currency:
		raise MobilePOSAPIError(
			"PROFILE_CONFIGURATION_INVALID",
			"The sale payment policy currency is invalid.",
			status=422,
			details={"field": "currency", "reason": "Expected a non-empty currency."},
		)
	decimal_places = frappe_get_currency_precision(currency)
	minimum = "1" if decimal_places == 0 else f"0.{('0' * (decimal_places - 1))}1"
	return {
		"currency": currency,
		"decimal_places": decimal_places,
		"minimum": minimum,
		"api_syntax": "ascii_decimal_dot",
		"rounding": "reject",
		"policy_version": "sale-payment-amount/v1",
	}


def sale_payment_amount_string(value: Any, *, currency: str) -> str:
	"""Validate and return the exact canonical decimal string for a sale amount.

	The comparison is exact ``Decimal`` arithmetic. There is no ``quantize``,
	no rounding, and no truncation. The returned string preserves the exact
	``Decimal`` representation of the parsed value.
	"""
	policy = sale_payment_amount_policy(currency)
	if not isinstance(value, str):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"amount is invalid.",
			details={"field": "amount", "reason": "Expected a decimal string."},
		)
	# Detect negatives explicitly so the contract surfaces ``negative_amount``
	# instead of the more generic ``malformed_decimal`` for inputs that fail
	# only because of the leading minus sign.
	if value.startswith("-"):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"amount is invalid.",
			details={"field": "amount", "reason": "negative_amount"},
		)
	if not _SALE_DECIMAL_SYNTAX.fullmatch(value):
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"amount is invalid.",
			details={"field": "amount", "reason": "malformed_decimal"},
		)
	parsed = Decimal(value)
	if parsed == 0:
		raise MobilePOSAPIError(
			"INVALID_PAYMENT",
			"Payment amount is invalid.",
			status=422,
			details={
				"field": "amount",
				"mode_of_payment": None,
				"reason": "empty_payments_amount",
			},
		)
	fractional = value.partition(".")[2]
	if len(fractional) > policy["decimal_places"]:
		raise MobilePOSAPIError(
			"INVALID_REQUEST",
			"amount is invalid.",
			details={"field": "amount", "reason": "excessive_scale"},
		)
	return str(parsed)


def frappe_get_currency_precision(currency: str) -> int:
	"""Resolve ERPNext currency precision for ``currency``.

	Uses ``frappe.get_precision`` on the ERPNext payment field so the policy
	follows the active site configuration. Falls back to the number of
	decimal places implied by ``Currency.fraction_units`` (the number of
	sub-units in one main unit, e.g. 100 for USD → 2 decimal places).
	"""
	try:
		precision = frappe.get_precision("Sales Invoice Payment", "amount", currency=currency)
	except Exception:
		precision = None
	if isinstance(precision, int) and precision >= 0:
		return precision
	try:
		fraction = frappe.get_cached_value("Currency", currency, "fraction_units")
	except Exception:
		fraction = None
	if isinstance(fraction, int) and fraction > 0:
		return _decimal_places_from_fraction_units(fraction)
	return 2


def _decimal_places_from_fraction_units(fraction_units: int) -> int:
	"""Convert a sub-unit count into the matching decimal-place count.

	``fraction_units=100`` (USD-style) means two decimal places, not 100.
	``fraction_units=1000`` (KWD-style) means three. Non-power-of-ten values
	(e.g. legacy ``fraction_units=5`` for some Mauritanian currencies) do
	not map cleanly to decimal places, so we default to 2.
	"""
	if fraction_units <= 0:
		return 2
	places = 0
	remainder = fraction_units
	while remainder > 1 and remainder % 10 == 0:
		remainder //= 10
		places += 1
	if remainder != 1:
		return 2
	return places
