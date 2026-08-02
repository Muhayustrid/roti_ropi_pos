from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.profiles import profile_dto
from roti_ropi_pos.mobile_pos.validation import opening_amount_string

COMPANY = "_Test Company"


def profile_with_payments(*payments):
	return SimpleNamespace(
		name="POS Test Profile",
		company=COMPANY,
		currency="IDR",
		warehouse="_Test Warehouse - _TC",
		selling_price_list="Standard Selling",
		customer="_Test Customer",
		payments=list(payments),
	)


def payment(mode: str, suggestion: str | None = None):
	row = SimpleNamespace(mode_of_payment=mode)
	row.custom_mobile_pos_suggested_opening_amount = suggestion
	return row


def mode(name: str, *, enabled=True, account_company=COMPANY):
	return SimpleNamespace(
		name=name,
		enabled=enabled,
		accounts=[SimpleNamespace(company=account_company, default_account=f"{name} - _TC")],
	)


def projected_profile(*payments):
	profile = profile_with_payments(*payments)
	modes = {row.mode_of_payment: mode(row.mode_of_payment) for row in payments}
	get_value = frappe.db.get_value

	def get_value_for_profile(doctype, *args, **kwargs):
		if doctype == "Company":
			return "INR"
		if doctype == "Account":
			return COMPANY
		return get_value(doctype, *args, **kwargs)

	with (
		patch("frappe.get_doc", side_effect=lambda doctype, name: modes[name]),
		patch("frappe.db.get_value", side_effect=get_value_for_profile),
	):
		return profile_dto(profile)


