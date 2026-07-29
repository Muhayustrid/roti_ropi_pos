from __future__ import annotations

import builtins
from decimal import Decimal

import frappe

from roti_ropi_pos.api.v1.bootstrap import mobile_pos_endpoint
from roti_ropi_pos.mobile_pos.authorization import get_authorized_profile
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import execute_idempotent
from roti_ropi_pos.mobile_pos.invoices import create_return as create_return_service
from roti_ropi_pos.mobile_pos.invoices import get_sale as get_sale_service
from roti_ropi_pos.mobile_pos.invoices import list_sales as list_sales_service
from roti_ropi_pos.mobile_pos.invoices import submit_sale
from roti_ropi_pos.mobile_pos.responses import success
from roti_ropi_pos.mobile_pos.validation import decimal_string, require_json_object


@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def submit(**kwargs) -> dict:
	"""Submit one idempotent Mobile POS sale."""
	payload = _parse_sale_payload(dict(frappe.form_dict))
	profile = get_authorized_profile(payload["pos_profile"])
	_lock_stock(payload["items"], profile.warehouse)
	return execute_idempotent(
		"v1.sales.submit",
		payload,
		lambda transaction_id: submit_sale(payload, transaction_id),
	)


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def list(pos_profile=None, status=None, q="", start=0, limit=20) -> dict:
	"""Return POS Invoice-only history for one authorized profile."""
	if not isinstance(pos_profile, str) or not pos_profile.strip():
		raise _invalid("pos_profile", "Expected a POS Profile name.")
	if status not in {"all", "paid", "return", "consolidated", "cancelled"}:
		raise _invalid("status", "Expected all, paid, return, consolidated, or cancelled.")
	if not isinstance(q, str):
		raise _invalid("q", "Expected a string.")
	profile = get_authorized_profile(pos_profile.strip())
	return success(
		list_sales_service(
			profile,
			status=status,
			q=q.strip(),
			start=_integer(start, "start", minimum=0),
			limit=min(_integer(limit, "limit", minimum=1), 100),
		)
	)


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def get(name=None) -> dict:
	"""Return one scoped POS Invoice detail."""
	if not isinstance(name, str) or not name.strip():
		raise _invalid("name", "Expected a POS Invoice name.")
	return success(get_sale_service(name.strip()))


@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def create_return(**kwargs) -> dict:
	"""Submit one idempotent POS Invoice return."""
	payload = _parse_return_payload(dict(frappe.form_dict))
	return execute_idempotent(
		"v1.sales.create_return",
		payload,
		lambda transaction_id: create_return_service(payload, transaction_id),
	)


def _lock_stock(items: list[dict], warehouse: str) -> None:
	stock_items = set()
	for row in items:
		item_code = row["item_code"]
		if frappe.get_cached_value("Item", item_code, "is_stock_item"):
			stock_items.add(item_code)
		if frappe.db.exists("Product Bundle", {"name": item_code, "disabled": 0}):
			stock_items.update(
				frappe.get_all(
					"Product Bundle Item",
					filters={"parent": item_code},
					pluck="item_code",
				)
			)
	if stock_items:
		frappe.db.sql(
			"""SELECT name FROM `tabBin`
			WHERE warehouse = %(warehouse)s AND item_code IN %(items)s
			ORDER BY item_code FOR UPDATE""",
			{"warehouse": warehouse, "items": sorted(stock_items)},
		)


def _parse_sale_payload(value) -> dict:
	value.pop("cmd", None)
	payload = require_json_object(value, field="payload")
	_unknown(
		payload,
		{
			"pos_profile",
			"customer",
			"walk_in_customer_name",
			"client_accepted_grand_total",
			"items",
			"payments",
		},
	)
	return {
		"pos_profile": _name(payload.get("pos_profile"), "pos_profile", "Expected a POS Profile name."),
		"customer": _optional_name(payload.get("customer"), "customer", "Expected a Customer name or null."),
		"walk_in_customer_name": _optional_name(
			payload.get("walk_in_customer_name"),
			"walk_in_customer_name",
			"Expected a display name or null.",
		),
		"client_accepted_grand_total": _positive_decimal(
			payload.get("client_accepted_grand_total"), "client_accepted_grand_total"
		),
		"items": _items(payload.get("items")),
		"payments": _payments(payload.get("payments")),
	}


