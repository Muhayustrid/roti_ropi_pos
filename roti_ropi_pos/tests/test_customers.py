from __future__ import annotations

import warnings

import frappe
from frappe.deprecation_dumpster import V17FrappeDeprecationWarning
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.tests.helpers import make_cashier, make_customer_group

COMPANY = "_Test Company"
WAREHOUSE = "_Test Warehouse - _TC"
CUSTOMER_FIELDS = ("customer_name", "customer_group", "mobile_no", "disabled")
CUSTOMER_GROUP_FIELDS = ("customer_group_name", "parent_customer_group", "is_group", "lft", "rgt")


class TestCustomers(IntegrationTestCase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.cashier = make_cashier("task4a-customer-search@rotiropi.test")

	def setUp(self) -> None:
		super().setUp()
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.marker = frappe.generate_hash(length=10)
		self.created_user_permissions = []
		self.customers = frappe.get_all(
			"Customer",
			filters={"disabled": 0},
			pluck="name",
			order_by="name asc",
			limit=6,
		)
		if len(self.customers) < 6:
			self.fail("Task 4A tests require six existing enabled Customer records.")
		self.customer_snapshots = {
			name: frappe.db.get_value("Customer", name, CUSTOMER_FIELDS, as_dict=True)
			for name in self.customers
		}

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		for permission in self.created_user_permissions:
			frappe.delete_doc("User Permission", permission, force=True)
		for name, values in self.customer_snapshots.items():
			frappe.db.set_value("Customer", name, values, update_modified=False)
		frappe.clear_cache(user=self.cashier)
		frappe.db.set_single_value(
			"POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice"
		)
		super().tearDown()

	def _customer(
		self,
		index: int,
		*,
		customer_name: str | None = None,
		customer_group: str | None = None,
		mobile_no: str | None = None,
		disabled: int = 0,
	) -> str:
		"""Configure one existing Customer for a test without creating a Customer."""
		name = self.customers[index]
		values = {
			"customer_name": customer_name or f"Existing Customer {self.marker} {index}",
			"customer_group": customer_group
			or frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"mobile_no": mobile_no,
			"disabled": disabled,
		}
		frappe.db.set_value("Customer", name, values, update_modified=False)
		return name

	def _make_profile(self, customer: str, *, customer_groups: list[str] | None = None):
		mode = frappe.get_doc("Mode of Payment", "Cash")
		if not frappe.db.exists("Mode of Payment Account", {"parent": "Cash", "company": COMPANY}):
			mode.append("accounts", {"company": COMPANY, "default_account": "Sales - _TC"})
			mode.save()
		doc = frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": f"CustTest {frappe.generate_hash(length=6)}",
				"company": COMPANY,
				"cost_center": "_Test Cost Center - _TC",
				"currency": "INR",
				"customer": customer,
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"income_account": "Sales - _TC",
				"naming_series": "_T-POS Profile-",
				"selling_price_list": frappe.db.get_value(
					"Price List", {"selling": 1, "enabled": 1}, "name"
				),
				"territory": "_Test Territory",
				"warehouse": WAREHOUSE,
				"write_off_account": "_Test Write Off - _TC",
				"write_off_cost_center": "_Test Write Off Cost Center - _TC",
				"location": "Block 1",
				"payments": [{"mode_of_payment": "Cash", "default": 1}],
				"applicable_for_users": [{"user": self.cashier, "default": 0}],
				"customer_groups": [{"customer_group": group} for group in (customer_groups or [])],
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _restrict_cashier_to_customer(self, customer: str) -> None:
		frappe.permissions.add_user_permission(
			"Customer",
			customer,
			self.cashier,
			ignore_permissions=True,
		)
		permission = frappe.db.get_value(
			"User Permission",
			{"user": self.cashier, "allow": "Customer", "for_value": customer},
		)
		self.created_user_permissions.append(permission)
		frappe.clear_cache(user=self.cashier)

	def test_import_guard(self) -> None:
		from roti_ropi_pos.api.v1 import customers as customers_api  # noqa: F401

	def test_search_by_customer_name(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0)
		target = self._customer(1, customer_name="Ayu Bakery Pelanggan")
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Ayu Bakery")

		self.assertIn(target, [row["name"] for row in result["customers"]])

	def test_search_by_customer_id(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0)
		target = self._customer(1)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = search_customers(profile, q=target)

		self.assertIn(target, [row["name"] for row in result["customers"]])

	def test_search_by_mobile_no(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0)
		target = self._customer(1, mobile_no="081234599999")
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="081234599999")

		self.assertIn(target, [row["name"] for row in result["customers"]])

	def test_search_no_match_returns_empty(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="XXXXNOEXIST9999")

		self.assertEqual(result["customers"], [])
		self.assertFalse(result["page"]["has_more"])

	def test_disabled_customer_excluded(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0)
		disabled = self._customer(1, customer_name="Disabled Pelanggan", disabled=1)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Disabled Pelanggan")

		self.assertNotIn(disabled, [row["name"] for row in result["customers"]])

	def test_permission_inaccessible_customer_excluded(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		allowed = self._customer(0, customer_name="Allowed Customer")
		hidden = self._customer(1, customer_name="Hidden Customer")
		profile = self._make_profile(allowed)
		self._restrict_cashier_to_customer(allowed)
		frappe.set_user(self.cashier)

		with warnings.catch_warnings():
			warnings.simplefilter("ignore", V17FrappeDeprecationWarning)
			result = search_customers(profile, q="Hidden Customer")

		self.assertNotIn(hidden, [row["name"] for row in result["customers"]])

	def test_pagination_has_more_and_deterministic_order(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0, customer_name="Walk-In Pagination")
		for index in range(1, 4):
			self._customer(
				index, customer_name=f"Paging {self.marker} Customer {index:02d}"
			)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		page1 = search_customers(profile, q=self.marker, start=0, limit=2)
		page2 = search_customers(profile, q=self.marker, start=2, limit=2)

		self.assertEqual(len(page1["customers"]), 2)
		self.assertTrue(page1["page"]["has_more"])
		self.assertEqual(len(page2["customers"]), 1)
		self.assertLessEqual(
			page1["customers"][-1]["customer_name"], page2["customers"][0]["customer_name"]
		)

	def test_limit_above_100_capped(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		result = search_customers(profile, limit=9999)

		self.assertLessEqual(len(result["customers"]), 100)
		self.assertEqual(result["page"]["limit"], 100)

	def test_negative_start_raises_invalid_request(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			search_customers(profile, start=-1)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "start")

	def test_zero_limit_raises_invalid_request(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			search_customers(profile, limit=0)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "limit")

	def test_empty_customer_groups_allows_all_enabled_customers(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0)
		target = self._customer(1, customer_name="Pelanggan Semua Grup")
		profile = self._make_profile(walk_in, customer_groups=[])
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Pelanggan Semua Grup")

		self.assertIn(target, [row["name"] for row in result["customers"]])

	def test_customer_group_closure_includes_configured_group_only(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		group = make_customer_group(f"Roti Group {frappe.generate_hash(length=6)}")
		other_group = frappe.db.get_value(
			"Customer Group", {"is_group": 0, "name": ["!=", group]}, "name"
		)
		walk_in = self._customer(0, customer_group=group)
		inside = self._customer(1, customer_name="Inside Group Customer", customer_group=group)
		outside = self._customer(2, customer_name="Outside Group Customer", customer_group=other_group)
		profile = self._make_profile(walk_in, customer_groups=[group])
		frappe.set_user(self.cashier)

		result = search_customers(profile)
		names = [row["name"] for row in result["customers"]]

		self.assertIn(inside, names)
		self.assertNotIn(outside, names)

	def test_search_query_cannot_bypass_customer_group_scope(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		allowed_group = make_customer_group(f"Allowed Group {frappe.generate_hash(length=6)}")
		other_group = frappe.db.get_value(
			"Customer Group", {"is_group": 0, "name": ["!=", allowed_group]}, "name"
		)
		walk_in = self._customer(0, customer_group=allowed_group)
		outside = self._customer(1, customer_name="Outside Query Match", customer_group=other_group)
		profile = self._make_profile(walk_in, customer_groups=[allowed_group])
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Outside Query Match")

		self.assertNotIn(outside, [row["name"] for row in result["customers"]])

	def test_customer_group_closure_includes_descendants(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		parent_group = make_customer_group(f"Parent Grp {frappe.generate_hash(length=6)}")
		frappe.db.set_value("Customer Group", parent_group, "is_group", 1)
		child_group = make_customer_group(
			f"Child Grp {frappe.generate_hash(length=6)}", parent_customer_group=parent_group
		)
		frappe.utils.nestedset.rebuild_tree("Customer Group")
		walk_in = self._customer(0, customer_group=child_group)
		child_customer = self._customer(
			1, customer_name="Child Group Customer", customer_group=child_group
		)
		profile = self._make_profile(walk_in, customer_groups=[parent_group])
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Child Group Customer")

		self.assertIn(child_customer, [row["name"] for row in result["customers"]])

	def test_is_default_walk_in_flag(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		walk_in = self._customer(0, customer_name="Walk-In Flag Test")
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = search_customers(profile, q="Walk-In Flag Test")
		walk_in_rows = [row for row in result["customers"] if row["name"] == walk_in]

		self.assertEqual(len(walk_in_rows), 1)
		self.assertTrue(walk_in_rows[0]["is_default_walk_in"])

	def test_customer_row_count_unchanged_after_search(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import search_customers

		profile = self._make_profile(self._customer(0))
		before = frappe.db.count("Customer")
		frappe.set_user(self.cashier)

		search_customers(profile, q="anything")
		search_customers(profile)

		self.assertEqual(frappe.db.count("Customer"), before)

	def test_endpoint_returns_success_envelope(self) -> None:
		from roti_ropi_pos.api.v1 import customers as customers_api

		walk_in = self._customer(0, customer_name="Walk-In Endpoint")
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		result = customers_api.search(pos_profile=profile.name, q="Walk-In Endpoint")

		self.assertTrue(result["ok"])
		self.assertIn("customers", result["data"])
		self.assertIn("page", result["data"])
		self.assertEqual(result["meta"]["api_version"], "v1")

	def test_endpoint_missing_pos_profile_returns_invalid_request(self) -> None:
		from roti_ropi_pos.api.v1 import customers as customers_api

		frappe.set_user(self.cashier)

		result = customers_api.search(pos_profile=None)

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "pos_profile")

	def test_endpoint_non_numeric_start_returns_invalid_request(self) -> None:
		from roti_ropi_pos.api.v1 import customers as customers_api

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		result = customers_api.search(pos_profile=profile.name, start="abc")

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "start")

	def test_endpoint_non_numeric_limit_returns_invalid_request(self) -> None:
		from roti_ropi_pos.api.v1 import customers as customers_api

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		result = customers_api.search(pos_profile=profile.name, limit="bad")

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "limit")

	def test_resolve_omitted_customer_uses_profile_default(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer

		walk_in = self._customer(0)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		resolved = resolve_customer(profile)

		self.assertEqual(resolved.name, walk_in)
		self.assertIsNone(resolved.custom_walk_in_customer_name)

	def test_resolve_explicit_valid_customer(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer

		walk_in = self._customer(0)
		registered = self._customer(1)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		resolved = resolve_customer(profile, selected_customer=registered)

		self.assertEqual(resolved.name, registered)
		self.assertIsNone(resolved.custom_walk_in_customer_name)

	def test_resolve_missing_default_raises_profile_configuration_invalid(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		profile.customer = "CUSTOMER-DOES-NOT-EXIST-XYZ"
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile)
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")
		self.assertEqual(error.exception.details["field"], "customer")

	def test_resolve_disabled_default_raises_profile_configuration_invalid(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		walk_in = self._customer(0, disabled=1)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile)
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_resolve_inaccessible_default_raises_profile_configuration_invalid(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		allowed = self._customer(0)
		hidden_default = self._customer(1)
		profile = self._make_profile(hidden_default)
		self._restrict_cashier_to_customer(allowed)
		frappe.set_user(self.cashier)

		with warnings.catch_warnings(), self.assertRaises(MobilePOSAPIError) as error:
			warnings.simplefilter("ignore", V17FrappeDeprecationWarning)
			resolve_customer(profile)
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_resolve_default_outside_group_raises_profile_configuration_invalid(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		allowed_group = make_customer_group(f"Scoped Grp {frappe.generate_hash(length=6)}")
		other_group = frappe.db.get_value(
			"Customer Group", {"is_group": 0, "name": ["!=", allowed_group]}, "name"
		)
		walk_in = self._customer(0, customer_group=other_group)
		profile = self._make_profile(walk_in, customer_groups=[allowed_group])
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile)
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")
		self.assertIn("Customer Groups", error.exception.details["reason"])

	def test_resolve_rejects_non_string_selected_customer(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile, selected_customer=42)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "customer")

	def test_resolve_rejects_blank_selected_customer(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile, selected_customer="\t  ")
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "customer")

	def test_resolve_explicit_nonexistent_customer_raises_resource_not_found(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(profile, selected_customer="CUSTOMER-DOES-NOT-EXIST-XYZ")
		self.assertEqual(error.exception.code, "RESOURCE_NOT_FOUND")
		self.assertEqual(error.exception.details["resource_type"], "Customer")

	def test_resolve_explicit_inaccessible_customer_raises_resource_not_found(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		allowed = self._customer(0)
		hidden = self._customer(1)
		profile = self._make_profile(allowed)
		self._restrict_cashier_to_customer(allowed)
		frappe.set_user(self.cashier)

		with warnings.catch_warnings(), self.assertRaises(MobilePOSAPIError) as error:
			warnings.simplefilter("ignore", V17FrappeDeprecationWarning)
			resolve_customer(profile, selected_customer=hidden)
		self.assertEqual(error.exception.code, "RESOURCE_NOT_FOUND")

	def test_walk_in_customer_name_accepted_for_profile_default(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer

		walk_in = self._customer(0)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		resolved = resolve_customer(profile, walk_in_customer_name="  Ayu  ")

		self.assertEqual(resolved.name, walk_in)
		self.assertEqual(resolved.custom_walk_in_customer_name, "Ayu")

	def test_walk_in_customer_name_rejected_for_registered_customer(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		walk_in = self._customer(0)
		registered = self._customer(1)
		profile = self._make_profile(walk_in)
		frappe.set_user(self.cashier)

		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(
				profile,
				selected_customer=registered,
				walk_in_customer_name="Somebody",
			)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "walk_in_customer_name")

	def test_resolver_never_creates_customer(self) -> None:
		from roti_ropi_pos.mobile_pos.customers import resolve_customer
		from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError

		profile = self._make_profile(self._customer(0))
		before = frappe.db.count("Customer")
		frappe.set_user(self.cashier)

		resolve_customer(profile)
		with self.assertRaises(MobilePOSAPIError):
			resolve_customer(profile, selected_customer="NONEXISTENT-XYZ-99")

		self.assertEqual(frappe.db.count("Customer"), before)
