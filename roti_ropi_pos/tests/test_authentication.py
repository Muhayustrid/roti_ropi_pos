import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.auth_hook import (
	MOBILE_POS_PATHS,
	validate_mobile_api_scope,
	validate_mobile_oauth_request,
)
from roti_ropi_pos.mobile_pos.authorization import (
	get_authorized_profile,
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
BOOTSTRAP_PATH = "/api/method/roti_ropi_pos.api.v1.bootstrap.get"


class TestAuthentication(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.saved_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
		frappe.conf["mobile_pos_oauth_client_id"] = CLIENT_ID
		self.cashier = make_cashier(f"auth-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.other = make_cashier(f"auth-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.profile = make_pos_profile(
			f"Mobile POS Auth {frappe.generate_hash(length=8)}",
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
		if self.saved_client_id is None:
			frappe.conf.pop("mobile_pos_oauth_client_id", None)
		else:
			frappe.conf["mobile_pos_oauth_client_id"] = self.saved_client_id
		frappe.set_user("Administrator")
		super().tearDown()

	def _request(self, path=BOOTSTRAP_PATH, *, user=None, form=None, authorization=""):
		frappe.set_user(self.cashier if user is None else user)
		frappe.local.form_dict = frappe._dict(form or {})
		set_request(path)
		return patch("frappe.get_request_header", return_value=authorization)

	def test_mobile_allowlist_contains_only_shipped_endpoints(self):
		self.assertEqual(
			MOBILE_POS_PATHS,
			{
				"/api/method/roti_ropi_pos.api.v1.bootstrap.get",
				"/api/method/roti_ropi_pos.api.v1.sessions.current",
				"/api/method/roti_ropi_pos.api.v1.sessions.open",
				"/api/method/roti_ropi_pos.api.v1.customers.search",
			},
		)

	def test_permission_fixture_preserves_core_roles_and_adds_exact_cashier_rows(self):
		with open(frappe.get_app_path("roti_ropi_pos", "fixtures", "custom_docperm.json")) as fixture:
			rows = json.load(fixture)
		cashier_rows = [row for row in rows if row["role"] == "Mobile POS Cashier"]
		self.assertEqual(len(cashier_rows), 6)
		self.assertTrue(any(row["role"] != "Mobile POS Cashier" for row in rows))
		self.assertEqual(
			{row["parent"] for row in cashier_rows},
			{
				"POS Profile",
				"POS Opening Entry",
				"POS Invoice",
				"POS Closing Entry",
				"Customer",
				"Item",
			},
		)
		for row in cashier_rows:
			for permission in ("cancel", "delete", "amend", "report", "export", "import", "share"):
				self.assertFalse(row[permission])

	def test_require_authenticated_user_rejects_guest(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			require_authenticated_user()

	def test_require_pos_invoice_mode_rejects_other_mode(self):
		frappe.db.set_single_value("POS Settings", "invoice_type", "Sales Invoice")
		with self.assertRaises(MobilePOSAPIError) as error:
			require_pos_invoice_mode()
		self.assertEqual(error.exception.code, "UNSUPPORTED_POS_MODE")

	def test_authorized_profile_rejects_other_cashier(self):
		frappe.set_user(self.other)
		with self.assertRaises(MobilePOSAPIError) as error:
			get_authorized_profile(self.profile)
		self.assertEqual(error.exception.code, "PROFILE_SCOPE_MISMATCH")

	def test_doc_permission_maps_known_denial_only(self):
		frappe.set_user(self.cashier)
		with self.assertRaises(MobilePOSAPIError) as error:
			require_doc_permission("Mobile POS Request", "read")
		self.assertEqual(error.exception.code, "PERMISSION_DENIED")
		with patch("frappe.has_permission", side_effect=RuntimeError("boom")):
			with self.assertRaisesRegex(RuntimeError, "boom"):
				require_doc_permission("POS Invoice", "create")

	def test_v1_requires_bearer_scheme(self):
		for authorization in ("", "token key:secret", "Basic dXNlcjpwYXNz"):
			with self.subTest(authorization=authorization), self._request(authorization=authorization):
				with self.assertRaises(frappe.AuthenticationError):
					validate_mobile_api_scope()

	def test_v1_accepts_matching_active_bearer(self):
		with self._request(authorization=f"Bearer {TOKEN}"):
			validate_mobile_api_scope()

	def test_v1_rejects_wrong_client_user_and_inactive_tokens(self):
		make_bearer_token("wrong-client", client_id="other-client", user=self.cashier)
		make_bearer_token("wrong-user", client_id=CLIENT_ID, user=self.other)
		make_bearer_token("inactive", client_id=CLIENT_ID, user=self.cashier, status="Revoked")
		for token in ("wrong-client", "wrong-user", "inactive", "missing"):
			with self.subTest(token=token), self._request(authorization=f"Bearer {token}"):
				with self.assertRaises(frappe.AuthenticationError):
					validate_mobile_api_scope()

	def test_v1_rejects_expired_active_token(self):
		frappe.db.set_value("OAuth Bearer Token", TOKEN, "expiration_time", "2020-01-01 00:00:00")
		with self._request(authorization=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_v1_rejects_disabled_cashier(self):
		frappe.db.set_value("User", self.cashier, "enabled", 0)
		with self._request(authorization=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_api_scope()

	def test_cashier_cannot_use_generic_v2_or_encoded_alternate_routes(self):
		for path in (
			"/api/method/frappe.client.get",
			"/api/resource/POS Invoice",
			"/api/v2/method/roti_ropi_pos.api.v1.bootstrap.get",
			"/api/method/roti_ropi_pos.api.v1.bootstrap%2Eget",
		):
			with self.subTest(path=path), self._request(path=path):
				with self.assertRaises(frappe.PermissionError):
					validate_mobile_api_scope()

	def test_legacy_cmd_rejected_except_exact_login_submission(self):
		with self._request(path="/api/method/frappe.client.get", form={"cmd": "frappe.client.get"}):
			with self.assertRaises(frappe.PermissionError):
				validate_mobile_api_scope()
		with self._request(path="/api/method/login", form={"cmd": "login"}):
			validate_mobile_api_scope()

	def test_mobile_authorize_and_approve_require_pkce_s256(self):
		for path in (
			"/api/method/frappe.integrations.oauth2.authorize",
			"/api/method/frappe.integrations.oauth2.approve",
		):
			for form in (
				{"client_id": CLIENT_ID},
				{"client_id": CLIENT_ID, "code_challenge": "abc", "code_challenge_method": "plain"},
			):
				with self.subTest(path=path, form=form), self._request(path=path, user="Guest", form=form):
					with self.assertRaises(frappe.AuthenticationError):
						validate_mobile_oauth_request(path, "Guest")
			with self._request(
				path=path,
				user="Guest",
				form={"client_id": CLIENT_ID, "code_challenge": "abc", "code_challenge_method": "S256"},
			):
				validate_mobile_oauth_request(path, "Guest")

	def test_public_token_flow_rejects_secret_basic_and_password_grant(self):
		path = "/api/method/frappe.integrations.oauth2.get_token"
		with self._request(path=path, user="Guest", form={"client_id": CLIENT_ID, "client_secret": "x"}):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_oauth_request(path, "Guest")
		with self._request(
			path=path,
			user="Guest",
			form={"client_id": CLIENT_ID},
			authorization="Basic dXNlcjpwYXNz",
		):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_oauth_request(path, "Guest")
		with self._request(
			path=path,
			user="Guest",
			form={"client_id": CLIENT_ID, "grant_type": "password"},
		):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_oauth_request(path, "Guest")

	def test_basic_mobile_client_is_detected_without_form_client_id(self):
		path = "/api/method/frappe.integrations.oauth2.get_token"
		import base64

		authorization = "Basic " + base64.b64encode(f"{CLIENT_ID}:ignored".encode()).decode()
		with self._request(path=path, user="Guest", authorization=authorization):
			with self.assertRaises(frappe.AuthenticationError):
				validate_mobile_oauth_request(path, "Guest")

	def test_trailing_slash_is_not_an_exact_mobile_api_path(self):
		with self._request(path=f"{BOOTSTRAP_PATH}/", authorization=f"Bearer {TOKEN}"):
			with self.assertRaises(frappe.PermissionError):
				validate_mobile_api_scope()

	def test_mobile_client_cannot_substitute_generic_oauth_route(self):
		path = "/api/method/frappe.client.get"
		with self._request(path=path, user="Guest", form={"client_id": CLIENT_ID}):
			with self.assertRaises(frappe.PermissionError):
				validate_mobile_oauth_request(path, "Guest")
