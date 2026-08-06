from __future__ import annotations

import base64
import binascii

import frappe

CASHIER_ROLE = "Mobile POS Cashier"

MOBILE_POS_PATHS = {
	"/api/method/roti_ropi_pos.api.v1.bootstrap.get",
	"/api/method/roti_ropi_pos.api.v1.sessions.current",
	"/api/method/roti_ropi_pos.api.v1.sessions.open",
	"/api/method/roti_ropi_pos.api.v1.customers.search",
	"/api/method/roti_ropi_pos.api.v1.catalog.search",
	"/api/method/roti_ropi_pos.api.v1.catalog.scan",
	"/api/method/roti_ropi_pos.api.v1.catalog.quote_item",
	"/api/method/roti_ropi_pos.api.v1.sales.submit",
	"/api/method/roti_ropi_pos.api.v1.sales.quote_cart",
	"/api/method/roti_ropi_pos.api.v1.sales.list",
	"/api/method/roti_ropi_pos.api.v1.sales.get",
	"/api/method/roti_ropi_pos.api.v1.sales.create_return",
	"/api/method/roti_ropi_pos.api.v1.closing.preview",
	"/api/method/roti_ropi_pos.api.v1.closing.submit",
	"/api/method/roti_ropi_pos.api.v1.closing.status",
}

MOBILE_POS_BROWSER_PATHS = {
	"/api/method/login",
	"/api/method/frappe.integrations.oauth2.authorize",
	"/api/method/frappe.integrations.oauth2.approve",
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
	is_mobile_cashier = _is_mobile_cashier(user)
	command = frappe.form_dict.get("cmd")
	is_login_submit = path == "/api/method/login" and command == "login"

	if command and (is_mobile_client or is_mobile_cashier) and not is_login_submit:
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


def _is_mobile_cashier(user: str) -> bool:
	return bool(
		user not in {"Guest", "Administrator"}
		and frappe.db.exists("Has Role", {"parent": user, "role": CASHIER_ROLE})
	)


def validate_mobile_api_scope() -> None:
	"""Restrict Mobile POS OAuth and cashier requests before endpoint dispatch."""
	path = frappe.request.path
	user = frappe.session.user
	validate_mobile_oauth_request(path, user)

	if path in MOBILE_POS_PATHS:
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
			or not _is_mobile_cashier(user)
		):
			raise frappe.AuthenticationError("The Mobile POS bearer token is not authorized.")
		return

	if _is_mobile_cashier(user) and path not in MOBILE_POS_BROWSER_PATHS:
		raise frappe.PermissionError("This account may access only the Mobile POS API.")
