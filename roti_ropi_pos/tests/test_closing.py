from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Event
from unittest.mock import MagicMock, patch
from uuid import uuid4

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import bootstrap as bootstrap_api
from roti_ropi_pos.api.v1 import closing as closing_api
from roti_ropi_pos.api.v1 import sessions as sessions_api
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.tests.helpers import close_test_openings, make_cashier, make_opening_entry
from roti_ropi_pos.tests.test_sessions import COMPANY, WAREHOUSE, make_valid_profile

ITEM = "_Test Item"


def _run_sale_during_closing(site, user, payload, transaction_id, sale_validated, closing_finished):
	from roti_ropi_pos.mobile_pos.invoices import submit_sale
	from roti_ropi_pos.overrides.pos_invoice import MobilePOSInvoice

	frappe.init(site=site)
	frappe.connect()
	original_validate = MobilePOSInvoice.validate_pos_opening_entry
	try:
		frappe.set_user(user)

		def pause_after_submit_validation(invoice):
			original_validate(invoice)
			if invoice.docstatus == 1:
				sale_validated.set()
				closing_finished.wait(timeout=10)

		with patch.object(MobilePOSInvoice, "validate_pos_opening_entry", pause_after_submit_validation):
			result = submit_sale(payload, transaction_id)
		frappe.db.commit()
		return result
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


