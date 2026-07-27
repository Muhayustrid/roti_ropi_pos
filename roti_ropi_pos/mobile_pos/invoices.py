from __future__ import annotations

from decimal import Decimal

import frappe
from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability
from erpnext.stock.get_item_details import get_conversion_factor

from roti_ropi_pos.mobile_pos.authorization import (
	get_authorized_profile,
	require_doc_permission,
	require_pos_invoice_mode,
)
from roti_ropi_pos.mobile_pos.catalog import quote_item
from roti_ropi_pos.mobile_pos.customers import resolve_customer
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import MutationResult
from roti_ropi_pos.mobile_pos.sessions import get_current_opening


def submit_sale(payload: dict, transaction_id: str) -> MutationResult:
	"""Create one fully settled, authoritative POS Invoice."""
	profile = get_authorized_profile(payload["pos_profile"])
	require_pos_invoice_mode()
	if not get_current_opening(profile):
		raise MobilePOSAPIError(
			"NO_OPEN_SESSION",
			"No open POS session is available for this profile.",
			status=422,
			details={"pos_profile": profile.name},
		)
	require_doc_permission("POS Invoice", "create")
	require_doc_permission("POS Invoice", "submit")
	customer = resolve_customer(
		profile,
		payload.get("customer"),
		payload.get("walk_in_customer_name"),
	)
	require_doc_permission("Item", "read")
	invoice = frappe.new_doc("POS Invoice")
	invoice.is_pos = 1
	invoice.pos_profile = profile.name
	invoice.company = profile.company
	invoice.customer = customer.name
	invoice.custom_walk_in_customer_name = customer.custom_walk_in_customer_name
	invoice.custom_mobile_pos_transaction_id = transaction_id
	_validate_total_stock(profile, payload["items"])
	_append_items(invoice, profile, customer.name, payload["items"])
	invoice.set_missing_values()
	invoice.calculate_taxes_and_totals()
	_verify_accepted_total(invoice, payload["client_accepted_grand_total"])
	invoice.set("payments", [])
	_append_payments(invoice, profile, payload["payments"])
	invoice.set_paid_amount()
	invoice.set_account_for_mode_of_payment()
	invoice.set_outstanding_amount()
	_verify_fully_settled(invoice)
	invoice.insert()
	invoice.submit()
	return MutationResult(
		data={"sale": sale_detail(invoice)},
		reference_doctype="POS Invoice",
		reference_name=invoice.name,
	)


def _validate_total_stock(profile, items: list[dict]) -> None:
	requested = {}
	for row in items:
		stock_qty = row["qty"] * Decimal(
			str(get_conversion_factor(row["item_code"], row["uom"])["conversion_factor"])
		)
		components = (
			frappe.get_all(
				"Product Bundle Item",
				filters={"parent": row["item_code"]},
				fields=["item_code", "qty", "uom"],
			)
			if frappe.db.exists("Product Bundle", {"name": row["item_code"], "disabled": 0})
			else []
		)
		if components:
			for component in components:
				component_qty = stock_qty * Decimal(str(component.qty)) * Decimal(
					str(get_conversion_factor(component.item_code, component.uom)["conversion_factor"])
				)
				requested[component.item_code] = requested.get(component.item_code, Decimal(0)) + component_qty
		else:
			requested[row["item_code"]] = requested.get(row["item_code"], Decimal(0)) + stock_qty
	for item_code, requested_qty in requested.items():
		available, is_stock_item, allow_negative = get_stock_availability(item_code, profile.warehouse)
		if is_stock_item and not allow_negative and Decimal(str(available)) < requested_qty:
			raise MobilePOSAPIError(
				"INSUFFICIENT_STOCK",
				"The requested quantity is not available.",
				status=422,
				details={
					"item_code": item_code,
					"warehouse": profile.warehouse,
					"requested_qty": _decimal(requested_qty),
					"available_qty": _decimal(available),
				},
			)


