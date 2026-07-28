from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import bootstrap as bootstrap_api
from roti_ropi_pos.mobile_pos.authorization import get_capabilities
from roti_ropi_pos.mobile_pos.profiles import list_assigned_profiles, profile_dto
from roti_ropi_pos.tests.helpers import (
	close_test_openings,
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
		self.cashier = make_cashier(f"bootstrap-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.other = make_cashier(f"bootstrap-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.profile = make_pos_profile(
			f"Mobile POS Bootstrap {frappe.generate_hash(length=8)}",
			company=COMPANY,
			warehouse=WAREHOUSE,
			customer=CUSTOMER,
			user=self.cashier,
		)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier, self.other)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def test_bootstrap_returns_safe_assigned_profile_and_auto_selects_single(self):
		frappe.set_user(self.cashier)
		result = bootstrap_api.get()
		self.assertTrue(result["ok"])
		self.assertEqual(result["data"]["selected_profile"]["name"], self.profile)
		self.assertEqual(result["data"]["user"]["name"], self.cashier)
		self.assertEqual(
			set(result["data"]["profiles"][0]),
			{
				"name",
				"company",
				"warehouse",
				"currency",
				"selling_price_list",
				"customer",
				"allow_partial_payment",
				"invoice_mode",
			},
		)

	def test_bootstrap_rejects_unassigned_profile(self):
		frappe.set_user(self.other)
		result = bootstrap_api.get(pos_profile=self.profile)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "PROFILE_SCOPE_MISMATCH")

	def test_bootstrap_rejects_guest_and_wrong_role(self):
		frappe.set_user("Guest")
		result = bootstrap_api.get()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")

	def test_list_profiles_checks_normal_read_permission(self):
		frappe.set_user(self.cashier)
		profile = MagicMock(name="profile")
		profile.name = self.profile
		profile.disabled = 0
		profile.check_permission.side_effect = frappe.PermissionError
		with (
			patch("frappe.db.get_all", return_value=[(self.profile,)]),
			patch("frappe.get_doc", return_value=profile),
		):
			self.assertEqual(list_assigned_profiles(self.cashier), [])

	def test_profile_permission_unknown_exception_propagates(self):
		frappe.set_user(self.cashier)
		with (
			patch("frappe.db.get_all", return_value=[(self.profile,)]),
			patch("frappe.get_doc", side_effect=RuntimeError("boom")),
			self.assertRaisesRegex(RuntimeError, "boom"),
		):
			list_assigned_profiles(self.cashier)

	def test_bootstrap_preserves_prior_day_opening_warning(self):
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile,
			period_start_date="2026-07-20 08:00:00",
			posting_date="2026-07-20",
		)
		frappe.set_user(self.cashier)
		result = bootstrap_api.get(pos_profile=self.profile)
		opening = result["data"]["opening_session"]
		self.assertEqual(opening["posting_date"], "2026-07-20")
		self.assertTrue(opening["period_start_date"])
		self.assertEqual(opening["warnings"][0]["code"], "STALE_OPENING")

	def test_capabilities_false_without_profile(self):
		frappe.set_user(self.cashier)
		self.assertFalse(any(get_capabilities().values()))

	def test_unsupported_mode_uses_stable_error(self):
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")
		frappe.set_user(self.cashier)
		result = bootstrap_api.get()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "UNSUPPORTED_POS_MODE")

	def test_profile_dto_does_not_trust_partial_payment_configuration(self):
		frappe.set_user(self.cashier)
		profile = frappe.get_doc("POS Profile", self.profile)
		self.assertFalse(profile_dto(profile)["allow_partial_payment"])
