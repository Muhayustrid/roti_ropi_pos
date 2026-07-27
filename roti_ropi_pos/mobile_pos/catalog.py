from __future__ import annotations

from decimal import Decimal

import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability
from erpnext.accounts.doctype.pos_profile.pos_profile import get_item_groups
from erpnext.selling.page.point_of_sale.point_of_sale import get_items
from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.get_item_details import get_item_details

from roti_ropi_pos.mobile_pos.authorization import require_doc_permission
from roti_ropi_pos.mobile_pos.customers import resolve_customer
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

SCANNER_METHOD = "erpnext.stock.utils.scan_barcode"
MISSING_UOM_CONVERSION = {
	"code": "MISSING_UOM_CONVERSION",
	"message": "The selected UOM has no conversion factor.",
}
# ponytail: bounded security post-filtering; use a permission-aware core query when available.
MAX_CATALOG_CORE_PAGES = 10


def search_items(
	profile, q: str = "", item_group: str | None = None, start: int = 0, limit: int = 20
) -> dict:
	"""Return permission-filtered POS Item display snapshots."""
	require_doc_permission("Item", "read")
	limit = min(limit, 100)
	groups = _allowed_item_groups(profile)
	if item_group and item_group not in groups:
		raise _not_found("item_group", item_group)
	visible = _visible_item_codes()
	page_length = limit + 1
	raw_start = 0
	rows = []
	target = start + limit + 1
	core_may_have_more = False
	for _ in range(MAX_CATALOG_CORE_PAGES):
		if len(rows) >= target:
			break
		result = get_items(
			start=raw_start,
			page_length=page_length,
			price_list=profile.selling_price_list,
			item_group=item_group or "",
			pos_profile=profile.name,
			search_term=q,
		)
		page = result.get("items", []) if isinstance(result, dict) else result
		rows.extend(
			row
			for row in page
			if _row_value(row, "item_group") in groups and _row_value(row, "item_code") in visible
		)
		if len(page) < page_length:
			break
		raw_start += len(page)
	else:
		core_may_have_more = True
	page_rows = rows[start : start + limit + 1]
	return {
		"items": [_catalog_dto(row, profile) for row in page_rows[:limit]],
		"page": {
			"start": start,
			"limit": limit,
			"has_more": len(page_rows) > limit or core_may_have_more,
		},
	}


def scan_value(profile, value: str) -> dict:
	"""Resolve barcode through current Frappe override and project safe scan data."""
	require_doc_permission("Item", "read")
	method_path = frappe.override_whitelisted_method(SCANNER_METHOD)
	scanner = frappe.get_attr(method_path)
	old_mute_messages = frappe.flags.mute_messages
	frappe.flags.mute_messages = True
	try:
		result = scanner(
			value,
			{
				"doctype": "POS Invoice",
				"company": profile.company,
				"warehouse": profile.warehouse,
				"set_warehouse": profile.warehouse,
			},
		)
	finally:
		frappe.flags.mute_messages = old_mute_messages
	item_code = result.get("item_code") if result else None
	if not item_code:
		raise _not_found("scan_value", value)
	item = _get_visible_item(item_code)
	_require_allowed_item(item, profile)
	uom = result.get("uom") or item.stock_uom
	factor = result.get("conversion_factor")
	if not factor:
		factor = _item_conversion_factor(item_code, uom)
	warnings = []
	if uom != item.stock_uom and not factor:
		warnings.append(MISSING_UOM_CONVERSION)
	return {
		"scan": {
			"item_code": item_code,
			"barcode": result.get("barcode") or None,
			"batch_no": result.get("batch_no") or None,
			"serial_no": result.get("serial_no") or None,
			"uom": uom,
			"conversion_factor": _decimal(factor) if factor else None,
			"warehouse": profile.warehouse,
		},
		"warnings": warnings,
	}


