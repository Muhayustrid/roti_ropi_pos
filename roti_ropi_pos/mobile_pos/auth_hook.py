from __future__ import annotations

import base64
import binascii

import frappe
import frappe.api.v1
import frappe.api.v2
from werkzeug.exceptions import HTTPException

CASHIER_ROLE = "Mobile POS Cashier"

MOBILE_POS_METHODS = {
	"roti_ropi_pos.api.v1.bootstrap.get",
	"roti_ropi_pos.api.v1.sessions.current",
	"roti_ropi_pos.api.v1.sessions.open",
	"roti_ropi_pos.api.v1.customers.search",
	"roti_ropi_pos.api.v1.catalog.search",
	"roti_ropi_pos.api.v1.catalog.scan",
	"roti_ropi_pos.api.v1.catalog.quote_item",
	"roti_ropi_pos.api.v1.sales.submit",
	"roti_ropi_pos.api.v1.sales.quote_cart",
	"roti_ropi_pos.api.v1.sales.quote_return",
	"roti_ropi_pos.api.v1.sales.list",
	"roti_ropi_pos.api.v1.sales.get",
	"roti_ropi_pos.api.v1.sales.create_return",
	"roti_ropi_pos.api.v1.closing.preview",
	"roti_ropi_pos.api.v1.closing.submit",
	"roti_ropi_pos.api.v1.closing.recover",
	"roti_ropi_pos.api.v1.closing.status",
}

MOBILE_POS_PATHS = {f"/api/method/{method}" for method in MOBILE_POS_METHODS}

MOBILE_POS_BROWSER_PATHS = {
	"/api/method/login",
	"/api/method/frappe.integrations.oauth2.authorize",
	"/api/method/frappe.integrations.oauth2.approve",
}

MOBILE_POS_CASHIER_EXACT_ROUTES = {
	("GET", "/logout", None),
	("POST", "/", "logout"),
	("POST", "/api/method/logout", None),
}

MOBILE_POS_TOKEN_PATHS = {
	"/api/method/frappe.integrations.oauth2.get_token",
}


def validate_mobile_oauth_request(path: str, user: str) -> None:
	"""Enforce exact routes and PKCE S256 for the configured public client."""
	mobile_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
	authorization = frappe.get_request_header("Authorization", "")
	client_id = frappe.form_dict.get("client_id") or _basic_username(authorization)
	is_mobile_client = bool(mobile_client_id and client_id == mobile_client_id)
	is_mobile_only = _is_mobile_only_account(user)
	command = frappe.form_dict.get("cmd")
	method = getattr(frappe.request, "method", "GET")
	is_exact_cashier_command = (method, path, command) in MOBILE_POS_CASHIER_EXACT_ROUTES
	is_login_submit = path == "/api/method/login" and command == "login"

	if command and (is_mobile_client or is_mobile_only) and not (is_login_submit or is_exact_cashier_command):
		raise frappe.PermissionError("Legacy command dispatch is not allowed.")
	if not is_mobile_client:
		return
	if path not in MOBILE_POS_BROWSER_PATHS | MOBILE_POS_TOKEN_PATHS:
		raise frappe.PermissionError("Alternate OAuth dispatch is not allowed.")
	if path in {
		"/api/method/frappe.integrations.oauth2.authorize",
		"/api/method/frappe.integrations.oauth2.approve",
	} and (
		not frappe.form_dict.get("code_challenge") or frappe.form_dict.get("code_challenge_method") != "S256"
	):
		raise frappe.AuthenticationError("Mobile POS requires PKCE S256.")
	if path in MOBILE_POS_TOKEN_PATHS:
		if (
			frappe.form_dict.get("client_secret")
			or authorization.lower().startswith("basic ")
			or frappe.form_dict.get("grant_type") not in {"authorization_code", "refresh_token"}
		):
			raise frappe.AuthenticationError("Mobile POS is a public Authorization Code client.")


def _basic_username(authorization: str) -> str | None:
	if not authorization.lower().startswith("basic "):
		return None
	try:
		encoded = authorization.split(" ", 1)[1]
		return base64.b64decode(encoded, validate=True).decode().split(":", 1)[0]
	except (binascii.Error, UnicodeDecodeError, IndexError):
		return None


