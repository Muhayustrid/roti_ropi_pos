from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import bootstrap as bootstrap_module
from roti_ropi_pos.mobile_pos.authorization import get_capabilities
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.profiles import profile_dto
from roti_ropi_pos.mobile_pos.sessions import opening_dto
from roti_ropi_pos.tests.helpers import (
	make_cashier,
	make_opening_entry,
	make_pos_profile,
)

COMPANY = "_Test Company"
WAREHOUSE = "_Test Warehouse - _TC"
CUSTOMER = "_Test Customer"


class TestBootstrap(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier("bootcashier@rotiropi.test")
		self.profile = make_pos_profile(
			"Mobile POS Boot Profile",
			company=COMPANY,
			warehouse=WAREHOUSE,
			customer=CUSTOMER,
			user=self.cashier,
		)

	def tearDown(self) -> None:
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		frappe.set_user("Administrator")
		super().tearDown()

	def _bootstrap_as(self, user, pos_profile=None):
		frappe.set_user(user)
		return bootstrap_module.get(pos_profile=pos_profile)

	def test_bootstrap_returns_only_assigned_enabled_profiles(self):
		result = self._bootstrap_as(self.cashier)
		names = [p["name"] for p in result["data"]["profiles"]]
		self.assertIn(self.profile, names)
		self.assertEqual(result["data"]["user"]["name"], self.cashier)
		self.assertEqual(result["data"]["pos_mode"], "POS Invoice")

	def test_profile_dto_projects_safe_fields_only(self):
		frappe.set_user(self.cashier)
		profile = frappe.get_doc("POS Profile", self.profile)
		dto = profile_dto(profile)
		self.assertEqual(
			set(dto),
			{
				"name",
				"company",
				"warehouse",
				"currency",
				"selling_price_list",
				"customer",
				"allow_partial_payment",
				"invoice_mode",
				"assigned_users",
			},
		)
		self.assertFalse(dto["allow_partial_payment"])
		self.assertEqual(dto["invoice_mode"], "POS Invoice")

	def test_bootstrap_auto_selects_single_assigned_profile(self):
		result = self._bootstrap_as(self.cashier)
		self.assertEqual(result["data"]["selected_profile"]["name"], self.profile)

	def test_bootstrap_with_explicit_profile_selects_it(self):
		result = self._bootstrap_as(self.cashier, pos_profile=self.profile)
		self.assertEqual(result["data"]["selected_profile"]["name"], self.profile)

	def test_bootstrap_rejects_unassigned_profile(self):
		result = self._bootstrap_as(self.cashier, pos_profile="Nonexistent Profile")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "PROFILE_SCOPE_MISMATCH")

	def test_bootstrap_capabilities_false_without_profile(self):
		# A second cashier with no profile assigned.
		other = make_cashier("bootother@rotiropi.test")
		result = self._bootstrap_as(other)
		caps = result["data"]["capabilities"]
		self.assertFalse(any(caps.values()))

	def test_capabilities_open_session_true_without_opening(self):
		frappe.set_user(self.cashier)
		profile = frappe.get_doc("POS Profile", self.profile)
		caps = get_capabilities(profile, opening=None)
		self.assertTrue(caps["open_session"])
		self.assertFalse(caps["submit_sale"])
		self.assertFalse(caps["create_return"])
		self.assertFalse(caps["close_session"])
		self.assertFalse(caps["cancel_sale"])

	def test_capabilities_submit_sale_true_with_active_opening(self):
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile,
			period_start_date=f"{frappe.utils.today()} 08:00:00",
			posting_date=frappe.utils.today(),
		)
		frappe.set_user(self.cashier)
		profile = frappe.get_doc("POS Profile", self.profile)
		# get_current_opening reads a submitted open entry; pass opening=None to exercise it.
		caps = get_capabilities(profile, opening=None)
		self.assertTrue(caps["submit_sale"])
		self.assertTrue(caps["close_session"])
		self.assertFalse(caps["open_session"])

	def test_opening_dto_includes_stale_warning_for_prior_day(self):
		opening = frappe.get_doc(
			{
				"doctype": "POS Opening Entry",
				"name": "POS-OPE-STALE-1",
				"user": self.cashier,
				"company": COMPANY,
				"pos_profile": self.profile,
				"period_start_date": "2026-07-20 08:00:00",
				"posting_date": "2026-07-20",
				"balance_details": [{"mode_of_payment": "Cash", "opening_amount": "500000"}],
				"status": "Open",
			}
		)
		dto = opening_dto(opening)
		self.assertEqual(dto["status"], "open")
		self.assertEqual(dto["posting_date"], "2026-07-20")
		codes = [w["code"] for w in dto["warnings"]]
		self.assertIn("STALE_OPENING", codes)

	def test_bootstrap_rejects_unsupported_pos_mode(self):
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")
		result = self._bootstrap_as(self.cashier)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "UNSUPPORTED_POS_MODE")

	def test_bootstrap_rejects_guest(self):
		frappe.set_user("Guest")
		result = bootstrap_module.get()
		# Guest has no cashier role; mobile_pos_endpoint maps to PERMISSION_DENIED.
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
