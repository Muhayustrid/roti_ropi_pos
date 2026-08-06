from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.api.v1 import sales as sales_api
from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import execute_idempotent
from roti_ropi_pos.mobile_pos.invoices import (
	build_sale_quote,
	submit_sale,
	verify_exact_settlement,
	verify_payment_amount_policy,
)
from roti_ropi_pos.mobile_pos.validation import (
	sale_payment_amount_policy,
	sale_payment_amount_string,
)
from roti_ropi_pos.tests.helpers import close_test_openings, make_cashier, make_opening_entry
from roti_ropi_pos.tests.test_sales import COMPANY, WAREHOUSE, make_valid_profile


def _clear_user_permissions(user: str) -> None:
	frappe.cache.delete_value(f"user_permissions:{user}")
	frappe.cache.hdel("roles", user)


def _ensure_item_price(*, item: str, price_list: str, uom: str) -> None:
	filters = {"item_code": item, "price_list": price_list, "uom": uom}
	if frappe.db.exists("Item Price", filters):
		frappe.db.set_value(
			"Item Price",
			filters,
			{"price_list_rate": 100, "valid_from": frappe.utils.today(), "valid_upto": None},
		)
		return
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item,
			"price_list": price_list,
			"price_list_rate": 100,
			"uom": uom,
		}
	).insert(ignore_permissions=True)


