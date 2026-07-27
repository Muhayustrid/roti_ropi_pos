from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError


class TestCatalogContracts(IntegrationTestCase):
	def test_effective_scanner_is_bakery_override(self):
		self.assertEqual(
			frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode"),
			"bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode",
		)
		scanner = frappe.get_attr(frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode"))
		self.assertIn(scanner, frappe.whitelisted)
		parameters = inspect.signature(scanner).parameters
		self.assertIn("search_value", parameters)
		self.assertIn("ctx", parameters)

	def test_search_uses_profile_values_and_returns_safe_decimal_dto(self):
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		row = {
			"item_code": "ITEM-001",
			"item_name": "Visible Item",
			"description": None,
			"item_image": None,
			"stock_uom": "Nos",
			"uom": "Nos",
			"price_list_rate": 25000,
			"actual_qty": 3,
			"currency": "IDR",
			"item_group": "Allowed",
		}
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._visible_item_codes", return_value={"ITEM-001"}),
			patch("roti_ropi_pos.mobile_pos.catalog.get_items", return_value={"items": [row]}) as get_items,
		):
			result = search_items(profile, limit=20)

		get_items.assert_called_once_with(
			start=0,
			page_length=21,
			price_list="PG-TEST",
			item_group="",
			pos_profile="POS-TEST",
			search_term="",
		)
		self.assertEqual(
			result,
			{
				"items": [
					{
						"item_code": "ITEM-001",
						"item_name": "Visible Item",
						"description": "",
						"image": None,
						"uom": "Nos",
						"price_list_rate": "25000",
						"currency": "IDR",
						"available_qty": "3",
					}
				],
				"page": {"start": 0, "limit": 20, "has_more": False},
			},
		)

	def test_search_scans_next_core_page_after_scope_filter(self):
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		forbidden = {"item_code": "FORBIDDEN", "item_group": "Forbidden"}
		visible = {
			"item_code": "VISIBLE",
			"item_group": "Allowed",
			"item_name": "Visible",
			"description": "",
			"uom": "Nos",
			"price_list_rate": 1,
			"actual_qty": 1,
		}
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._visible_item_codes", return_value={"VISIBLE"}),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.get_items",
				side_effect=[{"items": [forbidden, forbidden]}, {"items": [visible]}],
			),
		):
			result = search_items(profile, limit=1)

		self.assertEqual([item["item_code"] for item in result["items"]], ["VISIBLE"])
		self.assertFalse(result["page"]["has_more"])

	def test_search_applies_offset_after_scope_filter(self):
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		hidden = {"item_code": "HIDDEN", "item_group": "Forbidden"}
		first = {
			"item_code": "FIRST",
			"item_group": "Allowed",
			"item_name": "First",
			"uom": "Nos",
			"price_list_rate": 1,
			"actual_qty": 1,
		}
		second = {**first, "item_code": "SECOND", "item_name": "Second"}
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._visible_item_codes", return_value={"FIRST", "SECOND"}),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.get_items",
				return_value={"items": [hidden, first, second]},
			),
		):
			result = search_items(profile, start=1, limit=1)

		self.assertEqual([item["item_code"] for item in result["items"]], ["SECOND"])

	def test_search_finds_later_logical_offset_with_followup_page(self):
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		first_page = [{"item_code": f"FIRST-{index}", "item_group": "Allowed"} for index in range(2)]
		second_page = [
			{
				"item_code": f"ITEM-{index}",
				"item_group": "Allowed",
				"item_name": f"Item {index}",
				"uom": "Nos",
				"price_list_rate": 1,
				"actual_qty": 1,
			}
			for index in range(100)
		]
		visible = {row["item_code"] for row in first_page + second_page}
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._visible_item_codes", return_value=visible),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.get_items",
				side_effect=[{"items": first_page}, {"items": second_page}],
			) as get_items,
		):
			result = search_items(profile, start=20, limit=1)

		self.assertEqual(result["items"][0]["item_code"], "ITEM-18")
		self.assertEqual(get_items.call_args_list[1].kwargs["page_length"], 100)

	def test_search_bounds_filtered_core_page_scans(self):
		from roti_ropi_pos.mobile_pos.catalog import MAX_CATALOG_CORE_PAGES, search_items

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		row = {"item_code": "HIDDEN", "item_group": "Forbidden"}

		def full_page(*, page_length, **kwargs):
			return {"items": [row] * page_length}

		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._visible_item_codes", return_value=set()),
			patch("roti_ropi_pos.mobile_pos.catalog.get_items", side_effect=full_page) as get_items,
		):
			result = search_items(profile, limit=1)

		self.assertEqual(get_items.call_count, MAX_CATALOG_CORE_PAGES)
		self.assertTrue(result["page"]["has_more"])

	def test_search_rejects_unknown_or_unauthorized_group_without_disclosure(self):
		from roti_ropi_pos.mobile_pos.catalog import search_items

		profile = SimpleNamespace(name="POS-TEST", company="Test Company", warehouse="Test Warehouse")
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
		):
			with self.assertRaises(MobilePOSAPIError) as raised:
				search_items(profile, item_group="Forbidden")
		self.assertEqual(raised.exception.code, "RESOURCE_NOT_FOUND")
		self.assertEqual(raised.exception.details, {"resource_type": "item_group", "name": "Forbidden"})

	def test_scan_uses_effective_override_and_warns_for_missing_item_conversion(self):
		from roti_ropi_pos.mobile_pos.catalog import scan_value

		profile = SimpleNamespace(name="POS-TEST", company="Test Company", warehouse="Test Warehouse")
		item = SimpleNamespace(
			name="ITEM-001",
			item_group="Allowed",
			disabled=0,
			is_sales_item=1,
			has_variants=0,
			is_fixed_asset=0,
			stock_uom="Nos",
		)

		def scanner(value, context):
			return {"item_code": "ITEM-001", "batch_no": "BATCH-001", "uom": "Box"}

		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._get_visible_item", return_value=item),
			patch("roti_ropi_pos.mobile_pos.catalog._item_conversion_factor", return_value=None),
			patch("frappe.override_whitelisted_method", return_value="test.scanner"),
			patch("frappe.get_attr", return_value=scanner),
		):
			result = scan_value(profile, "BATCH-001")
		self.assertEqual(result["scan"]["warehouse"], "Test Warehouse")
		self.assertIsNone(result["scan"]["conversion_factor"])
		self.assertEqual(
			result["warnings"],
			[{"code": "MISSING_UOM_CONVERSION", "message": "The selected UOM has no conversion factor."}],
		)

	def test_catalog_routes_and_methods_are_registered(self):
		from roti_ropi_pos.api.v1 import catalog as catalog_api
		from roti_ropi_pos.mobile_pos.auth_hook import MOBILE_POS_PATHS

		self.assertEqual(
			{
				"/api/method/roti_ropi_pos.api.v1.catalog.search",
				"/api/method/roti_ropi_pos.api.v1.catalog.scan",
				"/api/method/roti_ropi_pos.api.v1.catalog.quote_item",
			}.difference(MOBILE_POS_PATHS),
			set(),
		)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[catalog_api.search], ["GET"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[catalog_api.scan], ["POST"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[catalog_api.quote_item], ["POST"])

	def test_quote_warns_when_erpnext_falls_back_to_one_for_missing_uom(self):
		from roti_ropi_pos.mobile_pos.catalog import MISSING_UOM_CONVERSION, quote_item

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		item = SimpleNamespace(
			name="ITEM-001",
			item_group="Allowed",
			disabled=0,
			is_sales_item=1,
			has_variants=0,
			is_fixed_asset=0,
			stock_uom="Nos",
		)
		details = frappe._dict(
			item_code="ITEM-001",
			uom="Carton",
			conversion_factor=1,
			price_list_rate=10,
			discount_percentage=0,
			rate=10,
		)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._get_visible_item", return_value=item),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.resolve_customer",
				return_value=SimpleNamespace(name="CUST-001"),
			),
			patch("roti_ropi_pos.mobile_pos.catalog.get_item_details", return_value=details),
			patch("roti_ropi_pos.mobile_pos.catalog._has_effective_conversion", return_value=False),
			patch("roti_ropi_pos.mobile_pos.catalog.get_stock_availability", return_value=(12, True, False)),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.utils.today", return_value="2026-07-27"),
		):
			result = quote_item(profile, customer=None, item_code="ITEM-001", qty=Decimal("1"), uom="Carton")

		self.assertEqual(result["warnings"], [MISSING_UOM_CONVERSION])

	def test_quote_uses_effective_erpnext_uom_factor_without_warning(self):
		from roti_ropi_pos.mobile_pos.catalog import quote_item

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		item = SimpleNamespace(
			name="ITEM-001",
			item_group="Allowed",
			disabled=0,
			is_sales_item=1,
			has_variants=0,
			is_fixed_asset=0,
			stock_uom="Nos",
		)
		details = frappe._dict(
			item_code="ITEM-001",
			uom="Box",
			conversion_factor=6,
			price_list_rate=10,
			discount_percentage=0,
			rate=10,
		)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._get_visible_item", return_value=item),
			patch(
				"roti_ropi_pos.mobile_pos.catalog.resolve_customer",
				return_value=SimpleNamespace(name="CUST-001"),
			),
			patch("roti_ropi_pos.mobile_pos.catalog.get_item_details", return_value=details),
			patch("roti_ropi_pos.mobile_pos.catalog._has_effective_conversion", return_value=True),
			patch("roti_ropi_pos.mobile_pos.catalog.get_stock_availability", return_value=(12, True, False)),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.utils.today", return_value="2026-07-27"),
		):
			result = quote_item(profile, customer=None, item_code="ITEM-001", qty=Decimal("1"), uom="Box")

		self.assertEqual(result["item"]["conversion_factor"], "6")
		self.assertEqual(result["warnings"], [])

	def test_quote_rejects_insufficient_batch_quantity(self):
		from roti_ropi_pos.mobile_pos.catalog import quote_item

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		item = SimpleNamespace(
			name="ITEM-001",
			item_group="Allowed",
			disabled=0,
			is_sales_item=1,
			has_variants=0,
			is_fixed_asset=0,
			stock_uom="Nos",
		)
		batch = SimpleNamespace(name="BATCH-001", item="ITEM-001", disabled=0, expiry_date=None)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._get_visible_item", return_value=item),
			patch("roti_ropi_pos.mobile_pos.catalog.resolve_customer"),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.get_doc", return_value=batch),
			patch("roti_ropi_pos.mobile_pos.catalog.get_item_details", return_value={"conversion_factor": 1}),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.utils.today", return_value="2026-07-27"),
			patch("roti_ropi_pos.mobile_pos.catalog.get_batch_qty", return_value=Decimal("1")),
		):
			with self.assertRaises(MobilePOSAPIError) as raised:
				quote_item(
					profile,
					customer=None,
					item_code="ITEM-001",
					qty=Decimal("2"),
					uom="Nos",
					batch_no="BATCH-001",
				)
		self.assertEqual(raised.exception.code, "INVALID_BATCH")
		self.assertEqual(raised.exception.details["reason"], "insufficient")

	def test_quote_validates_expired_batch_before_authoritative_quote(self):
		from roti_ropi_pos.mobile_pos.catalog import quote_item

		profile = SimpleNamespace(
			name="POS-TEST",
			company="Test Company",
			warehouse="Test Warehouse",
			selling_price_list="PG-TEST",
			currency="IDR",
		)
		item = SimpleNamespace(
			name="ITEM-001",
			item_group="Allowed",
			disabled=0,
			is_sales_item=1,
			has_variants=0,
			is_fixed_asset=0,
			stock_uom="Nos",
			has_batch_no=1,
		)
		batch = SimpleNamespace(
			name="BATCH-001",
			item="ITEM-001",
			disabled=0,
			expiry_date=frappe.utils.add_days(frappe.utils.today(), -1),
		)
		with (
			patch("roti_ropi_pos.mobile_pos.catalog.require_doc_permission"),
			patch("roti_ropi_pos.mobile_pos.catalog._allowed_item_groups", return_value={"Allowed"}),
			patch("roti_ropi_pos.mobile_pos.catalog._get_visible_item", return_value=item),
			patch("roti_ropi_pos.mobile_pos.catalog.resolve_customer"),
			patch("roti_ropi_pos.mobile_pos.catalog.frappe.get_doc", return_value=batch),
		):
			with self.assertRaises(MobilePOSAPIError) as raised:
				quote_item(
					profile,
					customer=None,
					item_code="ITEM-001",
					qty=Decimal("1"),
					uom="Nos",
					batch_no="BATCH-001",
				)
		self.assertEqual(raised.exception.code, "INVALID_BATCH")
		self.assertEqual(
			raised.exception.details, {"item_code": "ITEM-001", "batch_no": "BATCH-001", "reason": "expired"}
		)