def _run_closing_during_sale(site, user, payload, transaction_id, sale_validated, closing_finished):
	frappe.init(site=site)
	frappe.connect()
	try:
		frappe.set_user(user)
		frappe.local.form_dict = frappe._dict(payload)
		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": transaction_id})
		if not sale_validated.wait(timeout=3):
			raise AssertionError("Sale did not reach submit-time Opening validation.")
		with patch("erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry.consolidate_pos_invoices"):
			result = closing_api.submit()
		frappe.db.commit()
		closing_finished.set()
		return result
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


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

	def test_preview_exposes_task11_binding_and_counted_amount_policy(self):
		result = closing_api.preview(pos_profile=self.profile.name)
		data = result["data"]
		self.assertRegex(data["preview_id"], r"^[0-9a-f]{64}$")
		self.assertEqual(data["preview_version"], "closing-preview/v1")
		self.assertEqual(data["preview_binding"]["opening_entry"], self.opening)
		self.assertEqual(data["preview_binding"]["pos_profile"], self.profile.name)
		self.assertEqual(data["preview_binding"]["cashier"], self.cashier)
		self.assertEqual(
			data["counted_amount_policy"],
			{
				"currency": "INR",
				"decimal_places": 2,
				"max_scale": 2,
				"api_syntax": "ascii_decimal_dot",
				"minimum": "0.00",
				"maximum": "999999999999.99",
				"rounding": "reject",
				"policy_version": "closing-counted-amount/v1",
			},
		)

	def test_preview_aggregates_submitted_invoices(self):
		self._submit_sale()
		self._submit_sale()
		result = closing_api.preview(pos_profile=self.profile.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["invoice_count"], 2)
		self.assertEqual(Decimal(result["data"]["grand_total"]), Decimal("200"))

	def test_sale_cannot_commit_outside_locked_closing_snapshot(self):
		from roti_ropi_pos.api.v1 import sales as sales_api

		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		sale_payload = sales_api._parse_sale_payload(self._sale_payload())
		closing_payload = self._closing_payload(amount="500000", preview_id=preview_id)
		sale_key = str(uuid4())
		closing_key = str(uuid4())
		sale_validated = Event()
		closing_finished = Event()
		site = frappe.local.site
		frappe.db.commit()

		with ThreadPoolExecutor(max_workers=2) as executor:
			sale_future = executor.submit(
				_run_sale_during_closing,
				site,
				self.cashier,
				sale_payload,
				sale_key,
				sale_validated,
				closing_finished,
			)
			closing_future = executor.submit(
				_run_closing_during_sale,
				site,
				self.cashier,
				closing_payload,
				closing_key,
				sale_validated,
				closing_finished,
			)
			sale = sale_future.result(timeout=30)
			closing = closing_future.result(timeout=30)

		self.assertTrue(frappe.db.exists("POS Invoice", {"name": sale.reference_name, "docstatus": 1}))
		self.assertFalse(closing["ok"])
		self.assertEqual(closing["error"]["code"], "CLOSING_PREVIEW_STALE")
		self.assertFalse(
			frappe.db.exists(
				"POS Closing Entry",
				{"pos_opening_entry": self.opening, "docstatus": 1},
			)
		)

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
				self.assertEqual(result["error"]["code"], "CLOSING_DECIMAL_MALFORMED")

	def test_closing_parser_accepts_zero_amount(self):
		payload = closing_api._parse_closing_payload(self._closing_payload(amount="0"))
		self.assertEqual(payload["closing_balances"][0]["closing_amount"], "0")

	def test_closing_parser_rejects_negative_amount(self):
		result = self._close(str(uuid4()), amount="-1")
		self.assertEqual(result["error"]["code"], "CLOSING_AMOUNT_OUT_OF_BOUNDS")
		self.assertEqual(result["error"]["details"]["reason"], "below_minimum")

	def test_closing_parser_rejects_malformed_amount(self):
		result = self._close(str(uuid4()), amount="not-a-number")
		self.assertEqual(result["error"]["code"], "CLOSING_DECIMAL_MALFORMED")
		self.assertEqual(result["error"]["details"]["reason"], "malformed_decimal")

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
		payload = self._closing_payload()
		first = self._close(key, payload=payload)
		second = self._close(key, payload=payload)
		self.assertTrue(first["ok"])
		self.assertTrue(second["ok"])
		self.assertEqual(first["data"]["closing"]["name"], second["data"]["closing"]["name"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])

	def test_submit_sync_path_survives_core_commit_and_completes_request(self):
		self._submit_sale()
		key = str(uuid4())
		payload = self._closing_payload()
		with patch.object(frappe, "in_test", False):
			first = self._close(key, payload=payload)
			replay = self._close(key, payload=payload)

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
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
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
			result = self._close(str(uuid4()), preview_id=preview_id)
		self.assertIn("ok", result)
		self.assertLess(order.index("lock"), len(order) - 1 - order[::-1].index("invoices"))

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
		payload = self._closing_payload()
		frappe.set_user("Administrator")
		plain_user = frappe.db.get_value("User", {"user_type": "Website User", "enabled": 1}, "name")
		if not plain_user:
			plain_user = make_cashier(f"noperm-{frappe.generate_hash(8)}@rotiropi.test")
		# remove Mobile POS Cashier role to drop POS Closing Entry permission
		frappe.db.delete("Has Role", {"parent": plain_user, "role": "Mobile POS Cashier"})
		frappe.cache.hdel("roles", plain_user)
		frappe.set_user(plain_user)
		result = self._close(str(uuid4()), payload=payload)
		self.assertFalse(result["ok"])
		self.assertIn(result["error"]["code"], {"PERMISSION_ERROR", "NO_OPEN_SESSION", "PERMISSION_DENIED"})

	def test_submit_rejects_stale_preview_after_new_invoice_without_artifacts(self):
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		self._submit_sale()
		key = str(uuid4())
		result = self._close(key, preview_id=preview_id)
		self.assertEqual(result["error"]["code"], "CLOSING_PREVIEW_STALE")
		repeated = self._close(key, preview_id=preview_id)
		self.assertEqual(repeated["error"], result["error"])
		self.assertEqual(result["error"]["details"]["refresh_endpoint"], "v1.closing.preview")
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)
		self.assertEqual(frappe.db.count("POS Closing Entry", {"custom_mobile_pos_transaction_id": key}), 0)

	def test_submit_rejects_stale_preview_after_payment_snapshot_change(self):
		self._submit_sale()
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		invoice = frappe.db.get_value(
			"POS Invoice", {"owner": self.cashier, "docstatus": 1}, "name", order_by="creation desc"
		)
		payment = frappe.db.get_value(
			"Sales Invoice Payment", {"parenttype": "POS Invoice", "parent": invoice}, "name"
		)
		frappe.db.set_value("Sales Invoice Payment", payment, "amount", 99, update_modified=False)
		result = self._close(str(uuid4()), preview_id=preview_id)
		self.assertEqual(result["error"]["code"], "CLOSING_PREVIEW_STALE")

	def test_submit_rejects_stale_preview_for_replacement_opening(self):
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		frappe.set_user("Administrator")
		frappe.db.set_value("POS Opening Entry", self.opening, "status", "Closed")
		replacement = make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
			balances=[{"mode_of_payment": "Cash", "opening_amount": "500000"}],
		)
		frappe.set_user(self.cashier)
		result = self._close(str(uuid4()), preview_id=preview_id)
		self.assertEqual(result["error"]["code"], "CLOSING_PREVIEW_STALE")
		self.assertEqual(result["error"]["details"]["opening_entry"], replacement)

	def test_submit_rejects_preview_bound_to_a_different_profile(self):
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		frappe.set_user("Administrator")
		other_profile = make_valid_profile(
			f"Mobile POS Closing Other {frappe.generate_hash(length=8)}", self.cashier, default=0
		)
		frappe.db.set_value("POS Opening Entry", self.opening, "pos_profile", other_profile.name)
		frappe.set_user(self.cashier)
		payload = {
			"pos_profile": other_profile.name,
			"preview_id": preview_id,
			"closing_balances": [{"mode_of_payment": "Cash", "closing_amount": "0"}],
		}
		result = self._close(str(uuid4()), payload=payload)
		self.assertEqual(result["error"]["code"], "CLOSING_PREVIEW_STALE")

	def test_submit_requires_exact_preview_payment_mode_set(self):
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		cases = [
			(
				[
					{"mode_of_payment": "Cash", "closing_amount": "0"},
					{"mode_of_payment": "Cash", "closing_amount": "0"},
				],
				"CLOSING_PAYMENT_MODE_DUPLICATE",
			),
			([], "CLOSING_PAYMENT_MODE_MISSING"),
			(
				[{"mode_of_payment": "Unknown Task11 Mode", "closing_amount": "0"}],
				"CLOSING_PAYMENT_MODE_UNKNOWN",
			),
		]
		for balances, code in cases:
			with self.subTest(code=code):
				payload = {
					"pos_profile": self.profile.name,
					"preview_id": preview_id,
					"closing_balances": balances,
				}
				key = str(uuid4())
				result = self._close(key, payload=payload)
				self.assertEqual(result["error"]["code"], code)
				self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 0)

	def test_submit_accepts_zero_and_persists_exact_reconciliation(self):
		self._submit_sale()
		result = self._close(str(uuid4()), amount="0")
		self.assertTrue(result["ok"], result)
		receipt = result["data"]["closing"]
		closing = frappe.get_doc("POS Closing Entry", receipt["name"])
		row = closing.payment_reconciliation[0]
		self.assertEqual(Decimal(str(row.opening_amount)), Decimal("500000"))
		self.assertEqual(Decimal(str(row.expected_amount)), Decimal("500100"))
		self.assertEqual(Decimal(str(row.closing_amount)), Decimal("0"))
		self.assertEqual(Decimal(str(row.difference)), Decimal("-500100"))
		self.assertEqual(Decimal(str(closing.grand_total)), Decimal("100"))
		self.assertEqual(receipt, closing_api.status(name=closing.name)["data"]["closing"])

	def test_submit_decimal_policy_rejects_malformed_scale_and_overflow_without_rounding(self):
		cases = {
			".5": "CLOSING_DECIMAL_MALFORMED",
			"1.": "CLOSING_DECIMAL_MALFORMED",
			"1,000": "CLOSING_DECIMAL_MALFORMED",
			"1e2": "CLOSING_DECIMAL_MALFORMED",
			" 1": "CLOSING_DECIMAL_MALFORMED",
			"1 ": "CLOSING_DECIMAL_MALFORMED",
			"+1": "CLOSING_DECIMAL_MALFORMED",
			"-1": "CLOSING_AMOUNT_OUT_OF_BOUNDS",
			"1.001": "CLOSING_DECIMAL_SCALE_EXCEEDED",
			"1000000000000": "CLOSING_AMOUNT_OUT_OF_BOUNDS",
		}
		for amount, code in cases.items():
			with self.subTest(amount=amount):
				key = str(uuid4())
				result = self._close(key, amount=amount)
				self.assertEqual(result["error"]["code"], code)
				self.assertEqual(
					frappe.db.count("POS Closing Entry", {"custom_mobile_pos_transaction_id": key}), 0
				)

	def test_closing_hash_preserves_original_counted_decimal_string(self):
		self._submit_sale()
		key = str(uuid4())
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		first = self._close(key, amount="1.0", preview_id=preview_id)
		self.assertTrue(first["ok"], first)
		second = self._close(key, amount="1.00", preview_id=preview_id)
		self.assertEqual(second["error"]["code"], "IDEMPOTENCY_KEY_REUSED")

	def test_submit_with_new_key_after_terminal_close_is_rejected_as_already_closed(self):
		self._submit_sale()
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		self.assertTrue(self._close(str(uuid4()), preview_id=preview_id)["ok"])
		result = self._close(str(uuid4()), preview_id=preview_id)
		self.assertEqual(result["error"]["code"], "CLOSING_ALREADY_CLOSED")

	def test_distinct_key_cannot_create_second_closing_for_same_opening(self):
		preview_id = closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		first = self._make_unresolved_closing("Draft")
		second_key = str(uuid4())
		result = self._close(second_key, preview_id=preview_id)
		self.assertEqual(result["error"]["code"], "CLOSING_IN_PROGRESS")
		self.assertEqual(frappe.db.count("POS Closing Entry", {"pos_opening_entry": self.opening}), 1)
		self.assertEqual(
			frappe.db.count(
				"POS Closing Entry",
				{"custom_mobile_pos_transaction_id": first.custom_mobile_pos_transaction_id},
			),
			1,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": second_key}), 0)

	def test_queued_closing_keeps_opening_visible_and_blocks_mutations(self):
		closing = self._make_unresolved_closing("Queued")
		current = sessions_api.current(pos_profile=self.profile.name)["data"]
		self.assertEqual(current["opening_session"]["name"], self.opening)
		self.assertEqual(current["opening_session"]["lifecycle_state"], "closing_in_progress")
		self.assertEqual(current["closing"]["name"], closing.name)
		bootstrap = bootstrap_api.get(pos_profile=self.profile.name)["data"]
		self.assertFalse(any(bootstrap["capabilities"].values()))

	def test_failed_closing_keeps_opening_blocked_for_manager_review(self):
		closing = self._make_unresolved_closing("Failed")
		current = sessions_api.current(pos_profile=self.profile.name)["data"]
		self.assertEqual(current["opening_session"]["lifecycle_state"], "closing_failed")
		self.assertEqual(current["closing"]["name"], closing.name)
		self.assertEqual(current["closing"]["failure"]["code"], "CLOSING_FAILED")
		self.assertFalse(
			any(bootstrap_api.get(pos_profile=self.profile.name)["data"]["capabilities"].values())
		)

	def test_submitted_closing_allows_explicit_new_opening_capability(self):
		self._submit_sale()
		result = self._close(str(uuid4()), amount="0")
		self.assertTrue(result["ok"], result)
		bootstrap = bootstrap_api.get(pos_profile=self.profile.name)["data"]
		self.assertIsNone(bootstrap["opening_session"])
		self.assertIsNone(bootstrap["closing"])
		self.assertTrue(bootstrap["capabilities"]["open_session"])

	def test_cancelled_closing_restores_original_opening_as_active(self):
		closing = self._make_unresolved_closing("Cancelled")
		frappe.db.set_value("POS Opening Entry", self.opening, "pos_closing_entry", None)
		current = sessions_api.current(pos_profile=self.profile.name)["data"]
		self.assertEqual(current["opening_session"]["lifecycle_state"], "active")
		self.assertIsNone(current["closing"])
		capabilities = bootstrap_api.get(pos_profile=self.profile.name)["data"]["capabilities"]
		self.assertFalse(capabilities["open_session"])
		self.assertTrue(capabilities["close_session"])
		self.assertEqual(closing.status, "Cancelled")

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

	def _make_unresolved_closing(self, status: str):
		from roti_ropi_pos.mobile_pos.closing import _create_closing_draft

		key = str(uuid4())
		payload = closing_api._parse_closing_payload(self._closing_payload(amount="0"))
		closing = _create_closing_draft(self.profile, payload, key)
		frappe.db.set_value("POS Closing Entry", closing.name, "status", status)
		frappe.db.set_value("POS Opening Entry", self.opening, "pos_closing_entry", closing.name)
		closing.reload()
		return closing

	def _submit_sale(self):
		from unittest.mock import patch as _patch

		from roti_ropi_pos.api.v1 import sales as sales_api

		with _patch("frappe.get_request_header", return_value=str(uuid4())):
			frappe.local.form_dict = frappe._dict(self._sale_payload())
			return sales_api.submit()

	def _sale_payload(self):
		return {
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

	def _closing_payload(self, amount="500100", *, preview_id=None):
		preview_id = preview_id or closing_api.preview(pos_profile=self.profile.name)["data"]["preview_id"]
		return {
			"pos_profile": self.profile.name,
			"preview_id": preview_id,
			"closing_balances": [{"mode_of_payment": "Cash", "closing_amount": amount}],
		}

	def _close(self, idempotency_key: str, *, amount="500100", preview_id=None, payload=None):
		with patch("frappe.get_request_header", return_value=idempotency_key):
			frappe.local.form_dict = frappe._dict(
				payload or self._closing_payload(amount, preview_id=preview_id)
			)
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