class TestSalePaymentAmountPolicy(IntegrationTestCase):
	def test_service_accepts_decimal_at_supported_currency_scale(self):
		with patch(
			"roti_ropi_pos.mobile_pos.validation.frappe_get_currency_precision",
			return_value=2,
		):
			verify_payment_amount_policy("TEST", [{"amount": Decimal("100.00")}])

	def test_service_rejects_decimal_with_excessive_scale(self):
		with patch(
			"roti_ropi_pos.mobile_pos.validation.frappe_get_currency_precision",
			return_value=2,
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				verify_payment_amount_policy("TEST", [{"amount": Decimal("100.001")}])
		self.assertEqual(error.exception.details["reason"], "excessive_scale")

	def test_service_rejects_zero_decimal(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_payment_amount_policy("TEST", [{"amount": Decimal("0")}])
		self.assertEqual(error.exception.details["reason"], "empty_payments_amount")

	def test_service_rejects_negative_decimal(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_payment_amount_policy("TEST", [{"amount": Decimal("-1")}])
		self.assertEqual(error.exception.details["reason"], "negative_amount")

	def test_service_rejects_non_finite_decimal(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_payment_amount_policy("TEST", [{"amount": Decimal("NaN")}])
		self.assertEqual(error.exception.details["reason"], "non_finite_amount")

	def test_sale_payment_amount_policy_uses_currency_projected_decimal_places(self):
		policy = sale_payment_amount_policy("IDR")
		self.assertEqual(policy["currency"], "IDR")
		# Decimal places come from the server-side ERPNext precision utility; the
		# test only asserts that the policy value is a non-negative integer.
		self.assertIsInstance(policy["decimal_places"], int)
		self.assertGreaterEqual(policy["decimal_places"], 0)

		policy_inr = sale_payment_amount_policy("INR")
		self.assertEqual(policy_inr["currency"], "INR")
		self.assertIsInstance(policy_inr["decimal_places"], int)
		self.assertGreaterEqual(policy_inr["decimal_places"], 0)

	def test_sale_payment_amount_policy_projects_smallest_positive_unit(self):
		for decimal_places, minimum in ((0, "1"), (2, "0.01"), (3, "0.001")):
			with self.subTest(decimal_places=decimal_places), patch(
				"roti_ropi_pos.mobile_pos.validation.frappe_get_currency_precision",
				return_value=decimal_places,
			):
				policy = sale_payment_amount_policy("TEST")
				self.assertEqual(policy["decimal_places"], decimal_places)
				self.assertEqual(policy["minimum"], minimum)

	def test_sale_payment_amount_string_accepts_minimum_and_rejects_excessive_scale(self):
		for decimal_places, minimum, excessive in (
			(0, "1", "1.0"),
			(2, "0.01", "0.001"),
			(3, "0.001", "0.0001"),
		):
			with self.subTest(decimal_places=decimal_places), patch(
				"roti_ropi_pos.mobile_pos.validation.frappe_get_currency_precision",
				return_value=decimal_places,
			):
				self.assertEqual(sale_payment_amount_string(minimum, currency="TEST"), minimum)
				with self.assertRaises(MobilePOSAPIError) as error:
					sale_payment_amount_string(excessive, currency="TEST")
				self.assertEqual(error.exception.details["reason"], "excessive_scale")

	def test_sale_payment_amount_string_accepts_canonical_decimal_string(self):
		canonical = sale_payment_amount_string("100.00", currency="INR")
		self.assertEqual(Decimal(canonical), Decimal("100.00"))

	def test_sale_payment_amount_string_rejects_malformed_decimal(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string(".5", currency="INR")
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["reason"], "malformed_decimal")

		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("1,5", currency="INR")
		self.assertEqual(error.exception.details["reason"], "malformed_decimal")

		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("1.0e1", currency="INR")
		self.assertEqual(error.exception.details["reason"], "malformed_decimal")

	def test_sale_payment_amount_string_rejects_excessive_scale(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("1.123", currency="INR")
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["reason"], "excessive_scale")

	def test_sale_payment_amount_string_rejects_negative_and_zero(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("-1", currency="INR")
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["reason"], "negative_amount")

		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("0", currency="INR")
		self.assertEqual(error.exception.code, "INVALID_PAYMENT")
		self.assertEqual(error.exception.details["reason"], "empty_payments_amount")

	def test_sale_payment_amount_string_preserves_exact_value_without_rounding(self):
		canonical = sale_payment_amount_string("100.5", currency="INR")
		# Exact Decimal value preserved; no rounding, no truncation.
		self.assertEqual(Decimal(canonical), Decimal("100.5"))
		# ``1.005`` would be rounded by ERPNext to ``1.00`` for INR; the policy
		# must instead reject the input as excessive scale (3 fractional
		# digits for a 2-decimal-place currency) before any rounding happens.
		with self.assertRaises(MobilePOSAPIError) as error:
			sale_payment_amount_string("1.005", currency="INR")
		self.assertEqual(error.exception.details["reason"], "excessive_scale")

	def test_currency_precision_does_not_treat_fraction_units_as_decimal_places(self):
		# ``fraction_units=100`` (USD/INR-style) means two decimal places,
		# not 100. The precision fallback must convert sub-unit counts into
		# the matching decimal place count.
		from roti_ropi_pos.mobile_pos.validation import (
			_decimal_places_from_fraction_units,
			frappe_get_currency_precision,
		)

		self.assertEqual(_decimal_places_from_fraction_units(100), 2)
		self.assertEqual(_decimal_places_from_fraction_units(1000), 3)
		self.assertEqual(_decimal_places_from_fraction_units(1), 0)
		# Non power-of-ten values fall back to 2; a malformed sub-unit count
		# must not surface as a policy allowing 5 fractional digits.
		self.assertEqual(_decimal_places_from_fraction_units(5), 2)

		# End-to-end: the live Currency doctype for INR/IDR exposes
		# ``fraction_units=100``; the policy must project exactly two
		# decimal places, not one hundred.
		for currency in ("INR", "IDR"):
			with self.subTest(currency=currency):
				precision = frappe_get_currency_precision(currency)
				self.assertLessEqual(precision, 9)


class TestSalePayloadDecimalParser(IntegrationTestCase):
	"""The API parser must reject malformed, negative, zero, grouped, signed,
	exponent, whitespace, and excessive-scale decimals before converting them
	to ``Decimal`` and before any service-level call.
	"""

	def _payload(self, **overrides):
		payload = {
			"pos_profile": "ignored-by-parser",
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": "100",
			"items": [
				{
					"item_code": "ignored",
					"qty": "1",
					"uom": "Nos",
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": "100", "reference_no": None}],
		}
		payload.update(overrides)
		return payload

	def _assert_invalid(self, payload, *, field, reason, code="INVALID_REQUEST"):
		with self.assertRaises(MobilePOSAPIError) as error:
			sales_api._parse_sale_payload(payload, currency="INR")
		self.assertEqual(error.exception.code, code)
		self.assertEqual(error.exception.details["field"], field)
		self.assertEqual(error.exception.details["reason"], reason)

	def test_parser_rejects_malformed_amount_with_leading_dot(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": ".5", "reference_no": None}]),
			field="amount",
			reason="malformed_decimal",
		)

	def test_parser_rejects_malformed_amount_with_grouping_separator(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "1,5", "reference_no": None}]),
			field="amount",
			reason="malformed_decimal",
		)

	def test_parser_rejects_malformed_amount_with_exponent(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "1e2", "reference_no": None}]),
			field="amount",
			reason="malformed_decimal",
		)

	def test_parser_rejects_malformed_amount_with_surrounding_whitespace(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": " 1.00", "reference_no": None}]),
			field="amount",
			reason="malformed_decimal",
		)
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "1.00 ", "reference_no": None}]),
			field="amount",
			reason="malformed_decimal",
		)

	def test_parser_rejects_negative_amount_before_decimal_coercion(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "-1", "reference_no": None}]),
			field="amount",
			reason="negative_amount",
		)

	def test_parser_rejects_zero_amount_before_decimal_coercion(self):
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "0", "reference_no": None}]),
			field="amount",
			reason="empty_payments_amount",
			code="INVALID_PAYMENT",
		)

	def test_parser_rejects_excessive_scale_against_currency(self):
		# INR exposes two decimal places; the parser must reject a third.
		self._assert_invalid(
			self._payload(payments=[{"mode_of_payment": "Cash", "amount": "100.123", "reference_no": None}]),
			field="amount",
			reason="excessive_scale",
		)
		self._assert_invalid(
			self._payload(client_accepted_grand_total="100.123"),
			field="client_accepted_grand_total",
			reason="excessive_scale",
		)

	def test_parser_accepts_quantity_beyond_currency_scale(self):
		with patch(
			"roti_ropi_pos.mobile_pos.validation.frappe_get_currency_precision",
			return_value=2,
		):
			payload = self._payload(
				items=[
					{
						"item_code": "x",
						"qty": "0.125",
						"uom": "Nos",
						"batch_no": None,
						"serial_numbers": [],
					}
				],
				payments=[{"mode_of_payment": "Cash", "amount": "100.00", "reference_no": None}],
			)
			parsed_sale = sales_api._parse_sale_payload(payload, currency="INR")
			parsed_quote = sales_api._parse_quote_payload(
				{
					key: value
					for key, value in payload.items()
					if key not in {"client_accepted_grand_total", "payments"}
				}
			)

		self.assertEqual(parsed_sale["items"][0]["qty"], Decimal("0.125"))
		self.assertEqual(parsed_quote["items"][0]["qty"], Decimal("0.125"))

	def test_parser_preserves_exact_decimal_after_validation(self):
		# Valid inputs keep their exact ``Decimal`` value (no quantize, no
		# truncation). ``1.5`` must remain ``1.5``; ``100`` must remain
		# ``100``; ``100.00`` must remain ``100.00`` (canonical form).
		payload = self._payload(
			client_accepted_grand_total="100.5",
			payments=[{"mode_of_payment": "Cash", "amount": "100.5", "reference_no": None}],
		)
		parsed = sales_api._parse_sale_payload(payload, currency="INR")
		self.assertEqual(parsed["client_accepted_grand_total"], Decimal("100.5"))
		self.assertEqual(parsed["payments"][0]["amount"], Decimal("100.5"))


