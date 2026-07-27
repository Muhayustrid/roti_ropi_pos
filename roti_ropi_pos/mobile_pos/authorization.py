from __future__ import annotations

import frappe

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

CASHIER_ROLE = "Mobile POS Cashier"


def require_authenticated_user() -> str:
	"""Return the authenticated user or reject Guest."""
	if frappe.session.user == "Guest":
		raise frappe.PermissionError("Authentication is required.")
	return frappe.session.user


def require_pos_invoice_mode() -> None:
	"""Reject any site configured for a non POS-Invoice invoice mode."""
	invoice_type = frappe.db.get_single_value("POS Settings", "invoice_type")
	if invoice_type != "POS Invoice":
		raise MobilePOSAPIError(
			"UNSUPPORTED_POS_MODE",
			"The site is not configured for POS Invoice mode.",
			status=422,
			details={"configured_mode": invoice_type or "", "required_mode": "POS Invoice"},
		)


def get_authorized_profile(name: str):
	"""Return an enabled POS Profile assigned to the current user.

	Existence, disabled state, and permission failures are collapsed into the
	non-disclosing ``PROFILE_SCOPE_MISMATCH`` error. Unknown exceptions are not
	caught and propagate to the request-ID logger.
	"""
	user = require_authenticated_user()
	try:
		profile = frappe.get_doc("POS Profile", name)
	except frappe.DoesNotExistError as error:
		raise MobilePOSAPIError(
			"PROFILE_SCOPE_MISMATCH",
			"The POS Profile is not available.",
			status=403,
			details={"pos_profile": name},
		) from error
	try:
		profile.check_permission("read")
	except frappe.PermissionError as error:
		raise MobilePOSAPIError(
			"PROFILE_SCOPE_MISMATCH",
			"The POS Profile is not available.",
			status=403,
			details={"pos_profile": name},
		) from error
	if profile.disabled:
		raise MobilePOSAPIError(
			"PROFILE_SCOPE_MISMATCH",
			"The POS Profile is not available.",
			status=403,
			details={"pos_profile": name},
		)
	assigned = {row.user for row in profile.applicable_for_users}
	if user not in assigned:
		raise MobilePOSAPIError(
			"PROFILE_SCOPE_MISMATCH",
			"The POS Profile is not available.",
			status=403,
			details={"pos_profile": name},
		)
	return profile


def require_doc_permission(doctype: str, permission_type: str, doc=None) -> None:
	"""Reject a missing core permission with the stable envelope.

	Only ``frappe.PermissionError`` is mapped. Unknown exceptions propagate so
	they are never silently converted into authorization errors.
	"""
	try:
		if not frappe.has_permission(doctype, ptype=permission_type, doc=doc):
			raise frappe.PermissionError
	except frappe.PermissionError as error:
		raise MobilePOSAPIError(
			"PERMISSION_DENIED",
			"The operation is not permitted.",
			status=403,
		) from error


def has_cashier_role(user: str | None = None) -> bool:
	return CASHIER_ROLE in frappe.get_roles(user or frappe.session.user)


def get_capabilities(profile=None, opening=None) -> dict:
	"""Derive advertised capabilities from identity, profile, opening, and perms.

	The API never advertises a mutation that would immediately fail a
	server-known prerequisite. With no selected authorized profile every
	mutation capability is false.
	"""
	capabilities = {
		"open_session": False,
		"submit_sale": False,
		"create_return": False,
		"cancel_sale": False,
		"close_session": False,
	}
	if not profile:
		return capabilities
	from roti_ropi_pos.mobile_pos.sessions import get_current_opening

	if opening is None:
		opening = get_current_opening(profile)
	active = bool(opening)
	capabilities["open_session"] = not active and _can("POS Opening Entry", ("create", "submit"))
	capabilities["submit_sale"] = active and _can("POS Invoice", ("create", "submit"))
	capabilities["create_return"] = active and _can("POS Invoice", ("read", "create", "submit"))
	capabilities["close_session"] = active and _can("POS Closing Entry", ("create", "submit"))
	return capabilities


def _can(doctype: str, ptypes: tuple[str, ...]) -> bool:
	return all(frappe.has_permission(doctype, ptype=p) for p in ptypes)