def _has_cashier_role(user: str) -> bool:
	"""Return True when the account carries an explicit Mobile POS Cashier role row.

	Read the `Has Role` table rather than `frappe.get_roles`, which returns every
	existing role for `Administrator` and would therefore report the cashier role
	for an account that was never granted it. Built-in accounts are excluded so a
	bearer token can never authorise `Administrator` or `Guest`.
	"""
	return bool(
		user not in frappe.STANDARD_USERS
		and frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": CASHIER_ROLE})
	)


def _is_mobile_only_account(user: str) -> bool:
	"""Return True when the account exists solely to drive the Mobile POS API.

	Desk access is the framework's own boundary: core derives `User.user_type` from
	whether any assigned role sets `Role.desk_access`
	(`frappe.core.doctype.user.user.User.set_system_user`), and the shipped
	`Mobile POS Cashier` role sets `desk_access = 0`. An account that holds a desk
	role is a Desk account and keeps normal Frappe authorisation even when it also
	carries the cashier role — which the Setup Wizard grants to the first System
	User along with every other role
	(`frappe.desk.page.setup_wizard.setup_wizard._get_default_roles`).

	`User.has_desk_access` is asked directly rather than reading the denormalised
	`user_type`, so the boundary cannot desynchronise from the assigned roles.
	"""
	return _has_cashier_role(user) and not frappe.get_cached_doc("User", user).has_desk_access()


def validate_mobile_api_scope() -> None:
	"""Restrict Mobile POS OAuth and cashier requests before endpoint dispatch."""
	path = frappe.request.path
	user = frappe.session.user

	if MOBILE_POS_METHODS & _dispatch_identities():
		_validate_mobile_bearer(user)
		if frappe.form_dict.get("cmd") or path not in MOBILE_POS_PATHS:
			raise frappe.PermissionError("Alternate Mobile POS dispatch is not allowed.")
		return

	validate_mobile_oauth_request(path, user)
	if _is_mobile_only_account(user):
		method = getattr(frappe.request, "method", "GET")
		command = frappe.form_dict.get("cmd")
		if path not in MOBILE_POS_BROWSER_PATHS and (
			method,
			path,
			command,
		) not in MOBILE_POS_CASHIER_EXACT_ROUTES:
			raise frappe.PermissionError("This account may access only the Mobile POS API.")


def _dispatch_identities() -> set[str]:
	"""Return every method identity this request can dispatch to.

	Both the requested identity and the `override_whitelisted_methods` target are
	returned, because either being a Mobile POS callable is enough to require the
	bearer gate: an override redirects a Mobile POS route away from its own module,
	and it can equally redirect a generic route into one.
	"""
	if command := frappe.form_dict.get("cmd"):
		requested = command
	else:
		try:
			endpoint, arguments = frappe.api.API_URL_MAP.bind_to_environ(frappe.request.environ).match()
		except HTTPException:
			return set()

		if endpoint is frappe.api.v1.handle_rpc_call:
			requested = arguments["method"].split("/")[0]
		elif endpoint is frappe.api.v2.handle_rpc_call and not arguments.get("doctype"):
			requested = arguments["method"]
		else:
			return set()

	return {requested, frappe.override_whitelisted_method(requested)}


def _validate_mobile_bearer(user: str) -> None:
	auth_type, separator, access_token = frappe.get_request_header("Authorization", "").partition(" ")
	if auth_type.lower() != "bearer" or not separator or not access_token:
		raise frappe.AuthenticationError("OAuth bearer authentication is required.")
	token = frappe.db.get_value(
		"OAuth Bearer Token",
		{"access_token": access_token},
		["client", "user", "status", "expiration_time"],
		as_dict=True,
	)
	if (
		not token
		or token.client != frappe.conf.get("mobile_pos_oauth_client_id")
		or token.user != user
		or token.status != "Active"
		or not token.expiration_time
		or frappe.utils.now_datetime() >= token.expiration_time
		or not frappe.db.get_value("User", user, "enabled")
		or not _has_cashier_role(user)
	):
		raise frappe.AuthenticationError("The Mobile POS bearer token is not authorized.")
