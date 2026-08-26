"""RED → GREEN tests for Task A: exact Mobile bearer access for promotion facades."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from roti_ropi_pos.mobile_pos.auth_hook import (
	MOBILE_POS_METHODS,
	MOBILE_POS_PATHS,
	validate_mobile_api_scope,
)
from roti_ropi_pos.tests.helpers import (
	DESK_ROLE,
	clear_fake_request,
	grant_role_row,
	make_bearer_token,
	make_cashier,
	make_oauth_client,
	set_request,
)

HAS_SELLING = "selling_additional" in frappe.get_installed_apps()


def _pos_promo_api():
	import importlib

	return importlib.import_module("selling_additional.overrides.pos_promo_api")


CLIENT_ID = "rotiropi.mobilepos.test"
TOKEN = "promo-bearer-token-test"


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


PROMO_METHODS = {
	"selling_additional.overrides.pos_promo_api.get_available_promotions",
	"selling_additional.overrides.pos_promo_api.get_promotion_detail",
	"selling_additional.overrides.pos_promo_api.quote_promotion",
}
PROMO_PATHS = {f"/api/method/{m}" for m in PROMO_METHODS}


def _suffix():
	return uuid.uuid4().hex[:8]


class TestPromoBearerRoute(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		if not HAS_SELLING:
			self.skipTest("selling_additional not installed")
		self.suffix = _suffix()
		self.saved_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
		frappe.conf["mobile_pos_oauth_client_id"] = CLIENT_ID
		self._setup_org()
		self._setup_items()
		self._setup_profile_and_customer()
		self._setup_promotion()
		self.cashier = make_cashier(f"promo-{self.suffix}@rotiropi.test")
		# add cashier to profile's applicable_for_users
		profile = frappe.get_doc("POS Profile", self.pos_profile_name)
		profile.append("applicable_for_users", {"user": self.cashier, "default": 1})
		profile.save(ignore_permissions=True)
		self.other_cashier = make_cashier(f"promo-other-{self.suffix}@rotiropi.test")
		self.other_profile = self._make_other_profile()
		self.disabled_profile = self._make_disabled_profile()
		make_oauth_client(CLIENT_ID)
		make_bearer_token(TOKEN, client_id=CLIENT_ID, user=self.cashier)

	def tearDown(self):
		clear_fake_request()
		frappe.local.form_dict = frappe._dict()
		if self.saved_client_id is None:
			frappe.conf.pop("mobile_pos_oauth_client_id", None)
		else:
			frappe.conf["mobile_pos_oauth_client_id"] = self.saved_client_id
		frappe.set_user("Administrator")
		super().tearDown()

	# --- fixtures ---
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
		self.root_company = self._make_company("_Test PA Root Co", "R", is_group=1)
		self.outlet_company = self._make_company("_Test PA Outlet Co", "O", parent=self.root_company)
		self.outlet_warehouse = self._make_warehouse("_Test PA Outlet WH", self.outlet_company)
		self.other_warehouse = self._make_warehouse("_Test PA Other WH", self.outlet_company)

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
		self.parent_a = self._make_item(f"_Test PA Parent A {self.suffix}", 0)
		self.bread_a = self._make_item(f"_Test PA Bread A {self.suffix}", 1)
		self.bread_b = self._make_item(f"_Test PA Bread B {self.suffix}", 1)

	def _setup_profile_and_customer(self):
		self.customer_name = f"_Test PA Customer {self.suffix}"
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
		self.pos_profile_name = f"_Test PA POS Profile {self.suffix}"
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
			}
		).insert(ignore_permissions=True)

	def _make_other_profile(self):
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
		name = f"_Test PA Other Profile {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": name,
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
				"applicable_for_users": [{"user": self.other_cashier}],
			}
		).insert(ignore_permissions=True)
		return name

	def _make_disabled_profile(self):
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
		name = f"_Test PA Disabled Profile {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": name,
				"company": self.outlet_company,
				"warehouse": self.outlet_warehouse,
				"customer": self.customer_name,
				"currency": "IDR",
				"selling_price_list": "Standard Selling",
				"disabled": 1,
				"payments": [{"mode_of_payment": self.mop_name, "default": 1}],
				"write_off_account": write_off,
				"write_off_cost_center": cc,
				"income_account": income,
				"expense_account": write_off,
				"cost_center": cc,
				"write_off_limit": 1.0,
				"applicable_for_users": [{"user": self.cashier}],
			}
		).insert(ignore_permissions=True)
		return name

	def _setup_promotion(self):
		group_key = f"grp_{self.suffix}"
		promo = frappe.get_doc(
			{
				"doctype": "Promotion",
				"promotion_name": f"Promo Bearer {self.suffix}",
				"root_company": self.root_company,
				"parent_item": self.parent_a,
				"base_price": 20000,
				"currency": "IDR",
				"enabled": 1,
				"max_instances_per_invoice": 0,
				"components": [{"item_code": self.bread_a, "qty": 1}],
				"choice_groups": [{"group_key": group_key, "label": "Pilih", "pick_count": 1}],
				"options": [
					{"choice_group_key": group_key, "item_code": self.bread_b, "price_adjustment": 0},
					{"choice_group_key": group_key, "item_code": self.bread_a, "price_adjustment": 100},
				],
				"outlets": [
					{"company": self.outlet_company, "warehouse": self.outlet_warehouse, "enabled": 1}
				],
			}
		).insert(ignore_permissions=True)
		self.promo_name = promo.name
		self.group_key = group_key
		self.option_name = promo.options[0].name

	def _request(self, path, *, user=None, method="POST", form=None, authorization=""):
		frappe.set_user(user or self.cashier)
		frappe.local.form_dict = frappe._dict(form or {})
		set_request(path, method=method)
		return patch("frappe.get_request_header", return_value=authorization)

	def test_valid_cashier_bearer_can_reach_get_available_promotions(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			result = _pos_promo_api().get_available_promotions(self.pos_profile_name)
			self.assertIsInstance(result, list)

	def test_valid_cashier_bearer_can_reach_get_promotion_detail(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_promotion_detail"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			result = _pos_promo_api().get_promotion_detail(self.promo_name, self.pos_profile_name)
			self.assertEqual(result["promotion"], self.promo_name)
			self.assertIn("eligibility", result)

	def test_valid_cashier_bearer_can_reach_quote_promotion(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.quote_promotion"
		choices = json.dumps(
			[{"choice_group_key": self.group_key, "options": [{"option_id": self.option_name, "qty": 1}]}]
		)
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			result = _pos_promo_api().quote_promotion(self.promo_name, choices, self.pos_profile_name)
			self.assertIn("total_price", result)

	def test_missing_pos_profile_rejected_for_available(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError, TypeError)):
				_pos_promo_api().get_available_promotions(None)

	def test_missing_pos_profile_rejected_for_detail(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_promotion_detail"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError, TypeError)):
				_pos_promo_api().get_promotion_detail(self.promo_name, None)

	def test_missing_pos_profile_rejected_for_quote(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.quote_promotion"
		choices = json.dumps(
			[{"choice_group_key": self.group_key, "options": [{"option_id": self.option_name, "qty": 1}]}]
		)
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			with self.assertRaises((frappe.ValidationError, frappe.PermissionError, TypeError)):
				_pos_promo_api().quote_promotion(self.promo_name, choices, None)

	def test_unassigned_profile_rejected(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			with self.assertRaises(frappe.PermissionError):
				_pos_promo_api().get_available_promotions(self.other_profile)

	def test_disabled_profile_rejected(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			with self.assertRaises(frappe.PermissionError):
				_pos_promo_api().get_available_promotions(self.disabled_profile)

	def test_wrong_oauth_client_rejected(self):
		make_bearer_token("wrong-client-token", client_id="other-client", user=self.cashier)
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization="Bearer wrong-client-token"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_expired_token_rejected(self):
		frappe.db.set_value("OAuth Bearer Token", TOKEN, "expiration_time", "2020-01-01 00:00:00")
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_disabled_user_rejected(self):
		frappe.db.set_value("User", self.cashier, "enabled", 0)
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_user_without_cashier_role_rejected(self):
		from roti_ropi_pos.tests.test_sessions import make_plain_user

		plain = make_plain_user(f"plain-{self.suffix}@rotiropi.test")
		make_bearer_token("plain-token", client_id=CLIENT_ID, user=plain)
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, user=plain, method="POST", authorization="Bearer plain-token"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_desk_user_with_cashier_role_still_needs_valid_bearer_on_promo(self):
		grant_role_row(self.cashier, DESK_ROLE)
		self.assertTrue(frappe.get_doc("User", self.cashier).has_desk_access())
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=""):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()

	def test_get_method_rejected_for_promo_facades(self):
		from frappe import allowed_http_methods_for_whitelisted_func

		func = _pos_promo_api().get_available_promotions
		allowed = allowed_http_methods_for_whitelisted_func.get(func, ["GET", "POST", "PUT", "DELETE"])
		for method in ["GET", "PUT", "DELETE", "PATCH"]:
			with self.subTest(method=method):
				self.assertNotIn(method, allowed, f"{method} should be rejected")

	def test_generic_rpc_resource_v2_cmd_alias_paths_remain_rejected(self):
		for path in [
			"/api/resource/POS Invoice",
			"/api/v2/method/roti_ropi_pos.api.v1.bootstrap.get",
			"/api/method/frappe.client.get",
		]:
			with (
				self.subTest(path=path),
				self._request(path=path, method="POST", authorization=f"Bearer {TOKEN}"),
			):
				with self.assertRaises((frappe.AuthenticationError, frappe.PermissionError)):
					validate_mobile_api_scope()
		with self._request(
			path="/api/method/frappe.client.get",
			method="POST",
			form={"cmd": "selling_additional.overrides.pos_promo_api.get_available_promotions"},
			authorization=f"Bearer {TOKEN}",
		):
			with self.assertRaises(frappe.PermissionError):
				validate_mobile_api_scope()
		with self._request(
			path="/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions%2F",
			method="POST",
			authorization=f"Bearer {TOKEN}",
		):
			with self.assertRaises((frappe.AuthenticationError, frappe.PermissionError)):
				validate_mobile_api_scope()
		with self._request(
			path="/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions/extra",
			method="POST",
			authorization=f"Bearer {TOKEN}",
		):
			with self.assertRaises((frappe.AuthenticationError, frappe.PermissionError)):
				validate_mobile_api_scope()

	def test_desk_pos_xcall_post_still_works_for_promo(self):
		path = "/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions"
		with self._request(path, method="POST", authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()
			result = _pos_promo_api().get_available_promotions(self.pos_profile_name)
			self.assertIsInstance(result, list)

	def test_allowlist_contains_only_expected_promo_methods(self):
		for method in PROMO_METHODS:
			self.assertIn(method, MOBILE_POS_METHODS, f"{method} should be allowlisted")
		for path in PROMO_PATHS:
			self.assertIn(path, MOBILE_POS_PATHS, f"{path} should be allowlisted")
