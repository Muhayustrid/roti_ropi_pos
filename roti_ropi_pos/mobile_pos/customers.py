from __future__ import annotations

from dataclasses import dataclass

import frappe

from roti_ropi_pos.mobile_pos.authorization import require_doc_permission
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError


@dataclass(frozen=True)
class ResolvedCustomer:
	name: str
	custom_walk_in_customer_name: str | None


def customer_dto(row, profile) -> dict:
	return {
		"name": row.name,
		"customer_name": row.customer_name,
		"mobile_no": row.mobile_no or None,
		"is_default_walk_in": row.name == profile.customer,
	}


def search_customers(profile, q: str = "", start: int = 0, limit: int = 20) -> dict:
	if start < 0:
		raise _invalid_request("start", "Must be >= 0.")
	if limit <= 0:
		raise _invalid_request("limit", "Must be > 0.")

	limit = min(limit, 100)
	filters = _customer_filters(profile)
	fields = ["name", "customer_name", "mobile_no"]
	order_by = "customer_name asc, name asc"
	q = q.strip()

	if q:
		fetch_count = start + limit + 1
		rows_by_name = {}
		for field in ("name", "customer_name", "mobile_no"):
			rows = frappe.get_list(
				"Customer",
				fields=fields,
				filters=[*filters, [field, "like", f"%{q}%"]],
				order_by=order_by,
				limit=fetch_count,
			)
			rows_by_name.update({row.name: row for row in rows})
		rows = sorted(rows_by_name.values(), key=lambda row: (row.customer_name, row.name))[
			start:fetch_count
		]
	else:
		rows = frappe.get_list(
			"Customer",
			fields=fields,
			filters=filters,
			order_by=order_by,
			offset=start,
			limit=limit + 1,
		)

	has_more = len(rows) > limit
	return {
		"customers": [customer_dto(row, profile) for row in rows[:limit]],
		"page": {"start": start, "limit": limit, "has_more": has_more},
	}


def resolve_customer(
	profile,
	selected_customer: str | None = None,
	walk_in_customer_name: str | None = None,
) -> ResolvedCustomer:
	# Reject non-string or blank for explicit selected_customer.
	if selected_customer is not None:
		if not isinstance(selected_customer, str) or not selected_customer.strip():
			raise _invalid_request("customer", "Expected a non-empty Customer name.")
	is_explicit = bool(selected_customer)
	customer_name = selected_customer or profile.customer
	if not customer_name:
		raise _profile_customer_error(profile, "POS Profile has no default customer.")

	try:
		customer = frappe.get_doc("Customer", customer_name)
	except frappe.DoesNotExistError as error:
		raise _customer_error(
			profile,
			customer_name,
			is_explicit,
			"Configured default Customer does not exist.",
		) from error

	if customer.disabled:
		raise _customer_error(
			profile,
			customer_name,
			is_explicit,
			"Configured default Customer is disabled.",
		)

	try:
		require_doc_permission("Customer", "read", doc=customer)
	except MobilePOSAPIError as error:
		if error.code != "PERMISSION_DENIED":
			raise
		raise _customer_error(
			profile,
			customer_name,
			is_explicit,
			"Configured default Customer is not accessible.",
		) from error

	closure = _get_customer_group_closure(profile)
	if closure is not None and customer.customer_group not in closure:
		raise _customer_error(
			profile,
			customer_name,
			is_explicit,
			"Configured default Customer is outside the allowed Customer Groups.",
		)

	custom_walk_in_customer_name = None
	if walk_in_customer_name is not None:
		if not isinstance(walk_in_customer_name, str):
			raise _invalid_request("walk_in_customer_name", "Expected a string.")
		if customer.name != profile.customer:
			raise _invalid_request(
				"walk_in_customer_name",
				"This field is only accepted for the profile default walk-in Customer.",
			)
		custom_walk_in_customer_name = walk_in_customer_name.strip() or None

	return ResolvedCustomer(
		name=customer.name,
		custom_walk_in_customer_name=custom_walk_in_customer_name,
	)


def _customer_filters(profile) -> list[list]:
	filters = [["disabled", "=", 0]]
	if (closure := _get_customer_group_closure(profile)) is not None:
		filters.append(["customer_group", "in", sorted(closure)])
	return filters


def _get_customer_group_closure(profile) -> set[str] | None:
	configured = {row.customer_group for row in profile.customer_groups if row.customer_group}
	if not configured:
		return None

	closure = set(configured)
	for group in configured:
		coordinates = frappe.get_cached_value("Customer Group", group, ["lft", "rgt"])
		if not coordinates:
			continue
		lft, rgt = coordinates
		closure.update(
			frappe.get_all(
				"Customer Group",
				filters={"lft": [">", lft], "rgt": ["<", rgt]},
				pluck="name",
			)
		)
	return closure


def _customer_error(
	profile,
	customer_name: str,
	is_explicit: bool,
	default_reason: str,
) -> MobilePOSAPIError:
	if is_explicit:
		return MobilePOSAPIError(
			"RESOURCE_NOT_FOUND",
			"The Customer does not exist or is not visible.",
			status=404,
			details={"resource_type": "Customer", "name": customer_name},
		)
	return _profile_customer_error(profile, default_reason)


def _profile_customer_error(profile, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"PROFILE_CONFIGURATION_INVALID",
		"The configured default Customer is invalid.",
		status=422,
		details={"pos_profile": profile.name, "field": "customer", "reason": reason},
	)


def _invalid_request(field: str, reason: str) -> MobilePOSAPIError:
	return MobilePOSAPIError(
		"INVALID_REQUEST",
		f"{field} is invalid.",
		details={"field": field, "reason": reason},
	)
