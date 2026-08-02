from __future__ import annotations

from decimal import Decimal

import frappe

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.validation import opening_amount_string


def profile_opening_config(doc) -> dict:
	currency = frappe.db.get_value("Company", doc.company, "default_currency")
	if not currency:
		raise _profile_error(doc, "company", "Company currency could not be resolved.")
	decimal_places = frappe.get_precision("POS Opening Entry Detail", "opening_amount", currency=currency)
	column_type = frappe.db.get_column_type("POS Opening Entry Detail", "opening_amount")
	if decimal_places is None or not column_type:
		raise _profile_error(
			doc, "opening_amount", "Opening amount storage configuration could not be resolved."
		)

	modes = []
	seen = set()
	for row in doc.payments:
		mode_name = row.mode_of_payment
		if not isinstance(mode_name, str) or not mode_name or mode_name in seen:
			raise _profile_error(doc, "payments", "Payment rows must contain unique mode names.")
		seen.add(mode_name)
		try:
			mode = frappe.get_doc("Mode of Payment", mode_name)
		except frappe.DoesNotExistError as error:
			raise _profile_error(doc, "payments", "Linked Mode of Payment does not exist.") from error
		if not mode.enabled:
			raise _profile_error(doc, "payments", "Linked Mode of Payment is disabled.")
		accounts = [account for account in mode.accounts if account.company == doc.company]
		if len(accounts) != 1:
			raise _profile_error(doc, "payments", "Exactly one company-specific payment account is required.")
		if frappe.db.get_value("Account", accounts[0].default_account, "company") != doc.company:
			raise _profile_error(doc, "payments", "Payment account does not belong to the Company.")
		suggestion = getattr(row, "custom_mobile_pos_suggested_opening_amount", None) or "0"
		try:
			canonical = opening_amount_string(
				suggestion,
				field="custom_mobile_pos_suggested_opening_amount",
				decimal_places=decimal_places,
				column_type=column_type,
			)
		except MobilePOSAPIError as error:
			raise _profile_error(
				doc, "payments", error.details.get("reason", "Invalid suggested amount.")
			) from error
		modes.append(
			{
				"mode_of_payment": mode_name,
				"suggested_opening_amount": canonical,
				"amount_editable": True,
			}
		)
	if not modes:
		raise _profile_error(doc, "payments", "At least one payment mode is required.")
	return {
		"opening_payment_modes": modes,
		"opening_amount_policy": {
			"currency": currency,
			"decimal_places": decimal_places,
			"minimum": f"{Decimal(0):.{decimal_places}f}",
			"api_syntax": "ascii_decimal_dot",
			"rounding": "reject",
			"policy_version": "opening-amount/v1",
		},
		"decimal_places": decimal_places,
		"column_type": column_type,
	}


def _profile_error(doc, field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"PROFILE_CONFIGURATION_INVALID",
		"The POS Profile configuration is invalid.",
		status=422,
		details={"pos_profile": doc.name, "field": field, "reason": reason},
	)


def profile_dto(doc) -> dict:
	"""Project only the safe, contract-approved POS Profile summary fields."""
	config = profile_opening_config(doc)
	return {
		"name": doc.name,
		"company": doc.company,
		"warehouse": doc.warehouse,
		"currency": doc.currency,
		"selling_price_list": doc.selling_price_list,
		"customer": doc.customer,
		"allow_partial_payment": False,
		"invoice_mode": "POS Invoice",
		"opening_payment_modes": config["opening_payment_modes"],
		"opening_amount_policy": config["opening_amount_policy"],
	}


def list_assigned_profiles(user: str) -> list:
	"""Return enabled POS Profiles explicitly assigned to ``user``."""
	names = frappe.db.get_all(
		"POS Profile User",
		filters={"user": user},
		fields=["parent"],
		as_list=True,
	)
	profiles = []
	for (parent,) in names:
		profile = frappe.get_doc("POS Profile", parent)
		if profile.disabled:
			continue
		try:
			profile.check_permission("read")
		except frappe.PermissionError:
			continue
		profiles.append(profile)
	return profiles