def quote_item(
	profile, *, customer: str | None, item_code: str, qty: Decimal, uom: str, batch_no: str | None = None
) -> dict:
	"""Return ERPNext-calculated quote snapshot after explicit scope checks."""
	require_doc_permission("Item", "read")
	item = _get_visible_item(item_code)
	_require_allowed_item(item, profile)
	resolved = resolve_customer(profile, customer)
	if batch_no:
		_validate_batch(batch_no, item, profile)
	ctx = frappe._dict(
		{
			"doctype": "POS Invoice",
			"item_code": item_code,
			"company": profile.company,
			"customer": resolved.name,
			"pos_profile": profile.name,
			"is_pos": 1,
			"warehouse": profile.warehouse,
			"set_warehouse": profile.warehouse,
			"selling_price_list": profile.selling_price_list,
			"price_list": profile.selling_price_list,
			"currency": profile.currency,
			"price_list_currency": profile.currency,
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"transaction_date": frappe.utils.today(),
			"posting_date": frappe.utils.today(),
			"qty": float(qty),
			"uom": uom,
			"batch_no": batch_no or "",
		}
	)
	details = get_item_details(ctx, doc={"doctype": "POS Invoice", **ctx})
	factor = _item_conversion_factor(item_code, uom)
	warnings = []
	if uom != item.stock_uom and not factor:
		warnings.append(MISSING_UOM_CONVERSION)
	factor = factor or details.get("conversion_factor") or 1
	available_qty, _, _ = get_stock_availability(item_code, profile.warehouse)
	price_list_rate = details.get("price_list_rate") or 0
	discount_percentage = details.get("discount_percentage") or 0
	rate = details.get("rate")
	if rate in (None, 0) and price_list_rate:
		rate = Decimal(str(price_list_rate)) * (Decimal("1") - Decimal(str(discount_percentage)) / 100)
	return {
		"item": {
			"item_code": details.item_code,
			"qty": _decimal(qty),
			"uom": details.uom,
			"conversion_factor": _decimal(factor),
			"warehouse": profile.warehouse,
			"available_qty": _decimal(Decimal(str(available_qty)) / Decimal(str(factor))),
			"price_list_rate": _decimal(price_list_rate),
			"discount_percentage": _decimal(discount_percentage),
			"rate": _decimal(rate),
			"item_tax_template": details.get("item_tax_template") or None,
		},
		"warnings": warnings,
	}


def _allowed_item_groups(profile) -> set[str]:
	return {group.strip("'") for group in get_item_groups(profile.name)}


def _visible_item_codes() -> set[str]:
	return set(frappe.get_list("Item", pluck="name"))


def _get_visible_item(item_code: str):
	try:
		item = frappe.get_doc("Item", item_code)
	except frappe.DoesNotExistError as error:
		raise _not_found("item", item_code) from error
	if not frappe.has_permission("Item", ptype="read", doc=item):
		raise _not_found("item", item_code)
	return item


def _require_allowed_item(item, profile) -> None:
	if (
		item.item_group not in _allowed_item_groups(profile)
		or item.disabled
		or not item.is_sales_item
		or item.has_variants
		or item.is_fixed_asset
	):
		raise _not_found("item", item.name)


def _item_conversion_factor(item_code: str, uom: str) -> Decimal | None:
	factor = frappe.db.get_value(
		"UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor"
	)
	return Decimal(str(factor)) if factor and Decimal(str(factor)) > 0 else None


def _validate_batch(batch_no: str, item, profile) -> None:
	try:
		batch = frappe.get_doc("Batch", batch_no)
	except frappe.DoesNotExistError as error:
		raise _invalid_batch(item.name, batch_no, "not_found") from error
	if batch.item != item.name:
		raise _invalid_batch(item.name, batch_no, "wrong_item")
	if batch.disabled:
		raise _invalid_batch(item.name, batch_no, "not_found")
	if batch.expiry_date and frappe.utils.getdate(batch.expiry_date) < frappe.utils.getdate():
		raise _invalid_batch(item.name, batch_no, "expired")
	if not get_batch_qty(batch_no=batch_no, warehouse=profile.warehouse, item_code=item.name):
		raise _invalid_batch(item.name, batch_no, "wrong_warehouse")


def _catalog_dto(row, profile) -> dict:
	return {
		"item_code": _row_value(row, "item_code"),
		"item_name": _row_value(row, "item_name"),
		"description": _row_value(row, "description") or "",
		"image": _row_value(row, "item_image") or None,
		"uom": _row_value(row, "uom") or _row_value(row, "stock_uom"),
		"price_list_rate": _decimal(_row_value(row, "price_list_rate")),
		"currency": _row_value(row, "currency") or profile.currency,
		"available_qty": _decimal(_row_value(row, "actual_qty")),
	}


def _row_value(row, key):
	return row.get(key) if isinstance(row, dict) else getattr(row, key, None)


def _decimal(value) -> str:
	return format(Decimal(str(value or 0)), "f")


def _not_found(resource_type: str, name: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"RESOURCE_NOT_FOUND",
		"The requested resource was not found.",
		status=404,
		details={"resource_type": resource_type, "name": name},
	)


def _invalid_batch(item_code: str, batch_no: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_BATCH",
		"The selected batch is invalid.",
		status=422,
		details={"item_code": item_code, "batch_no": batch_no, "reason": reason},
	)