def _parse_return_payload(value) -> dict:
	value.pop("cmd", None)
	payload = require_json_object(value, field="payload")
	_unknown(payload, {"source_name", "reason", "items", "payments"})
	reason = _name(payload.get("reason"), "reason", "Expected a non-empty return reason.")
	items = payload.get("items")
	if not isinstance(items, builtins.list) or not items:
		raise _invalid("items", "Expected a non-empty array of items.")
	parsed_items = []
	for row in items:
		if not isinstance(row, dict):
			raise _invalid("items", "Each row must be an object.")
		_unknown(row, {"source_item_row", "qty"})
		parsed_items.append(
			{
				"source_item_row": _name(
					row.get("source_item_row"),
					"source_item_row",
					"Expected a POS Invoice Item row ID.",
				),
				"qty": _positive_decimal(row.get("qty"), "qty"),
			}
		)
	if len({row["source_item_row"] for row in parsed_items}) != len(parsed_items):
		raise _invalid("items", "Duplicate source_item_row values are not accepted.")
	return {
		"source_name": _name(payload.get("source_name"), "source_name", "Expected a POS Invoice name."),
		"reason": reason,
		"items": parsed_items,
		"payments": _return_payments(payload.get("payments")),
	}


def _return_payments(value) -> list[dict]:
	return _payments(value, positive=False)


def _items(value) -> list[dict]:
	if not isinstance(value, builtins.list) or not value:
		raise _invalid("items", "Expected a non-empty array of items.")
	items = []
	for index, row in enumerate(value):
		if not isinstance(row, dict):
			raise _invalid("items", f"Row {index} must be an object.")
		_unknown(row, {"item_code", "qty", "uom", "batch_no", "serial_numbers"})
		batch_no = _optional_name(row.get("batch_no"), "batch_no", "Expected a Batch name or null.")
		serial_numbers = row.get("serial_numbers", [])
		if not isinstance(serial_numbers, builtins.list) or not all(
			isinstance(serial_no, str) and serial_no.strip() for serial_no in serial_numbers
		):
			raise _invalid("serial_numbers", "Expected an array of serial number strings.")
		if len(set(serial_numbers)) != len(serial_numbers):
			raise _invalid("serial_numbers", "Duplicate serial numbers are not accepted.")
		items.append(
			{
				"item_code": _name(row.get("item_code"), "item_code", "Expected an Item code."),
				"qty": _positive_decimal(row.get("qty"), "qty"),
				"uom": _name(row.get("uom"), "uom", "Expected a UOM."),
				"batch_no": batch_no,
				"serial_numbers": [serial_no.strip() for serial_no in serial_numbers],
			}
		)
	return items


def _payments(value, *, positive: bool = True) -> list[dict]:
	if not isinstance(value, builtins.list) or not value:
		raise _invalid("payments", "Expected a non-empty array of payments.")
	payments = []
	for index, row in enumerate(value):
		if not isinstance(row, dict):
			raise _invalid("payments", f"Row {index} must be an object.")
		_unknown(row, {"mode_of_payment", "amount", "reference_no"})
		amount = decimal_string(row.get("amount"), field="amount")
		if (positive and amount <= 0) or (not positive and amount >= 0):
			raise _invalid("amount", f"Expected a {'positive' if positive else 'negative'} decimal string.")
		payments.append(
			{
				"mode_of_payment": _name(
					row.get("mode_of_payment"), "mode_of_payment", "Expected a payment mode name."
				),
				"amount": amount,
				"reference_no": _optional_name(
					row.get("reference_no"), "reference_no", "Expected a reference number or null."
				),
			}
		)
	return payments


def _unknown(payload: dict, allowed: set[str]) -> None:
	unknown = sorted(set(payload) - allowed)
	if unknown:
		raise _invalid(unknown[0], "This field is not accepted.")


def _name(value, field: str, reason: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise _invalid(field, reason)
	return value.strip()


def _optional_name(value, field: str, reason: str) -> str | None:
	if value is None:
		return None
	return _name(value, field, reason)


def _integer(value, field: str, *, minimum: int) -> int:
	if isinstance(value, bool) or isinstance(value, float):
		raise _invalid(field, "Expected an integer.")
	if isinstance(value, int):
		integer = value
	elif isinstance(value, str) and value.isdigit():
		integer = int(value)
	else:
		raise _invalid(field, "Expected an integer.")
	if integer < minimum:
		raise _invalid(field, f"Expected an integer greater than or equal to {minimum}.")
	return integer


def _positive_decimal(value, field: str) -> Decimal:
	parsed = decimal_string(value, field=field)
	if parsed <= 0:
		raise _invalid(field, "Expected a positive decimal string.")
	return parsed


def _invalid(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
