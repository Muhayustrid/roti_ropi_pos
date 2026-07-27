import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import customers as customers_api
from roti_ropi_pos.mobile_pos.customers import resolve_customer, search_customers
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.tests.helpers import make_cashier, make_customer_group

COMPANY = "_Test Company"


class TestCustomers(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"customers-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.customers = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", limit=4)
		if len(self.customers) < 4:
			self.fail("Customer tests require four existing enabled Customers.")
		self.snapshots = {
			name: frappe.db.get_value(
				"Customer", name, ["customer_name", "customer_group", "mobile_no", "disabled"], as_dict=True
			)
			for name in self.customers
		}
		self.profile = self._make_profile()

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		for name, values in self.snapshots.items():
			frappe.db.set_value("Customer", name, values, update_modified=False)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def _make_profile(self):
		mode = frappe.get_doc("Mode of Payment", "Cash")
		if not frappe.db.exists("Mode of Payment Account", {"parent": "Cash", "company": COMPANY}):
			mode.append("accounts", {"company": COMPANY, "default_account": "Sales - _TC"})
			mode.save()
		profile = frappe.get_doc(
			{
				"doctype": "POS Profile",
				"name": f"Mobile POS Customer {frappe.generate_hash(length=8)}",
				"company": COMPANY,
				"cost_center": "_Test Cost Center - _TC",
				"currency": "INR",
				"customer": self.customers[0],
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"income_account": "Sales - _TC",
				"naming_series": "_T-POS Profile-",
				"selling_price_list": frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name"),
				"territory": "_Test Territory",
				"warehouse": "_Test Warehouse - _TC",
				"write_off_account": "_Test Write Off - _TC",
				"write_off_cost_center": "_Test Write Off Cost Center - _TC",
				"location": "Block 1",
				"payments": [{"mode_of_payment": "Cash", "default": 1}],
				"applicable_for_users": [{"user": self.cashier, "default": 1}],
			}
		)
		profile.insert(ignore_permissions=True)
		return profile

	def _set_customer(self, index, *, label=None, mobile=None, group=None, disabled=0):
		name = self.customers[index]
		frappe.db.set_value(
			"Customer",
			name,
			{
				"customer_name": label or f"Customer {index}",
				"mobile_no": mobile,
				"customer_group": group or frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"disabled": disabled,
			},
			update_modified=False,
		)
		return name

	def test_search_matches_name_id_mobile_and_marks_default(self):
		default = self._set_customer(0, label="Walk In Customer")
		target = self._set_customer(1, label="Ayu Bakery", mobile="081234500001")
		self.profile.customer = default
		frappe.set_user(self.cashier)
		for query in (target, "Ayu Bakery", "081234500001"):
			with self.subTest(query=query):
				rows = search_customers(self.profile, query)["customers"]
				self.assertIn(target, [row["name"] for row in rows])
		default_row = search_customers(self.profile, "Walk In Customer")["customers"][0]
		self.assertTrue(default_row["is_default_walk_in"])

	def test_search_is_bounded_and_excludes_disabled(self):
		disabled = self._set_customer(1, label="Disabled Customer", disabled=1)
		frappe.set_user(self.cashier)
		result = search_customers(self.profile, "Disabled Customer", start=0, limit=999)
		self.assertNotIn(disabled, [row["name"] for row in result["customers"]])
		self.assertEqual(result["page"]["limit"], 100)
		for start, limit, field in ((-1, 20, "start"), (0, 0, "limit")):
			with self.subTest(field=field), self.assertRaises(MobilePOSAPIError) as error:
				search_customers(self.profile, start=start, limit=limit)
			self.assertEqual(error.exception.details["field"], field)

	def test_group_scope_includes_descendants_and_excludes_other_groups(self):
		parent = make_customer_group(f"Parent {frappe.generate_hash(length=6)}")
		frappe.db.set_value("Customer Group", parent, "is_group", 1)
		child = make_customer_group(f"Child {frappe.generate_hash(length=6)}", parent_customer_group=parent)
		frappe.utils.nestedset.rebuild_tree("Customer Group")
		other = frappe.db.get_value(
			"Customer Group", {"is_group": 0, "name": ["not in", [parent, child]]}, "name"
		)
		inside = self._set_customer(0, label="Inside Group", group=child)
		outside = self._set_customer(1, label="Outside Group", group=other)
		self.profile.set("customer_groups", [{"customer_group": parent}])
		self.profile.customer = inside
		frappe.set_user(self.cashier)
		names = [row["name"] for row in search_customers(self.profile)["customers"]]
		self.assertIn(inside, names)
		self.assertNotIn(outside, names)

	def test_resolution_uses_default_and_restricts_walk_in_name(self):
		default = self._set_customer(0)
		registered = self._set_customer(1)
		self.profile.customer = default
		frappe.set_user(self.cashier)
		resolved = resolve_customer(self.profile, walk_in_customer_name="  Ayu  ")
		self.assertEqual(resolved.name, default)
		self.assertEqual(resolved.custom_walk_in_customer_name, "Ayu")
		with self.assertRaises(MobilePOSAPIError) as error:
			resolve_customer(
				self.profile,
				selected_customer=registered,
				walk_in_customer_name="Ayu",
			)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")

	def test_invalid_default_and_explicit_selection_use_distinct_errors(self):
		self.profile.customer = "MISSING-CUSTOMER"
		frappe.set_user(self.cashier)
		with self.assertRaises(MobilePOSAPIError) as default_error:
			resolve_customer(self.profile)
		self.assertEqual(default_error.exception.code, "PROFILE_CONFIGURATION_INVALID")
		self.profile.customer = self.customers[0]
		with self.assertRaises(MobilePOSAPIError) as explicit_error:
			resolve_customer(self.profile, selected_customer="MISSING-CUSTOMER")
		self.assertEqual(explicit_error.exception.code, "RESOURCE_NOT_FOUND")

	def test_search_and_resolution_never_create_customer(self):
		before = frappe.db.count("Customer")
		frappe.set_user(self.cashier)
		search_customers(self.profile)
		resolve_customer(self.profile)
		self.assertEqual(frappe.db.count("Customer"), before)

	def test_endpoint_returns_contract_envelope(self):
		frappe.set_user(self.cashier)
		result = customers_api.search(pos_profile=self.profile.name, start="0", limit="20")
		self.assertTrue(result["ok"])
		self.assertIn("customers", result["data"])
		self.assertIn("page", result["data"])
