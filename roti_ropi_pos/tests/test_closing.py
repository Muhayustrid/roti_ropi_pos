from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import closing as closing_api
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
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

	def test_preview_preserves_exact_decimal_payments(self):
		opening = frappe.get_doc("POS Opening Entry", self.opening)
		frappe.db.set_value(
			"POS Opening Entry Detail",
			opening.balance_details[0].name,
			"opening_amount",
			Decimal("0.1"),
			update_modified=False,
		)
		original_get_all = frappe.get_all

		def get_all(doctype, *args, **kwargs):
			if doctype == "Sales Invoice Payment":
				return [frappe._dict(mode_of_payment="Cash", amount=Decimal("0.2"))]
			return original_get_all(doctype, *args, **kwargs)

		with (
			patch(
				"roti_ropi_pos.mobile_pos.closing._eligible_invoices",
				return_value=[frappe._dict(name="X", grand_total=Decimal("0.2"))],
			),
			patch("frappe.get_all", side_effect=get_all),
		):
			result = closing_api.preview(pos_profile=self.profile.name)
		cash = result["data"]["expected_payments"][0]
		self.assertEqual(cash["opening_amount"], "0.1")
		self.assertEqual(cash["expected_amount"], "0.3")

	def test_submit_rejects_non_finite_closing_amount(self):
		for amount in ("NaN", "Infinity"):
			with self.subTest(amount=amount):
				result = self._close(str(uuid4()), amount=amount)
				self.assertFalse(result["ok"])
				self.assertEqual(result["error"]["code"], "INVALID_REQUEST")

	def test_closing_parser_accepts_zero_amount(self):
		payload = closing_api._parse_closing_payload(self._closing_payload(amount="0"))
		self.assertEqual(payload["closing_balances"][0]["closing_amount"], Decimal("0"))

	def test_closing_parser_rejects_negative_amount(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			closing_api._parse_closing_payload(self._closing_payload(amount="-1"))
		self.assertEqual(error.exception.details["reason"], "negative_amount")

	def test_closing_parser_rejects_malformed_amount(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			closing_api._parse_closing_payload(self._closing_payload(amount="not-a-number"))
		self.assertEqual(error.exception.details["reason"], "malformed_decimal")

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
		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")
		self.assertEqual(result["error"]["details"], {"pos_profile": self.profile.name})

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

	def test_submit_sync_path_survives_core_commit_and_completes_request(self):
		self._submit_sale()
		key = str(uuid4())
		with patch.object(frappe, "in_test", False):
			first = self._close(key)
			replay = self._close(key)

		self.assertTrue(first["ok"], first)
		self.assertEqual(first["data"]["closing"]["status"], "submitted")
		self.assertEqual(replay["data"]["closing"]["name"], first["data"]["closing"]["name"])
		self.assertTrue(replay["meta"]["replayed"])
		request = frappe.get_doc("Mobile POS Request", {"idempotency_key": key})
		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.reference_name, first["data"]["closing"]["name"])
		self.assertIsNone(request.lease_expires_at)

	def test_submit_commits_recovery_phases_before_submit(self):
		self._submit_sale()
		states = []

		def capture_commit():
			request = frappe.get_all(
				"Mobile POS Request",
				filters={"endpoint": "v1.closing.submit"},
				fields=["phase", "reference_name"],
				order_by="creation desc",
				limit=1,
			)
			states.append((request[0].phase, request[0].reference_name) if request else (None, None))

		with patch.object(frappe.db, "commit", side_effect=capture_commit):
			result = self._close(str(uuid4()))
		self.assertTrue(result["ok"], result)
		self.assertIn(("Reserved", None), states)
		self.assertTrue(any(phase == "DraftCreated" and reference for phase, reference in states))
		self.assertTrue(any(phase == "SubmitStarted" and reference for phase, reference in states))

	def test_submit_locks_opening_before_invoice_snapshot(self):
		order = []
		with (
			patch(
				"roti_ropi_pos.mobile_pos.closing._lock_opening",
				side_effect=lambda _name: order.append("lock"),
			),
			patch(
				"roti_ropi_pos.mobile_pos.closing._eligible_invoices",
				side_effect=lambda _opening: order.append("invoices") or [],
			),
		):
			result = self._close(str(uuid4()))
		self.assertIn("ok", result)
		self.assertLess(order.index("lock"), order.index("invoices"))

	def test_unexpired_processing_request_returns_in_progress(self):
		from roti_ropi_pos.mobile_pos.idempotency import (
			_create_processing_request,
			_scope_key,
			canonical_hash,
		)

		key = str(uuid4())
		payload = self._closing_payload()
		request = _create_processing_request(
			_scope_key(key, "v1.closing.submit"),
			key,
			"v1.closing.submit",
			canonical_hash("v1.closing.submit", payload),
		)
		request.phase = "Reserved"
		request.lease_expires_at = frappe.utils.now_datetime() + timedelta(minutes=1)
		request.save(ignore_permissions=True)
		frappe.db.commit()

		result = self._close(key)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "REQUEST_IN_PROGRESS")
		self.assertTrue(result["error"]["retryable"])
		self.assertEqual(
			result["error"]["details"],
			{"endpoint": "v1.closing.submit", "retry_after_seconds": 1},
		)

	def test_expired_draft_request_resumes_same_closing(self):
		from roti_ropi_pos.mobile_pos.closing import _create_closing_draft
		from roti_ropi_pos.mobile_pos.idempotency import (
			_create_processing_request,
			_scope_key,
			canonical_hash,
		)

		key = str(uuid4())
		payload = self._closing_payload()
		request = _create_processing_request(
			_scope_key(key, "v1.closing.submit"),
			key,
			"v1.closing.submit",
			canonical_hash("v1.closing.submit", payload),
		)
		request.phase = "Reserved"
		request.lease_expires_at = frappe.utils.now_datetime() - timedelta(seconds=1)
		request.save(ignore_permissions=True)
		closing = _create_closing_draft(self.profile, payload, key)
		request.reference_doctype = "POS Closing Entry"
		request.reference_name = closing.name
		request.phase = "SubmitStarted"
		request.flags.ignore_links = True
		request.save(ignore_permissions=True)
		frappe.db.commit()

		def submit_existing(name):
			frappe.db.set_value(
				"POS Closing Entry",
				name,
				{"docstatus": 1, "status": "Submitted"},
				update_modified=False,
			)

		with patch(
			"roti_ropi_pos.mobile_pos.closing._submit_persisted_closing",
			side_effect=submit_existing,
		) as submit:
			result = self._close(key)
		submit.assert_called_once_with(closing.name)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["data"]["closing"]["name"], closing.name)
		self.assertEqual(
			frappe.db.count("POS Closing Entry", {"custom_mobile_pos_transaction_id": key}),
			1,
		)

	def test_rejected_closing_replays_stored_error(self):
		key = str(uuid4())
		with patch(
			"roti_ropi_pos.mobile_pos.closing._submit_persisted_closing",
			side_effect=frappe.ValidationError("invalid close"),
		):
			first = self._close(key)
			replay = self._close(key)
		self.assertFalse(first["ok"])
		self.assertFalse(replay["ok"])
		self.assertEqual(first["error"]["code"], "INVALID_REQUEST")
		self.assertTrue(replay["meta"]["replayed"])
		request = frappe.get_doc("Mobile POS Request", {"idempotency_key": key})
		self.assertEqual(request.status, "Rejected")
		self.assertIsNone(request.lease_expires_at)

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
		self.assertIn(result["error"]["code"], {"PERMISSION_ERROR", "NO_OPEN_SESSION", "PERMISSION_DENIED"})

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

	def test_queued_consolidation_uses_internal_identity_and_restores_cashier(self):
		from roti_ropi_pos.mobile_pos.closing import ensure_committed_closing_job

		closing = MagicMock(docstatus=1, status="Queued")
		users = []
		with (
			patch("frappe.get_doc", return_value=closing),
			patch(
				"erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log."
				"consolidate_pos_invoices",
				side_effect=lambda **_kwargs: users.append(frappe.session.user),
			),
		):
			ensure_committed_closing_job("TEST-CLO")

		self.assertEqual(users, ["Administrator"])
		self.assertEqual(frappe.session.user, self.cashier)

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
		self.assertIn(
			result["error"]["code"],
			{"PERMISSION_DENIED", "PROFILE_SCOPE_MISMATCH", "NOT_FOUND"},
		)

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

	def _closing_payload(self, amount="500100"):
		return {
			"pos_profile": self.profile.name,
			"closing_balances": [{"mode_of_payment": "Cash", "closing_amount": amount}],
		}

	def _close(self, idempotency_key: str, *, amount="500100"):
		with patch("frappe.get_request_header", return_value=idempotency_key):
			frappe.local.form_dict = frappe._dict(self._closing_payload(amount))
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
