from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import (
	CONFLICT_RESOLUTION_ATTEMPTS,
	MutationResult,
	_create_processing_request,
	_resolve_committed_request,
	_scope_key,
	canonical_hash,
	delete_expired_requests,
	execute_idempotent,
	normalize_for_hash,
	verify_business_reference,
)

KEY = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
KEY_DEL1 = "6ba7b810-9dad-41d1-80b4-00c04fd430c9"
KEY_DEL2 = "6ba7b810-9dad-41d1-80b4-00c04fd430ca"
KEY_DEL3 = "6ba7b810-9dad-41d1-80b4-00c04fd430cb"
KEY_DEL4 = "6ba7b810-9dad-41d1-80b4-00c04fd430cc"


def _result(name="INV-1"):
	return MutationResult(data={"name": name}, reference_doctype="POS Invoice", reference_name=name)


def _open_entry(profile_name, transaction_id):
	frappe.db.get_value("POS Profile", profile_name, "name", for_update=True)
	frappe.db.get_value("User", frappe.session.user, "name", for_update=True)
	profile = frappe.get_doc("POS Profile", profile_name)
	opening = frappe.get_doc(
		{
			"doctype": "POS Opening Entry",
			"period_start_date": frappe.utils.now_datetime(),
			"posting_date": frappe.utils.today(),
			"user": frappe.session.user,
			"pos_profile": profile.name,
			"company": profile.company,
			"balance_details": [{"mode_of_payment": "Cash", "opening_amount": 0}],
			"custom_mobile_pos_transaction_id": transaction_id,
		}
	)
	opening.insert()
	opening.submit()
	return MutationResult(
		data={"opening_session": {"name": opening.name}},
		reference_doctype="POS Opening Entry",
		reference_name=opening.name,
	)


