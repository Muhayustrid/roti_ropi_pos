"""Integration tests for Task B: authoritative promotion-aware quote + submit parity.

Covers:
- promotion-only quote → submit parity
- mixed cart quote → submit parity
- replay same key/body → one invoice, one selection, one fact, meta.replayed
- price change after quote → PRICE_CHANGED and no invoice from stale total
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from roti_ropi_pos.api.v1.sales import _parse_quote_payload, _parse_sale_payload
from roti_ropi_pos.mobile_pos.invoices import build_sale_quote, submit_sale
from roti_ropi_pos.tests.helpers import make_cashier, make_pos_profile

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


class TestPromoQuoteSubmitIntegration(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		if not HAS_SELLING:
			self.skipTest("selling_additional not installed")
		self.suffix = _suffix()
		frappe.set_user("Administrator")
		self._setup_org()
		self._setup_items()
		self._setup_profile_and_customer()
		self.cashier = make_cashier(f"int-{self.suffix}@rotiropi.test")
		profile = frappe.get_doc("POS Profile", self.pos_profile_name)
		profile.append("applicable_for_users", {"user": self.cashier, "default": 1})
		profile.save(ignore_permissions=True)
		self._ensure_opening()
		self._setup_promotion()
		frappe.set_user(self.cashier)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

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
		self.root_company = self._make_company("_Test Int Root Co", "R", is_group=1)
		self.outlet_company = self._make_company("_Test Int Outlet Co", "O", parent=self.root_company)
		self.outlet_warehouse = self._make_warehouse("_Test Int Outlet WH", self.outlet_company)

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
		self.regular_item = f"_Test Int Regular {self.suffix}"
		self._make_item(self.regular_item, 1)
		from roti_ropi_pos.tests.helpers import ensure_pos_availability

		ensure_pos_availability(self.regular_item, self.outlet_warehouse, 100)
		if not frappe.db.exists("Price List", "Standard Selling"):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": "Standard Selling",
					"selling": 1,
					"currency": "IDR",
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists(
			"Item Price", {"item_code": self.regular_item, "price_list": "Standard Selling"}
		):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": self.regular_item,
					"price_list": "Standard Selling",
					"selling": 1,
					"price_list_rate": 15000,
				}
			).insert(ignore_permissions=True)
		self.parent_item = f"_Test Int Parent {self.suffix}"
		self.comp_item = f"_Test Int Comp {self.suffix}"
		self.opt_item = f"_Test Int Opt {self.suffix}"
		for code, stock in [(self.parent_item, 0), (self.comp_item, 1), (self.opt_item, 1)]:
			self._make_item(code, stock)
		ensure_pos_availability(self.comp_item, self.outlet_warehouse, 50)
		ensure_pos_availability(self.opt_item, self.outlet_warehouse, 50)

	def _setup_profile_and_customer(self):
		self.customer_name = f"_Test Int Customer {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": self.customer_name,
				"customer_group": "Individual",
				"territory": "All Territories",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
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
		self.pos_profile_name = f"_Test Int POS {self.suffix}"
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
				"promotion_name": f"Promo Int {self.suffix}",
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

	def test_promotion_only_quote_then_submit_parity(self):
		# Quote promotion-only
		quote_payload = {
			"pos_profile": self.profile,
			"items": [],
			"promotions": self._valid_promotion_payload(),
		}
		parsed_quote = _parse_quote_payload(quote_payload)
		before_invoices = frappe.db.count("POS Invoice")
		quote = build_sale_quote(parsed_quote)
		after_quote_invoices = frappe.db.count("POS Invoice")
		self.assertEqual(before_invoices, after_quote_invoices)
		self.assertIn(self.parent_item, {r["item_code"] for r in quote["items"]})
		# Build payment from quote payable
		payable = quote["payable"]
		grand_total = quote["grand_total"]
		# Submit same logical cart
		sale_payload_raw = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": grand_total,
			"items": [],
			"payments": [{"mode_of_payment": self.mop_name, "amount": payable, "reference_no": None}],
			"promotions": self._valid_promotion_payload(),
		}
		sale_parsed = _parse_sale_payload(sale_payload_raw, currency="IDR")
		txn = (
			uuid.uuid4().hex[:8]
			+ "-"
			+ uuid.uuid4().hex[:4]
			+ "-"
			+ uuid.uuid4().hex[:4]
			+ "-"
			+ uuid.uuid4().hex[:4]
			+ "-"
			+ uuid.uuid4().hex[:12]
		)
		# ensure uuid format lower
		import re

		txn = str(uuid.uuid4())
		result = submit_sale(sale_parsed, txn)
		sale = frappe.get_doc("POS Invoice", result.reference_name)
		self.assertEqual(str(Decimal(str(sale.grand_total))), str(Decimal(grand_total)))
		# Model C rows
		roles = {row.item_code: row.custom_selling_additional_promotion_role for row in sale.items}
		self.assertEqual(roles.get(self.parent_item), "Promotion Parent")
		self.assertEqual(roles.get(self.comp_item), "Promotion Component")
		# exactly one selection and two facts (one Fixed Component + one Option) after submit
		self.assertEqual(len(sale.custom_selling_additional_promotion_selections or []), 1)
		facts = frappe.get_all("Promotion Selection Fact", filters={"pos_invoice": sale.name})
		self.assertEqual(len(facts), 2)

	def test_mixed_quote_then_submit_parity(self):
		quote_payload = {
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
		parsed_quote = _parse_quote_payload(quote_payload)
		quote = build_sale_quote(parsed_quote)
		self.assertIn("taxes", quote)
		self.assertIn("payment_modes", quote)
		payable = quote["payable"]
		grand_total = quote["grand_total"]
		sale_payload_raw = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": grand_total,
			"items": [
				{
					"item_code": self.regular_item,
					"qty": "1",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [{"mode_of_payment": self.mop_name, "amount": payable, "reference_no": None}],
			"promotions": self._valid_promotion_payload(),
		}
		sale_parsed = _parse_sale_payload(sale_payload_raw, currency="IDR")
		txn = str(uuid.uuid4())
		result = submit_sale(sale_parsed, txn)
		sale = frappe.get_doc("POS Invoice", result.reference_name)
		self.assertEqual(str(Decimal(str(sale.grand_total))), str(Decimal(grand_total)))
		codes = {r.item_code for r in sale.items}
		self.assertIn(self.regular_item, codes)
		self.assertIn(self.parent_item, codes)
		# ensure once each
		self.assertEqual(len([r for r in sale.items if r.item_code == self.parent_item]), 1)
		self.assertEqual(len([r for r in sale.items if r.item_code == self.regular_item]), 1)

	def test_replay_same_key_same_body(self):
		from roti_ropi_pos.mobile_pos.idempotency import execute_idempotent

		quote_payload = {
			"pos_profile": self.profile,
			"items": [],
			"promotions": self._valid_promotion_payload(),
		}
		parsed_quote = _parse_quote_payload(quote_payload)
		quote = build_sale_quote(parsed_quote)
		payable = quote["payable"]
		grand_total = quote["grand_total"]
		sale_payload_raw = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": grand_total,
			"items": [],
			"payments": [{"mode_of_payment": self.mop_name, "amount": payable, "reference_no": None}],
			"promotions": self._valid_promotion_payload(),
		}
		sale_parsed = _parse_sale_payload(sale_payload_raw, currency="IDR")
		key = str(uuid.uuid4())
		# first submit via idempotent
		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
		result1 = execute_idempotent(
			"v1.sales.submit", sale_parsed, lambda tid: submit_sale(sale_parsed, tid)
		)
		# second replay same key and body
		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
		result2 = execute_idempotent(
			"v1.sales.submit", sale_parsed, lambda tid: submit_sale(sale_parsed, tid)
		)
		self.assertEqual(
			result1["data"]["sale"]["summary"]["name"], result2["data"]["sale"]["summary"]["name"]
		)
		self.assertIn("meta", result2)
		self.assertIs(result2["meta"]["replayed"], True)
		# Check Mobile POS Request count for that key
		req_count = frappe.db.count("Mobile POS Request", {"idempotency_key": key})
		self.assertEqual(req_count, 1)
		# Change promotion choices under same key should return IDEMPOTENCY_KEY_REUSED
		bad_payload = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": grand_total,
			"items": [],
			"payments": [{"mode_of_payment": self.mop_name, "amount": payable, "reference_no": None}],
			"promotions": {
				"instances": [
					{
						"promotion": self.promo_name,
						"selections": [
							{
								"choice_group_key": self.group_key,
								"options": [{"option_id": self.option_name, "qty": 2}],
							}
						],
					}
				]
			},
		}
		bad_parsed = _parse_sale_payload(bad_payload, currency="IDR")
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
		with self.assertRaises(MobilePOSAPIError) as ctx:
			execute_idempotent("v1.sales.submit", bad_parsed, lambda tid: submit_sale(bad_parsed, tid))
		self.assertEqual(ctx.exception.code, "IDEMPOTENCY_KEY_REUSED")

	def test_price_change_after_quote(self):
		quote_payload = {
			"pos_profile": self.profile,
			"items": [],
			"promotions": self._valid_promotion_payload(),
		}
		parsed_quote = _parse_quote_payload(quote_payload)
		quote = build_sale_quote(parsed_quote)
		old_grand = quote["grand_total"]
		old_payable = quote["payable"]
		# Change backend price: update promotion base_price
		frappe.db.set_value("Promotion", self.promo_name, "base_price", 99999)
		# Re-quote should give new price
		new_quote = build_sale_quote(parsed_quote)
		new_grand = new_quote["grand_total"]
		self.assertNotEqual(old_grand, new_grand)
		# Try submit with old accepted total should get PRICE_CHANGED and no invoice
		before = frappe.db.count("POS Invoice")
		sale_payload_raw = {
			"pos_profile": self.profile,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": old_grand,
			"items": [],
			"payments": [{"mode_of_payment": self.mop_name, "amount": old_payable, "reference_no": None}],
			"promotions": self._valid_promotion_payload(),
		}
		sale_parsed = _parse_sale_payload(sale_payload_raw, currency="IDR")
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		with self.assertRaises(MobilePOSAPIError) as ctx:
			submit_sale(sale_parsed, str(uuid.uuid4()))
		self.assertEqual(ctx.exception.code, "PRICE_CHANGED")
		after = frappe.db.count("POS Invoice")
		self.assertEqual(before, after)

	def test_invalid_promotion_quote_maps_validation_to_invalid_request_no_artifact(self):
		"""Regression for ValidationError → INVALID_REQUEST mapping in invoices._materialize_if_promoted.

		Uses a semantically invalid promotion (nonexistent) via the real quote path.
		Must map frappe.ValidationError to MobilePOSAPIError INVALID_REQUEST with
		field=promotions, and must leave no business or accounting artifact.
		Fails if the mapping is removed (would raise raw ValidationError instead).
		"""
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		bad_payload = {"instances": [{"promotion": "NONEXISTENT-PROMO-XYZ", "selections": []}]}
		payload = {"pos_profile": self.profile, "items": [], "promotions": bad_payload}
		parsed = _parse_quote_payload(payload)

		before_invoice = frappe.db.count("POS Invoice")
		before_request = frappe.db.count("Mobile POS Request")
		before_fact = frappe.db.count("Promotion Selection Fact")
		before_gle = frappe.db.count("GL Entry")
		before_sle = frappe.db.count("Stock Ledger Entry")
		before_price = frappe.db.count("Item Price", {"item_code": self.parent_item, "selling": 1})
		# child table rows (POS Promotion Selection) via direct sql — frappe.db.count works for child
		try:
			before_sel = frappe.db.count("POS Promotion Selection")
		except Exception:
			before_sel = frappe.db.sql("select count(*) from `tabPOS Promotion Selection`")[0][0]

		with self.assertRaises(MobilePOSAPIError) as ctx:
			build_sale_quote(parsed)

		self.assertEqual(ctx.exception.code, "INVALID_REQUEST")
		self.assertEqual(ctx.exception.details.get("field"), "promotions")
		self.assertIn("NONEXISTENT-PROMO-XYZ", ctx.exception.details.get("reason", ""))

		# no business or accounting artifact
		self.assertEqual(before_invoice, frappe.db.count("POS Invoice"))
		self.assertEqual(before_request, frappe.db.count("Mobile POS Request"))
		self.assertEqual(before_fact, frappe.db.count("Promotion Selection Fact"))
		self.assertEqual(before_gle, frappe.db.count("GL Entry"))
		self.assertEqual(before_sle, frappe.db.count("Stock Ledger Entry"))
		self.assertEqual(
			before_price, frappe.db.count("Item Price", {"item_code": self.parent_item, "selling": 1})
		)
		try:
			after_sel = frappe.db.count("POS Promotion Selection")
		except Exception:
			after_sel = frappe.db.sql("select count(*) from `tabPOS Promotion Selection`")[0][0]
		self.assertEqual(before_sel, after_sel)
