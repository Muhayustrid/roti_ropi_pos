from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import frappe
from erpnext.accounts.doctype.mode_of_payment.test_mode_of_payment import (
	set_default_account_for_mode_of_payment,
)
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import sales as sales_api
from roti_ropi_pos.mobile_pos import validation
from roti_ropi_pos.mobile_pos import invoices
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.tests.helpers import close_test_openings, make_cashier, make_opening_entry
from roti_ropi_pos.tests.test_sessions import COMPANY, WAREHOUSE, make_valid_profile


def _run_return_attempt(site, user, payload, key, barrier):
	frappe.init(site=site)
	frappe.connect()
	try:
		frappe.set_user(user)
		barrier.wait(timeout=10)
		for _ in range(2):
			frappe.local.form_dict = frappe._dict(payload)
			frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
			try:
				result = sales_api.create_return()
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				continue
			frappe.db.commit()
			return result
		raise AssertionError("Return transaction deadlocked twice.")
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


class TestTask10ReturnContract(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"return-{frappe.generate_hash(length=8)}@rotiropi.test")
		frappe.cache.delete_value(f"user_permissions:{self.cashier}")
		frappe.cache.hdel("roles", self.cashier)
		self.profile = make_valid_profile(f"Mobile POS Return {frappe.generate_hash(length=8)}", self.cashier)
		frappe.clear_cache(doctype="POS Invoice")
		frappe.clear_cache(user=self.cashier)
		self.opening = make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		self.item = "_Test Item"
		self.uom = frappe.db.get_value("Item", self.item, "stock_uom")
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		self.profile.append(
			"item_groups", {"item_group": frappe.db.get_value("Item", self.item, "item_group")}
		)
		for payment in self.profile.payments:
			if payment.mode_of_payment == "Cash":
				payment.allow_in_returns = 1
		self.profile.save(ignore_permissions=True)
		self._ensure_item_price()
		make_stock_entry(target=WAREHOUSE, item_code=self.item, qty=10, basic_rate=100)
		frappe.set_user(self.cashier)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def test_sale_detail_projects_no_prior_return(self):
		sale = self._submit(qty="2", total="200")

		result = sales_api.get(name=sale["summary"]["name"])

		self.assertTrue(result["ok"])
		self.assertEqual(
			result["data"]["sale"]["return_contract"]["allowed_refund_modes"],
			[{"mode_of_payment": "Cash"}],
		)
		self.assertEqual(
			result["data"]["sale"]["items"][0]["returnability"],
			{
				"original_row_id": sale["items"][0]["row_id"],
				"item_code": self.item,
				"original_qty": "2.0",
				"returned_qty": "0",
				"remaining_qty": "2.0",
				"uom": self.uom,
				"batch_numbers": [],
				"serial_numbers": [],
				"eligible": True,
				"rejection_reason": None,
			},
		)

	def test_sale_detail_projects_multiple_prior_returns(self):
		sale = self._submit(qty="3", total="300")
		self._create_return(sale, qty="1")
		self._create_return(sale, qty="1")

		row = sales_api.get(name=sale["summary"]["name"])["data"]["sale"]["items"][0]

		self.assertEqual(row["returnability"]["returned_qty"], "2.0")
		self.assertEqual(row["returnability"]["remaining_qty"], "1.0")
		self.assertTrue(row["returnability"]["eligible"])

	def test_sale_detail_ignores_draft_returns(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return

		sale = self._submit(qty="2", total="200")
		frappe.set_user("Administrator")
		draft = make_sales_return(sale["summary"]["name"])
		draft.items[0].qty = -1
		draft.calculate_taxes_and_totals()
		draft.set("payments", [])
		draft.append("payments", {"mode_of_payment": "Cash", "amount": -100})
		draft.set_paid_amount()
		draft.set_account_for_mode_of_payment()
		draft.set_outstanding_amount()
		draft.insert(ignore_permissions=True)
		frappe.set_user(self.cashier)

		row = sales_api.get(name=sale["summary"]["name"])["data"]["sale"]["items"][0]

		self.assertEqual(row["returnability"]["returned_qty"], "0")
		self.assertEqual(row["returnability"]["remaining_qty"], "2.0")

	def test_sale_detail_marks_fully_returned_row_ineligible(self):
		sale = self._submit(qty="2", total="200")
		self._create_return(sale, qty="2")

		row = sales_api.get(name=sale["summary"]["name"])["data"]["sale"]["items"][0]

		self.assertEqual(row["returnability"]["returned_qty"], "2.0")
		self.assertEqual(row["returnability"]["remaining_qty"], "0")
		self.assertFalse(row["returnability"]["eligible"])
		self.assertEqual(row["returnability"]["rejection_reason"], "RETURN_LIMIT_REACHED")

	def test_sale_detail_includes_direct_and_bundle_tracking_references(self):
		row = frappe._dict(
			batch_no="DIRECT-BATCH",
			serial_no="DIRECT-SERIAL\nSHARED-SERIAL",
			serial_and_batch_bundle="BUNDLE-1",
		)

		with (
			patch.object(invoices, "get_batches_from_bundle", return_value={"BUNDLE-BATCH": 1}),
			patch.object(
				invoices,
				"get_serial_nos_from_bundle",
				return_value=["SHARED-SERIAL", "BUNDLE-SERIAL"],
			),
		):
			batches, serials = invoices._serial_batch_references(row)

		self.assertEqual(batches, ["DIRECT-BATCH", "BUNDLE-BATCH"])
		self.assertEqual(serials, ["DIRECT-SERIAL", "SHARED-SERIAL", "BUNDLE-SERIAL"])

	def test_return_quantity_policy_rejects_non_exact_decimal_input(self):
		original = frappe.db.get_default("float_precision")
		frappe.db.set_default("float_precision", 2)
		try:
			self.assertEqual(validation.return_quantity_string("0.01"), Decimal("0.01"))
			for value, reason in (
				("0", "zero_amount"),
				("0.001", "excessive_scale"),
				("-1", "negative_amount"),
				("+1", "malformed_decimal"),
				("1e2", "malformed_decimal"),
				(" 1", "malformed_decimal"),
				("1,000", "malformed_decimal"),
			):
				with self.subTest(value=value), self.assertRaises(MobilePOSAPIError) as error:
					validation.return_quantity_string(value)
				self.assertEqual(error.exception.details["reason"], reason)
		finally:
			frappe.db.set_default("float_precision", original)

	def test_quote_return_calculates_refund_and_creates_no_artifacts(self):
		sale = self._submit(qty="2", total="200")
		before_invoices = frappe.db.count("POS Invoice")
		before_requests = frappe.db.count("Mobile POS Request")

		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)
		result = sales_api.quote_return()

		self.assertTrue(result["ok"], result)
		quote = result["data"]["return_quote"]
		self.assertEqual(quote["source_name"], sale["summary"]["name"])
		self.assertEqual(quote["grand_total"], "-100.0")
		self.assertEqual(quote["refund_amount"], "100.0")
		self.assertEqual(
			quote["refund_allocations"],
			[{"mode_of_payment": "Cash", "amount": "-100.0", "reference_no": None}],
		)
		self.assertEqual(quote["selected_refund_mode"], "Cash")
		self.assertEqual(frappe.db.count("POS Invoice"), before_invoices)
		self.assertEqual(frappe.db.count("Mobile POS Request"), before_requests)

	def test_create_return_owns_refund_allocation_and_receipt(self):
		sale = self._submit(qty="2", total="200")
		key = str(uuid4())
		payload = {
			"source_name": sale["summary"]["name"],
			"reason": " Damaged package ",
			"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
		}

		frappe.local.form_dict = frappe._dict(payload)
		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertTrue(result["ok"], result)
		receipt = result["data"]["return_sale"]
		self.assertEqual(receipt["return_against"], sale["summary"]["name"])
		self.assertEqual(receipt["return_reason"], "Damaged package")
		self.assertEqual(receipt["refund_amount"], "100.0")
		self.assertEqual(receipt["summary"]["grand_total"], "-100.0")
		self.assertEqual(receipt["summary"]["outstanding_amount"], "0")
		self.assertEqual(
			receipt["refund_allocations"],
			[{"mode_of_payment": "Cash", "amount": "-100.0", "reference_no": None}],
		)
		self.assertEqual(
			frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key, "docstatus": 1}),
			1,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 1)

	def test_multiple_refund_modes_require_an_allowed_selection(self):
		sale = self._submit(qty="2", total="200")
		self._add_bank_refund_mode()
		base = {
			"source_name": sale["summary"]["name"],
			"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
		}

		missing = self._quote_return(base)
		self.assertFalse(missing["ok"])
		self.assertEqual(missing["error"]["details"]["reason"], "required_for_multiple_refund_modes")
		rejected = self._quote_return({**base, "refund_mode": "Not Allowed"})
		self.assertEqual(rejected["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(rejected["error"]["details"]["reason"], "refund_mode_not_allowed")
		accepted = self._quote_return({**base, "refund_mode": "Bank Draft"})
		self.assertTrue(accepted["ok"], accepted)
		self.assertEqual(
			accepted["data"]["return_quote"]["refund_allocations"][0]["mode_of_payment"],
			"Bank Draft",
		)

	def test_no_refund_mode_rejects_without_artifacts(self):
		sale = self._submit(qty="1", total="100")
		frappe.set_user("Administrator")
		self.profile.reload()
		for payment in self.profile.payments:
			payment.allow_in_returns = 0
		self.profile.save(ignore_permissions=True)
		frappe.set_user(self.cashier)
		returnability = sales_api.get(name=sale["summary"]["name"])["data"]["sale"]["items"][0][
			"returnability"
		]
		self.assertFalse(returnability["eligible"])
		self.assertEqual(returnability["rejection_reason"], "NO_VALID_REFUND_MODE")
		key = str(uuid4())
		before = frappe.db.count("POS Invoice")
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "PROFILE_CONFIGURATION_INVALID")
		self.assertEqual(result["error"]["details"]["reason"], "no_valid_refund_mode")
		self.assertEqual(frappe.db.count("POS Invoice"), before)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_refund_mode_without_company_account_is_not_allowed(self):
		sale = self._submit(qty="1", total="100")
		frappe.set_user("Administrator")
		frappe.db.delete("Mode of Payment Account", {"parent": "Cash", "company": COMPANY})
		frappe.set_user(self.cashier)
		key = str(uuid4())
		before = frappe.db.count("POS Invoice")
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "PROFILE_CONFIGURATION_INVALID")
		self.assertEqual(result["error"]["details"]["reason"], "no_valid_refund_mode")
		self.assertEqual(frappe.db.count("POS Invoice"), before)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_create_return_rejects_client_accounting_fields(self):
		sale = self._submit(qty="1", total="100")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
				"payments": [{"mode_of_payment": "Cash", "amount": "-1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "payments")
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_create_return_rejects_duplicate_source_rows_without_artifacts(self):
		sale = self._submit(qty="2", total="200")
		key = str(uuid4())
		row = {"source_item_row": sale["items"][0]["row_id"], "qty": "1"}
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [row, row],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "items")
		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_return_limit_error_tells_android_to_refresh(self):
		sale = self._submit(qty="2", total="200")
		self._create_return(sale, qty="1")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "2"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "RETURN_LIMIT_EXCEEDED")
		self.assertEqual(
			result["error"]["details"],
			{
				"source_name": sale["summary"]["name"],
				"source_item_row": sale["items"][0]["row_id"],
				"requested_qty": "2",
				"remaining_qty": "1.0",
				"refresh_endpoint": "v1.sales.get",
			},
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_partial_serial_return_is_rejected_without_artifacts(self):
		sale = self._submit(qty="2", total="200")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with (
			patch("frappe.get_request_header", return_value=key),
			patch.object(invoices, "_is_serialized_item", return_value=True),
		):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "INVALID_SERIAL_NUMBER")
		self.assertEqual(result["error"]["details"]["reason"], "partial_serial_return_not_supported")
		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_return_replay_has_one_return_and_one_request(self):
		sale = self._submit(qty="2", total="200")
		key = str(uuid4())
		payload = {
			"source_name": sale["summary"]["name"],
			"reason": "Damaged",
			"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
		}

		with patch("frappe.get_request_header", return_value=key):
			frappe.local.form_dict = frappe._dict(payload)
			first = sales_api.create_return()
			frappe.local.form_dict = frappe._dict(payload)
			second = sales_api.create_return()

		self.assertEqual(first["data"], second["data"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])
		self.assertEqual(
			frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key, "docstatus": 1}), 1
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 1)

	def test_return_requires_reason_before_idempotency(self):
		sale = self._submit(qty="1", total="100")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "reason")
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_return_requires_current_cashier_source_scope(self):
		sale = self._submit(qty="1", total="100")
		frappe.db.set_value("POS Invoice", sale["summary"]["name"], "owner", "other@example.com")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "RESOURCE_NOT_FOUND")
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_return_requires_active_opening_without_artifacts(self):
		sale = self._submit(qty="1", total="100")
		frappe.db.set_value("POS Opening Entry", self.opening, "status", "Closed")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with patch("frappe.get_request_header", return_value=key):
			result = sales_api.create_return()

		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_return_submit_failure_rolls_back_all_artifacts(self):
		sale = self._submit(qty="1", total="100")
		key = str(uuid4())
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
			}
		)

		with (
			patch("frappe.get_request_header", return_value=key),
			patch("roti_ropi_pos.overrides.pos_invoice.MobilePOSInvoice.submit", side_effect=RuntimeError),
			self.assertRaises(RuntimeError),
		):
			sales_api.create_return()

		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_distinct_keys_cannot_concurrently_over_return(self):
		self.assertEqual(
			frappe.db.sql("SELECT @@transaction_isolation")[0][0].upper(),
			"REPEATABLE-READ",
		)
		sale = self._submit(qty="1", total="100")
		payload = {
			"source_name": sale["summary"]["name"],
			"reason": "Damaged",
			"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": "1"}],
		}
		keys = [str(uuid4()), str(uuid4())]
		user = frappe.session.user
		request = getattr(frappe.local, "request", None)
		site = frappe.local.site
		frappe.db.commit()
		barrier = Barrier(2)
		try:
			with ThreadPoolExecutor(max_workers=2) as executor:
				results = [
					future.result(timeout=30)
					for future in [
						executor.submit(_run_return_attempt, site, user, payload, key, barrier)
						for key in keys
					]
				]
		finally:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(user)
			if request is not None:
				frappe.local.request = request

		self.assertEqual(sum(result["ok"] for result in results), 1)
		self.assertEqual(
			[result["error"]["code"] for result in results if not result["ok"]],
			["RETURN_LIMIT_EXCEEDED"],
		)
		self.assertEqual(
			frappe.db.count(
				"POS Invoice",
				{"return_against": sale["summary"]["name"], "is_return": 1, "docstatus": 1},
			),
			1,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": ["in", keys]}), 1)

	def _submit(self, *, qty: str, total: str) -> dict:
		payload = {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": total,
			"items": [
				{
					"item_code": self.item,
					"qty": qty,
					"uom": self.uom,
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": total, "reference_no": None}],
		}
		frappe.local.form_dict = frappe._dict(payload)
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = sales_api.submit()
		self.assertTrue(result["ok"], result)
		return result["data"]["sale"]

	def _create_return(self, sale: dict, *, qty: str) -> dict:
		frappe.local.form_dict = frappe._dict(
			{
				"source_name": sale["summary"]["name"],
				"reason": "Damaged",
				"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": qty}],
			}
		)
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = sales_api.create_return()
		self.assertTrue(result["ok"], result)
		return result["data"]["return_sale"]

	def _quote_return(self, payload: dict) -> dict:
		frappe.local.form_dict = frappe._dict(payload)
		return sales_api.quote_return()

	def _add_bank_refund_mode(self) -> None:
		frappe.set_user("Administrator")
		set_default_account_for_mode_of_payment(
			frappe.get_doc("Mode of Payment", "Bank Draft"), COMPANY, "_Test Bank - _TC"
		)
		self.profile.reload()
		self.profile.append("payments", {"mode_of_payment": "Bank Draft", "allow_in_returns": 1})
		self.profile.save(ignore_permissions=True)
		frappe.set_user(self.cashier)

	def _ensure_item_price(self) -> None:
		filters = {"item_code": self.item, "price_list": self.profile.selling_price_list, "uom": self.uom}
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
				"item_code": self.item,
				"price_list": self.profile.selling_price_list,
				"price_list_rate": 100,
				"uom": self.uom,
			}
		).insert(ignore_permissions=True)
