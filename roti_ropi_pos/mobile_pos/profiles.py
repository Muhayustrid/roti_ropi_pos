from __future__ import annotations

import frappe


def profile_dto(doc) -> dict:
	"""Project only the safe, contract-approved POS Profile summary fields."""
	return {
		"name": doc.name,
		"company": doc.company,
		"warehouse": doc.warehouse,
		"currency": doc.currency,
		"selling_price_list": doc.selling_price_list,
		"customer": doc.customer,
		# The MVP invariant forces full settlement; the contract always exposes
		# false here even if the profile is configured otherwise.
		"allow_partial_payment": False,
		"invoice_mode": "POS Invoice",
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
