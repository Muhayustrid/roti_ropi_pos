"""Source-contract tests for the Mobile POS backend.

Each test pins an assumption about installed ERPNext/Frappe/bakery_manufacturing
source that our app code depends on.  A failure names the exact boundary to
re-audit before the next upgrade.

Convention: assertion messages start with "SOURCE CONTRACT:" so they are easy
to grep in CI output.
"""
from __future__ import annotations

import inspect
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
    """Bakery barcode override contract."""

    def test_custom_scan_barcode_signature_matches_core(self):
        from bakery_manufacturing.overrides.barcode_scanner import custom_scan_barcode
        from erpnext.stock.utils import scan_barcode

        core_params = list(inspect.signature(scan_barcode).parameters)
        override_params = list(inspect.signature(custom_scan_barcode).parameters)
        self.assertEqual(
            core_params,
            override_params,
            f"SOURCE CONTRACT: custom_scan_barcode signature {override_params} diverged from "
            f"core scan_barcode {core_params} — audit bakery_manufacturing.overrides.barcode_scanner",
        )

    def test_bakery_override_calls_original_scan_barcode(self):
        src = inspect.getsource(
            __import__(
                "bakery_manufacturing.overrides.barcode_scanner",
                fromlist=["custom_scan_barcode"],
            ).custom_scan_barcode
        )
        self.assertIn(
            "scan_barcode",
            src,
            "SOURCE CONTRACT: custom_scan_barcode no longer delegates to core scan_barcode — "
            "audit bakery_manufacturing.overrides.barcode_scanner",
        )

    def test_scanner_method_constant_matches_registered_override(self):
        """SCANNER_METHOD in catalog.py must equal the key registered in bakery hooks."""
        from roti_ropi_pos.mobile_pos.catalog import SCANNER_METHOD

        override_map = frappe.get_hooks(
            "override_whitelisted_methods", app_name="bakery_manufacturing"
        )
        self.assertIn(
            SCANNER_METHOD,
            override_map,
            f"SOURCE CONTRACT: SCANNER_METHOD {SCANNER_METHOD!r} not in bakery "
            "override_whitelisted_methods — audit roti_ropi_pos.mobile_pos.catalog.SCANNER_METHOD",
        )

    def test_frappe_dispatch_resolves_effective_bakery_scanner(self):
        from roti_ropi_pos.mobile_pos.catalog import SCANNER_METHOD

        self.assertEqual(
            frappe.override_whitelisted_method(SCANNER_METHOD),
            "bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode",
            "SOURCE CONTRACT: Frappe no longer dispatches SCANNER_METHOD to bakery override — "
            "audit override_whitelisted_methods resolution and installed app order",
        )


class TestAppHooks(IntegrationTestCase):
    """App hook registrations our runtime depends on."""

    def test_auth_hook_registered(self):
        hooks = frappe.get_hooks("auth_hooks", app_name="roti_ropi_pos")
        self.assertIn(
            "roti_ropi_pos.mobile_pos.auth_hook.validate_mobile_api_scope",
            hooks,
            "SOURCE CONTRACT: auth_hook not registered in hooks.py — "
            "audit roti_ropi_pos.hooks.auth_hooks",
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
        import roti_ropi_pos.overrides.pos_closing_entry as closing_override
        from erpnext.accounts.doctype.pos_closing_entry.pos_closing_entry import POSClosingEntry

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
        self.assertTrue(
            self._field_exists("POS Invoice", "custom_walk_in_customer_name"),
            "SOURCE CONTRACT: custom_walk_in_customer_name missing on POS Invoice — "
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
