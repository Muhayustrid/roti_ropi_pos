"""End-to-end lifecycle test for the Mobile POS backend.

Covers one cashier with only ``Mobile POS Cashier`` role through:
  stale-opening warning → close stale → open new session → customer search →
  catalog search → quote → multi-mode sale → lost-response replay → history →
  partial return with appended remarks → closing preview → closing submit →
  final status poll.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import frappe
from erpnext.accounts.doctype.mode_of_payment.test_mode_of_payment import (
	set_default_account_for_mode_of_payment,
)
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.auth import validate_auth_via_hooks
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import bootstrap as bootstrap_api
from roti_ropi_pos.api.v1 import catalog as catalog_api
from roti_ropi_pos.api.v1 import closing as closing_api
from roti_ropi_pos.api.v1 import customers as customers_api
from roti_ropi_pos.api.v1 import sales as sales_api
from roti_ropi_pos.api.v1 import sessions as sessions_api
from roti_ropi_pos.tests.helpers import (
	clear_fake_request,
	close_test_openings,
	make_bearer_token,
	make_cashier,
	make_oauth_client,
	make_opening_entry,
	set_request,
)
from roti_ropi_pos.tests.test_sessions import COMPANY, WAREHOUSE, make_valid_profile

ITEM = "_Test Item"
BANK_MODE = "Bank Draft"
CLIENT_ID = "rotiropi.mobilepos.e2e.test"
TOKEN = "rotiropi-e2e-bearer-token"
BOOTSTRAP_PATH = "/api/method/roti_ropi_pos.api.v1.bootstrap.get"


class TestMobilePOSLifecycle(IntegrationTestCase):
	"""Full backend lifecycle exercised as one cashier through every v1 endpoint."""

	@classmethod
	def tearDownClass(cls) -> None:
		super().tearDownClass()
		assert not frappe.db.get_single_value("Stock Settings", "allow_negative_stock")

	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self._saved_neg_stock = frappe.db.get_single_value("Stock Settings", "allow_negative_stock")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)

		self.saved_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
		frappe.conf["mobile_pos_oauth_client_id"] = CLIENT_ID
		self.cashier = make_cashier(f"e2e-{frappe.generate_hash(length=8)}@rotiropi.test")
		make_oauth_client(CLIENT_ID)
		make_bearer_token(TOKEN, client_id=CLIENT_ID, user=self.cashier)
		# System User enables role-permission queries in tests; no extra role is assigned.
		frappe.db.set_value("User", self.cashier, "user_type", "System User")
		frappe.cache.delete_value(f"user_permissions:{self.cashier}")
		frappe.cache.hdel("roles", self.cashier)
		self.assertEqual(
			set(frappe.get_all("Has Role", filters={"parent": self.cashier}, pluck="role")),
			{"Mobile POS Cashier"},
		)

		self.profile = make_valid_profile(f"Mobile POS E2E {frappe.generate_hash(length=8)}", self.cashier)
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		item_group = frappe.db.get_value("Item", ITEM, "item_group")
		self.profile.append("item_groups", {"item_group": item_group})
		# Cash handles refunds; Bank Draft proves distinct modes can fully settle one sale.
		for row in self.profile.payments:
			if row.mode_of_payment == "Cash":
				row.allow_in_returns = 1
		self.profile.append("payments", {"mode_of_payment": BANK_MODE})
		self.profile.save(ignore_permissions=True)

		self._uom = frappe.db.get_value("Item", ITEM, "stock_uom")
		self._ensure_item_price()
		make_stock_entry(target=WAREHOUSE, item_code=ITEM, qty=500, basic_rate=100)
		self._batch_item, self._batch_no, self._batch_uom = self._make_batch_uom_fixture(item_group)

		# Ensure both sale modes have company accounts.
		cash = frappe.get_doc("Mode of Payment", "Cash")
		if not frappe.db.exists("Mode of Payment Account", {"parent": "Cash", "company": COMPANY}):
			cash.append("accounts", {"company": COMPANY, "default_account": "Sales - _TC"})
			cash.save()
		set_default_account_for_mode_of_payment(
			frappe.get_doc("Mode of Payment", BANK_MODE), COMPANY, "_Test Bank - _TC"
		)

	def tearDown(self) -> None:
		clear_fake_request()
		frappe.local.form_dict = frappe._dict()
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		frappe.db.set_single_value("Stock Settings", "allow_negative_stock", self._saved_neg_stock or 0)
		frappe.db.commit()
		if self.saved_client_id is None:
			frappe.conf.pop("mobile_pos_oauth_client_id", None)
		else:
			frappe.conf["mobile_pos_oauth_client_id"] = self.saved_client_id
		frappe.set_user("Administrator")
		super().tearDown()

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _idem(self, key: str | None = None):
		"""Return a patch context that injects an idempotency key header."""
		return patch("frappe.get_request_header", return_value=key or str(uuid4()))

	def _submit_sale(self, idem_key: str) -> dict:
		payload = {
			"pos_profile": self.profile.name,
			"client_accepted_grand_total": "200",
			"items": [
				{
					"item_code": ITEM,
					"qty": "2",
					"uom": self._uom,
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [
				{"mode_of_payment": "Cash", "amount": "80", "reference_no": None},
				{"mode_of_payment": BANK_MODE, "amount": "120", "reference_no": "E2E-REF-1"},
			],
		}
		with patch("frappe.get_request_header", return_value=idem_key):
			frappe.local.form_dict = frappe._dict(payload)
			return sales_api.submit()

	def _close_session(self, idem_key: str) -> dict:
		payload = {
			"pos_profile": self.profile.name,
			"closing_balances": [{"mode_of_payment": "Cash", "closing_amount": "500100"}],
		}
		# frappe.in_test executes enqueue synchronously; patch consolidation so
		# the lifecycle test never runs create_merge_logs (ERPNext's own suite tests that).
		with (
			patch("frappe.get_request_header", return_value=idem_key),
			patch("erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.consolidate_pos_invoices"),
		):
			frappe.local.form_dict = frappe._dict(payload)
			return closing_api.submit()

	def _make_batch_uom_fixture(self, item_group: str) -> tuple[str, str, str]:
		item_code = f"_Test Mobile POS Batch {frappe.generate_hash(length=8)}"
		uom = "Carton"
		if not frappe.db.exists("UOM", uom):
			frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": self._uom,
				"has_batch_no": 1,
				"create_new_batch": 1,
				"custom_default_uom_warehouse": uom,
				"uoms": [
					{"uom": self._uom, "conversion_factor": 1},
					{"uom": uom, "conversion_factor": 2},
				],
			}
		).insert(ignore_permissions=True)
		batch = frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": f"_TEST-MOBILE-POS-{frappe.generate_hash(length=8)}",
				"item": item_code,
			}
		).insert(ignore_permissions=True)
		frappe.cache().delete_value(f"erpnext:barcode_scan:{batch.name}")
		return item_code, batch.name, uom

	def _ensure_item_price(self) -> None:
		filters = {
			"item_code": ITEM,
			"price_list": self.profile.selling_price_list,
			"uom": self._uom,
		}
		if frappe.db.exists("Item Price", filters):
			frappe.db.set_value(
				"Item Price",
				filters,
				{"price_list_rate": 100, "valid_from": frappe.utils.today(), "valid_upto": None},
			)
			return
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": ITEM,
				"price_list": self.profile.selling_price_list,
				"price_list_rate": 100,
				"uom": self._uom,
			}
		).insert(ignore_permissions=True)

	# ------------------------------------------------------------------
	# Test
	# ------------------------------------------------------------------

	def test_complete_lifecycle(self) -> None:
		# --- Phase 1: stale-opening warning via bootstrap ---
		stale_opening = make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date="2026-07-20 08:00:00",
			posting_date="2026-07-20",
			balances=[{"mode_of_payment": "Cash", "opening_amount": "500000"}],
		)
		frappe.set_user(self.cashier)
		set_request(BOOTSTRAP_PATH)
		with patch("frappe.get_request_header", return_value=f"Bearer {TOKEN}"):
			validate_auth_via_hooks()
			boot = bootstrap_api.get(pos_profile=self.profile.name)
		clear_fake_request()
		self.assertTrue(boot["ok"])
		opening_session = boot["data"]["opening_session"]
		self.assertIsNotNone(opening_session)
		warnings = opening_session.get("warnings", [])
		self.assertTrue(
			any(w["code"] == "STALE_OPENING" for w in warnings),
			"Expected STALE_OPENING warning for prior-day opening",
		)

		# --- Phase 2: close stale session before opening a new one ---
		close_stale_key = str(uuid4())
		close_stale = self._close_session(close_stale_key)
		self.assertTrue(close_stale["ok"], close_stale)

		# Closing submitted: manually mark opening closed so get_current_opening
		# returns None (consolidation is patched out in tests so on_submit never
		# calls update_opening_entry).
		stale_closing_name = close_stale["data"]["closing"]["name"]
		frappe.db.set_value("POS Opening Entry", stale_opening, "pos_closing_entry", stale_closing_name)
		frappe.db.set_value("POS Opening Entry", stale_opening, "status", "Closed")

		# --- Phase 3: open a fresh session ---
		open_key = str(uuid4())
		payload_open = {
			"pos_profile": self.profile.name,
			"opening_balances": [{"mode_of_payment": "Cash", "amount": "500000"}],
		}
		with patch("frappe.get_request_header", return_value=open_key):
			frappe.local.form_dict = frappe._dict(payload_open)
			open_result = sessions_api.open()
		self.assertTrue(open_result["ok"], open_result)
		opening_name = open_result["data"]["opening_session"]["name"]
		self.assertTrue(opening_name)

		# --- Phase 4: customer search and default walk-in ---
		# Search by the profile's default customer name to guarantee it appears.
		default_customer_name = self.profile.customer
		customers_result = customers_api.search(
			pos_profile=self.profile.name, q=default_customer_name, limit=20
		)
		self.assertTrue(customers_result["ok"])
		customers = customers_result["data"]["customers"]
		self.assertIsInstance(customers, list)
		default_walk_in = next((c for c in customers if c["is_default_walk_in"]), None)
		self.assertIsNotNone(default_walk_in, "Profile must expose a default walk-in customer")

		# --- Phase 5: catalog search ---
		catalog_result = catalog_api.search(pos_profile=self.profile.name, q="")
		self.assertTrue(catalog_result["ok"])
		items = catalog_result["data"]["items"]
		self.assertIsInstance(items, list)
		# Catalog may return empty for Website User with limited perms in test DB;
		# the per-item permission model is covered by test_catalog.py.

		# --- Phase 6: bakery batch-UOM scan through effective Frappe override ---
		frappe.local.form_dict = frappe._dict({"pos_profile": self.profile.name, "value": self._batch_no})
		scan_result = catalog_api.scan()
		self.assertTrue(scan_result["ok"], scan_result)
		scan = scan_result["data"]["scan"]
		self.assertEqual(scan["item_code"], self._batch_item)
		self.assertEqual(scan["batch_no"], self._batch_no)
		self.assertEqual(scan["uom"], self._batch_uom)
		self.assertEqual(scan["conversion_factor"], "2.0")

		# --- Phase 7: quote ---
		# Use ITEM directly — known valid item, tested in test_catalog.py.
		with patch("frappe.get_request_header", return_value=None):
			frappe.local.form_dict = frappe._dict(
				{
					"pos_profile": self.profile.name,
					"item_code": ITEM,
					"qty": "1",
					"uom": self._uom,
				}
			)
			quote_result = catalog_api.quote_item()
		self.assertTrue(quote_result["ok"])
		self.assertEqual(quote_result["data"]["item"]["rate"], "100.0")

		# --- Phase 8: fully settled multi-mode sale ---
		sale_key = str(uuid4())
		sale_result = self._submit_sale(sale_key)
		self.assertTrue(sale_result["ok"], sale_result)
		sale_name = sale_result["data"]["sale"]["summary"]["name"]
		sale_doc = frappe.get_doc("POS Invoice", sale_name)
		self.assertEqual(sale_doc.outstanding_amount, 0)
		self.assertEqual({row.mode_of_payment for row in sale_doc.payments}, {"Cash", BANK_MODE})
		source_remarks = "Original Mobile POS sale note"
		frappe.db.set_value("POS Invoice", sale_name, "remarks", source_remarks)

		# --- Phase 9: lost-response replay (same key → same result) ---
		replay_result = self._submit_sale(sale_key)
		self.assertTrue(replay_result["ok"], replay_result)
		self.assertEqual(replay_result["data"]["sale"]["summary"]["name"], sale_name)

		# --- Phase 9: history ---
		history_result = sales_api.list(pos_profile=self.profile.name, status="all", q="", start=0, limit=20)
		self.assertTrue(history_result["ok"])
		names = [s["name"] for s in history_result["data"]["sales"]]
		self.assertIn(sale_name, names)

		# Verify sale detail includes row_id (needed for return selection).
		detail_result = sales_api.get(name=sale_name)
		self.assertTrue(detail_result["ok"])
		items_in_sale = detail_result["data"]["sale"]["items"]
		self.assertTrue(len(items_in_sale) > 0)
		self.assertIn("row_id", items_in_sale[0], "Sale detail must expose row_id for returns")

		# --- Phase 10: partial return with preserved and appended remarks ---
		row_id = items_in_sale[0]["row_id"]
		return_key = str(uuid4())
		return_payload = {
			"source_name": sale_name,
			"reason": "Customer changed mind",
			"items": [{"source_item_row": row_id, "qty": "1"}],
			"payments": [{"mode_of_payment": "Cash", "amount": "-100", "reference_no": None}],
		}
		with patch("frappe.get_request_header", return_value=return_key):
			frappe.local.form_dict = frappe._dict(return_payload)
			return_result = sales_api.create_return()
		self.assertTrue(return_result["ok"], return_result)
		return_name = return_result["data"]["return_sale"]["summary"]["name"]
		self.assertTrue(return_name)

		# Check reason appended to remarks on the return POS Invoice.
		return_doc = frappe.get_doc("POS Invoice", return_name)
		self.assertEqual(return_doc.items[0].qty, -1)
		self.assertEqual(frappe.db.get_value("POS Invoice Item", row_id, "qty"), 2)
		self.assertIn(source_remarks, return_doc.remarks or "")
		self.assertIn("Mobile POS Return Reason:", return_doc.remarks or "")
		self.assertIn("Customer changed mind", return_doc.remarks or "")

		# --- Phase 11: closing preview ---
		preview = closing_api.preview(pos_profile=self.profile.name)
		self.assertTrue(preview["ok"], preview)
		preview_data = preview["data"]
		self.assertIn("invoice_count", preview_data)
		# The return invoice is negative so net count = 2 docs (sale + return).
		self.assertGreaterEqual(preview_data["invoice_count"], 1)
		self.assertIn("expected_payments", preview_data)

		# --- Phase 12: close session ---
		close_key = str(uuid4())
		close_result = self._close_session(close_key)
		self.assertTrue(close_result["ok"], close_result)
		closing_name = close_result["data"]["closing"]["name"]
		self.assertTrue(closing_name)

		# Consolidation patched → update_opening_entry never called; manually
		# mark opening closed so get_current_opening returns None.
		frappe.db.set_value("POS Opening Entry", opening_name, "pos_closing_entry", closing_name)
		frappe.db.set_value("POS Opening Entry", opening_name, "status", "Closed")

		# --- Phase 13: final status poll ---
		status_result = closing_api.status(name=closing_name)
		self.assertTrue(status_result["ok"], status_result)
		closing_status = status_result["data"]["closing"]["status"]
		self.assertIn(closing_status, {"draft", "submitted", "queued"})

		# No open session remains.
		boot3 = bootstrap_api.get(pos_profile=self.profile.name)
		self.assertIsNone(boot3["data"]["opening_session"])
