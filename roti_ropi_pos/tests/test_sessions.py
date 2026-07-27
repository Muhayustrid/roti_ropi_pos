from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import sessions as sessions_api
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.sessions import open_session
from roti_ropi_pos.tests.helpers import make_cashier, make_opening_entry

COMPANY = "_Test Company"
WAREHOUSE = "_Test Warehouse - _TC"


class TestSessions(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"sessions-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.idempotency_key = str(uuid4())
		self.profile = make_valid_profile(
			f"Mobile POS Session {frappe.generate_hash(length=8)}",
			self.cashier,
		)

	def tearDown(self) -> None:
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		frappe.set_user("Administrator")
		super().tearDown()

	def test_current_reuses_shared_lookup_and_preserves_stale_warning(self):
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date="2026-07-20 08:00:00",
			posting_date="2026-07-20",
			balances=[{"mode_of_payment": "Cash", "opening_amount": "500000"}],
		)
		frappe.set_user(self.cashier)
		result = sessions_api.current(pos_profile=self.profile.name)
		opening = result["data"]["opening_session"]
		self.assertEqual(opening["pos_profile"], self.profile.name)
		self.assertEqual(opening["posting_date"], "2026-07-20")
		self.assertTrue(opening["period_start_date"])
		self.assertEqual(opening["warnings"][0]["code"], "STALE_OPENING")

	def test_opening_period_start_uses_site_timezone_offset(self):
		opening = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"name": "TEST-OPE-TIMEZONE",
				"user": self.cashier,
				"company": COMPANY,
				"pos_profile": self.profile.name,
				"period_start_date": "2026-07-20 08:00:00",
				"posting_date": "2026-07-20",
				"balance_details": [],
			}
		)
		from roti_ropi_pos.mobile_pos.sessions import opening_dto

		self.assertRegex(opening_dto(opening)["period_start_date"], r"[+-]\d\d:\d\d$")

	def test_open_session_creates_submitted_entry_from_server_owned_scope(self):
		frappe.set_user(self.cashier)
		result = open_session(
			self.profile,
			[{"mode_of_payment": "Cash", "opening_amount": Decimal("500000")}],
			self.idempotency_key,
		)
		opening = frappe.get_doc("POS Opening Entry", result.reference_name)
		self.assertEqual(opening.docstatus, 1)
		self.assertEqual(opening.status, "Open")
		self.assertEqual(opening.user, self.cashier)
		self.assertEqual(opening.company, COMPANY)
		self.assertEqual(opening.pos_profile, self.profile.name)
		self.assertEqual(opening.custom_mobile_pos_transaction_id, self.idempotency_key)
		self.assertEqual(result.data["opening_session"]["name"], opening.name)

	def test_open_session_rejects_mode_outside_profile(self):
		frappe.set_user(self.cashier)
		with self.assertRaises(MobilePOSAPIError) as error:
			open_session(
				self.profile,
				[{"mode_of_payment": "Card", "opening_amount": Decimal("0")}],
				self.idempotency_key,
			)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")

	def test_open_endpoint_rejects_duplicate_payment_mode(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(
			{
				"pos_profile": self.profile.name,
				"opening_balances": [
					{"mode_of_payment": "Cash", "amount": "0"},
					{"mode_of_payment": "Cash", "amount": "1"},
				],
			}
		)
		with patch("frappe.get_request_header", return_value=self.idempotency_key):
			result = sessions_api.open()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(
			frappe.db.count("POS Opening Entry", {"custom_mobile_pos_transaction_id": self.idempotency_key}),
			0,
		)

	def test_open_session_requires_core_create_and_submit_permissions(self):
		plain_user = make_plain_user(f"plain-{frappe.generate_hash(length=8)}@rotiropi.test")
		frappe.set_user(plain_user)
		with self.assertRaises(MobilePOSAPIError) as error:
			open_session(
				self.profile,
				[{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
				self.idempotency_key,
			)
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")

	def test_open_endpoint_replays_one_submitted_entry(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(
			{
				"pos_profile": self.profile.name,
				"opening_balances": [{"mode_of_payment": "Cash", "amount": "500000"}],
			}
		)
		with patch("frappe.get_request_header", return_value=self.idempotency_key):
			first = sessions_api.open()
			self.assertEqual(frappe.response["http_status_code"], 201)
			second = sessions_api.open()
		self.assertEqual(first["data"], second["data"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])
		self.assertEqual(frappe.response["http_status_code"], 200)
		self.assertEqual(
			frappe.db.count("POS Opening Entry", {"custom_mobile_pos_transaction_id": self.idempotency_key}),
			1,
		)

	def test_open_endpoint_accepts_router_injected_cmd(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(
			{
				"cmd": "roti_ropi_pos.api.v1.sessions.open",
				"pos_profile": self.profile.name,
				"opening_balances": [{"mode_of_payment": "Cash", "amount": "0"}],
			}
		)
		with patch("frappe.get_request_header", return_value=self.idempotency_key):
			result = sessions_api.open()
		self.assertTrue(result["ok"])

	def test_same_profile_different_user_conflict_is_rejected(self):
		frappe.set_user(self.cashier)
		open_session(
			self.profile,
			[{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
			self.idempotency_key,
		)
		other_cashier = make_cashier(f"other-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.profile.append("applicable_for_users", {"user": other_cashier, "default": 1})
		self.profile.save(ignore_permissions=True)
		frappe.set_user(other_cashier)
		with self.assertRaises(MobilePOSAPIError) as error:
			open_session(
				self.profile,
				[{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
				"6ba7b810-9dad-41d1-80b4-00c04fd430c9",
			)
		self.assertEqual(error.exception.code, "SESSION_ALREADY_OPEN")
		self.assertEqual(error.exception.details["pos_profile"], self.profile.name)

	def test_same_user_different_profile_conflict_is_rejected(self):
		frappe.set_user(self.cashier)
		open_session(
			self.profile,
			[{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
			self.idempotency_key,
		)
		second_profile = make_valid_profile(
			f"Mobile POS Session {frappe.generate_hash(length=8)}",
			self.cashier,
			default=0,
		)
		with self.assertRaises(MobilePOSAPIError) as error:
			open_session(
				second_profile,
				[{"mode_of_payment": "Cash", "opening_amount": Decimal("0")}],
				"6ba7b810-9dad-41d1-80b4-00c04fd430ca",
			)
		self.assertEqual(error.exception.code, "SESSION_ALREADY_OPEN")
		self.assertEqual(error.exception.details["pos_profile"], self.profile.name)


def make_valid_profile(name: str, user: str, *, default: int = 1):
	mode = frappe.get_doc("Mode of Payment", "Cash")
	if not frappe.db.exists("Mode of Payment Account", {"parent": "Cash", "company": COMPANY}):
		mode.append("accounts", {"company": COMPANY, "default_account": "Sales - _TC"})
		mode.save()
	profile = frappe.get_doc(
		{
			"doctype": "POS Profile",
			"name": name,
			"company": COMPANY,
			"cost_center": "_Test Cost Center - _TC",
			"currency": "INR",
			"customer": frappe.db.get_value("Customer", {"disabled": 0}, "name"),
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"expense_account": "_Test Account Cost for Goods Sold - _TC",
			"income_account": "Sales - _TC",
			"naming_series": "_T-POS Profile-",
			"selling_price_list": frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
			"territory": "_Test Territory",
			"warehouse": WAREHOUSE,
			"write_off_account": "_Test Write Off - _TC",
			"write_off_cost_center": "_Test Write Off Cost Center - _TC",
			"location": "Block 1",
			"payments": [{"mode_of_payment": "Cash", "default": 1}],
			"applicable_for_users": [{"user": user, "default": default}],
		}
	)
	profile.insert(ignore_permissions=True)
	return profile


def make_plain_user(email: str) -> str:
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "Plain", "enabled": 1, "roles": []}
	)
	user.flags.ignore_validate = True
	user.flags.ignore_links = True
	user.insert(ignore_permissions=True)
	return email
