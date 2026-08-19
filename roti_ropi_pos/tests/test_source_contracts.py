"""Source-contract tests for the Mobile POS backend.

Each test pins an assumption about installed ERPNext/Frappe/stock_additional
source that our app code depends on.  A failure names the exact boundary to
re-audit before the next upgrade.

Convention: assertion messages start with "SOURCE CONTRACT:" so they are easy
to grep in CI output.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase


class TestCallableSignatures(IntegrationTestCase):
	"""Installed ERPNext callable signatures our services call directly."""

	def test_make_sales_return_accepts_source_name_and_target_doc(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return

		params = list(inspect.signature(make_sales_return).parameters)
		self.assertIn(
			"source_name",
			params,
			"SOURCE CONTRACT: make_sales_return lost `source_name` param — "
			"audit roti_ropi_pos.mobile_pos.invoices.create_return",
		)
		self.assertIn(
			"target_doc",
			params,
			"SOURCE CONTRACT: make_sales_return lost `target_doc` param — "
			"audit roti_ropi_pos.mobile_pos.invoices.create_return",
		)

	def test_get_stock_availability_accepts_item_code_and_warehouse(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import get_stock_availability

		params = list(inspect.signature(get_stock_availability).parameters)
		self.assertEqual(
			params[:2],
			["item_code", "warehouse"],
			"SOURCE CONTRACT: get_stock_availability signature changed — "
			"audit roti_ropi_pos.mobile_pos.invoices._validate_total_stock",
		)

	def test_get_items_accepts_required_pos_params(self):
		from erpnext.selling.page.point_of_sale.point_of_sale import get_items

		params = list(inspect.signature(get_items).parameters)
		for required in ("start", "page_length", "price_list", "item_group", "pos_profile"):
			self.assertIn(
				required,
				params,
				f"SOURCE CONTRACT: get_items lost `{required}` param — "
				"audit roti_ropi_pos.mobile_pos.catalog.search_items",
			)

	def test_get_conversion_factor_accepts_item_code_and_uom(self):
		from erpnext.stock.get_item_details import get_conversion_factor

		params = list(inspect.signature(get_conversion_factor).parameters)
		self.assertEqual(
			params[:2],
			["item_code", "uom"],
			"SOURCE CONTRACT: get_conversion_factor signature changed — "
			"audit roti_ropi_pos.mobile_pos.invoices._append_items",
		)

	def test_consolidate_pos_invoices_accepts_closing_entry_kwarg(self):
		from erpnext.accounts.doctype.pos_invoice_merge_log.pos_invoice_merge_log import (
			consolidate_pos_invoices,
		)

		params = inspect.signature(consolidate_pos_invoices).parameters
		self.assertIn(
			"closing_entry",
			params,
			"SOURCE CONTRACT: consolidate_pos_invoices lost `closing_entry` kwarg — "
			"audit roti_ropi_pos.mobile_pos.closing.ensure_committed_closing_job",
		)

	def test_get_batch_qty_accepts_batch_no(self):
		from erpnext.stock.doctype.batch.batch import get_batch_qty

		params = list(inspect.signature(get_batch_qty).parameters)
		self.assertIn(
			"batch_no",
			params,
			"SOURCE CONTRACT: get_batch_qty lost `batch_no` param — "
			"audit roti_ropi_pos.mobile_pos.invoices._append_items",
		)

	def test_get_uom_conv_factor_accepts_uom_and_stock_uom(self):
		from erpnext.stock.doctype.item.item import get_uom_conv_factor

		params = list(inspect.signature(get_uom_conv_factor).parameters)
		self.assertEqual(
			params[:2],
			["uom", "stock_uom"],
			"SOURCE CONTRACT: get_uom_conv_factor signature changed — "
			"audit roti_ropi_pos.mobile_pos.invoices._append_items",
		)

	def test_get_item_details_accepts_ctx_as_first_param(self):
		from erpnext.stock.get_item_details import get_item_details

		params = list(inspect.signature(get_item_details).parameters)
		self.assertEqual(
			params[0],
			"ctx",
			"SOURCE CONTRACT: get_item_details first param is no longer `ctx` — "
			"audit roti_ropi_pos.mobile_pos.catalog.quote_item",
		)


class TestPOSClosingEntryController(IntegrationTestCase):
	"""POSClosingEntry controller methods our override depends on."""

	def test_on_submit_exists(self):
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		self.assertTrue(
			hasattr(POSClosingEntry, "on_submit"),
			"SOURCE CONTRACT: POSClosingEntry.on_submit removed — "
			"audit roti_ropi_pos.overrides.pos_closing_entry.MobilePOSClosingEntry",
		)

	def test_build_invoice_query_supports_authoritative_closing_snapshot(self):
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import build_invoice_query

		self.assertEqual(
			list(inspect.signature(build_invoice_query).parameters),
			["invoice_doctype", "user", "pos_profile", "start", "end"],
			"SOURCE CONTRACT: build_invoice_query signature changed — audit Closing preview binding",
		)

	def test_closing_reconciliation_fields_remain_persisted_core_fields(self):
		fields = frappe.get_meta("POS Closing Entry Detail").fields
		self.assertTrue(
			{"opening_amount", "expected_amount", "closing_amount", "difference"}
			<= {field.fieldname for field in fields},
			"SOURCE CONTRACT: Closing reconciliation fields changed — audit terminal receipt",
		)

	def test_set_status_exists(self):
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		self.assertTrue(
			hasattr(POSClosingEntry, "set_status"),
			"SOURCE CONTRACT: POSClosingEntry.set_status removed — "
			"audit roti_ropi_pos.overrides.pos_closing_entry (Queued status path)",
		)

	def test_update_sales_invoices_closing_entry_exists(self):
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		self.assertTrue(
			hasattr(POSClosingEntry, "update_sales_invoices_closing_entry"),
			"SOURCE CONTRACT: POSClosingEntry.update_sales_invoices_closing_entry removed — "
			"audit roti_ropi_pos.overrides.pos_closing_entry (Queued path skips super().on_submit)",
		)

	def test_core_on_submit_calls_consolidate_synchronously(self):
		"""Core on_submit must call consolidate_pos_invoices — our override skips super() for >=10
		invoices and relies on that call never happening via the override path."""
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		src = inspect.getsource(POSClosingEntry.on_submit)
		self.assertIn(
			"consolidate_pos_invoices",
			src,
			"SOURCE CONTRACT: POSClosingEntry.on_submit no longer calls consolidate_pos_invoices — "
			"audit roti_ropi_pos.overrides.pos_closing_entry threshold logic",
		)

	def test_core_on_submit_has_no_invoice_count_threshold(self):
		"""Core on_submit must NOT have its own len(pos_invoices) threshold; our override owns
		that split.  If core added one, the two thresholds could diverge."""
		import re

		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		src = inspect.getsource(POSClosingEntry.on_submit)
		thresholds = re.findall(r"len\([^)]+pos_invoice[^)]*\)\s*[<>=!]+\s*\d+", src)
		self.assertEqual(
			thresholds,
			[],
			f"SOURCE CONTRACT: POSClosingEntry.on_submit now has invoice-count threshold(s) "
			f"{thresholds} — audit roti_ropi_pos.overrides.pos_closing_entry split logic",
		)


class TestBarcodeOverride(IntegrationTestCase):
	"""Stock barcode override contract."""

	def test_custom_scan_barcode_signature_matches_core(self):
		from erpnext.stock.utils import scan_barcode
		from stock_additional.overrides.barcode_scanner import custom_scan_barcode

		core_params = list(inspect.signature(scan_barcode).parameters)
		override_params = list(inspect.signature(custom_scan_barcode).parameters)
		self.assertEqual(
			core_params,
			override_params,
			f"SOURCE CONTRACT: custom_scan_barcode signature {override_params} diverged from "
			f"core scan_barcode {core_params} — audit stock_additional.overrides.barcode_scanner",
		)

	def test_stock_override_calls_original_scan_barcode(self):
		from stock_additional.overrides.barcode_scanner import custom_scan_barcode

		with patch(
			"stock_additional.overrides.barcode_scanner.original_scan_barcode", return_value={}
		) as core:
			custom_scan_barcode("SOME-BARCODE")

		core.assert_called_once_with("SOME-BARCODE", None)

	def test_scanner_method_constant_matches_registered_override(self):
		"""SCANNER_METHOD in catalog.py must equal the key registered in stock hooks."""
		from roti_ropi_pos.mobile_pos.catalog import SCANNER_METHOD

		override_map = frappe.get_hooks("override_whitelisted_methods", app_name="stock_additional")
		self.assertIn(
			SCANNER_METHOD,
			override_map,
			f"SOURCE CONTRACT: SCANNER_METHOD {SCANNER_METHOD!r} not in stock "
			"override_whitelisted_methods — audit roti_ropi_pos.mobile_pos.catalog.SCANNER_METHOD",
		)

	def test_frappe_dispatch_resolves_effective_stock_scanner(self):
		from roti_ropi_pos.mobile_pos.catalog import SCANNER_METHOD

		self.assertEqual(
			frappe.override_whitelisted_method(SCANNER_METHOD),
			"stock_additional.overrides.barcode_scanner.custom_scan_barcode",
			"SOURCE CONTRACT: Frappe no longer dispatches SCANNER_METHOD to stock override — "
			"audit override_whitelisted_methods resolution and installed app order",
		)


class TestAppHooks(IntegrationTestCase):
	"""App hook registrations our runtime depends on."""

	def test_roti_dependencies_use_extracted_apps(self):
		from roti_ropi_pos import hooks

		self.assertEqual(
			hooks.required_apps,
			["erpnext", "stock_additional", "selling_additional"],
		)

	def test_effective_past_order_provider_is_selling_additional(self):
		self.assertEqual(
			frappe.override_whitelisted_method(
				"erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"
			),
			"selling_additional.overrides.pos_overrides.custom_get_past_order_list",
			"SOURCE CONTRACT: past-order override no longer owned by selling_additional",
		)

	def test_auth_hook_registered(self):
		hooks = frappe.get_hooks("auth_hooks", app_name="roti_ropi_pos")
		self.assertIn(
			"roti_ropi_pos.mobile_pos.auth_hook.validate_mobile_api_scope",
			hooks,
			"SOURCE CONTRACT: auth_hook not registered in hooks.py — audit roti_ropi_pos.hooks.auth_hooks",
		)

	def test_pos_closing_entry_override_registered(self):
		overrides = frappe.get_hooks("override_doctype_class", app_name="roti_ropi_pos")
		self.assertIn(
			"POS Closing Entry",
			overrides,
			"SOURCE CONTRACT: POS Closing Entry override_doctype_class not registered — "
			"audit roti_ropi_pos.hooks.override_doctype_class",
		)
		self.assertIn(
			"roti_ropi_pos.overrides.pos_closing_entry.MobilePOSClosingEntry",
			overrides["POS Closing Entry"],
			"SOURCE CONTRACT: MobilePOSClosingEntry path changed in hooks.py — "
			"audit roti_ropi_pos.hooks.override_doctype_class",
		)

	def test_pos_invoice_override_registered(self):
		overrides = frappe.get_hooks("override_doctype_class", app_name="roti_ropi_pos")
		self.assertIn(
			"POS Invoice",
			overrides,
			"SOURCE CONTRACT: POS Invoice override_doctype_class not registered — "
			"audit roti_ropi_pos.hooks.override_doctype_class",
		)

	def test_user_override_registered(self):
		overrides = frappe.get_hooks("override_doctype_class", app_name="roti_ropi_pos")
		self.assertEqual(
			overrides.get("User"),
			["roti_ropi_pos.overrides.user.MobilePOSUser"],
			"SOURCE CONTRACT: User override is not registered correctly — audit roti_ropi_pos.hooks",
		)

	def test_frappe_controller_dispatch_uses_mobile_user_override(self):
		from frappe.model.base_document import get_controller

		from roti_ropi_pos.overrides.user import MobilePOSUser

		self.assertIs(get_controller("User"), MobilePOSUser)

	def test_frappe_controller_dispatch_uses_mobile_closing_override(self):
		from frappe.model.base_document import get_controller

		from roti_ropi_pos.overrides.pos_closing_entry import MobilePOSClosingEntry

		self.assertIs(
			get_controller("POS Closing Entry"),
			MobilePOSClosingEntry,
			"SOURCE CONTRACT: Frappe controller dispatch bypasses MobilePOSClosingEntry — "
			"audit override_doctype_class resolution and controller cache",
		)

	def test_frappe_auth_dispatch_executes_mobile_scope_hook(self):
		from frappe.auth import validate_auth_via_hooks

		from roti_ropi_pos.tests.helpers import clear_fake_request, set_request

		saved_user = frappe.session.user
		try:
			frappe.set_user("Guest")
			set_request("/api/method/roti_ropi_pos.api.v1.bootstrap.get")
			with (
				patch("frappe.get_request_header", return_value=""),
				self.assertRaises(
					frappe.AuthenticationError,
					msg="SOURCE CONTRACT: Frappe auth dispatcher did not execute Mobile POS scope hook — "
					"audit frappe.auth.validate_auth_via_hooks and auth_hooks registration",
				),
			):
				validate_auth_via_hooks()
		finally:
			clear_fake_request()
			frappe.set_user(saved_user)

	def test_queued_closing_defers_job_until_after_commit(self):
		from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

		import roti_ropi_pos.overrides.pos_closing_entry as closing_override

		closing = object.__new__(closing_override.MobilePOSClosingEntry)
		closing.pos_invoices = [object()] * 10
		closing.pos_opening_entry = "SOURCE-CONTRACT-OPE"
		closing.name = "SOURCE-CONTRACT-CLO"
		closing.doctype = "POS Closing Entry"
		closing.docstatus = 1
		closing.status = "Submitted"
		closing.set_status = MagicMock()
		closing.update_sales_invoices_closing_entry = MagicMock()
		callbacks = []

		with (
			patch.object(POSClosingEntry, "on_submit") as core_submit,
			patch.object(closing_override, "ensure_committed_closing_job") as job,
			patch("frappe.publish_realtime"),
			patch.object(frappe.db, "after_commit", MagicMock(add=callbacks.append)),
		):
			closing.on_submit()
			core_submit.assert_not_called()
			job.assert_not_called()
			self.assertEqual(
				len(callbacks),
				1,
				"SOURCE CONTRACT: queued closing did not register exactly one after-commit job — "
				"audit MobilePOSClosingEntry.on_submit and frappe.db.after_commit",
			)
			callbacks[0]()
			job.assert_called_once_with("SOURCE-CONTRACT-CLO")


class TestNoPrivateSellingImports(IntegrationTestCase):
	"""roti consumes selling_additional only through effective hooks and stable Frappe APIs."""

	def test_no_private_selling_additional_imports(self):
		app_path = Path(frappe.get_app_path("roti_ropi_pos"))
		offenders = []
		for source_path in app_path.rglob("*.py"):
			if "__pycache__" in source_path.parts:
				continue
			tree = ast.parse(source_path.read_text())
			relative = source_path.relative_to(app_path)
			for node in ast.walk(tree):
				if isinstance(node, ast.Import):
					for alias in node.names:
						if alias.name == "selling_additional" or alias.name.startswith("selling_additional."):
							offenders.append(f"{relative}: import {alias.name}")
				elif isinstance(node, ast.ImportFrom):
					module = node.module or ""
					if module == "selling_additional" or module.startswith("selling_additional."):
						names = ", ".join(alias.name for alias in node.names)
						offenders.append(f"{relative}: from {module} import {names}")
		self.assertEqual(
			offenders,
			[],
			"SOURCE CONTRACT: roti_ropi_pos must not import selling_additional helpers or "
			"exception types; integrate through effective hooks, persisted ERPNext data, or "
			"public contracts",
		)


class TestNoERPNextTestModuleImports(IntegrationTestCase):
	"""Roti tests must not import an ERPNext *test* module.

	``erpnext.tests.utils`` instantiates ``BootStrapTestData()`` at module scope, and
	its price-list bootstrap treats the hardcoded ``"INR"`` as part of the existence
	check. On a site whose ``Standard Buying`` / ``Standard Selling`` carry any other
	currency the check misses and the insert collides, so importing any ERPNext test
	module (directly or transitively — every one of them imports ``ERPNextTestSuite``)
	kills test *discovery* with ``DuplicateEntryError: ('Price List', 'Standard
	Buying', ...)`` before one test runs. Own the fixture helper instead; see
	``roti_ropi_pos.tests.helpers.set_default_account_for_mode_of_payment``.

	Frappe's own test modules are not covered here: they carry no import-time fixture
	bootstrap (``frappe.tests.utils.generators._try_create`` guards on
	``frappe.db.exists``, so it is currency-safe), and this contract is a guard against
	the measured failure, not a general style rule.
	"""

	def test_no_erpnext_test_module_imports(self):
		app_path = Path(frappe.get_app_path("roti_ropi_pos"))

		def is_erpnext_test_module(module: str) -> bool:
			if module != "erpnext" and not module.startswith("erpnext."):
				return False
			return any(part == "tests" or part.startswith("test_") for part in module.split("."))

		offenders = []
		for source_path in app_path.rglob("*.py"):
			if "__pycache__" in source_path.parts:
				continue
			tree = ast.parse(source_path.read_text())
			relative = source_path.relative_to(app_path)
			for node in ast.walk(tree):
				if isinstance(node, ast.Import):
					for alias in node.names:
						if is_erpnext_test_module(alias.name):
							offenders.append(f"{relative}: import {alias.name}")
				elif isinstance(node, ast.ImportFrom):
					module = node.module or ""
					if is_erpnext_test_module(module):
						names = ", ".join(alias.name for alias in node.names)
						offenders.append(f"{relative}: from {module} import {names}")
		self.assertEqual(
			offenders,
			[],
			"SOURCE CONTRACT: importing an ERPNext test module drags in erpnext.tests.utils, "
			"whose import-time BootStrapTestData() breaks test discovery on any site whose "
			"price lists are not INR — own the fixture helper in roti_ropi_pos.tests.helpers "
			"instead",
		)


class TestErrorCodeContract(IntegrationTestCase):
	"""``docs/mobile-pos/api-contract.md`` must stay 1:1 with runtime error codes.

	Android freezes its error enum from the contract tables, so a code that only one
	side knows about is a client bug waiting to happen: an undocumented runtime code
	reaches the app as an unknown value, and a documented code with no producer becomes
	dead branches the app can never exercise. The runtime is authority — a failure here
	means the document is stale, not that the runtime should change.
	"""

	# Non-error codes: stable enum values inside successful bodies (warnings,
	# closing failure, returnability rejection), listed in their own contract table.
	NON_ERROR_CODES = frozenset(
		{
			"STALE_OPENING",
			"MISSING_UOM_CONVERSION",
			"CLOSING_FAILED",
			"SOURCE_NOT_RETURNABLE",
			"RETURN_LIMIT_REACHED",
			"NO_VALID_REFUND_MODE",
			"SERIAL_BATCH_REFERENCE_UNAVAILABLE",
		}
	)

	def _contract_path(self) -> Path:
		return Path(frappe.get_app_path("roti_ropi_pos")).parent / "docs" / "mobile-pos" / "api-contract.md"

	def _documented_codes(self) -> set[str]:
		"""Codes in a leading `| HTTP | \\`CODE\\` |` cell of the main error table."""
		import re

		text = self._contract_path().read_text()
		table = text.split("## Stable In-Endpoint Error Codes", 1)[1].split("### Removed", 1)[0]
		return set(re.findall(r"^\|\s*\d{3}\s*\|\s*`([A-Z][A-Z0-9_]+)`\s*\|", table, re.MULTILINE))

	def _runtime_codes(self) -> dict[str, set[str]]:
		"""Map each runtime error-code literal to the modules that contain it.

		Codes are collected by literal shape rather than from the first argument of
		``MobilePOSAPIError``, because several are dispatched through a variable
		(``closing._raise_payment_error``, ``closing._raise_closing_unavailable``) and a
		first-argument scan would silently miss exactly the codes most likely to drift.
		Success-body enum values match the same shape, so they are excluded through
		``NON_ERROR_CODES`` and pinned by their own tests.
		"""
		import re

		shape = re.compile(r"\A[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\Z")
		app_path = Path(frappe.get_app_path("roti_ropi_pos"))
		producers: dict[str, set[str]] = {}
		for directory in ("mobile_pos", "api/v1"):
			for source_path in sorted((app_path / directory).glob("*.py")):
				tree = ast.parse(source_path.read_text())
				for node in ast.walk(tree):
					if (
						isinstance(node, ast.Constant)
						and isinstance(node.value, str)
						and shape.match(node.value)
						and node.value not in self.NON_ERROR_CODES
					):
						producers.setdefault(node.value, set()).add(source_path.name)
		return producers

	def test_every_runtime_error_code_is_documented(self):
		undocumented = {
			code: sorted(files)
			for code, files in self._runtime_codes().items()
			if code not in self._documented_codes()
		}
		self.assertEqual(
			undocumented,
			{},
			"SOURCE CONTRACT: runtime raises Mobile POS error codes that the contract does not "
			f"document: {undocumented} — add them to the Stable In-Endpoint Error Codes table in "
			"docs/mobile-pos/api-contract.md before Android freezes its enum",
		)

	def test_every_documented_error_code_has_a_runtime_producer(self):
		orphans = sorted(self._documented_codes() - set(self._runtime_codes()))
		self.assertEqual(
			orphans,
			[],
			f"SOURCE CONTRACT: contract documents error codes with no runtime producer: {orphans} — "
			"remove or deprecate them in docs/mobile-pos/api-contract.md; the runtime is authority",
		)

	def test_non_error_codes_are_not_in_the_error_table(self):
		"""Success-body enum values must not leak into the error-code table.

		They are stable and frozen by Android too, but they never appear in
		``message.error.code``, so documenting one as an error would make the client
		expect an envelope it can never receive.
		"""
		leaked = sorted(self.NON_ERROR_CODES & self._documented_codes())
		self.assertEqual(
			leaked,
			[],
			f"SOURCE CONTRACT: non-error codes listed as in-endpoint errors: {leaked} — "
			"keep them in the Non-Error Stable Codes table",
		)

	def test_non_error_codes_are_documented(self):
		text = self._contract_path().read_text()
		missing = sorted(code for code in self.NON_ERROR_CODES if f"`{code}`" not in text)
		self.assertEqual(
			missing,
			[],
			f"SOURCE CONTRACT: non-error stable codes are undocumented: {missing} — "
			"add them to the Non-Error Stable Codes table in docs/mobile-pos/api-contract.md",
		)

	def test_retryable_codes_match_the_documented_pair(self):
		"""Exactly the two documented codes may carry ``retryable=True``.

		Android decides whether to resend a mutation with the same idempotency key from
		this flag alone, so a new retryable code is a contract change, not an
		implementation detail.
		"""
		app_path = Path(frappe.get_app_path("roti_ropi_pos"))
		retryable = set()
		for directory in ("mobile_pos", "api/v1"):
			for source_path in sorted((app_path / directory).glob("*.py")):
				for node in ast.walk(ast.parse(source_path.read_text())):
					if (
						isinstance(node, ast.Call)
						and getattr(node.func, "id", None) == "MobilePOSAPIError"
						and node.args
						and isinstance(node.args[0], ast.Constant)
						and any(
							keyword.arg == "retryable"
							and isinstance(keyword.value, ast.Constant)
							and keyword.value.value is True
							for keyword in node.keywords
						)
					):
						retryable.add(node.args[0].value)
		self.assertEqual(
			retryable,
			{"REQUEST_IN_PROGRESS", "TEMPORARILY_UNAVAILABLE"},
			f"SOURCE CONTRACT: retryable Mobile POS error codes changed to {sorted(retryable)} — "
			"update the Retryable Semantics section in docs/mobile-pos/api-contract.md",
		)


class TestRequiredDocTypeFields(IntegrationTestCase):
	"""Custom fields our services read/write must exist on installed DocTypes."""

	def _field_exists(self, doctype: str, fieldname: str) -> bool:
		meta = frappe.get_meta(doctype)
		return any(f.fieldname == fieldname for f in meta.fields)

	def test_pos_invoice_has_transaction_id_field(self):
		self.assertTrue(
			self._field_exists("POS Invoice", "custom_mobile_pos_transaction_id"),
			"SOURCE CONTRACT: custom_mobile_pos_transaction_id missing on POS Invoice — "
			"run bench migrate or check fixtures",
		)

	def test_pos_invoice_has_walk_in_customer_name_field(self):
		for doctype in ("POS Invoice", "Sales Invoice"):
			self.assertTrue(
				self._field_exists(doctype, "custom_walk_in_customer_name"),
				f"SOURCE CONTRACT: custom_walk_in_customer_name missing on {doctype} — "
				"run bench migrate or check fixtures",
			)

	def test_pos_opening_entry_has_transaction_id_field(self):
		self.assertTrue(
			self._field_exists("POS Opening Entry", "custom_mobile_pos_transaction_id"),
			"SOURCE CONTRACT: custom_mobile_pos_transaction_id missing on POS Opening Entry — "
			"run bench migrate or check fixtures",
		)

	def test_pos_closing_entry_has_transaction_id_field(self):
		self.assertTrue(
			self._field_exists("POS Closing Entry", "custom_mobile_pos_transaction_id"),
			"SOURCE CONTRACT: custom_mobile_pos_transaction_id missing on POS Closing Entry — "
			"run bench migrate or check fixtures",
		)


class TestPOSInvoiceModeAssumption(IntegrationTestCase):
	"""require_pos_invoice_mode must be verifiable in POS Settings."""

	def test_pos_settings_invoice_type_single_doctype_exists(self):
		self.assertTrue(
			frappe.db.exists("DocType", "POS Settings"),
			"SOURCE CONTRACT: POS Settings DocType missing — "
			"audit roti_ropi_pos.mobile_pos.authorization.require_pos_invoice_mode",
		)

	def test_pos_settings_has_invoice_type_field(self):
		meta = frappe.get_meta("POS Settings")
		field_names = [f.fieldname for f in meta.fields]
		self.assertIn(
			"invoice_type",
			field_names,
			"SOURCE CONTRACT: invoice_type field missing on POS Settings — "
			"audit roti_ropi_pos.mobile_pos.authorization.require_pos_invoice_mode",
		)

	def test_pos_settings_invoice_type_accepts_pos_invoice_value(self):
		saved = frappe.db.get_single_value("POS Settings", "invoice_type")
		try:
			frappe.db.set_single_value("POS Settings", "invoice_type", "POS Invoice")
			read_back = frappe.db.get_single_value("POS Settings", "invoice_type")
			self.assertEqual(
				read_back,
				"POS Invoice",
				"SOURCE CONTRACT: POS Settings.invoice_type cannot store 'POS Invoice' — "
				"audit roti_ropi_pos.mobile_pos.authorization.require_pos_invoice_mode",
			)
		finally:
			frappe.db.set_single_value("POS Settings", "invoice_type", saved or "POS Invoice")
