from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.auth_hook import (
	validate_mobile_api_scope,
	validate_mobile_oauth_request,
)
from roti_ropi_pos.mobile_pos.authorization import (
	get_authorized_profile,
	has_cashier_role,
	require_authenticated_user,
	require_doc_permission,
	require_pos_invoice_mode,
)
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.tests.helpers import (
	clear_fake_request,
	make_bearer_token,
	make_cashier,
	make_oauth_client,
	make_pos_profile,
	set_request,
)

COMPANY = "_Test Company"
WAREHOUSE = "_Test Warehouse - _TC"
CUSTOMER = "_Test Customer"
CLIENT_ID = "rotiropi.mobilepos.test"
TOKEN = "rotiropi-bearer-token-test"


class TestAuthentication(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self._saved_conf = dict(frappe.conf)
		frappe.conf["mobile_pos_oauth_client_id"] = CLIENT_ID
		self.cashier = make_cashier("cashier1@rotiropi.test")
		self.other = make_cashier("cashier2@rotiropi.test")
		self.profile = make_pos_profile(
			"Mobile POS Test Profile A",
			company=COMPANY,
			warehouse=WAREHOUSE,
			customer=CUSTOMER,
			user=self.cashier,
		)
		make_oauth_client(CLIENT_ID)
		make_bearer_token(TOKEN, client_id=CLIENT_ID, user=self.cashier)

	def tearDown(self) -> None:
		clear_fake_request()
		frappe.local.form_dict = frappe._dict()
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		frappe.conf.clear()
		frappe.conf.update(self._saved_conf)
		frappe.set_user("Administrator")
		super().tearDown()

	def test_require_pos_invoice_mode_rejects_sales_invoice_mode(self):
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")
		with self.assertRaises(MobilePOSAPIError) as error:
			require_pos_invoice_mode()
		self.assertEqual(error.exception.code, "UNSUPPORTED_POS_MODE")
		self.assertEqual(error.exception.details["required_mode"], "POS Invoice")

	def test_require_pos_invoice_mode_accepts_pos_invoice(self):
		require_pos_invoice_mode()

	def test_require_authenticated_user_rejects_guest(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			require_authenticated_user()

	def test_get_authorized_profile_returns_assigned_profile(self):
		frappe.set_user(self.cashier)
		profile = get_authorized_profile(self.profile)
		self.assertEqual(profile.name, self.profile)

	def test_get_authorized_profile_rejects_unassigned_user(self):
		frappe.set_user(self.other)
		with self.assertRaises(MobilePOSAPIError) as error:
			get_authorized_profile(self.profile)
		self.assertEqual(error.exception.code, "PROFILE_SCOPE_MISMATCH")

	def test_get_authorized_profile_rejects_disabled_profile(self):
		make_pos_profile(
			"Mobile POS Test Profile Disabled",
			company=COMPANY,
			warehouse=WAREHOUSE,
			customer=CUSTOMER,
			user=self.cashier,
			disabled=1,
		)
		frappe.set_user(self.cashier)
		with self.assertRaises(MobilePOSAPIError) as error:
			get_authorized_profile("Mobile POS Test Profile Disabled")
		self.assertEqual(error.exception.code, "PROFILE_SCOPE_MISMATCH")

	def test_get_authorized_profile_rejects_user_without_cashier_role(self):
		# A user without Mobile POS Cashier lacks Custom DocPerm read on POS Profile.
		plain = make_cashier_plain("plain@rotiropi.test")
		frappe.set_user(plain)
		with self.assertRaises(MobilePOSAPIError) as error:
			get_authorized_profile(self.profile)
		self.assertEqual(error.exception.code, "PROFILE_SCOPE_MISMATCH")

	def test_require_doc_permission_denies_missing_perm(self):
		# Mobile POS Request has no cashier permission by contract.
		frappe.set_user(self.cashier)
		with self.assertRaises(MobilePOSAPIError) as error:
			require_doc_permission("Mobile POS Request", "read")
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")

	def test_require_doc_permission_re_raises_unknown_exception(self):
		with patch("frappe.has_permission", side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				require_doc_permission("POS Invoice", "create")

	def test_has_cashier_role(self):
		frappe.set_user(self.cashier)
		self.assertTrue(has_cashier_role())
		frappe.set_user("Guest")
		self.assertFalse(has_cashier_role())

	def test_auth_hook_rejects_legacy_cmd_for_mobile_cashier(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({"cmd": "frappe.client.get"})
		set_request("/api/method/frappe.client.get")
		with self.assertRaises(frappe.PermissionError):
			validate_mobile_api_scope()

	def test_auth_hook_v1_path_requires_bearer(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({})
		set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
		with patch("frappe.get_request_header", return_value=""):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_auth_hook_v1_path_accepts_valid_bearer(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({})
		set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
		with patch("frappe.get_request_header", return_value=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()  # should not raise

	def test_auth_hook_rejects_client_cmd_for_exact_v1_path(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({"cmd": "roti_ropi_pos.api.v1.bootstrap.get"})
		set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
		with patch("frappe.get_request_header", return_value=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.PermissionError):
				validate_mobile_api_scope()

	def test_auth_hook_v1_path_rejects_wrong_client_bearer(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({})
		make_bearer_token("other-client-token", client_id="some-other-client", user=self.cashier)
		set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
		with patch("frappe.get_request_header", return_value="Bearer other-client-token"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_auth_hook_v1_path_rejects_disabled_user_bearer(self):
		frappe.db.set_value("User", self.cashier, "enabled", 0)
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({})
		set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
		with patch("frappe.get_request_header", return_value=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()
		frappe.db.set_value("User", self.cashier, "enabled", 1)

	def test_auth_hook_cashier_blocked_from_generic_resource(self):
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict({})
		set_request("/api/resource/POS Invoice")
		with self.assertRaises(frappe.PermissionError):
			validate_mobile_api_scope()

	def test_auth_hook_authorize_requires_pkce_s256(self):
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict({"client_id": CLIENT_ID})
		set_request("/api/method/frappe.integrations.oauth2.authorize")
		with self.assertRaises(frappe.AuthenticationError):
			validate_mobile_oauth_request("/api/method/frappe.integrations.oauth2.authorize", "Guest")

	def test_auth_hook_authorize_rejects_plain_challenge(self):
		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict(
			{"client_id": CLIENT_ID, "code_challenge": "abc", "code_challenge_method": "plain"}
		)
		set_request("/api/method/frappe.integrations.oauth2.authorize")
		with self.assertRaises(frappe.AuthenticationError):
			validate_mobile_oauth_request("/api/method/frappe.integrations.oauth2.authorize", "Guest")

	def test_auth_hook_token_rejects_client_secret_and_basic(self):
		frappe.local.form_dict = frappe._dict({"client_id": CLIENT_ID, "client_secret": "x"})
		set_request("/api/method/frappe.integrations.oauth2.get_token")
		with self.assertRaises(frappe.AuthenticationError):
			validate_mobile_oauth_request("/api/method/frappe.integrations.oauth2.get_token", "Guest")
		frappe.local.form_dict = frappe._dict({"client_id": CLIENT_ID})
		with patch("frappe.get_request_header", return_value="Basic dXNlcjpwYXNz"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_oauth_request("/api/method/frappe.integrations.oauth2.get_token", "Guest")

	def test_auth_hook_mobile_client_blocked_from_generic_method(self):
		frappe.local.form_dict = frappe._dict({"client_id": CLIENT_ID})
		set_request("/api/method/frappe.client.get")
		with self.assertRaises(frappe.PermissionError):
			validate_mobile_oauth_request("/api/method/frappe.client.get", "Guest")


def make_cashier_plain(email: str) -> str:
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True)
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "Plain", "enabled": 1, "roles": []}
	)
	user.flags.ignore_validate = True
	user.flags.ignore_links = True
	user.insert(ignore_permissions=True)
	return email