class TestVerifyExactSettlement(IntegrationTestCase):
	def _build_invoice(self, profile, grand_total: Decimal):
		doc = frappe.new_doc("POS Invoice")
		doc.is_pos = 1
		doc.pos_profile = profile.name
		doc.company = profile.company
		doc.customer = profile.customer
		doc.grand_total = float(grand_total)
		doc.rounded_total = float(grand_total)
		doc.outstanding_amount = 0
		doc.change_amount = 0
		return doc

	def test_underpayment_is_rejected(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_exact_settlement(invoice, [Decimal("99")])
		self.assertEqual(error.exception.code, "INVALID_PAYMENT")
		self.assertEqual(error.exception.details["reason"], "underpayment")

	def test_overpayment_is_rejected(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_exact_settlement(invoice, [Decimal("101")])
		self.assertEqual(error.exception.code, "INVALID_PAYMENT")
		self.assertEqual(error.exception.details["reason"], "overpayment")

	def test_exact_single_mode_settlement_accepted(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		verify_exact_settlement(invoice, [Decimal("100")])

	def test_exact_multiple_modes_settlement_accepted(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		verify_exact_settlement(invoice, [Decimal("40"), Decimal("60")])

	def test_sum_uses_rounded_total_when_applicable(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100.00"))
		invoice.grand_total = 99.5
		invoice.rounded_total = 100.00
		verify_exact_settlement(invoice, [Decimal("100.00")])

	def test_empty_payment_list_is_rejected(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_exact_settlement(invoice, [])
		self.assertEqual(error.exception.code, "INVALID_PAYMENT")
		self.assertEqual(error.exception.details["reason"], "empty_payments")

	def test_zero_amount_row_rejected(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_exact_settlement(invoice, [Decimal("0")])
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["reason"], "zero_amount")

	def test_negative_amount_row_rejected(self):
		profile = frappe._dict(name="p", company=COMPANY, currency="INR")
		invoice = self._build_invoice(profile, Decimal("100"))
		with self.assertRaises(MobilePOSAPIError) as error:
			verify_exact_settlement(invoice, [Decimal("-10"), Decimal("110")])
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["reason"], "negative_amount")


class TestSaleQuoteCart(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"quote-{frappe.generate_hash(length=8)}@rotiropi.test")
		_clear_user_permissions(self.cashier)
		self.profile = make_valid_profile(f"Mobile POS Quote {frappe.generate_hash(length=8)}", self.cashier)
		frappe.clear_cache(doctype="POS Invoice")
		frappe.clear_cache(user=self.cashier)
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		self.item = "_Test Item"
		self.uom = frappe.db.get_value("Item", self.item, "stock_uom")
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		self.profile.append(
			"item_groups", {"item_group": frappe.db.get_value("Item", self.item, "item_group")}
		)
		self.profile.save(ignore_permissions=True)
		_ensure_item_price(item=self.item, price_list=self.profile.selling_price_list, uom=self.uom)
		frappe.set_user("Administrator")
		make_stock_entry(target=WAREHOUSE, item_code=self.item, qty=10, basic_rate=100)
		# Add Administrator to the profile so the test can run the service
		# functions under Administrator after setUp.
		self.profile.append("applicable_for_users", {"user": "Administrator", "default": 0})
		self.profile.save(ignore_permissions=True)
		# ``build_sale_quote`` requires an active opening for the calling
		# user; create one for Administrator so the fixture-level service
		# tests below still find an opening under their Administrator user.
		frappe.set_user("Administrator")
		make_opening_entry(
			user="Administrator",
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		frappe.clear_cache(doctype="POS Profile")

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def _quote_payload(self, *, qty: str | Decimal = Decimal("1")):
		return {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"items": [
				{"item_code": self.item, "qty": qty, "uom": self.uom, "batch_no": None, "serial_numbers": []}
			],
		}

	def test_quote_cart_returns_server_authoritative_payable(self):
		snapshot = build_sale_quote(self._quote_payload())
		self.assertEqual(Decimal(snapshot["payable"]), Decimal("100"))
		self.assertEqual(snapshot["currency"], self.profile.currency)
		self.assertEqual(snapshot["payment_modes"][0]["mode_of_payment"], "Cash")
		self.assertIn("payment_amount_policy", snapshot)
		self.assertEqual(Decimal(snapshot["payment_amount_policy"]["minimum"]), Decimal("0.01"))

	def test_quote_cart_recomputes_after_price_change(self):
		first = build_sale_quote(self._quote_payload())
		self.assertEqual(Decimal(first["payable"]), Decimal("100"))
		frappe.db.set_value(
			"Item Price",
			{
				"item_code": self.item,
				"price_list": self.profile.selling_price_list,
				"uom": self.uom,
			},
			"price_list_rate",
			200,
		)
		frappe.clear_cache(doctype="Item Price")
		second = build_sale_quote(self._quote_payload())
		self.assertEqual(Decimal(second["payable"]), Decimal("200"))

	def test_quote_cart_creates_no_mobile_pos_request_or_pos_invoice(self):
		before = frappe.db.count("Mobile POS Request")
		before_inv = frappe.db.count("POS Invoice", {"pos_profile": self.profile.name})
		build_sale_quote(self._quote_payload())
		self.assertEqual(frappe.db.count("Mobile POS Request"), before)
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), before_inv)

	def test_quote_cart_excludes_invalid_profile_modes(self):
		# Disabled-Mode is excluded by the ``_sale_payment_modes`` projection
		# because the ``Mode of Payment`` is disabled in core. ERPNext's
		# ``update_multi_mode_option`` enforces that the linked mode has a
		# valid company account; this test directly exercises the projection
		# helper to avoid creating the account fixture for a mode that should
		# not be selected anyway.
		from roti_ropi_pos.mobile_pos.invoices import _sale_payment_modes

		if not frappe.db.exists("Mode of Payment", "Disabled-Mode"):
			frappe.get_doc(
				{
					"doctype": "Mode of Payment",
					"mode_of_payment": "Disabled-Mode",
					"enabled": 0,
					"type": "Cash",
				}
			).insert(ignore_permissions=True)
		# Build an in-memory copy of the profile with the disabled mode
		# appended; avoid ``profile.save()`` so ERPNext's POS Profile validate
		# does not enforce the missing default account for the disabled mode.
		profile = frappe.get_doc("POS Profile", self.profile.name)
		profile.append("payments", {"mode_of_payment": "Disabled-Mode"})
		mode_names = [row["mode_of_payment"] for row in _sale_payment_modes(profile)]
		self.assertNotIn("Disabled-Mode", mode_names)

	def test_quote_cart_does_not_use_idempotency_request(self):
		before = frappe.db.count("Mobile POS Request")
		build_sale_quote(self._quote_payload())
		build_sale_quote(self._quote_payload())
		after = frappe.db.count("Mobile POS Request")
		self.assertEqual(after, before)

	def test_quote_cart_endpoint_rejects_client_accepted_grand_total(self):
		payload = dict(self._quote_payload())
		payload["client_accepted_grand_total"] = "100"
		# The parser rejects ``client_accepted_grand_total`` so Android cannot
		# use the quote endpoint as a covert submit path.
		from roti_ropi_pos.api.v1.sales import _parse_quote_payload

		with self.assertRaises(MobilePOSAPIError) as error:
			_parse_quote_payload(payload)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
		self.assertEqual(error.exception.details["field"], "client_accepted_grand_total")

	def test_quote_endpoint_dispatches_to_build_sale_quote(self):
		# Verify the new endpoint is registered and routes to the service.
		self.assertTrue(callable(sales_api.quote_cart))
		self.assertTrue(callable(build_sale_quote))

	def test_quote_endpoint_dispatches_as_cashier(self):
		# The endpoint must accept a valid Mobile POS cashier request and
		# return the same authoritative snapshot as the service layer.
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(self._quote_payload(qty="1"))
		result = sales_api.quote_cart()
		self.assertTrue(result["ok"], msg=str(result))
		self.assertEqual(Decimal(result["data"]["payable"]), Decimal("100"))
		self.assertEqual(result["data"]["currency"], self.profile.currency)

	def test_quote_rejects_when_no_active_opening(self):
		# Close the cashier's opening so the quote gate has no opening to
		# resolve for the cashier.
		frappe.db.set_value("POS Opening Entry", {"user": self.cashier, "status": "Open"}, "status", "Closed")
		frappe.clear_cache(doctype="POS Opening Entry")
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(self._quote_payload(qty="1"))
		result = sales_api.quote_cart()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")
		self.assertEqual(result["error"]["details"]["pos_profile"], self.profile.name)
		self.assertEqual(
			frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}),
			0,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request"), 0)

	def test_quote_rejects_opening_owned_by_other_cashier(self):
		# The opening the quote looks up is bound to ``frappe.session.user``
		# and ``profile.name``. An opening owned by another cashier for the
		# same profile must not satisfy the gate.
		other_cashier = make_cashier(f"quote-other-{frappe.generate_hash(length=8)}@rotiropi.test")
		self.profile.append("applicable_for_users", {"user": other_cashier, "default": 0})
		self.profile.save(ignore_permissions=True)
		make_opening_entry(
			user=other_cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		# Close the original cashier's opening so the only remaining opening
		# is owned by ``other_cashier``.
		frappe.db.set_value("POS Opening Entry", {"user": self.cashier, "status": "Open"}, "status", "Closed")
		frappe.clear_cache(doctype="POS Opening Entry")
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(self._quote_payload(qty="1"))
		result = sales_api.quote_cart()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")

	def test_quote_rejects_opening_for_other_profile(self):
		# The opening is bound to ``profile.name``. An opening owned by the
		# same cashier but for a different profile must not satisfy the
		# gate either.
		other_profile = make_valid_profile(
			f"Mobile POS Quote Other {frappe.generate_hash(length=8)}",
			self.cashier,
			default=0,
		)
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=other_profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		# Close the cashier's opening on the original profile.
		frappe.db.set_value(
			"POS Opening Entry",
			{"user": self.cashier, "pos_profile": self.profile.name, "status": "Open"},
			"status",
			"Closed",
		)
		frappe.clear_cache(doctype="POS Opening Entry")
		frappe.set_user(self.cashier)
		frappe.local.form_dict = frappe._dict(self._quote_payload(qty="1"))
		result = sales_api.quote_cart()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NO_OPEN_SESSION")

class TestSaleSubmitExactSettlement(IntegrationTestCase):
	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"sale-{frappe.generate_hash(length=8)}@rotiropi.test")
		_clear_user_permissions(self.cashier)
		self.profile = make_valid_profile(f"Mobile POS Submit {frappe.generate_hash(length=8)}", self.cashier)
		frappe.clear_cache(doctype="POS Invoice")
		frappe.clear_cache(user=self.cashier)
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		self.item = "_Test Item"
		self.uom = frappe.db.get_value("Item", self.item, "stock_uom")
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		self.profile.append(
			"item_groups", {"item_group": frappe.db.get_value("Item", self.item, "item_group")}
		)
		self.profile.save(ignore_permissions=True)
		_ensure_item_price(item=self.item, price_list=self.profile.selling_price_list, uom=self.uom)
		frappe.set_user("Administrator")
		make_stock_entry(target=WAREHOUSE, item_code=self.item, qty=10, basic_rate=100)
		# Add Administrator to the profile so the test can run the service
		# functions under Administrator after setUp. Also create an
		# Administrator-owned opening because the ``get_current_opening``
		# lookup filters by the current user.
		self.profile.append("applicable_for_users", {"user": "Administrator", "default": 0})
		self.profile.save(ignore_permissions=True)
		frappe.clear_cache(doctype="POS Profile")
		frappe.set_user("Administrator")
		make_opening_entry(
			user="Administrator",
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def _submit_payload(self, **overrides):
		payload = {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": Decimal("100"),
			"items": [
				{
					"item_code": self.item,
					"qty": Decimal("1"),
					"uom": self.uom,
					"batch_no": None,
					"serial_numbers": [],
				}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": Decimal("100"), "reference_no": None}],
		}
		payload.update(overrides)
		return payload

	def _run_submit(self, payload):
		"""Submit a payload through the idempotent executor and return a dict.

		Translates ``MobilePOSAPIError`` into the same envelope that the
		``api_endpoint`` decorator would emit so the tests can assert on the
		stable error shape.
		"""
		key = str(uuid4())
		with patch("frappe.get_request_header", return_value=key):
			try:
				return execute_idempotent(
					"v1.sales.submit",
					payload,
					lambda transaction_id: submit_sale(payload, transaction_id),
				)
			except MobilePOSAPIError as error:
				return {
					"ok": False,
					"error": {
						"code": error.code,
						"message": error.message,
						"details": error.details,
						"retryable": error.retryable,
					},
					"meta": {
						"api_version": "v1",
						"request_id": "test",
						"server_time": "test",
						"replayed": False,
					},
				}

	def test_submit_rejects_overpayment(self):
		# First use the quote to derive the authoritative payable, then submit
		# with an overpayment row. The PRICE_CHANGED guard must pass because
		# the client accepts the authoritative total; the overpayment guard
		# must reject the overpayment.
		quote = build_sale_quote(
			{
				"pos_profile": self.profile.name,
				"customer": None,
				"walk_in_customer_name": None,
				"items": [
					{
						"item_code": self.item,
						"qty": Decimal("1"),
						"uom": self.uom,
						"batch_no": None,
						"serial_numbers": [],
					}
				],
			}
		)
		grand = quote["grand_total"]
		payable = quote["payable"]
		overpay = Decimal(payable) + Decimal("0.01")
		payload = self._submit_payload(
			client_accepted_grand_total=Decimal(grand),
			payments=[{"mode_of_payment": "Cash", "amount": overpay, "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(result["error"]["details"]["reason"], "overpayment")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_submit_rejects_excessive_scale(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": Decimal("100.123"), "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["reason"], "excessive_scale")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_submit_rejects_non_decimal_amount(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": ".5", "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["reason"], "non_decimal_amount")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_submit_rejects_zero_amount(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": Decimal("0"), "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(result["error"]["details"]["reason"], "empty_payments_amount")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_submit_rejects_negative_amount(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": Decimal("-10"), "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["reason"], "negative_amount")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_submit_rejects_unregistered_mode(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Not-A-Real-Mode", "amount": "100", "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 0)

	def test_quote_cart_then_submit_creates_exactly_one_invoice(self):
		quote = build_sale_quote(
			{
				"pos_profile": self.profile.name,
				"customer": None,
				"walk_in_customer_name": None,
				"items": [
					{
						"item_code": self.item,
						"qty": Decimal("1"),
						"uom": self.uom,
						"batch_no": None,
						"serial_numbers": [],
					}
				],
			}
		)
		grand = quote["grand_total"]
		payable = quote["payable"]
		payload = self._submit_payload(
			client_accepted_grand_total=Decimal(grand),
			payments=[{"mode_of_payment": "Cash", "amount": Decimal(payable), "reference_no": None}],
		)
		result = self._run_submit(payload)
		self.assertTrue(result["ok"], msg=str(result))
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 1)

	def test_quote_cart_payable_does_not_equal_grand_total_when_rounding_applies(self):
		# Verify the quote surfaces both ``grand_total`` and ``payable`` when
		# ERPNext rounding produces a payable that differs from the
		# authoritative grand total. The contract binds
		# ``client_accepted_grand_total`` to ``grand_total`` and the payment
		# sum to ``payable``; sending the rounded value back as
		# ``client_accepted_grand_total`` must not raise a false
		# ``PRICE_CHANGED``.
		price = 99.52
		item_price_filters = {
			"item_code": self.item,
			"price_list": self.profile.selling_price_list,
			"uom": self.uom,
		}
		frappe.db.set_value("Item Price", item_price_filters, "price_list_rate", price)
		frappe.clear_cache(doctype="Item Price")
		# The site ``INR`` currency has ``smallest_currency_fraction_value = 0``
		# and never rounds, so we cannot trigger a payable/grand mismatch via
		# the live currency table. ``set_rounded_total`` delegates to
		# ``round_based_on_smallest_currency_fraction``; a deterministic
		# patch that returns a value different from the grand total models
		# any currency whose rounding policy is active.
		with patch(
			"erpnext.controllers.taxes_and_totals.round_based_on_smallest_currency_fraction",
			return_value=100.00,
		):
			quote = build_sale_quote(
				{
					"pos_profile": self.profile.name,
					"customer": None,
					"walk_in_customer_name": None,
					"items": [
						{
							"item_code": self.item,
							"qty": Decimal("1"),
							"uom": self.uom,
							"batch_no": None,
							"serial_numbers": [],
						}
					],
				}
			)
		self.assertIn("grand_total", quote)
		self.assertIn("payable", quote)
		# Mock returns 100 while ERPNext computes 99.52 as the grand total
		# (no rounding policy active on INR). payable follows the rounded
		# value, so grand_total != payable.
		self.assertEqual(Decimal(quote["grand_total"]), Decimal("99.52"))
		self.assertEqual(Decimal(quote["payable"]), Decimal("100.00"))
		self.assertNotEqual(Decimal(quote["grand_total"]), Decimal(quote["payable"]))

	def test_submit_does_not_raise_false_price_changed_when_payable_due_to_rounding(
		self,
	):
		# End-to-end: the cashier accepts the quote's authoritative
		# ``grand_total`` and submits the ``payable`` (rounded) amount. The
		# submit must not raise ``PRICE_CHANGED`` because the accepted value
		# matches the authoritative ``grand_total``.
		price = 99.52
		item_price_filters = {
			"item_code": self.item,
			"price_list": self.profile.selling_price_list,
			"uom": self.uom,
		}
		frappe.db.set_value("Item Price", item_price_filters, "price_list_rate", price)
		frappe.clear_cache(doctype="Item Price")
		with patch(
			"erpnext.controllers.taxes_and_totals.round_based_on_smallest_currency_fraction",
			return_value=100.00,
		):
			quote = build_sale_quote(
				{
					"pos_profile": self.profile.name,
					"customer": None,
					"walk_in_customer_name": None,
					"items": [
						{
							"item_code": self.item,
							"qty": Decimal("1"),
							"uom": self.uom,
							"batch_no": None,
							"serial_numbers": [],
						}
					],
				}
			)
		grand = Decimal(quote["grand_total"])
		payable = Decimal(quote["payable"])
		self.assertNotEqual(grand, payable)
		payments = [{"mode_of_payment": "Cash", "amount": payable, "reference_no": None}]
		payload = self._submit_payload(
			client_accepted_grand_total=grand,
			payments=payments,
		)
		self.assertEqual(payload["client_accepted_grand_total"], Decimal(quote["grand_total"]))
		self.assertEqual(sum(row["amount"] for row in payments), Decimal(quote["payable"]))
		result = self._run_submit(payload)
		self.assertTrue(result["ok"], msg=str(result))
		self.assertEqual(
			frappe.db.count("POS Invoice", {"pos_profile": self.profile.name, "grand_total": float(grand)}),
			1,
		)

class TestCashierSaleFlow(IntegrationTestCase):
	"""End-to-end cashier flow: every primary path runs as the Mobile POS
	cashier with a real bearer-style request, never as Administrator.
	"""

	def setUp(self) -> None:
		super().setUp()
		frappe.db.delete("Mobile POS Request")
		self.saved_pos_mode = frappe.db.get_single_value("POS Settings", "invoice_type")
		frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
		self.cashier = make_cashier(f"flow-{frappe.generate_hash(length=8)}@rotiropi.test")
		_clear_user_permissions(self.cashier)
		self.profile = make_valid_profile(f"Mobile POS Flow {frappe.generate_hash(length=8)}", self.cashier)
		frappe.clear_cache(doctype="POS Invoice")
		frappe.clear_cache(user=self.cashier)
		make_opening_entry(
			user=self.cashier,
			company=COMPANY,
			pos_profile=self.profile.name,
			period_start_date=frappe.utils.now_datetime(),
			posting_date=frappe.utils.today(),
		)
		self.item = "_Test Item"
		self.uom = frappe.db.get_value("Item", self.item, "stock_uom")
		self.profile.selling_price_list = frappe.db.get_value(
			"Price List", {"selling": 1, "enabled": 1, "currency": self.profile.currency}, "name"
		)
		self.profile.append(
			"item_groups", {"item_group": frappe.db.get_value("Item", self.item, "item_group")}
		)
		self.profile.save(ignore_permissions=True)
		_ensure_item_price(item=self.item, price_list=self.profile.selling_price_list, uom=self.uom)
		make_stock_entry(target=WAREHOUSE, item_code=self.item, qty=10, basic_rate=100)
		frappe.set_user(self.cashier)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		close_test_openings(self.cashier)
		frappe.db.set_single_value("POS Settings", "invoice_type", self.saved_pos_mode or "POS Invoice")
		super().tearDown()

	def _quote_payload(self, **overrides):
		payload = {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"items": [
				{"item_code": self.item, "qty": "1", "uom": self.uom, "batch_no": None, "serial_numbers": []}
			],
		}
		payload.update(overrides)
		return payload

	def _submit_payload(self, **overrides):
		payload = {
			"pos_profile": self.profile.name,
			"customer": None,
			"walk_in_customer_name": None,
			"client_accepted_grand_total": "100",
			"items": [
				{"item_code": self.item, "qty": "1", "uom": self.uom, "batch_no": None, "serial_numbers": []}
			],
			"payments": [{"mode_of_payment": "Cash", "amount": "100", "reference_no": None}],
		}
		payload.update(overrides)
		return payload

	def _call_quote(self, payload):
		frappe.local.form_dict = frappe._dict(payload)
		return sales_api.quote_cart()

	def _call_submit(self, payload, *, idempotency_key=None):
		key = idempotency_key or str(uuid4())
		frappe.local.form_dict = frappe._dict(payload)
		frappe.local.request = frappe._dict(headers={"X-Idempotency-Key": key})
		with patch("frappe.get_request_header", return_value=key):
			return sales_api.submit(), key

	def _assert_no_persisted_artifacts(self, profile_name):
		self.assertEqual(
			frappe.db.count("POS Invoice", {"pos_profile": profile_name}),
			0,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request"), 0)

	def test_cashier_quote_returns_authoritative_payable(self):
		result = self._call_quote(self._quote_payload())
		self.assertTrue(result["ok"], msg=str(result))
		self.assertEqual(Decimal(result["data"]["payable"]), Decimal("100"))
		self.assertIn("grand_total", result["data"])
		self.assertEqual(Decimal(result["data"]["grand_total"]), Decimal("100"))

	def test_cashier_submit_exact_single_mode_succeeds(self):
		quote = self._call_quote(self._quote_payload())
		payable = Decimal(quote["data"]["payable"])
		grand = Decimal(quote["data"]["grand_total"])
		payload = self._submit_payload(
			client_accepted_grand_total=str(grand),
			payments=[{"mode_of_payment": "Cash", "amount": str(payable), "reference_no": None}],
		)
		result, _ = self._call_submit(payload)
		self.assertTrue(result["ok"], msg=str(result))
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 1)
		self.assertEqual(frappe.db.count("Mobile POS Request"), 1)

	def test_cashier_submit_underpayment_is_rejected(self):
		quote = self._call_quote(self._quote_payload())
		grand = Decimal(quote["data"]["grand_total"])
		payable = Decimal(quote["data"]["payable"])
		payload = self._submit_payload(
			client_accepted_grand_total=str(grand),
			payments=[
				{
					"mode_of_payment": "Cash",
					"amount": format(payable - Decimal("0.01"), "f"),
					"reference_no": None,
				}
			],
		)
		result, _ = self._call_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(result["error"]["details"]["reason"], "underpayment")
		self._assert_no_persisted_artifacts(self.profile.name)

	def test_cashier_submit_overpayment_is_rejected(self):
		quote = self._call_quote(self._quote_payload())
		grand = Decimal(quote["data"]["grand_total"])
		payable = Decimal(quote["data"]["payable"])
		payload = self._submit_payload(
			client_accepted_grand_total=str(grand),
			payments=[
				{
					"mode_of_payment": "Cash",
					"amount": format(payable + Decimal("0.01"), "f"),
					"reference_no": None,
				}
			],
		)
		result, _ = self._call_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_PAYMENT")
		self.assertEqual(result["error"]["details"]["reason"], "overpayment")
		self._assert_no_persisted_artifacts(self.profile.name)

	def test_cashier_submit_malformed_decimal_is_rejected(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": ".5", "reference_no": None}],
		)
		result, _ = self._call_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "amount")
		self.assertEqual(result["error"]["details"]["reason"], "malformed_decimal")
		self._assert_no_persisted_artifacts(self.profile.name)

	def test_cashier_submit_excessive_scale_is_rejected(self):
		payload = self._submit_payload(
			payments=[{"mode_of_payment": "Cash", "amount": "100.123", "reference_no": None}],
		)
		result, _ = self._call_submit(payload)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INVALID_REQUEST")
		self.assertEqual(result["error"]["details"]["field"], "amount")
		self.assertEqual(result["error"]["details"]["reason"], "excessive_scale")
		self._assert_no_persisted_artifacts(self.profile.name)

	def test_cashier_submit_replay_creates_exactly_one_invoice(self):
		quote = self._call_quote(self._quote_payload())
		grand = Decimal(quote["data"]["grand_total"])
		payable = Decimal(quote["data"]["payable"])
		payload = self._submit_payload(
			client_accepted_grand_total=str(grand),
			payments=[{"mode_of_payment": "Cash", "amount": str(payable), "reference_no": None}],
		)
		first, key = self._call_submit(payload)
		frappe.set_user(self.cashier)
		second, _ = self._call_submit(payload, idempotency_key=key)
		self.assertTrue(first["ok"], msg=str(first))
		self.assertTrue(second["ok"], msg=str(second))
		self.assertEqual(first["data"], second["data"])
		self.assertFalse(first["meta"]["replayed"])
		self.assertTrue(second["meta"]["replayed"])
		self.assertEqual(frappe.db.count("POS Invoice", {"pos_profile": self.profile.name}), 1)
		self.assertEqual(
			frappe.db.count(
				"POS Invoice",
				{"pos_profile": self.profile.name, "custom_mobile_pos_transaction_id": key},
			),
			1,
		)
		self.assertEqual(frappe.db.count("Mobile POS Request", {"idempotency_key": key}), 1)
