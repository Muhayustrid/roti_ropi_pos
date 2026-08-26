"""RED → GREEN tests for Task B: authoritative promotion-aware cart quote."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from roti_ropi_pos.api.v1.sales import _parse_quote_payload
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.invoices import build_sale_quote
from roti_ropi_pos.tests.helpers import (
	clear_fake_request,
	make_cashier,
	make_pos_profile,
)

HAS_SELLING = "selling_additional" in frappe.get_installed_apps()


def _get_default_mode_of_payment(company: str) -> str:
	mop_list = frappe.get_all(
		"Mode of Payment", filters={"enabled": 1}, pluck="name", order_by="creation asc"
	)
	for mop_name in mop_list:
		if frappe.db.exists("Mode of Payment Account", {"parent": mop_name, "company": company}):
			return mop_name
	mop_name = f"_Test MOP {company[:10]}"
	if frappe.db.exists("Mode of Payment", mop_name):
		return mop_name
	default_account = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": ("in", ["Cash", "Bank"]), "is_group": 0},
		"name",
		order_by="creation asc",
	) or frappe.db.get_value("Account", {"company": company, "is_group": 0}, "name", order_by="creation asc")
	accounts = []
	if default_account:
		accounts.append({"company": company, "default_account": default_account})
	mop = frappe.get_doc(
		{"doctype": "Mode of Payment", "mode_of_payment": mop_name, "enabled": 1, "accounts": accounts}
	)
	mop.insert(ignore_permissions=True)
	return mop.name


def _get_default_account(company: str, account_type: str = "Expense") -> str:
	if account_type == "Expense":
		existing = frappe.db.get_value(
			"Account",
			{
				"company": company,
				"account_type": (
					"in",
					["Expense", "Expense Account", "Indirect Expense", "Cost of Goods Sold"],
				),
				"is_group": 0,
			},
			"name",
			order_by="creation asc",
		) or frappe.db.get_value(
			"Account",
			{"company": company, "root_type": "Expense", "is_group": 0},
			"name",
			order_by="creation asc",
		)
	else:
		existing = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": account_type, "is_group": 0},
			"name",
			order_by="creation asc",
		)
	if existing:
		return existing
	existing = frappe.db.get_value(
		"Account", {"company": company, "is_group": 0}, "name", order_by="creation asc"
	)
	return existing


def _get_default_cost_center(company: str) -> str:
	existing = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0}, "name", order_by="creation asc"
	)
	if existing:
		return existing
	parent_cc = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 1}, "name", order_by="creation asc"
	)
	doc = frappe.get_doc(
		{
			"doctype": "Cost Center",
			"cost_center_name": f"_Test CC {company[:10]}",
			"company": company,
			"is_group": 0,
			"parent_cost_center": parent_cc,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _suffix():
	return uuid.uuid4().hex[:8]


class TestQuoteCartPromotions(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		if not HAS_SELLING:
			self.skipTest("selling_additional not installed")
		self.suffix = _suffix()
		frappe.set_user("Administrator")
		self._setup_org()
		self._setup_items()
		self._setup_profile_and_customer()
		self.cashier = make_cashier(f"quote-{self.suffix}@rotiropi.test")
		profile = frappe.get_doc("POS Profile", self.pos_profile_name)
		profile.append("applicable_for_users", {"user": self.cashier, "default": 1})
		profile.save(ignore_permissions=True)
		self._ensure_opening()
		self._setup_promotion()
		frappe.set_user(self.cashier)

	def tearDown(self):
		clear_fake_request()
		frappe.set_user("Administrator")
		super().tearDown()

	# --- org fixtures ---
	def _make_company(self, prefix, abbr_tag, is_group=0, parent=None):
		company_name = f"{prefix} {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company_name,
				"abbr": f"{self.suffix.upper()[:6]}{abbr_tag}",
				"is_group": is_group,
				"parent_company": parent,
				"default_currency": "IDR",
				"country": "Indonesia",
			}
		).insert(ignore_permissions=True)
		return company_name

	def _make_warehouse(self, prefix, company):
		return (
			frappe.get_doc(
				{"doctype": "Warehouse", "warehouse_name": f"{prefix} {self.suffix}", "company": company}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _setup_org(self):
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "name": "Transit"}).insert(ignore_permissions=True)
		if not frappe.db.exists("Fiscal Year", "2026"):
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": "2026",
					"year_start_date": "2026-01-01",
					"year_end_date": "2026-12-31",
				}
			).insert(ignore_permissions=True)
		self.root_company = self._make_company("_Test Quote Root Co", "R", is_group=1)
		self.outlet_company = self._make_company("_Test Quote Outlet Co", "O", parent=self.root_company)
		self.outlet_warehouse = self._make_warehouse("_Test Quote Outlet WH", self.outlet_company)

	def _make_item(self, code, stock):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": "All Item Groups",
				"is_stock_item": stock,
				"is_sales_item": 1,
				"stock_uom": "Nos",
			}
		).insert(ignore_permissions=True)
		return code

	def _setup_items(self):
		self.regular_item = f"_Test Regular Item {self.suffix}"
		self._make_item(self.regular_item, 1)
		# stock and price for regular
		from roti_ropi_pos.tests.helpers import ensure_pos_availability

		ensure_pos_availability(self.regular_item, self.outlet_warehouse, 100)
		if not frappe.db.exists(
			"Item Price", {"item_code": self.regular_item, "price_list": "Standard Selling"}
		):
			if not frappe.db.exists("Price List", "Standard Selling"):
				frappe.get_doc(
					{
						"doctype": "Price List",
						"price_list_name": "Standard Selling",
						"selling": 1,
						"currency": "IDR",
					}
				).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": self.regular_item,
					"price_list": "Standard Selling",
					"selling": 1,
					"price_list_rate": 15000,
				}
			).insert(ignore_permissions=True)
		self.parent_item = f"_Test Quote Parent {self.suffix}"
		self.comp_item = f"_Test Quote Comp {self.suffix}"
		self.opt_item = f"_Test Quote Opt {self.suffix}"
		for code, stock in [(self.parent_item, 0), (self.comp_item, 1), (self.opt_item, 1)]:
			self._make_item(code, stock)
		ensure_pos_availability(self.comp_item, self.outlet_warehouse, 50)
		ensure_pos_availability(self.opt_item, self.outlet_warehouse, 50)

	def _setup_profile_and_customer(self):
		self.customer_name = f"_Test Quote Customer {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self.customer_name,
				"customer_group": "Individual",
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		if not frappe.db.exists("Price List", "Standard Selling"):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": "Standard Selling",
					"selling": 1,
					"currency": "IDR",
				}
			).insert(ignore_permissions=True)

		self.mop_name = _get_default_mode_of_payment(self.outlet_company)
		write_off = _get_default_account(self.outlet_company, "Expense")
		cc = _get_default_cost_center(self.outlet_company)
		income = (
			frappe.db.get_value(
				"Account",
				{"company": self.outlet_company, "root_type": "Income", "is_group": 0},
				"name",
				order_by="creation asc",
			)
			or write_off
		)
		self.pos_profile_name = f"_Test Quote POS {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": self.pos_profile_name,
				"company": self.outlet_company,
				"warehouse": self.outlet_warehouse,
				"customer": self.customer_name,
				"currency": "IDR",
				"selling_price_list": "Standard Selling",
				"payments": [{"mode_of_payment": self.mop_name, "default": 1}],
				"write_off_account": write_off,
				"write_off_cost_center": cc,
				"income_account": income,
				"expense_account": write_off,
				"cost_center": cc,
				"write_off_limit": 1.0,
				"item_groups": [{"item_group": "All Item Groups"}],
			}
		).insert(ignore_permissions=True)
		self.profile = self.pos_profile_name

	def _ensure_opening(self):
		from roti_ropi_pos.tests.helpers import make_opening_entry

		make_opening_entry(
			user=self.cashier,
			company=self.outlet_company,
			pos_profile=self.pos_profile_name,
			period_start_date=nowdate(),
			posting_date=nowdate(),
		)

	def _setup_promotion(self):
		self.group_key = f"grp_{self.suffix}"
		promo = frappe.get_doc(
			{
				"doctype": "Promotion",
				"promotion_name": f"Promo Quote {self.suffix}",
				"root_company": self.root_company,
				"parent_item": self.parent_item,
				"base_price": 25000,
				"currency": "IDR",
				"enabled": 1,
				"max_instances_per_invoice": 0,
				"components": [{"item_code": self.comp_item, "qty": 1}],
				"choice_groups": [{"group_key": self.group_key, "label": "Pilih", "pick_count": 1}],
				"options": [
					{"choice_group_key": self.group_key, "item_code": self.opt_item, "price_adjustment": 0},
					{"choice_group_key": self.group_key, "item_code": self.opt_item, "price_adjustment": 100},
				],
				"outlets": [
					{"company": self.outlet_company, "warehouse": self.outlet_warehouse, "enabled": 1}
				],
			}
		).insert(ignore_permissions=True)
		self.promo_name = promo.name
		self.option_name = promo.options[0].name

	def _valid_promotion_payload(self):
		return {
			"instances": [
				{
					"promotion": self.promo_name,
					"selections": [
						{
							"choice_group_key": self.group_key,
							"options": [{"option_id": self.option_name, "qty": 1}],
						}
					],
				}
			]
		}

	def test_parser_accepts_valid_promotion_object(self):
		payload = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"items": [],
			"promotions": self._valid_promotion_payload(),
		}
		parsed = _parse_quote_payload(payload)
		self.assertIn("promotions", parsed)
		self.assertIsInstance(parsed["promotions"], str)
		self.assertIn(self.promo_name, parsed["promotions"])

	def test_promotion_only_quote_accepts_empty_items(self):
		payload = {"pos_profile": self.profile, "items": [], "promotions": self._valid_promotion_payload()}
		parsed = _parse_quote_payload(payload)
		self.assertEqual(parsed["items"], [])
		result = build_sale_quote(parsed)
		codes = {row["item_code"] for row in result["items"]}
		self.assertIn(self.parent_item, codes)

	def test_plain_quote_still_rejects_empty_items(self):
		payload = {"pos_profile": self.profile, "items": []}
		with self.assertRaises(MobilePOSAPIError) as ctx:
			_parse_quote_payload(payload)
		self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

	def test_oversized_promotion_payload_returns_invalid_request(self):
		big = {"instances": [{"promotion": self.promo_name, "selections": [], "extra": "x" * (70 * 1024)}]}
		payload = {"pos_profile": self.profile, "items": [], "promotions": big}
		with self.assertRaises(MobilePOSAPIError) as ctx:
			_parse_quote_payload(payload)
		self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
		self.assertIn("64 KiB", ctx.exception.details.get("reason", ""))

	def test_invalid_top_level_promotion_types_return_invalid_request(self):
		for bad in ["string", 123, [], ["not", "dict"]]:
			with self.subTest(bad=bad):
				payload = {"pos_profile": self.profile, "items": [], "promotions": bad}
				with self.assertRaises(MobilePOSAPIError) as ctx:
					_parse_quote_payload(payload)
				self.assertEqual(ctx.exception.code, "INVALID_REQUEST")

	def test_promotion_only_quote_returns_model_c_rows(self):
		payload = {"pos_profile": self.profile, "items": [], "promotions": self._valid_promotion_payload()}
		parsed = _parse_quote_payload(payload)
		result = build_sale_quote(parsed)
		parent_rows = [r for r in result["items"] if r["item_code"] == self.parent_item]
		self.assertEqual(len(parent_rows), 1)
		self.assertEqual(Decimal(parent_rows[0]["rate"]), Decimal("25000"))
		comp_rows = [r for r in result["items"] if r["item_code"] == self.comp_item]
		self.assertTrue(comp_rows)
		for r in comp_rows:
			self.assertEqual(Decimal(r["rate"]), Decimal("0"))
		self.assertIn("grand_total", result)
		self.assertIn("payable", result)
		self.assertIn("taxes", result)

	def test_mixed_regular_and_promotion_quote_returns_combined_totals(self):
		payload = {
			"pos_profile": self.profile,
			"items": [
				{
					"item_code": self.regular_item,
					"qty": "1",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"promotions": self._valid_promotion_payload(),
		}
		parsed = _parse_quote_payload(payload)
		result = build_sale_quote(parsed)
		codes = {r["item_code"] for r in result["items"]}
		self.assertIn(self.regular_item, codes)
		self.assertIn(self.parent_item, codes)
		self.assertTrue(Decimal(result["grand_total"]) > Decimal("0"))
		self.assertTrue(Decimal(result["payable"]) > Decimal("0"))
		self.assertIn("payment_modes", result)
		self.assertIn("payment_amount_policy", result)

	def test_quote_creates_no_invoice_request_selection_fact(self):
		before_invoices = frappe.db.count("POS Invoice")
		before_requests = frappe.db.count("Mobile POS Request")
		payload = {"pos_profile": self.profile, "items": [], "promotions": self._valid_promotion_payload()}
		parsed = _parse_quote_payload(payload)
		build_sale_quote(parsed)
		after_invoices = frappe.db.count("POS Invoice")
		after_requests = frappe.db.count("Mobile POS Request")
		self.assertEqual(before_invoices, after_invoices)
		self.assertEqual(before_requests, after_requests)
		parent_prices = frappe.db.count("Item Price", {"item_code": self.parent_item, "selling": 1})
		self.assertEqual(parent_prices, 0)

	def test_quote_output_supplies_payment_modes_and_policy(self):
		payload = {"pos_profile": self.profile, "items": [], "promotions": self._valid_promotion_payload()}
		parsed = _parse_quote_payload(payload)
		result = build_sale_quote(parsed)
		self.assertIsInstance(result["payment_modes"], list)
		self.assertTrue(len(result["payment_modes"]) > 0)
		policy = result["payment_amount_policy"]
		self.assertIn("decimal_places", policy)
		self.assertIn("currency", policy)

	def test_semantically_invalid_promotion_uses_existing_error_contract(self):
		bad_payload = {"instances": [{"promotion": "NONEXISTENT-PROMO", "selections": []}]}
		payload = {"pos_profile": self.profile, "items": [], "promotions": bad_payload}
		parsed = _parse_quote_payload(payload)
		with self.assertRaises(Exception):
			build_sale_quote(parsed)

	def test_existing_regular_quote_unchanged_when_promotions_omitted(self):
		payload = {
			"pos_profile": self.profile,
			"items": [
				{
					"item_code": self.regular_item,
					"qty": "2",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
		}
		parsed = _parse_quote_payload(payload)
		result = build_sale_quote(parsed)
		codes = {r["item_code"] for r in result["items"]}
		self.assertNotIn(self.parent_item, codes)
		self.assertIn(self.regular_item, codes)
		self.assertIn("grand_total", result)

	def test_promotions_null_equivalent_to_omission(self):
		payload_null = {
			"pos_profile": self.profile,
			"items": [
				{
					"item_code": self.regular_item,
					"qty": "1",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"promotions": None,
		}
		payload_omit = {
			"pos_profile": self.profile,
			"items": [
				{
					"item_code": self.regular_item,
					"qty": "1",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
		}
		parsed_null = _parse_quote_payload(payload_null)
		parsed_omit = _parse_quote_payload(payload_omit)
		self.assertIsNone(parsed_null["promotions"])
		self.assertIsNone(parsed_omit["promotions"])
		result_null = build_sale_quote(parsed_null)
		result_omit = build_sale_quote(parsed_omit)
		self.assertEqual(result_null["grand_total"], result_omit["grand_total"])
		self.assertEqual(result_null["payable"], result_omit["payable"])
