from __future__ import annotations

import functools
from collections.abc import Callable

import frappe

from roti_ropi_pos.mobile_pos.authorization import (
	get_authorized_profile,
	get_capabilities,
	has_cashier_role,
	require_authenticated_user,
	require_pos_invoice_mode,
)
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.profiles import list_assigned_profiles, profile_dto
from roti_ropi_pos.mobile_pos.responses import api_endpoint, success
from roti_ropi_pos.mobile_pos.sessions import get_current_opening, opening_dto


def mobile_pos_endpoint(func: Callable[..., dict]) -> Callable[..., dict]:
	"""Common decorator for every v1 endpoint.

	Before endpoint logic it verifies the enabled user, ``Mobile POS Cashier``,
	and supported POS Invoice mode. Bearer/client boundary and route denial are
	enforced by the registered ``auth_hook`` before this decorator runs. The
	composed Phase 1 ``api_endpoint`` owns savepoint/error mapping for every v1
	adapter.
	"""

	@functools.wraps(func)
	def wrapper(*args, **kwargs) -> dict:
		try:
			user = require_authenticated_user()
			if not frappe.db.get_value("User", user, "enabled"):
				raise MobilePOSAPIError(
					"PERMISSION_DENIED",
					"The operation is not permitted.",
					status=403,
				)
			if not has_cashier_role(user):
				raise MobilePOSAPIError(
					"PERMISSION_DENIED",
					"The operation is not permitted.",
					status=403,
				)
			require_pos_invoice_mode()
			return func(*args, **kwargs)
		except frappe.PermissionError as error:
			# Known permission failures (e.g. Guest) map to the stable 403 envelope.
			raise MobilePOSAPIError(
				"PERMISSION_DENIED",
				"The operation is not permitted.",
				status=403,
			) from error

	return api_endpoint(wrapper)


@frappe.whitelist(methods=["GET"])
@mobile_pos_endpoint
def get(pos_profile: str | None = None) -> dict:
	"""Return the cashier's bootstrap: user, profiles, opening, capabilities."""
	user = require_authenticated_user()
	profiles = list_assigned_profiles(user)
	selected = None
	if pos_profile:
		selected = get_authorized_profile(pos_profile)
	elif len(profiles) == 1:
		selected = profiles[0]
	opening = get_current_opening(selected) if selected else None
	return success(
		{
			"user": {"name": user, "full_name": frappe.db.get_value("User", user, "full_name")},
			"profiles": [profile_dto(p) for p in profiles],
			"selected_profile": profile_dto(selected) if selected else None,
			"opening_session": opening_dto(opening) if opening else None,
			"capabilities": get_capabilities(selected, opening),
			"pos_mode": "POS Invoice",
		}
	)