def _run_open_attempt(site, user, profile_name, key, barrier):
	frappe.init(site=site)
	frappe.connect()
	try:
		frappe.set_user(user)
		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
		barrier.wait(timeout=10)
		try:
			response = execute_idempotent(
				"v1.sessions.open",
				{
					"pos_profile": profile_name,
					"opening_balances": [{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
				},
				lambda transaction_id: _open_entry(profile_name, transaction_id),
			)
		except MobilePOSAPIError as error:
			if error.code != "REQUEST_IN_PROGRESS" or not error.retryable:
				raise
			frappe.db.rollback()
			return {"error_code": error.code, "retryable": error.retryable}
		frappe.db.commit()
		return response
	except Exception:
		frappe.db.rollback()
		raise
	finally:
		frappe.destroy()


class TestIdempotency(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		# Frappe v16 does not roll back between tests within a class, so isolate
		# each test against the app-owned control record table.
		frappe.db.delete("Mobile POS Request")

	def test_normalize_for_hash_normalizes_decimals(self):
		self.assertEqual(normalize_for_hash(Decimal("1.0")), "1")
		self.assertEqual(normalize_for_hash(Decimal("1.00")), "1")
		self.assertEqual(normalize_for_hash({"b": Decimal("2.0"), "a": Decimal("1.0")}), {"a": "1", "b": "2"})

	def test_canonical_hash_is_stable_for_equivalent_payloads(self):
		self.assertEqual(
			canonical_hash("v1.sales.submit", {"qty": Decimal("1.0")}),
			canonical_hash("v1.sales.submit", {"qty": Decimal("1.00")}),
		)
		self.assertNotEqual(
			canonical_hash("v1.sales.submit", {"qty": Decimal("1.0")}),
			canonical_hash("v1.sales.submit", {"qty": Decimal("2.0")}),
		)

	def test_same_key_and_payload_replays_one_operation(self):
		calls = []
		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			first = execute_idempotent(
				"v1.sales.submit",
				{"qty": "1"},
				lambda transaction_id: calls.append(1) or _result("INV-1"),
			)
			second = execute_idempotent(
				"v1.sales.submit",
				{"qty": "1"},
				lambda transaction_id: calls.append(2) or _result("INV-2"),
			)
		self.assertEqual(calls, [1])
		self.assertEqual(first["data"], second["data"])
		self.assertEqual(first["meta"]["replayed"], False)
		self.assertEqual(second["meta"]["replayed"], True)

	def test_same_key_and_changed_payload_is_conflict(self):
		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
			with self.assertRaises(MobilePOSAPIError) as error:
				execute_idempotent("v1.sales.submit", {"qty": "2"}, lambda transaction_id: _result())
		self.assertEqual(error.exception.code, "IDEMPOTENCY_KEY_REUSED")
		self.assertEqual(error.exception.status, 409)
		self.assertEqual(error.exception.details, {"endpoint": "v1.sales.submit"})

	def test_replay_preserves_request_id_and_sets_http_200(self):
		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			first = execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
			request_id = first["meta"]["request_id"]
			frappe.response["http_status_code"] = None
			second = execute_idempotent(
				"v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result("INV-2")
			)
		self.assertEqual(second["meta"]["request_id"], request_id)
		self.assertEqual(frappe.response["http_status_code"], 200)
		self.assertEqual(second["data"], {"name": "INV-1"})

	def test_first_execution_sets_http_201(self):
		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			frappe.response["http_status_code"] = None
			execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
		self.assertEqual(frappe.response["http_status_code"], 201)

	def test_operation_passes_idempotency_key_as_transaction_id(self):
		received = {}

		def op(transaction_id):
			received["key"] = transaction_id
			return _result()

		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			execute_idempotent("v1.sales.submit", {"qty": "1"}, op)
		self.assertEqual(received["key"], KEY)

	def test_operation_failure_leaves_no_request_row(self):
		with (
			patch("frappe.get_request_header", return_value=KEY),
		):
			with self.assertRaises(RuntimeError):
				execute_idempotent(
					"v1.sales.submit",
					{"qty": "1"},
					lambda transaction_id: (_ for _ in ()).throw(RuntimeError("boom")),
				)
		self.assertFalse(frappe.db.exists("Mobile POS Request", {"idempotency_key": KEY}))

	def test_missing_idempotency_key_is_rejected(self):
		with patch("frappe.get_request_header", return_value=None):
			with self.assertRaises(MobilePOSAPIError) as error:
				execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
		self.assertEqual(error.exception.code, "INVALID_REQUEST")

	def test_invalid_idempotency_key_is_rejected(self):
		with patch("frappe.get_request_header", return_value="not-a-uuid"):
			with self.assertRaises(MobilePOSAPIError) as error:
				execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
		self.assertEqual(error.exception.code, "INVALID_REQUEST")

	def test_verify_business_reference_passes_on_matching_transaction_id(self):
		result = _result()
		with patch("frappe.db.get_value", return_value=KEY):
			verify_business_reference("v1.sales.submit", result, KEY)

	def test_verify_business_reference_rejects_wrong_doctype(self):
		result = MutationResult(data={}, reference_doctype="Sales Invoice", reference_name="X")
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_business_reference("v1.sales.submit", result, KEY)
		self.assertEqual(error.exception.status, 500)

	def test_verify_business_reference_rejects_transaction_id_mismatch(self):
		result = _result()
		with patch("frappe.db.get_value", return_value="different"):
			with self.assertRaises(MobilePOSAPIError) as error:
				verify_business_reference("v1.sales.submit", result, KEY)
		self.assertEqual(error.exception.status, 500)

	def test_twenty_repeated_attempts_produce_one_request_and_one_reference(self):
		calls = []
		with (
			patch("frappe.get_request_header", return_value=KEY),
			patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
		):
			responses = [
				execute_idempotent(
					"v1.sales.submit",
					{"qty": "1"},
					lambda transaction_id: calls.append(1) or _result("INV-1"),
				)
				for _ in range(20)
			]
		self.assertEqual(len(calls), 1)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": KEY}), 1)
		self.assertTrue(all(r["data"] == {"name": "INV-1"} for r in responses))
		self.assertEqual(sum(1 for r in responses if r["meta"]["replayed"]), 19)

	def test_twenty_concurrent_attempts_create_one_opening_and_one_request(self):
		from erpnext.accounts.doctype.pos_profile.test_pos_profile import make_pos_profile
		from frappe.core.doctype.user_permission.test_user_permission import create_user

		user = create_user(
			f"idem-concurrent-{frappe.generate_hash(length=8)}@rotiropi.test",
			"Accounts Manager",
			"Accounts User",
			"Sales Manager",
			"Stock User",
			"Item Manager",
		).name
		frappe.set_user(user)
		profile = make_pos_profile(name=f"Idem Concurrent {frappe.generate_hash(length=8)}")
		profile.append("applicable_for_users", {"user": user, "default": 1})
		profile.save()
		key = str(uuid4())
		site = frappe.local.site
		frappe.db.commit()
		barrier = Barrier(20)

		with ThreadPoolExecutor(max_workers=20) as executor:
			futures = [
				executor.submit(_run_open_attempt, site, user, profile.name, key, barrier) for _ in range(20)
			]
			results = [future.result(timeout=30) for future in futures]

		responses = [row for row in results if "meta" in row]
		in_progress = [row for row in results if row.get("error_code") == "REQUEST_IN_PROGRESS"]
		first = [row for row in responses if not row["meta"]["replayed"]]
		replays = [row for row in responses if row["meta"]["replayed"]]
		self.assertEqual(len(first), 1)
		self.assertGreaterEqual(len(replays), 1)
		self.assertTrue(all(row["retryable"] for row in in_progress))
		self.assertEqual(len(responses) + len(in_progress), 20)
		self.assertEqual(
			frappe.db.count(
				"POS Opening Entry",
				{"custom_mobile_pos_transaction_id": key, "docstatus": 1},
			),
			1,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 1)
		self.assertEqual(
			frappe.db.count(
				"Mobile POS Request",
				{"idempotency_key": key, "status": "Completed"},
			),
			1,
		)
		opening_name = first[0]["data"]["opening_session"]["name"]
		self.assertTrue(all(row["data"]["opening_session"]["name"] == opening_name for row in responses))

		frappe.set_user(user)
		request = getattr(frappe.local, "request", None)
		try:
			frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
			for _ in in_progress:
				retry = execute_idempotent(
					"v1.sessions.open",
					{
						"pos_profile": profile.name,
						"opening_balances": [{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
					},
					lambda transaction_id: self.fail("retry must replay, not execute"),
				)
				self.assertTrue(retry["meta"]["replayed"])
				self.assertEqual(retry["data"]["opening_session"]["name"], opening_name)
		finally:
			frappe.local.request = request
			frappe.set_user("Administrator")

	def test_processing_request_blocks_concurrent_same_key(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		scope_key = _scope_key(KEY, "v1.sales.submit")
		with patch("frappe.get_request_header", return_value=KEY):
			_create_processing_request(scope_key, KEY, "v1.sales.submit", request_hash)
			with self.assertRaises(MobilePOSAPIError) as error:
				execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: _result())
		self.assertEqual(error.exception.code, "REQUEST_IN_PROGRESS")
		self.assertTrue(error.exception.retryable)

	def test_delete_expired_requests_removes_terminal_unheld_with_matching_reference(self):
		# create a Completed request with an expired expires_at
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		scope_key = _scope_key(KEY_DEL1, "v1.sales.submit")
		doc = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": scope_key,
				"idempotency_key": KEY_DEL1,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"reference_doctype": "POS Invoice",
				"reference_name": "FAKE-INV-1",
				"http_status": 201,
				"response_json": frappe.as_json({"ok": True, "data": {}, "meta": {"api_version": "v1"}}),
				"resolved_at": "2026-01-01 00:00:00",
				"expires_at": "2026-01-02 00:00:00",
				"audit_reference_written": 1,
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True)
		# referenced document carries matching transaction id -> deletion allowed
		with patch("frappe.db.get_value", return_value=KEY_DEL1):
			deleted = delete_expired_requests()
		self.assertGreaterEqual(deleted, 1)
		self.assertFalse(frappe.db.exists("Mobile POS Request", doc.name))

	def test_delete_expired_preserves_leased_terminal_request(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		doc = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY_DEL2, "v1.sales.submit"),
				"idempotency_key": KEY_DEL2,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"expires_at": "2026-01-02 00:00:00",
				"lease_expires_at": "2026-01-01 00:00:00",
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True)
		delete_expired_requests()
		self.assertTrue(frappe.db.exists("Mobile POS Request", doc.name))

	def test_delete_expired_preserves_recovery_phase(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		doc = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY_DEL3, "v1.sales.submit"),
				"idempotency_key": KEY_DEL3,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Rejected",
				"phase": "SubmitStarted",
				"expires_at": "2026-01-02 00:00:00",
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True)
		delete_expired_requests()
		self.assertTrue(frappe.db.exists("Mobile POS Request", doc.name))

	def test_delete_expired_preserves_processing_and_held(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		processing = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY_DEL2, "v1.sales.submit"),
				"idempotency_key": KEY_DEL2,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Processing",
			}
		)
		processing.insert(ignore_permissions=True, ignore_links=True)
		held = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY_DEL3, "v1.sales.submit"),
				"idempotency_key": KEY_DEL3,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"retention_hold": 1,
				"retention_reason": "audit",
				"resolved_at": "2026-01-01 00:00:00",
				"expires_at": "2026-01-02 00:00:00",
			}
		)
		held.insert(ignore_permissions=True, ignore_links=True)
		delete_expired_requests()
		self.assertTrue(frappe.db.exists("Mobile POS Request", processing.name))
		self.assertTrue(frappe.db.exists("Mobile POS Request", held.name))

	def test_resolve_committed_request_missing_then_completed_uses_locking_read(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		completed = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY, "v1.sales.submit"),
				"idempotency_key": KEY,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"reference_doctype": "POS Invoice",
				"reference_name": "INV-1",
				"http_status": 201,
				"response_json": frappe.as_json(
					{"ok": True, "data": {"name": "INV-1"}, "meta": {"api_version": "v1"}}
				),
				"resolved_at": "2026-01-01 00:00:00",
				"expires_at": "2026-01-02 00:00:00",
				"audit_reference_written": 1,
			}
		)
		completed.insert(ignore_permissions=True, ignore_links=True)
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			if len(calls) == 1:
				return None
			return completed

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			result = _resolve_committed_request(
				_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
			)
		self.assertEqual(result["data"], {"name": "INV-1"})
		self.assertTrue(result["meta"]["replayed"])
		self.assertTrue(calls)
		self.assertTrue(all(for_update is True for for_update in calls))
		self.assertGreaterEqual(sleep_mock.call_count, 1)

	def test_resolve_committed_request_retries_deadlocked_locking_read(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		completed = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY, "v1.sales.submit"),
				"idempotency_key": KEY,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"reference_doctype": "POS Invoice",
				"reference_name": "INV-1",
				"http_status": 201,
				"response_json": frappe.as_json(
					{"ok": True, "data": {"name": "INV-1"}, "meta": {"api_version": "v1"}}
				),
				"resolved_at": "2026-01-01 00:00:00",
				"expires_at": "2026-01-02 00:00:00",
				"audit_reference_written": 1,
			}
		)
		completed.insert(ignore_permissions=True, ignore_links=True)
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			if len(calls) == 1:
				raise frappe.QueryDeadlockError("deadlock")
			return completed

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			result = _resolve_committed_request(
				_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
			)
		self.assertEqual(result["data"], {"name": "INV-1"})
		self.assertTrue(result["meta"]["replayed"])
		self.assertEqual(calls, [True, True])
		sleep_mock.assert_called_once()

	def test_resolve_committed_request_repeated_deadlock_raises_retryable(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			raise frappe.QueryDeadlockError("deadlock")

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				_resolve_committed_request(
					_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
				)
		self.assertEqual(error.exception.code, "REQUEST_IN_PROGRESS")
		self.assertTrue(error.exception.retryable)
		self.assertEqual(calls, [True] * CONFLICT_RESOLUTION_ATTEMPTS)
		self.assertEqual(sleep_mock.call_count, CONFLICT_RESOLUTION_ATTEMPTS - 1)

	def test_resolve_committed_request_bounded_processing_raises_retryable(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		processing = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY, "v1.sales.submit"),
				"idempotency_key": KEY,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Processing",
			}
		)
		processing.insert(ignore_permissions=True, ignore_links=True)
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			return processing

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				_resolve_committed_request(
					_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
				)
		self.assertEqual(error.exception.code, "REQUEST_IN_PROGRESS")
		self.assertTrue(error.exception.retryable)
		self.assertEqual(len(calls), CONFLICT_RESOLUTION_ATTEMPTS)
		self.assertTrue(all(for_update is True for for_update in calls))
		self.assertEqual(sleep_mock.call_count, CONFLICT_RESOLUTION_ATTEMPTS - 1)

	def test_resolve_committed_request_hash_mismatch_raises_immediately(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		other = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY, "v1.sales.submit"),
				"idempotency_key": KEY,
				"endpoint": "v1.sales.submit",
				"request_hash": "different-hash",
				"user": frappe.session.user,
				"status": "Processing",
			}
		)
		other.insert(ignore_permissions=True, ignore_links=True)
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			return other

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				_resolve_committed_request(
					_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
				)
		self.assertEqual(error.exception.code, "IDEMPOTENCY_KEY_REUSED")
		self.assertEqual(len(calls), 1)
		self.assertTrue(calls[0])
		sleep_mock.assert_not_called()

	def test_resolve_committed_request_missing_row_exhaustion_raises_invariant(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		calls = []

		def fake_get_existing(scope_key, *, for_update=False):
			calls.append(for_update)
			return None

		with (
			patch(
				"roti_ropi_pos.mobile_pos.idempotency._get_existing_request",
				side_effect=fake_get_existing,
			),
			patch("roti_ropi_pos.mobile_pos.idempotency.time.sleep") as sleep_mock,
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				_resolve_committed_request(
					_scope_key(KEY, "v1.sales.submit"), request_hash, "v1.sales.submit"
				)
		self.assertEqual(error.exception.code, "IDEMPOTENCY_INVARIANT")
		self.assertEqual(error.exception.status, 500)
		self.assertEqual(len(calls), CONFLICT_RESOLUTION_ATTEMPTS)
		self.assertTrue(all(for_update is True for for_update in calls))
		self.assertEqual(sleep_mock.call_count, CONFLICT_RESOLUTION_ATTEMPTS - 1)

	def test_delete_expired_sets_hold_on_reference_mismatch(self):
		request_hash = canonical_hash("v1.sales.submit", {"qty": "1"})
		doc = frappe.get_doc(
			{
				"doctype": "Mobile POS Request",
				"scope_key": _scope_key(KEY_DEL4, "v1.sales.submit"),
				"idempotency_key": KEY_DEL4,
				"endpoint": "v1.sales.submit",
				"request_hash": request_hash,
				"user": frappe.session.user,
				"status": "Completed",
				"reference_doctype": "POS Invoice",
				"reference_name": "FAKE-INV-2",
				"resolved_at": "2026-01-01 00:00:00",
				"expires_at": "2026-01-02 00:00:00",
				"audit_reference_written": 1,
			}
		)
		doc.insert(ignore_permissions=True, ignore_links=True)
		with patch("frappe.db.get_value", return_value="mismatched"):
			delete_expired_requests()
		updated = frappe.get_doc("Mobile POS Request", doc.name)
		self.assertEqual(updated.retention_hold, 1)
		self.assertTrue(updated.retention_reason)
		self.assertTrue(frappe.db.exists("Mobile POS Request", doc.name))
