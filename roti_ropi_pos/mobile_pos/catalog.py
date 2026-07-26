from __future__ import annotations

from decimal import Decimal

import frappe
from frappe.utils import getdate, today

from erpnext.selling.page.point_of_sale.point_of_sale import get_items
from erpnext.stock.get_item_details import get_batch_qty, get_item_details

from roti_ropi_pos.mobile_pos.authorization import require_doc_permission
from roti_ropi_pos.mobile_pos.customers import resolve_customer
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.validation import decimal_string

MISSING_UOM_CONVERSION = {
	"code": "MISSING_UOM_CONVERSION",
	"message": "The selected UOM has no conversion factor.",
}


def item_dto(item) -> dict:
	"""Project an ERPNext catalog row to the public Mobile POS contract."""
	item = frappe._dict(item)
	return {
		"item_code": item.item_code,
		"item_name": item.item_name,
		"description": item.description or None,
		"image": item.item_image or None,
		"uom": item.uom or item.stock_uom,
		"price_list_rate": _decimal(item.price_list_rate),
		"currency": item.currency,
		"available_qty": _decimal(item.actual_qty),
	}


def search_items(profile, q: str = "", item_group: str | None = None, start: int = 0, limit: int = 20) -> dict:
	"""Search core POS catalog within the selected authorized profile scope."""
	if start < 0:
		raise _invalid_request("start", "Must be >= 0.")
	if limit <= 0:
		raise _invalid_request("limit", "Must be > 0.")

	require_doc_permission("Item", "read")
	limit = min(limit, 100)
	result = get_items(
		start,
		limit + 1,
		profile.selling_price_list,
		item_group or "",
		profile.name,
		q,
	)
	rows = (result or {}).get("items", [])
	return {
		"items": [item_dto(row) for row in rows[:limit]],
		"page": {"start": start, "limit": limit, "has_more": len(rows) > limit},
	}


def scan_value(profile, value: str) -> dict:
	"""Scan using the registered ERPNext method, including bakery's override."""
	require_doc_permission("Item", "read")
	method_path = frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode")
	scanner = frappe.get_attr(method_path)
	result = scanner(value, {"doctype": "POS Invoice", "warehouse": profile.warehouse})
	if not result:
		raise MobilePOSAPIError(
			"RESOURCE_NOT_FOUND",
			"No item, serial number, batch, or barcode matched.",
			status=404,
			details={"resource_type": "scan_value", "name": value},
		)
	return map_scan_result(result, profile)


def map_scan_result(result, profile) -> dict:
	"""Return only public scan fields and an app-owned UOM warning."""
	uom = result.get("uom")
	conversion_factor = result.get("conversion_factor")
	warnings = []
	if uom and not conversion_factor and _is_non_stock_uom(result.get("item_code"), uom):
		warnings.append(MISSING_UOM_CONVERSION.copy())
	return {
		"scan": {
			"item_code": result.get("item_code"),
			"barcode": result.get("barcode"),
			"batch_no": result.get("batch_no"),
			"serial_no": result.get("serial_no"),
			"uom": uom,
			"conversion_factor": _decimal(conversion_factor) if conversion_factor else None,
			"warehouse": result.get("warehouse") or profile.warehouse,
		},
		"warnings": warnings,
	}


def quote_item(
	profile,
	*,
	item_code: str,
	qty: str,
	customer: str | None = None,
	walk_in_customer_name: str | None = None,
	uom: str | None = None,
	batch_no: str | None = None,
) -> dict:
	"""Get a non-authoritative, server-derived POS item quote."""
	if not isinstance(item_code, str) or not item_code.strip():
		raise _invalid_request("item_code", "Expected an Item code.")
	if uom is not None and (not isinstance(uom, str) or not uom.strip()):
		raise _invalid_request("uom", "Expected a UOM name.")
	if batch_no is not None and (not isinstance(batch_no, str) or not batch_no.strip()):
		raise _invalid_request("batch_no", "Expected a Batch number.")

	require_doc_permission("Item", "read")
	quantity = decimal_string(qty, field="qty")
	if quantity <= 0:
		raise _invalid_request("qty", "Must be > 0.")
	item_code = item_code.strip()
	batch_no = batch_no.strip() if batch_no else None
	if batch_no:
		_validate_batch(item_code, batch_no, profile.warehouse)

	resolved_customer = resolve_customer(profile, customer, walk_in_customer_name)
	context = frappe._dict(
		{
			"doctype": "POS Invoice",
			"item_code": item_code,
			"qty": quantity,
			"uom": uom.strip() if uom else None,
			"warehouse": profile.warehouse,
			"company": profile.company,
			"pos_profile": profile.name,
			"currency": profile.currency,
			"selling_price_list": profile.selling_price_list,
			"price_list": profile.selling_price_list,
			"price_list_currency": profile.currency,
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"customer": resolved_customer.name,
			"is_pos": 1,
			"batch_no": batch_no,
		}
	)
	details = get_item_details(context)
	if batch_no and Decimal(str(details.get("stock_qty") or 0)) > Decimal(
		str(get_batch_qty(batch_no, profile.warehouse, item_code).get("actual_batch_qty") or 0)
	):
		raise _invalid_batch(item_code, batch_no, "Batch has insufficient quantity.")
	selected_uom = details.get("uom") or uom or details.get("stock_uom")
	conversion_factor = details.get("conversion_factor")
	warnings = []
	if selected_uom and not conversion_factor and _is_non_stock_uom(item_code, selected_uom):
		warnings.append(MISSING_UOM_CONVERSION.copy())
	return {
		"item": {
			"item_code": details.item_code,
			"qty": _decimal(details.get("qty", quantity)),
			"uom": selected_uom,
			"conversion_factor": _decimal(conversion_factor) if conversion_factor else None,
			"warehouse": details.get("warehouse") or profile.warehouse,
			"available_qty": _decimal(details.get("actual_qty")),
			"price_list_rate": _decimal(details.get("price_list_rate")),
			"discount_percentage": _decimal(details.get("discount_percentage")),
			"rate": _decimal(details.get("rate")),
			"item_tax_template": details.get("item_tax_template"),
		},
		"warnings": warnings,
	}


def _validate_batch(item_code: str, batch_no: str, warehouse: str) -> None:
	batch = frappe.db.get_value(
		"Batch", batch_no, ["item", "expiry_date", "disabled"], as_dict=True
	)
	if not batch or batch.disabled:
		raise _invalid_batch(item_code, batch_no, "Batch is not available.")
	if batch.item != item_code:
		raise _invalid_batch(item_code, batch_no, "Batch belongs to a different Item.")
	if batch.expiry_date and getdate(batch.expiry_date) < getdate(today()):
		raise _invalid_batch(item_code, batch_no, "Batch is expired.")
	if not get_batch_qty(batch_no, warehouse, item_code).get("actual_batch_qty"):
		raise _invalid_batch(item_code, batch_no, "Batch is not available in the profile warehouse.")


def _is_non_stock_uom(item_code: str | None, uom: str) -> bool:
	if not item_code:
		return False
	stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
	return bool(stock_uom and stock_uom != uom)


def _decimal(value) -> str:
	return format(Decimal(str(value or 0)), "f")


def _invalid_request(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)


def _invalid_batch(item_code: str, batch_no: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_BATCH",
		"The selected batch is invalid.",
		status=422,
		details={"item_code": item_code, "batch_no": batch_no, "reason": reason},
	)