def _append_items(invoice, profile, customer: str, items: list[dict]) -> None:
	for row in items:
		item = frappe.get_cached_value(
			"Item", row["item_code"], ["has_batch_no", "has_serial_no"], as_dict=True
		)
		if item.has_batch_no and not row.get("batch_no"):
			raise MobilePOSAPIError(
				"INVALID_BATCH",
				"The selected batch is invalid.",
				status=422,
				details={
					"item_code": row["item_code"],
					"batch_no": None,
					"reason": "batch_required",
				},
			)
		if item.has_serial_no and not row.get("serial_numbers"):
			raise _invalid_serial(row, "serial_numbers_required")
		if row.get("batch_no") and not item.has_batch_no:
			raise MobilePOSAPIError(
				"INVALID_BATCH",
				"The selected batch is invalid.",
				status=422,
				details={
					"item_code": row["item_code"],
					"batch_no": row["batch_no"],
					"reason": "item_not_batch_tracked",
				},
			)
		if row.get("serial_numbers") and not item.has_serial_no:
			raise _invalid_serial(row, "item_not_serialized")
		quoted = quote_item(
			profile,
			customer=customer,
			item_code=row["item_code"],
			qty=row["qty"],
			uom=row["uom"],
			batch_no=row.get("batch_no"),
		)["item"]
		if row.get("serial_numbers"):
			valid_serials = set(
				frappe.get_all(
					"Serial No",
					filters={
						"name": ["in", row["serial_numbers"]],
						"item_code": row["item_code"],
						"warehouse": profile.warehouse,
						"status": "Active",
					},
					pluck="name",
				)
			)
			if invalid := next(
				(serial for serial in row["serial_numbers"] if serial not in valid_serials), None
			):
				raise _invalid_serial(row, "not_available", serial_no=invalid)
			if Decimal(len(row["serial_numbers"])) != row["qty"] * Decimal(quoted["conversion_factor"]):
				raise _invalid_serial(row, "quantity_mismatch")
		available, is_stock_item, allow_negative = get_stock_availability(
			row["item_code"], profile.warehouse
		)
		requested = row["qty"] * Decimal(quoted["conversion_factor"])
		if is_stock_item and not allow_negative and Decimal(str(available)) < requested:
			raise MobilePOSAPIError(
				"INSUFFICIENT_STOCK",
				"The requested quantity is not available.",
				status=422,
				details={
					"item_code": row["item_code"],
					"warehouse": profile.warehouse,
					"requested_qty": _decimal(requested),
					"available_qty": _decimal(available),
				},
			)
		invoice.append(
			"items",
			{
				"item_code": row["item_code"],
				"qty": float(row["qty"]),
				"uom": row["uom"],
				"conversion_factor": quoted["conversion_factor"],
				"warehouse": quoted["warehouse"],
				"price_list_rate": quoted["price_list_rate"],
				"discount_percentage": quoted["discount_percentage"],
				"rate": quoted["rate"],
				"item_tax_template": quoted["item_tax_template"],
				"batch_no": row.get("batch_no") or None,
				"serial_no": "\n".join(row.get("serial_numbers", [])) or None,
				"use_serial_batch_fields": int(bool(row.get("batch_no") or row.get("serial_numbers"))),
			},
		)


def _append_payments(invoice, profile, payments: list[dict]) -> None:
	allowed_modes = {
		row.mode_of_payment
		for row in profile.payments
		if frappe.get_cached_value("Mode of Payment", row.mode_of_payment, "enabled")
	}
	seen = set()
	for row in payments:
		mode = row["mode_of_payment"]
		if mode not in allowed_modes:
			raise _invalid_payment(mode, "Payment mode is not configured for this POS Profile.")
		if mode in seen:
			raise _invalid_payment(mode, "Payment mode is duplicated.")
		seen.add(mode)
		invoice.append(
			"payments",
			{
				"mode_of_payment": mode,
				"amount": float(row["amount"]),
				"reference_no": row.get("reference_no") or None,
			},
		)


def _verify_accepted_total(invoice, accepted: Decimal) -> None:
	authoritative = Decimal(str(invoice.grand_total))
	if authoritative != accepted:
		raise MobilePOSAPIError(
			"PRICE_CHANGED",
			"The authoritative total differs from the accepted client quote.",
			status=422,
			details={
				"accepted_grand_total": _decimal(accepted),
				"authoritative_grand_total": _decimal(authoritative),
				"currency": invoice.currency,
				"items": [sale_item_dto(row) for row in invoice.items],
				"taxes": [sale_tax_dto(row) for row in invoice.taxes],
			},
		)


def _verify_fully_settled(invoice) -> None:
	if Decimal(str(invoice.outstanding_amount)) != Decimal("0"):
		raise _invalid_payment(None, "Invoice is not fully settled.")


def sale_summary(doc) -> dict:
	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"status": (doc.status or "").lower(),
		"customer": doc.customer,
		"walk_in_customer_name": doc.custom_walk_in_customer_name or None,
		"currency": doc.currency,
		"grand_total": _decimal(doc.grand_total),
		"paid_amount": _decimal(doc.paid_amount),
		"change_amount": _decimal(doc.change_amount),
		"posting_date": str(doc.posting_date),
		"posting_time": str(doc.posting_time),
	}


def sale_detail(doc) -> dict:
	return {
		"summary": sale_summary(doc),
		"items": [sale_item_dto(row) for row in doc.items],
		"taxes": [sale_tax_dto(row) for row in doc.taxes],
		"payments": [
			{
				"mode_of_payment": row.mode_of_payment,
				"amount": _decimal(row.amount),
				"reference_no": row.reference_no or None,
			}
			for row in doc.payments
		],
	}


def sale_item_dto(row) -> dict:
	return {
		"row_id": row.name or None,
		"item_code": row.item_code,
		"item_name": row.item_name,
		"qty": _decimal(row.qty),
		"uom": row.uom,
		"conversion_factor": _decimal(row.conversion_factor),
		"rate": _decimal(row.rate),
		"amount": _decimal(row.amount),
		"batch_no": row.batch_no or None,
		"serial_numbers": [value for value in (row.serial_no or "").split("\n") if value],
	}


def sale_tax_dto(row) -> dict:
	return {
		"description": row.description or "",
		"rate": _decimal(row.rate),
		"tax_amount": _decimal(row.tax_amount),
		"total": _decimal(row.total),
	}


def _invalid_serial(row: dict, reason: str, *, serial_no: str | None = None) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_SERIAL_NUMBER",
		"The selected serial number is invalid.",
		status=422,
		details={
			"item_code": row["item_code"],
			"serial_no": serial_no or next(iter(row["serial_numbers"]), None),
			"reason": reason,
		},
	)


def _invalid_payment(mode: str | None, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_PAYMENT",
		"Payment details are invalid.",
		status=422,
		details={"mode_of_payment": mode, "reason": reason},
	)


def _decimal(value) -> str:
	return format(Decimal(str(value or 0)), "f")
