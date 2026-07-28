from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import closing as closing_api
from roti_ropi_pos.tests.helpers import close_test_openings, make_cashier, make_opening_entry
from roti_ropi_pos.tests.test_sessions import COMPANY, WAREHOUSE, make_valid_profile

ITEM = "_Test Item"


class TestClosingPreview(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"closing-{frappe.generate_hash(length=8)}@rotiropi.test")
		frappe.db.set_value("User", self.cashier, "user_type", "System User")
		frappe.cache.delete_value(f"user_permissions:{self.cashier}")
		frappe.cache.hdel("roles", self.cashier)
		self.profile = make_valid_profile(
			f"Mobile POS Closing {frappe.generate_hash(length=8)}", self.cashier
		)
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		self.profile.append("item_groups", {"item_group": frappe.db.get_value("Item", ITEM, "item_group")})
		self.profile.save(ignore_permissions=True)
		self._ensure_item_price()
		make_stock_entry(target=WAREHOUSE, item_code=ITEM, qty=20, basic_rate=100)
		self.opening = make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
			balances=[{"mode_of_payment": "Cash", "opening_amount": "500000"}],
		)
		frappe.set_user(self.cashier)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def test_preview_returns_opening_session_and_empty_invoice_count(self):
		result = closing_api.preview(pos_profile=self.profile.name)
		self.assertTrue(result["ok"])
		data = result["data"]
		self.assertIn("opening_session", data)
		self.assertEqual(data["opening_session"]["pos_profile"], self.profile.name)
		self.assertEqual(data["invoice_count"], 0)
		self.assertIn("grand_total", data)
		self.assertIn("expected_payments", data)

	def test_preview_aggregates_submitted_invoices(self):
		self._submit_sale()
		self._submit_sale()
		result = closing_api.preview(pos_profile=self.profile.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["invoice_count"], 2)
		self.assertEqual(Decimal(result["data"]["grand_total"]), Decimal("200"))

	def test_preview_excludes_consolidated_invoices(self):
		inv_name = self._submit_sale()["data"]["sale"]["summary"]["name"]
		# mark as already consolidated
		frappe.db.set_value("POS Invoice", inv_name, "consolidated_invoice", "FAKE-SINV-001")
		result = closing_api.preview(pos_profile=self.profile.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["invoice_count"], 0)

	def test_preview_expected_payments_combine_opening_and_sales(self):
		self._submit_sale()
		result = closing_api.preview(pos_profile=self.profile.name)
		payments = result["data"]["expected_payments"]
		cash = next(p for p in payments if p["mode_of_payment"] == "Cash")
		self.assertEqual(Decimal(cash["opening_amount"]), Decimal("500000"))
		self.assertEqual(Decimal(cash["expected_amount"]), Decimal("500100"))

	def test_preview_stale_opening_warning_preserved(self):
		frappe.db.set_value(
			"POS Opening Entry",
			self.opening,
			"period_start_date",
			"2026-07-01 08:00:00",
			update_modified=False,
		)
		result = closing_api.preview(pos_profile=self.profile.name)
		warnings = result["data"]["opening_session"]["warnings"]
		self.assertTrue(any(w["code"] == "STALE_OPENING" for w in warnings))

	def test_preview_requires_active_opening(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("POS Opening Entry", self.opening, "status", "Closed", update_modified=False)
		frappe.set_user(self.cashier)
		result = closing_api.preview(pos_profile=self.profile.name)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NO_ACTIVE_SESSION")

	def test_preview_requires_pos_profile(self):
		result = closing_api.preview(pos_profile=None)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

	# ── submit (sync path: < 10 invoices) ───────────────────────────────

	def test_submit_creates_closing_entry_and_returns_closing_dto(self):
		self._submit_sale()
		key = str(uuid4())
		result = self._close(key)
		self.assertTrue(result["ok"], result)
		closing = result["data"]["closing"]
		self.assertIn(closing["status"], {"draft", "submitted"})
		self.assertEqual(closing["invoice_count"], 1)
		self.assertIsNone(closing["failure"])
		self.assertIn("name", closing)
		self.assertIn("opening_entry", closing)
		self.assertEqual(closing["pos_profile"], self.profile.name)

	def test_submit_replay_returns_same_reference(self):
		self._submit_sale()
		key = str(uuid4())
		first = self._close(key)
		second = self._close(key)
		self.assertTrue(first["ok"])
		self.assertTrue(second["ok"])
		self.assertEqual(first["data"]["closing"]["name"], second["data"]["closing"]["name"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])

	def test_submit_requires_closing_entry_create_permission(self):
		self._submit_sale()
		frappe.set_user("Administrator")
		plain_user = frappe.db.get_value("User", {"user_type": "Website User", "enabled": 1}, "name")
		if not plain_user:
			plain_user = make_cashier(f"noperm-{frappe.generate_hash(8)}@rotiropi.test")
		# remove Mobile POS Cashier role to drop POS Closing Entry permission
		frappe.db.delete("Has Role", {"parent": plain_user, "role": "Mobile POS Cashier"})
		frappe.cache.hdel("roles", plain_user)
		frappe.set_user(plain_user)
		result = self._close(str(uuid4()))
		self.assertFalse(result["ok"])
		self.assertIn(result["error"]["code"], {"PERMISSION_ERROR", "NO_ACTIVE_SESSION", "PERMISSION_DENIED"})

	# ── submit (queued path: >= 10 invoices) ────────────────────────────

	def test_submit_queued_path_deferred_enqueue_after_commit(self):
		"""Boundary: >= 10 invoices triggers queued consolidation.

		frappe.in_test executes enqueued jobs immediately, so patch enqueue
		to a spy rather than let it run — the test verifies the enqueue boundary,
		not real consolidation (that lives in ERPNext's own test suite).
		"""
		for _ in range(10):
			self._submit_sale()

		enqueue_calls = []

		def _capture_enqueue(*args, **kwargs):
			enqueue_calls.append((args, kwargs))

		with patch(
			"roti_ropi_pos.mobile_pos.closing.ensure_committed_closing_job",
			side_effect=_capture_enqueue,
		):
			key = str(uuid4())
			result = self._close(key)

		self.assertTrue(result["ok"], result)
		closing = result["data"]["closing"]
		# queued status expected for >= 10 invoices before consolidation runs
		self.assertEqual(closing["status"], "queued")
		self.assertEqual(closing["invoice_count"], 10)

	# ── status ───────────────────────────────────────────────────────────

	def test_status_returns_closing_dto_by_name(self):
		self._submit_sale()
		closing_name = self._close(str(uuid4()))["data"]["closing"]["name"]
		frappe.set_user(self.cashier)
		result = closing_api.status(name=closing_name)
		self.assertTrue(result["ok"])
		self.assertIn(result["data"]["closing"]["status"], {"draft", "queued", "submitted"})

	def test_status_maps_failed_without_exposing_error_message(self):
		self._submit_sale()
		closing_name = self._close(str(uuid4()))["data"]["closing"]["name"]
		frappe.db.set_value("POS Closing Entry", closing_name, "status", "Failed")
		frappe.db.set_value("POS Closing Entry", closing_name, "error_message", "SECRET internal traceback")
		frappe.set_user(self.cashier)
		result = closing_api.status(name=closing_name)
		self.assertTrue(result["ok"])
		closing_dto = result["data"]["closing"]
		self.assertEqual(closing_dto["status"], "failed")
		self.assertIsNotNone(closing_dto["failure"])
		self.assertEqual(closing_dto["failure"]["code"], "CLOSING_FAILED")
		self.assertNotIn("SECRET", str(closing_dto))

	def test_status_requires_name(self):
		result = closing_api.status(name=None)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

	def test_status_scoped_to_authorized_profile(self):
		"""Another cashier cannot poll a closing entry they do not own."""
		self._submit_sale()
		closing_name = self._close(str(uuid4()))["data"]["closing"]["name"]
		other = make_cashier(f"other-{frappe.generate_hash(8)}@rotiropi.test")
		frappe.set_user(other)
		result = closing_api.status(name=closing_name)
		self.assertFalse(result["ok"])
		self.assertIn(result["error"]["code"], {"PERMISSION_ERROR", "NOT_FOUND"})

	# ── source-contract boundary ─────────────────────────────────────────

	def test_on_submit_sync_threshold_is_ten(self):
		"""on_submit calls super < 10 invoices, defers >= 10. Fails on ERPNext threshold change."""
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		import roti_ropi_pos.overrides.pos_closing_entry as _ov

		class _Fake(_ov.MobilePOSClosingEntry):
			pass

		def _inst(n):
			obj = object.__new__(_Fake)
			obj.pos_invoices = [object()] * n
			obj.pos_opening_entry = "TEST-OPE"
			obj.name = "TEST-CLO"
			obj.doctype = "POS Closing Entry"
			obj.docstatus = 1
			obj.status = "Submitted"
			obj.set_status = MagicMock()
			obj.update_sales_invoices_closing_entry = MagicMock()
			return obj

		with patch.object(POSClosingEntry, "on_submit") as super_mock:
			_Fake.on_submit(_inst(9))
			super_mock.assert_called_once()

		captured = []
		with (
			patch.object(POSClosingEntry, "on_submit") as super_mock2,
			patch.object(_ov, "ensure_committed_closing_job") as enqueue_mock,
			patch("frappe.publish_realtime"),
			patch.object(frappe.db, "after_commit", MagicMock(add=lambda fn: captured.append(fn))),
		):
			_Fake.on_submit(_inst(10))
			super_mock2.assert_not_called()
			for fn in captured:
				fn()
			enqueue_mock.assert_called_once()

	# ── helpers ──────────────────────────────────────────────────────────

	def _submit_sale(self):
		from unittest.mock import patch as _patch

		from roti_ropi_pos.api.v1 import sales as sales_api

		payload = {
			"pos_profile": self.profile.name,
			"customer": self.profile.customer,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": "100",
			"items": [
				{
					"item_code": ITEM,
					"qty": "1",
					"uom": frappe.db.get_value("Item", ITEM, "stock_uom"),
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": "100", "reference_no": None}],
		}
		with _patch("frappe.get_request_header", return_value=str(uuid4())):
			frappe.local.form_dict = frappe._dict(payload)
			return sales_api.submit()

	def _close(self, idempotency_key: str):
		payload = {
			"pos_profile": self.profile.name,
			"closing_balances": [{"mode_of_payment": "Cash", "closing_amount": "500100"}],
		}
		with patch("frappe.get_request_header", return_value=idempotency_key):
			frappe.local.form_dict = frappe._dict(payload)
			return closing_api.submit()

	def _ensure_item_price(self) -> None:
		uom = frappe.db.get_value("Item", ITEM, "stock_uom")
		filters = {"item_code": ITEM, "price_list": self.profile.selling_price_list, "uom": uom}
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
				"uom": uom,
			}
		).insert(ignore_permissions=True)