class TestOpeningProjection(IntegrationTestCase):
	def test_profile_projection_preserves_payment_row_order(self):
		dto = projected_profile(payment("Cash"), payment("Bank"))
		self.assertEqual(
			[row["mode_of_payment"] for row in dto["opening_payment_modes"]],
			["Cash", "Bank"],
		)

	def test_profile_projection_returns_configured_suggestion(self):
		dto = projected_profile(payment("Cash", "200000.00"))
		self.assertEqual(dto["opening_payment_modes"][0]["suggested_opening_amount"], "200000.00")

	def test_blank_suggestion_returns_canonical_zero(self):
		dto = projected_profile(payment("Cash", ""))
		self.assertEqual(dto["opening_payment_modes"][0]["suggested_opening_amount"], "0.00")

	def test_amount_is_always_editable(self):
		dto = projected_profile(payment("Cash", "200000.00"))
		self.assertTrue(dto["opening_payment_modes"][0]["amount_editable"])

	def test_policy_uses_company_currency_not_profile_currency(self):
		dto = projected_profile(payment("Cash"))
		self.assertEqual(dto["currency"], "IDR")
		self.assertEqual(dto["opening_amount_policy"]["currency"], "INR")
		self.assertEqual(dto["opening_amount_policy"]["decimal_places"], 2)

	def test_profile_projection_exposes_no_accounting_fields(self):
		dto = projected_profile(payment("Cash"))
		self.assertNotIn("accounts", dto)
		self.assertNotIn("default_account", dto)
		self.assertNotIn("company_account", dto)
		self.assertNotIn("ledger", dto)

	def test_empty_payment_rows_fail_closed(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			projected_profile()
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_duplicate_payment_rows_fail_closed(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			projected_profile(payment("Cash"), payment("Cash"))
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_missing_linked_mode_fails_closed(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			with patch("frappe.get_doc", side_effect=frappe.DoesNotExistError):
				profile_dto(profile_with_payments(payment("Missing")))
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_disabled_linked_mode_fails_closed(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			with patch("frappe.get_doc", return_value=mode("Cash", enabled=False)):
				profile_dto(profile_with_payments(payment("Cash")))
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_missing_payment_account_fails_closed(self):
		bad_mode = SimpleNamespace(name="Cash", enabled=True, accounts=[])
		with self.assertRaises(MobilePOSAPIError) as error:
			with patch("frappe.get_doc", return_value=bad_mode):
				profile_dto(profile_with_payments(payment("Cash")))
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")

	def test_wrong_company_payment_account_fails_closed(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			with patch("frappe.get_doc", return_value=mode("Cash", account_company="Other Company")):
				profile_dto(profile_with_payments(payment("Cash")))
		self.assertEqual(error.exception.code, "PROFILE_CONFIGURATION_INVALID")


class TestOpeningAmountValidation(IntegrationTestCase):
	def test_strict_decimal_grammar(self):
		invalid = ["1,00", "+1.00", "1e2", " 1.00", "1.00 ", "1."]
		for value in invalid:
			with self.subTest(value=value), self.assertRaises(MobilePOSAPIError):
				opening_amount_string(value, field="amount", decimal_places=2)

	def test_decimal_requires_runtime_fractional_precision(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			opening_amount_string("1.001", field="amount", decimal_places=2)
		self.assertEqual(error.exception.details["reason"], "Too many fractional digits.")

	def test_decimal_does_not_round_or_truncate(self):
		self.assertEqual(opening_amount_string("1.20", field="amount", decimal_places=2), "1.20")

	def test_decimal_rejects_fractional_digits_beyond_database_scale(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			opening_amount_string(
				"1.001",
				field="amount",
				decimal_places=4,
				column_type="decimal(21,2)",
			)
		self.assertEqual(error.exception.details["reason"], "Too many fractional digits.")

	def test_decimal_rejects_negative_amount(self):
		with self.assertRaises(MobilePOSAPIError) as error:
			opening_amount_string("-0.01", field="amount", decimal_places=2)
		self.assertEqual(error.exception.details["reason"], "Amount must be non-negative.")

	def test_decimal_rejects_database_capacity_overflow(self):
		column_type = frappe.db.get_column_type("POS Opening Entry Detail", "opening_amount")
		precision, scale = column_type.removeprefix("decimal(").removesuffix(")").split(",")
		overflowing = "9" * (int(precision) - int(scale) + 1)
		with self.assertRaises(MobilePOSAPIError) as error:
			opening_amount_string(
				overflowing, field="amount", decimal_places=int(scale), column_type=column_type
			)
		self.assertEqual(error.exception.details["reason"], "Amount exceeds database capacity.")

	def test_custom_field_fixture_declares_suggested_amount(self):
		fixture_path = Path(frappe.get_app_path("roti_ropi_pos", "fixtures", "custom_field.json"))
		rows = json.loads(fixture_path.read_text())
		field = next(row for row in rows if row["fieldname"] == "custom_mobile_pos_suggested_opening_amount")
		self.assertEqual(field["dt"], "POS Payment Method")
		self.assertEqual(field["fieldtype"], "Data")


class TestOpeningEndpointContract(IntegrationTestCase):
	def test_client_modes_are_checked_against_projection(self):
		from roti_ropi_pos.mobile_pos.sessions import normalize_opening_balances

		profile = profile_with_payments(payment("Cash"))
		with patch(
			"roti_ropi_pos.mobile_pos.sessions.profile_opening_config",
			return_value={
				"opening_payment_modes": [{"mode_of_payment": "Cash"}],
				"decimal_places": 2,
				"column_type": "decimal(21,9)",
			},
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				normalize_opening_balances(profile, [{"mode_of_payment": "Card", "opening_amount": "0"}])
		self.assertEqual(error.exception.code, "INVALID_REQUEST")

	def test_duplicate_client_modes_are_rejected(self):
		from roti_ropi_pos.mobile_pos.sessions import normalize_opening_balances

		profile = profile_with_payments(payment("Cash"))
		with patch(
			"roti_ropi_pos.mobile_pos.sessions.profile_opening_config",
			return_value={
				"opening_payment_modes": [{"mode_of_payment": "Cash"}],
				"decimal_places": 2,
				"column_type": "decimal(21,9)",
			},
		):
			with self.assertRaises(MobilePOSAPIError) as error:
				normalize_opening_balances(
					profile,
					[
						{"mode_of_payment": "Cash", "opening_amount": "0"},
						{"mode_of_payment": "Cash", "opening_amount": "1"},
					],
				)
		self.assertEqual(error.exception.code, "INVALID_REQUEST")
