from __future__ import annotations

import frappe

MOBILE_POS_PATHS = {
	"/api/method/roti_ropi_pos.api.v1.bootstrap.get",
	"/api/method/roti_ropi_pos.api.v1.sessions.current",
	"/api/method/roti_ropi_pos.api.v1.sessions.open",
	"/api/method/roti_ropi_pos.api.v1.customers.search",
	"/api/method/roti_ropi_pos.api.v1.catalog.search",
	"/api/method/roti_ropi_pos.api.v1.catalog.scan",
	"/api/method/roti_ropi_pos.api.v1.catalog.quote_item",
	"/api/method/roti_ropi_pos.api.v1.sales.submit",
	"/api/method/roti_ropi_pos.api.v1.sales.get",
	"/api/method/roti_ropi_pos.api.v1.sales.list",
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

CASHIER_ROLE = "Mobile POS Cashier"


def validate_mobile_oauth_request(path: str, user: str) -> None:
	"""Enforce the public-client OAuth and route boundary for Mobile POS.

	Applies only to requests carrying the configured Mobile POS client id or to
	``Mobile POS Cashier`` accounts. Non-mobile users keep normal Frappe
	behavior. The hook compares Werkzeug's decoded ``request.path`` to exact
	entries; it never uses prefix, substring, query, or client-supplied command
	matching.
	"""
	mobile_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
	client_id = frappe.form_dict.get("client_id")
	is_mobile_client = bool(mobile_client_id and client_id == mobile_client_id)
	is_mobile_cashier = user != "Guest" and CASHIER_ROLE in frappe.get_roles(user)
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
	}:
		if (
			not frappe.form_dict.get("code_challenge")
			or frappe.form_dict.get("code_challenge_method") != "S256"
		):
			raise frappe.AuthenticationError("Mobile POS requires PKCE S256.")
	if path in MOBILE_POS_TOKEN_PATHS:
		authorization = frappe.get_request_header("Authorization", "")
		if frappe.form_dict.get("client_secret") or authorization.lower().startswith("basic "):
			raise frappe.AuthenticationError("Mobile POS is a public OAuth client.")


def validate_mobile_api_scope() -> None:
	"""Auth hook registered in ``auth_hooks``."""
	path = frappe.request.path.rstrip("/")
	user = frappe.session.user
	validate_mobile_oauth_request(path, user)
	if path in MOBILE_POS_PATHS:
		auth_type, separator, access_token = frappe.get_request_header("Authorization", "").partition(" ")
		if auth_type.lower() != "bearer" or not separator or not access_token:
			raise frappe.AuthenticationError("OAuth bearer authentication is required.")
		token = frappe.db.get_value(
			"OAuth Bearer Token",
			access_token,
			["client", "user", "status"],
			as_dict=True,
		)
		if (
			not token
			or token.client != frappe.conf.get("mobile_pos_oauth_client_id")
			or token.user != user
			or token.status != "Active"
			or not frappe.db.get_value("User", user, "enabled")
			or CASHIER_ROLE not in frappe.get_roles(user)
			or path not in MOBILE_POS_PATHS
		):
			raise frappe.AuthenticationError("The Mobile POS bearer token is not authorized.")
		return
	if user != "Guest" and CASHIER_ROLE in frappe.get_roles(user) and path not in MOBILE_POS_BROWSER_PATHS:
		frappe.throw("This account may access only the Mobile POS API.", frappe.PermissionError)
