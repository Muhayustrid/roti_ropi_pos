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
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.invoices import submit_sale
from roti_ropi_pos.tests.helpers import close_test_openings, make_cashier, make_opening_entry
from roti_ropi_pos.tests.test_sessions import COMPANY, WAREHOUSE, make_valid_profile


def _run_sale_attempt(site, user, payload, key, barrier):
	frappe.init(site=site)
	frappe.connect()
	try:
		frappe.set_user(user)
		barrier.wait(timeout=10)
		for _ in range(2):
			frappe.local.form_dict = frappe._dict(payload)
			frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
			try:
				result = sales_api.submit()
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				continue
			if not result["ok"]:
				frappe.db.rollback()
				return {
					"error_code": result["error"]["code"],
					"retryable": result["error"]["retryable"],
				}
			frappe.db.commit()
			return result
		raise AssertionError("Sale transaction deadlocked twice.")
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


class TestSaleSubmit(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"sales-{frappe.generate_hash(length=8)}@rotiropi.test")
		self._clear_user_permissions(self.cashier)
		self.profile = make_valid_profile(f"Mobile POS Sale {frappe.generate_hash(length=8)}", self.cashier)
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
		self.profile.save(ignore_permissions=True)
		self._ensure_item_price()
		make_stock_entry(target=WAREHOUSE, item_code=self.item, qty=10, basic_rate=100)
		frappe.set_user(self.cashier)
		self.assertTrue(frappe.has_permission("POS Invoice", ptype="create"))
		self.assertTrue(frappe.has_permission("POS Invoice", ptype="submit"))
		self.assertTrue(frappe.has_permission("Item", ptype="read"))
		self.assertTrue(frappe.has_permission("Customer", ptype="read"))
		self.assertTrue(frappe.has_permission("Item", ptype="read", doc=frappe.get_doc("Item", self.item)))
		self.assertTrue(
			frappe.has_permission(
				"Customer", ptype="read", doc=frappe.get_doc("Customer", self.profile.customer)
			)
		)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def test_sale_parser_accepts_normal_item_and_payment_lists(self):
		payload = sales_api._parse_sale_payload(self._payload())
		self.assertEqual(payload["items"][0]["item_code"], self.item)
		self.assertEqual(payload["payments"][0]["amount"], Decimal("100"))

	def test_submit_creates_paid_invoice_with_zero_outstanding(self):
		result = self._submit()
		invoice = frappe.get_doc("POS Invoice", result["data"]["sale"]["summary"]["name"])
		self.assertEqual(invoice.docstatus, 1)
		self.assertEqual(invoice.status, "Paid")
		self.assertEqual(Decimal(str(invoice.outstanding_amount)), Decimal("0"))

	def test_price_changed_returns_error_and_no_invoice(self):
		payload = self._payload(client_accepted_grand_total="999")
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "PRICE_CHANGED")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_underpayment_returns_invalid_payment(self):
		payload = self._payload(payments=[{"mode_of_payment": "Cash", "amount": "1", "reference_no": None}])
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_distinct_profile_payment_modes_can_fully_settle(self):
		frappe.set_user("Administrator")
		set_default_account_for_mode_of_payment(
			frappe.get_doc("Mode of Payment", "Bank Draft"), COMPANY, "_Test Bank - _TC"
		)
		self.profile.append("payments", {"mode_of_payment": "Bank Draft"})
		self.profile.save(ignore_permissions=True)
		frappe.set_user(self.cashier)
		result = self._submit(
			payments=[
				{"mode_of_payment": "Cash", "amount": "40", "reference_no": None},
				{"mode_of_payment": "Bank Draft", "amount": "60", "reference_no": "REF-1"},
			]
		)
		invoice = frappe.get_doc("POS Invoice", result["data"]["sale"]["summary"]["name"])
		self.assertEqual(invoice.outstanding_amount, 0)
		self.assertEqual({row.mode_of_payment for row in invoice.payments}, {"Cash", "Bank Draft"})

	def test_insufficient_stock_rolls_back_invoice_and_request(self):
		payload = self._payload(
			client_accepted_grand_total="100000000",
			items=[{**self._payload()["items"][0], "qty": "1000000"}],
			payments=[{"mode_of_payment": "Cash", "amount": "100000000", "reference_no": None}],
		)
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INSUFFICIENT_STOCK")
		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_unknown_batch_rolls_back_invoice_and_request(self):
		payload = self._payload(items=[{**self._payload()["items"][0], "batch_no": "MISSING-BATCH"}])
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_BATCH")
		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_unknown_serial_rolls_back_invoice_and_request(self):
		payload = self._payload(items=[{**self._payload()["items"][0], "serial_numbers": ["MISSING-SERIAL"]}])
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_SERIAL_NUMBER")
		self.assertEqual(frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}), 0)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_batch_tracked_item_requires_batch_selection(self):
		with patch("frappe.get_cached_value", return_value=frappe._dict(has_batch_no=1, has_serial_no=0)):
			result = self._submit()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_BATCH")
		self.assertEqual(result["error"]["details"]["reason"], "batch_required")

	def test_serialized_item_requires_serial_selection(self):
		with patch("frappe.get_cached_value", return_value=frappe._dict(has_batch_no=0, has_serial_no=1)):
			result = self._submit()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_SERIAL_NUMBER")
		self.assertEqual(result["error"]["details"]["reason"], "serial_numbers_required")

	def test_server_owned_fields_are_rejected(self):
		payload = self._payload()
		payload["items"][0]["rate"] = "1"
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "rate")

	def test_no_open_session_returns_error(self):
		frappe.db.delete("POS Opening Entry", {"name": self.opening})
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = self._endpoint(self._payload())
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")

	def test_prior_day_opening_can_submit_sale(self):
		frappe.db.set_value(
			"POS Opening Entry",
			self.opening,
			"period_start_date",
			frappe.utils.add_days(frappe.utils.now_datetime(), -1),
		)
		result = self._submit()
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["sale"]["summary"]["status"], "paid")

	def test_requires_pos_invoice_create_and_submit_permission(self):
		has_permission = frappe.has_permission

		def deny_invoice_create(doctype=None, ptype="read", **kwargs):
			if doctype == "POS Invoice" and ptype == "create":
				return False
			return has_permission(doctype, ptype=ptype, **kwargs)

		with (
			patch("frappe.has_permission", side_effect=deny_invoice_create),
			self.assertRaises(MobilePOSAPIError) as error,
		):
			submit_sale(self._payload(), str(uuid4()))
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")

	def test_idempotent_replay_returns_same_result(self):
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			first = self._endpoint(self._payload())
			self.assertEqual(frappe.response["http_status_code"], 201)
			second = self._endpoint(self._payload())
		self.assertEqual(first["data"], second["data"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])
		self.assertEqual(frappe.response["http_status_code"], 200)
		self.assertEqual(
			frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key}),
			1,
		)

	def test_twenty_concurrent_attempts_create_one_invoice_and_request(self):
		user = frappe.session.user
		request = getattr(frappe.local, "request", None)
		key = str(uuid4())
		payload = self._payload()
		site = frappe.local.site
		frappe.db.commit()
		barrier = Barrier(20)
		try:
			with ThreadPoolExecutor(max_workers=20) as executor:
				futures = [
					executor.submit(_run_sale_attempt, site, user, payload, key, barrier) for _ in range(20)
				]
				results = [future.result(timeout=30) for future in futures]
		finally:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(user)
			if request is not None:
				frappe.local.request = request
		responses = [result for result in results if "meta" in result]
		in_progress = [result for result in results if result.get("error_code") == "REQUEST_IN_PROGRESS"]
		self.assertEqual(len(responses) + len(in_progress), 20)
		self.assertEqual(
			frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key, "docstatus": 1}), 1
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 1)

	def test_distinct_keys_cannot_oversell_same_stock(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability

		available, _, _ = get_stock_availability(self.item, WAREHOUSE)
		qty = Decimal(str(available))
		self.assertGreater(qty, 0)
		total = qty * Decimal("100")
		payload = self._payload(
			client_accepted_grand_total=format(total, "f"),
			items=[{**self._payload()["items"][0], "qty": format(qty, "f")}],
			payments=[{"mode_of_payment": "Cash", "amount": format(total, "f"), "reference_no": None}],
		)
		user = frappe.session.user
		request = getattr(frappe.local, "request", None)
		site = frappe.local.site
		keys = [str(uuid4()), str(uuid4())]
		frappe.db.commit()
		barrier = Barrier(2)
		try:
			with ThreadPoolExecutor(max_workers=2) as executor:
				futures = [
					executor.submit(_run_sale_attempt, site, user, payload, key, barrier) for key in keys
				]
				results = [future.result(timeout=30) for future in futures]
		finally:
			frappe.init(site=site)
			frappe.connect()
			frappe.set_user(user)
			if request is not None:
				frappe.local.request = request
		self.assertEqual(sum(result.get("ok", False) for result in results), 1)
		self.assertEqual(
			frappe.db.count(
				"POS Invoice", {"custom_mobile_pos_transaction_id": ["in", keys], "docstatus": 1}
			),
			1,
		)

	def test_walk_in_name_is_accepted_for_default_customer(self):
		result = self._submit(walk_in_customer_name="Ayu")
		invoice = frappe.get_doc("POS Invoice", result["data"]["sale"]["summary"]["name"])
		self.assertEqual(invoice.custom_walk_in_customer_name, "Ayu")

	def test_walk_in_name_is_rejected_for_non_walk_in_customer(self):
		customer = frappe.db.get_value(
			"Customer", {"disabled": 0, "name": ["!=", self.profile.customer]}, "name"
		)
		if not customer:
			self.skipTest("No second enabled Customer is available in test site.")
		payload = self._payload(customer=customer, walk_in_customer_name="Ayu")
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			result = self._endpoint(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

	def test_history_returns_scoped_pos_invoices_and_walk_in_search(self):
		matching = self._submit(walk_in_customer_name="Ayu")
		non_matching = self._submit(walk_in_customer_name="Bima")
		frappe.db.set_value(
			"POS Invoice", non_matching["data"]["sale"]["summary"]["name"], "pos_profile", "Not This Profile"
		)
		result = self._history(pos_profile=self.profile.name, status="all", limit="101")
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["sales"], [matching["data"]["sale"]["summary"]])
		self.assertEqual(result["data"]["page"], {"start": 0, "limit": 100, "has_more": False})
		self.assertEqual(result["data"]["sales"][0]["doctype"], "POS Invoice")
		self.assertEqual(
			self._history(pos_profile=self.profile.name, status="paid", q="ayu")["data"]["sales"],
			[matching["data"]["sale"]["summary"]],
		)
		self.assertFalse(self._get_sale(non_matching["data"]["sale"]["summary"]["name"])["ok"])
		self.assertEqual(frappe.response["http_status_code"], 404)

	def test_history_requires_allowed_status_and_maps_credit_note_to_paid(self):
		sale = self._submit()["data"]["sale"]
		frappe.db.set_value("POS Invoice", sale["summary"]["name"], "status", "Credit Note Issued")
		result = self._history(pos_profile=self.profile.name, status="paid")
		self.assertEqual(result["data"]["sales"], [{**sale["summary"], "status": "paid"}])
		result = self._history(pos_profile=self.profile.name, status="bad")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["details"]["field"], "status")

	def test_history_accepts_integer_pagination_and_rejects_non_integers(self):
		result = self._history(pos_profile=self.profile.name, status="all", start="0", limit="1")
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["page"], {"start": 0, "limit": 1, "has_more": False})
		result = self._history(pos_profile=self.profile.name, status="all", start=0.5)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["details"]["field"], "start")
		result = self._history(pos_profile=self.profile.name, status="all", limit=True)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["details"]["field"], "limit")

	def test_return_parser_accepts_negative_payment_and_rejects_positive_payment(self):
		sale = self._submit()["data"]["sale"]
		self._allow_cash_returns()
		result = self._return(self._return_payload(sale, qty="1", amount="-100"))
		self.assertTrue(result["ok"])
		self.assertIn("return_sale", result["data"])
		self.assertNotIn("sale", result["data"])
		invoice = frappe.get_doc("POS Invoice", result["data"]["return_sale"]["summary"]["name"])
		self.assertEqual(Decimal(str(invoice.payments[0].amount)), Decimal("-100"))
		result = self._return(self._return_payload(sale, qty="1", amount="100"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["details"]["field"], "amount")

	def test_sale_detail_maps_credit_note_issued_to_paid(self):
		result = self._submit()
		name = result["data"]["sale"]["summary"]["name"]
		frappe.db.set_value("POS Invoice", name, "status", "Credit Note Issued")
		detail = self._get_sale(name)
		self.assertTrue(detail["ok"])
		self.assertEqual(detail["data"]["sale"]["summary"]["status"], "paid")

	def test_return_creates_partial_refund_with_reason(self):
		sale = self._two_item_sale()
		frappe.db.set_value("POS Invoice", sale["summary"]["name"], "remarks", "Original remark")
		self._allow_cash_returns()
		result = self._return(self._return_payload(sale, qty="1", amount="-100"))
		self.assertTrue(result["ok"])
		invoice = frappe.get_doc("POS Invoice", result["data"]["return_sale"]["summary"]["name"])
		self.assertTrue(invoice.is_return)
		self.assertEqual(invoice.return_against, sale["summary"]["name"])
		self.assertEqual(Decimal(str(invoice.items[0].qty)), Decimal("-1"))
		self.assertEqual(Decimal(str(invoice.payments[0].amount)), Decimal("-100"))
		self.assertEqual(invoice.remarks.count("Original remark"), 1)
		self.assertEqual(invoice.remarks.count("Mobile POS Return Reason: Damaged"), 1)

	def test_return_rejects_qty_beyond_core_remaining_quantity(self):
		sale = self._two_item_sale()
		self._allow_cash_returns()
		self._return(self._return_payload(sale, qty="1", amount="-100"))
		result = self._return(self._return_payload(sale, qty="2", amount="-200"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "RETURN_LIMIT_EXCEEDED")
		self.assertEqual(
			result["error"]["details"],
			{
				"source_item_row": sale["items"][0]["row_id"],
				"requested_qty": "2",
				"remaining_qty": "1.0",
			},
		)

	def test_return_rejects_disallowed_or_unsettled_refund_payments(self):
		sale = self._submit()["data"]["sale"]
		result = self._return(self._return_payload(sale, qty="1", amount="-100"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self._allow_cash_returns()
		result = self._return(self._return_payload(sale, qty="1", amount="-99"))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")

	def test_return_replay_returns_same_reference(self):
		sale = self._submit()["data"]["sale"]
		self._allow_cash_returns()
		payload = self._return_payload(sale, qty="1", amount="-100")
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			first = self._return_endpoint(payload)
			second = self._return_endpoint(payload)
		self.assertTrue(first["ok"])
		self.assertEqual(first["data"], second["data"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])
		self.assertEqual(
			frappe.db.count("POS Invoice", {"custom_mobile_pos_transaction_id": key, "docstatus": 1}), 1
		)

	def _submit(self, **overrides):
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			return self._endpoint(self._payload(**overrides))

	def _two_item_sale(self):
		return self._submit(
			client_accepted_grand_total="200",
			items=[{**self._payload()["items"][0], "qty": "2"}],
			payments=[{"mode_of_payment": "Cash", "amount": "200", "reference_no": None}],
		)["data"]["sale"]

	def _history(self, **query):
		return sales_api.list(**query)

	def _get_sale(self, name):
		return sales_api.get(name=name)

	def _return(self, payload):
		with patch("frappe.get_request_header", return_value=str(uuid4())):
			return self._return_endpoint(payload)

	def _return_endpoint(self, payload):
		frappe.local.form_dict = frappe._dict(payload)
		return sales_api.create_return()

	def _return_payload(self, sale, *, qty, amount):
		return {
			"source_name": sale["summary"]["name"],
			"reason": " Damaged ",
			"items": [{"source_item_row": sale["items"][0]["row_id"], "qty": qty}],
			"payments": [{"mode_of_payment": "Cash", "amount": amount, "reference_no": None}],
		}

	def _allow_cash_returns(self):
		frappe.set_user("Administrator")
		self.profile.reload()
		for payment in self.profile.payments:
			if payment.mode_of_payment == "Cash":
				payment.allow_in_returns = 1
		self.profile.save(ignore_permissions=True)
		frappe.set_user(self.cashier)

	def _endpoint(self, payload):
		frappe.local.form_dict = frappe._dict(payload)
		return sales_api.submit()

	def _payload(self, **overrides):
		payload = {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": "100",
			"items": [
				{"item_code": self.item, "qty": "1", "uom": self.uom, "batch_no": None, "serial_numbers": []}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": "100", "reference_no": None}],
		}
		payload.update(overrides)
		return payload

	def _clear_user_permissions(self, user: str) -> None:
		frappe.cache.delete_value(f"user_permissions:{user}")
		frappe.cache.hdel("roles", user)

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
