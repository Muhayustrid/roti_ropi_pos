from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError


class TestCatalog(IntegrationTestCase):
	def test_item_dto_exposes_only_catalog_contract_fields(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import item_dto

		item = frappe._dict(
			item_code="CROISSANT",
			item_name="Croissant",
			description="Butter croissant",
			item_image="/files/croissant.png",
			uom="Nos",
			price_list_rate=15000,
			currency="IDR",
			actual_qty=18,
			valuation_rate=9999,
			item_defaults=[{"expense_account": "Internal"}],
		)

		self.assertEqual(
			item_dto(item),
			{
				"item_code": "CROISSANT",
				"item_name": "Croissant",
				"description": "Butter croissant",
				"image": "/files/croissant.png",
				"uom": "Nos",
				"price_list_rate": "15000",
				"currency": "IDR",
				"available_qty": "18",
			},
		)

	def test_item_dto_maps_core_exact_scan_dict(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import item_dto

		self.assertEqual(
			item_dto(
				{
					"item_code": "CROISSANT",
					"item_name": "Croissant",
					"description": "Butter croissant",
					"item_image": None,
					"uom": "Nos",
					"price_list_rate": 15000,
					"currency": "IDR",
					"actual_qty": 18,
				}
			),
			{
				"item_code": "CROISSANT",
				"item_name": "Croissant",
				"description": "Butter croissant",
				"image": None,
				"uom": "Nos",
				"price_list_rate": "15000",
				"currency": "IDR",
				"available_qty": "18",
			},
		)

	def test_search_uses_authorized_profile_and_returns_bounded_page(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = frappe._dict(
			name="POS-01", selling_price_list="Outlet Price", warehouse="Outlet Warehouse"
		)
		core_result = {
			"items": [
				frappe._dict(
					item_code="CROISSANT",
					item_name="Croissant",
					description="Butter croissant",
					item_image=None,
					uom="Nos",
					price_list_rate=Decimal("15000"),
					currency="IDR",
					actual_qty=18,
				),
				frappe._dict(
					item_code="DANISH",
					item_name="Danish",
					description="Danish pastry",
					item_image=None,
					uom="Nos",
					price_list_rate=Decimal("18000"),
					currency="IDR",
					actual_qty=9,
				),
			]
		}
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission") as permission,
			patch("roti_ropi_pos.mobile_pos.catalog.get_items", return_value=core_result) as core,
		):
			result = search_items(profile, q="cro", item_group="Pastry", start=2, limit=1)

		permission.assert_called_once_with("Item", "read")
		core.assert_called_once_with(2, 2, "Outlet Price", "Pastry", "POS-01", "cro")
		self.assertEqual(result["page"], {"start": 2, "limit": 1, "has_more": True})
		self.assertEqual([row["item_code"] for row in result["items"]], ["CROISSANT"])

	def test_search_rejects_invalid_pagination(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = frappe._dict(name="POS-01", selling_price_list="Outlet Price", warehouse="Outlet Warehouse")
		with self.assertRaises(MobilePOSAPIError) as error:
			search_items(profile, start=-1)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "start")

	def test_search_handles_core_empty_list_response(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = frappe._dict(name="POS-01", selling_price_list="Outlet Price", warehouse="Outlet Warehouse")
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog.get_items", return_value=[]),
		):
			result = search_items(profile)

		self.assertEqual(result, {"items": [], "page": {"start": 0, "limit": 20, "has_more": False}})

	def test_scan_uses_effective_override_and_reports_missing_uom_conversion(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import scan_value

		profile = frappe._dict(name="POS-01", warehouse="Outlet Warehouse")
		result = {
			"item_code": "CROISSANT-PACK",
			"batch_no": "BATCH-01",
			"uom": "Pack",
		}
		with (
			patch(
				"roti_ropi_pos.mobile_pos.catalog.frappe.override_whitelisted_method",
				return_value="effective.scanner",
			) as resolve,
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.get_attr", return_value=lambda value, ctx: result),
			patch("roti_ropi_pos.mobile_pos.catalog._is_non_stock_uom", return_value=True),
		):
			response = scan_value(profile, "BATCH-01")

		resolve.assert_called_once_with("erpnext.stock.utils.scan_barcode")
		self.assertEqual(response["scan"]["item_code"], "CROISSANT-PACK")
		self.assertEqual(response["warnings"][0]["code"], "MISSING_UOM_CONVERSION")

	def test_scan_no_match_is_resource_not_found(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import scan_value

		profile = frappe._dict(name="POS-01", warehouse="Outlet Warehouse")
		with (
			patch(
				"roti_ropi_pos.mobile_pos.catalog.frappe.override_whitelisted_method",
				return_value="effective.scanner",
			),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.get_attr", return_value=lambda value, ctx: {}),
			self.assertRaises(MobilePOSAPIError) as error,
		):
			scan_value(profile, "NO-MATCH")
		self.assertEqual(error.exception.code, "RESOURCE_NOT_FOUND")

	def test_quote_uses_server_owned_context_and_customer_resolution(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import quote_item
		from roti_ropi_pos.mobile_pos.customers import ResolvedCustomer

		profile = frappe._dict(
			name="POS-01",
			company="Roti Ropi",
			warehouse="Outlet Warehouse",
			selling_price_list="Outlet Price",
			currency="IDR",
		)
		details = frappe._dict(
			item_code="CROISSANT",
			qty=Decimal("2"),
			uom="Nos",
			conversion_factor=1,
			warehouse="Outlet Warehouse",
			actual_qty=18,
			price_list_rate=Decimal("15000"),
			discount_percentage=0,
			rate=Decimal("15000"),
			item_tax_template="VAT 10% - RR",
		)
		with (
			patch(
				"roti_ropi_pos.mobile_pos.catalog.resolve_customer",
				return_value=ResolvedCustomer("Walk In Customer", None),
			) as resolve,
			patch("roti_ropi_pos.mobile_pos.catalog.get_item_details", return_value=details) as get_details,
		):
			response = quote_item(profile, item_code="CROISSANT", qty="2")

		resolve.assert_called_once_with(profile, None, None)
		context = get_details.call_args.args[0]
		self.assertEqual(context.company, "Roti Ropi")
		self.assertEqual(context.pos_profile, "POS-01")
		self.assertEqual(context.warehouse, "Outlet Warehouse")
		self.assertEqual(context.selling_price_list, "Outlet Price")
		self.assertEqual(context.customer, "Walk In Customer")
		self.assertEqual(response["item"]["rate"], "15000")
		self.assertEqual(response["warnings"], [])

	def test_quote_rejects_expired_batch(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import quote_item

		profile = frappe._dict(name="POS-01", warehouse="Outlet Warehouse")
		with patch("roti_ropi_pos.mobile_pos.catalog._validate_batch") as validate:
			validate.side_effect = MobilePOSAPIError(
				"INVALID_BATCH", "The batch is expired.", status=422, details={"item_code": "CROISSANT", "batch_no": "BATCH-01", "reason": "Expired."}
			)
			with self.assertRaises(MobilePOSAPIError) as error:
				quote_item(profile, item_code="CROISSANT", qty="2", batch_no="BATCH-01")
		self.assertEqual(error.exception.code, "INVALID_BATCH")

	def test_batch_without_warehouse_quantity_is_invalid(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import _validate_batch

		batch = frappe._dict(item="CROISSANT", expiry_date=None, disabled=0)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.db.get_value", return_value=batch),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.get_batch_qty",
				return_value={"actual_batch_qty": 0},
			),
			self.assertRaises(MobilePOSAPIError) as error,
		):
			_validate_batch("CROISSANT", "BATCH-01", "Outlet Warehouse")
		self.assertEqual(error.exception.code, "INVALID_BATCH")
		self.assertIn("warehouse", error.exception.details["reason"].lower())

	def test_quote_rejects_batch_with_less_than_authoritative_stock_qty(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import quote_item
		from roti_ropi_pos.mobile_pos.customers import ResolvedCustomer

		profile = frappe._dict(
			name="POS-01",
			company="Roti Ropi",
			warehouse="Outlet Warehouse",
			selling_price_list="Outlet Price",
			currency="IDR",
		)
		details = frappe._dict(item_code="CROISSANT", stock_qty=2, uom="Nos", qty=2)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._validate_batch"),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.resolve_customer",
				return_value=ResolvedCustomer("Walk In Customer", None),
			),
			patch("roti_ropi_pos.mobile_pos.catalog.get_item_details", return_value=details),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.get_batch_qty",
				return_value={"actual_batch_qty": 1},
			),
			self.assertRaises(MobilePOSAPIError) as error,
		):
			quote_item(profile, item_code="CROISSANT", qty="2", batch_no="BATCH-01")
		self.assertEqual(error.exception.code, "INVALID_BATCH")
		self.assertIn("insufficient", error.exception.details["reason"].lower())

	def test_scan_requires_item_read_permission(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import scan_value

		profile = frappe._dict(name="POS-01", warehouse="Outlet Warehouse")
		with patch(
			"roti_ropi_pos.mobile_pos.catalog.require_doc_permission",
			side_effect=MobilePOSAPIError("PERMISSION_DENIED", "Denied.", status=403),
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				scan_value(profile, "BATCH-01")
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")

	def test_quote_requires_item_read_permission(self) -> None:
		from roti_ropi_pos.mobile_pos.catalog import quote_item

		profile = frappe._dict(name="POS-01", warehouse="Outlet Warehouse")
		with patch(
			"roti_ropi_pos.mobile_pos.catalog.require_doc_permission",
			side_effect=MobilePOSAPIError("PERMISSION_DENIED", "Denied.", status=403),
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				quote_item(profile, item_code="CROISSANT", qty="2")
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")

	def test_scan_barcode_override_resolves_to_bakery(self) -> None:
		method_path = frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode")
		self.assertEqual(
			method_path,
			"bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode",
		)
