# Stock Additional Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transfer Item custom-UOM and barcode-scanner ownership from `bakery_manufacturing` to `stock_additional`, then fail closed for invalid conversions.

**Architecture:** Keep one pure resolver as the correctness boundary. Item validation and runtime scanning call that resolver. The scanner delegates to ERPNext core first, enriches only batch results, and mutates a copy only after validation succeeds. The coordinated bakery revision removes its active hook and fixture while retaining a one-release lazy Python shim. `roti_ropi_pos` continues dynamic hook resolution and changes only dependency and source-contract ownership.

**Tech Stack:** Python 3.14, Frappe and ERPNext v16, MariaDB, unittest/Frappe integration tests, Ruff, and pre-commit.

**Spec:** `docs/superpowers/specs/2026-08-14-app-ownership-extraction-design.md`

## Global Constraints

- Complete `2026-08-14-additional-app-shells.md` first.
- Use existing `development.localhost` for implementation tests, per the user's execution-time choice. Keep `allow_tests = true`, scheduler disabled, rollback-isolated fixtures, and no destructive shared cleanup.
- Run bench commands inside `/workspace/development/frappe-bench`.
- Pass `--site development.localhost` to every site command.
- Verify ERPNext's installed scanner signature before changing the override.
- Keep `custom_scan_barcode(search_value: str, ctx: dict | str | None = None)`.
- Keep ERPNext core as the first scan operation.
- Never return a custom UOM without a positive conversion factor.
- Never mutate the core response before all custom-UOM validation succeeds.
- Use the exact fixture identity `Item-custom_default_uom_warehouse`.
- End with exactly one active scanner provider.
- Do not edit ERPNext or Frappe.
- Do not modify or stage bakery's dirty bundle, untracked sidebar test, or unrelated files. Re-verify the bundle full-file SHA-256 `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8` before and after bakery handoff.
- Do not modify or stage `roti_ropi_pos/tests/test_sales.py` or other existing user work.
- Do not commit, push, migrate an active site, or deploy without separate approval.

---

### Task 1: Pin the Stock Contracts Before Moving Code

**Files:**
- Create: `stock_additional/stock_additional/tests/__init__.py`
- Create: `stock_additional/stock_additional/tests/test_uom_resolver.py`
- Create: `stock_additional/stock_additional/tests/test_barcode_scanner.py`
- Create: `stock_additional/stock_additional/tests/test_item_validation.py`
- Create: `stock_additional/stock_additional/tests/test_hooks.py`

**Interfaces:**
- Consumes: `erpnext.stock.utils.scan_barcode(search_value, ctx=None)`.
- Produces: the required signature and fail-closed behavior as executable tests.
- Produces: `resolve_custom_uom(item) -> ResolvedCustomUOM | None`.
- Produces: `validate_item_custom_uom(item, method=None) -> None`.
- Produces: `custom_scan_barcode(search_value, ctx=None) -> dict`.

- [ ] **Step 1: Verify the installed core contract**

Read installed `erpnext/stock/utils.py`. Record:

```python
@frappe.whitelist()
def scan_barcode(search_value: str, ctx: dict | str | None = None) -> BarcodeScanResult:
```

Confirm core returns `{}` when no match and may return a cached mutable mapping. Stop if signature differs.

- [ ] **Step 2: Write failing pure resolver tests**

Create `stock_additional/stock_additional/tests/test_uom_resolver.py`:

```python
import unittest

import frappe

from stock_additional.uom import resolve_custom_uom


def item_doc(*, custom_uom=None, uoms=None):
	return frappe._dict(
		name="ITEM-1",
		stock_uom="Gram",
		custom_default_uom_warehouse=custom_uom,
		uoms=[frappe._dict(row) for row in (uoms or [])],
	)


class TestResolveCustomUOM(unittest.TestCase):
	def test_empty_custom_uom_passes_through(self):
		item = item_doc()
		self.assertIsNone(resolve_custom_uom(item))

	def test_stock_uom_passes_without_conversion_row(self):
		item = item_doc(custom_uom="Gram")
		self.assertIsNone(resolve_custom_uom(item))

	def test_valid_conversion_returns_uom_and_factor(self):
		item = item_doc(
			custom_uom="Carton",
			uoms=[{"uom": "Carton", "conversion_factor": 1000}],
		)
		resolved = resolve_custom_uom(item)
		self.assertEqual(resolved.uom, "Carton")
		self.assertEqual(resolved.conversion_factor, 1000.0)

	def test_missing_conversion_fails_closed(self):
		item = item_doc(custom_uom="Carton")
		with self.assertRaises(frappe.ValidationError):
			resolve_custom_uom(item)

	def test_zero_and_negative_conversion_fail_closed(self):
		for factor in (0, -1):
			with self.subTest(factor=factor):
				item = item_doc(
					custom_uom="Carton",
					uoms=[{"uom": "Carton", "conversion_factor": factor}],
				)
				with self.assertRaises(frappe.ValidationError):
					resolve_custom_uom(item)
```

- [ ] **Step 3: Write failing scanner unit tests**

Create `stock_additional/stock_additional/tests/test_barcode_scanner.py`:

```python
import unittest
from unittest.mock import patch

import frappe

from stock_additional.overrides.barcode_scanner import custom_scan_barcode


class TestCustomScanBarcode(unittest.TestCase):
	@patch("stock_additional.overrides.barcode_scanner.resolve_item_custom_uom")
	@patch("stock_additional.overrides.barcode_scanner.original_scan_barcode")
	def test_delegates_to_core_first(self, core_scan, resolve):
		core_scan.return_value = {"item_code": "ITEM-1", "batch_no": "BATCH-1"}
		resolve.return_value = None

		result = custom_scan_barcode("BATCH-1", {"company": "Company"})

		core_scan.assert_called_once_with("BATCH-1", {"company": "Company"})
		resolve.assert_called_once_with("ITEM-1")
		self.assertEqual(result, core_scan.return_value)

	@patch("stock_additional.overrides.barcode_scanner.resolve_item_custom_uom")
	@patch("stock_additional.overrides.barcode_scanner.original_scan_barcode")
	def test_non_batch_result_is_untouched(self, core_scan, resolve):
		core_result = {"item_code": "ITEM-1", "barcode": "CODE", "uom": None}
		core_scan.return_value = core_result

		result = custom_scan_barcode("CODE")

		resolve.assert_not_called()
		self.assertIs(result, core_result)

	@patch("stock_additional.overrides.barcode_scanner.resolve_item_custom_uom")
	@patch("stock_additional.overrides.barcode_scanner.original_scan_barcode")
	def test_valid_batch_enriches_a_copy(self, core_scan, resolve):
		core_result = {"item_code": "ITEM-1", "batch_no": "BATCH-1"}
		core_scan.return_value = core_result
		resolve.return_value = type("Resolved", (), {"uom": "Carton", "conversion_factor": 1000.0})()

		result = custom_scan_barcode("BATCH-1")

		self.assertEqual(result["uom"], "Carton")
		self.assertEqual(result["conversion_factor"], 1000.0)
		self.assertNotIn("uom", core_result)
		self.assertIsNot(result, core_result)

	@patch("stock_additional.overrides.barcode_scanner.resolve_item_custom_uom")
	@patch("stock_additional.overrides.barcode_scanner.original_scan_barcode")
	def test_rejection_does_not_mutate_core_result(self, core_scan, resolve):
		core_result = {"item_code": "ITEM-1", "batch_no": "BATCH-1"}
		core_scan.return_value = core_result
		resolve.side_effect = frappe.ValidationError("invalid conversion")

		with self.assertRaises(frappe.ValidationError):
			custom_scan_barcode("BATCH-1")

		self.assertEqual(core_result, {"item_code": "ITEM-1", "batch_no": "BATCH-1"})
```

- [ ] **Step 4: Write failing hook contract tests**

Create `stock_additional/stock_additional/tests/test_hooks.py`:

```python
import importlib
import inspect

import frappe
from frappe.tests import IntegrationTestCase


SCANNER_METHOD = "erpnext.stock.utils.scan_barcode"
STOCK_SCANNER = "stock_additional.overrides.barcode_scanner.custom_scan_barcode"


class TestStockHooks(IntegrationTestCase):
	def test_target_hooks_have_exact_shape(self):
		hooks = importlib.import_module("stock_additional.hooks")
		self.assertEqual(hooks.required_apps, ["erpnext"])
		self.assertEqual(
			hooks.override_whitelisted_methods,
			{SCANNER_METHOD: STOCK_SCANNER},
		)
		self.assertEqual(
			hooks.doc_events,
			{"Item": {"validate": "stock_additional.uom.validate_item_custom_uom"}},
		)

	def test_scanner_signature_matches_core(self):
		from erpnext.stock.utils import scan_barcode
		from stock_additional.overrides.barcode_scanner import custom_scan_barcode

		self.assertEqual(
			tuple(inspect.signature(custom_scan_barcode).parameters),
			tuple(inspect.signature(scan_barcode).parameters),
		)

	def test_exact_item_fixture_identity(self):
		hooks = importlib.import_module("stock_additional.hooks")
		self.assertEqual(
			hooks.fixtures,
			[
				{
					"dt": "Custom Field",
					"filters": [["name", "=", "Item-custom_default_uom_warehouse"]],
				}
			],
		)
```

- [ ] **Step 5: Run tests and verify RED**

```bash
cd /workspace/development/frappe-bench
python -m unittest stock_additional.tests.test_uom_resolver
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_barcode_scanner
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_item_validation
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_hooks
```

Expected: FAIL because `stock_additional.uom`, scanner implementation, and target hooks do not exist.

### Task 2: Implement the Fail-Closed UOM Boundary

**Files:**
- Create: `stock_additional/stock_additional/exceptions.py`
- Create: `stock_additional/stock_additional/uom.py`
- Modify: `stock_additional/stock_additional/tests/test_item_validation.py`

**Interfaces:**
- `InvalidCustomUOMError(item_code: str, uom: str, reason: str)` is the public, typed configuration-error boundary.
- `ResolvedCustomUOM(uom: str, conversion_factor: float)` is immutable.
- `resolve_custom_uom(item) -> ResolvedCustomUOM | None` reads the in-memory Item document.
- `resolve_item_custom_uom(item_code: str) -> ResolvedCustomUOM | None` loads fresh Item and UOM child state from the database for every runtime scan.
- `validate_item_custom_uom(item, method=None) -> None` delegates to `resolve_custom_uom`.

- [ ] **Step 1: Implement the minimal resolver**

Create `stock_additional/exceptions.py`:

```python
import frappe


class InvalidCustomUOMError(frappe.ValidationError):
	def __init__(self, item_code: str, uom: str, reason: str):
		self.item_code = item_code
		self.uom = uom
		self.reason = reason
		super().__init__(
			f"Item {item_code}: Default UOM {uom} requires a positive conversion factor in the UOMs table."
		)
```

Create `stock_additional/uom.py`:

```python
from dataclasses import dataclass

import frappe
from frappe.utils import flt

from stock_additional.exceptions import InvalidCustomUOMError


@dataclass(frozen=True)
class ResolvedCustomUOM:
	uom: str
	conversion_factor: float


def resolve_custom_uom(item) -> ResolvedCustomUOM | None:
	custom_uom = item.get("custom_default_uom_warehouse")
	if not custom_uom or custom_uom == item.stock_uom:
		return None

	row = next((row for row in item.get("uoms", []) if row.uom == custom_uom), None)
	factor = flt(row.conversion_factor) if row else 0.0
	if factor <= 0:
		raise InvalidCustomUOMError(
			item.name,
			custom_uom,
			"missing" if row is None else "non_positive",
		)

	return ResolvedCustomUOM(custom_uom, factor)


def resolve_item_custom_uom(item_code: str) -> ResolvedCustomUOM | None:
	item = frappe.get_doc("Item", item_code)
	return resolve_custom_uom(item)


def validate_item_custom_uom(item, method=None) -> None:
	resolve_custom_uom(item)
```

The subtype preserves normal Frappe Item validation while giving `roti_ropi_pos` one exact exception to map. Do not parse exception text or catch all `frappe.ValidationError` instances. Reuse one resolver. Do not query `UOM Conversion Detail` separately in loops. Runtime correctness takes priority over cached reads because direct database writes and legacy invalid rows can bypass Item cache invalidation.

- [ ] **Step 2: Add hook-level Item validation and fresh-runtime tests**

Extend `test_item_validation.py` with an `IntegrationTestCase` that creates unique Items. Assert normal document saves accept empty custom UOM, stock UOM, and a positive differing conversion. Assert document saves reject missing, zero, and negative factors.

Create legacy-invalid runtime state only after inserting a valid Item. Use test-only direct database updates on the exact Item Custom Field and its `UOM Conversion Detail` row. Do not call `Item.save()` after corruption because the new hook must reject it. Then call `resolve_item_custom_uom(item.name)` and assert it reads the changed database state instead of a previously cached Item.

Test each sequence:

```python
item = make_valid_item(custom_uom="Carton", factor=12)
frappe.get_cached_doc("Item", item.name)
frappe.db.set_value(
	"UOM Conversion Detail",
	item.uoms[0].name,
	"conversion_factor",
	0,
	update_modified=False,
)
with self.assertRaises(frappe.ValidationError):
	resolve_item_custom_uom(item.name)
```

Use `frappe.db.set_value` for zero and negative factors. Delete only the unique child row through `frappe.db.delete` for the missing-row case. `IntegrationTestCase` rollback restores all direct changes. Do not call `frappe.db.commit()` or force-delete shared data.

- [ ] **Step 3: Run resolver and Item tests**

```bash
cd /workspace/development/frappe-bench
python -m unittest stock_additional.tests.test_uom_resolver
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_item_validation
```

Expected: pure resolver tests pass. Integration tests pass after Task 3 registers the hook. Before registration, invalid-save coverage remains RED.

### Task 3: Add the Scanner, Hook, and Exact Fixture

**Files:**
- Create: `stock_additional/stock_additional/overrides/__init__.py`
- Create: `stock_additional/stock_additional/overrides/barcode_scanner.py`
- Modify: `stock_additional/stock_additional/hooks.py`
- Create: `stock_additional/stock_additional/fixtures/custom_field.json`
- Modify: `stock_additional/stock_additional/tests/test_barcode_scanner.py`
- Modify: `stock_additional/stock_additional/tests/test_hooks.py`

**Interfaces:**
- Active method: `erpnext.stock.utils.scan_barcode`.
- Provider: `stock_additional.overrides.barcode_scanner.custom_scan_barcode`.
- Item hook: `Item.validate` to `stock_additional.uom.validate_item_custom_uom`.
- Fixture: exact `name = Item-custom_default_uom_warehouse`.

- [ ] **Step 1: Implement the scanner**

Create `stock_additional/overrides/barcode_scanner.py`:

```python
import frappe
from erpnext.stock.utils import scan_barcode as original_scan_barcode

from stock_additional.uom import resolve_item_custom_uom


@frappe.whitelist()
def custom_scan_barcode(search_value: str, ctx: dict | str | None = None):
	data = original_scan_barcode(search_value, ctx)
	if not data or not data.get("batch_no") or not data.get("item_code"):
		return data

	resolved = resolve_item_custom_uom(data["item_code"])
	if not resolved:
		return data

	enriched = dict(data)
	enriched["uom"] = resolved.uom
	enriched["conversion_factor"] = resolved.conversion_factor
	return enriched
```

Do not catch `frappe.ValidationError`. Runtime invalid data must stop the scan.

- [ ] **Step 2: Register exact hooks**

Add to `stock_additional/hooks.py`:

```python
required_apps = ["erpnext"]

override_whitelisted_methods = {
	"erpnext.stock.utils.scan_barcode": "stock_additional.overrides.barcode_scanner.custom_scan_barcode",
}

doc_events = {
	"Item": {
		"validate": "stock_additional.uom.validate_item_custom_uom",
	},
}

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["name", "=", "Item-custom_default_uom_warehouse"]],
	},
]
```

Keep the shell `before_install` guard.

- [ ] **Step 3: Create the exact fixture**

Copy only the `Item-custom_default_uom_warehouse` object from bakery's fixture. Preserve every definition value, including `module: null`, `name`, `dt`, `fieldname`, field type, options, label, insert position, and `no_copy`. Fixture ownership comes from the target app's exact-name fixture declaration, not the Custom Field `module` value. Stored Item values remain unchanged.

Do not export by `fieldname` alone.

- [ ] **Step 4: Run targeted tests and verify GREEN**

```bash
cd /workspace/development/frappe-bench
python -m unittest stock_additional.tests.test_uom_resolver
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_barcode_scanner
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_item_validation
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_hooks
```

Expected: unit tests pass. Hook integration remains RED until bakery removes its duplicate provider in Task 5.

- [ ] **Step 5: Add real batch integration coverage**

Port bakery's existing batch test into `stock_additional/tests/test_barcode_scanner.py`. Improve isolation:

- create unique Item and Batch records;
- use `IntegrationTestCase` rollback;
- clear ERPNext's `erpnext:barcode_scan:<value>` cache key per test;
- do not `commit()`;
- do not force-delete shared records;
- test valid factor, empty custom UOM, stock UOM, non-batch passthrough, missing factor, zero factor, and negative factor;
- assert invalid scans return no data because they raise before returning;
- assert the original core result is unchanged with the unit test.

Run:

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_barcode_scanner
```

Expected: PASS.

- [ ] **Step 6: Stop for stock repository commit approval**

Show intended diff and tests. After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/stock_additional
git add stock_additional/hooks.py stock_additional/exceptions.py \
  stock_additional/uom.py stock_additional/overrides \
  stock_additional/fixtures/custom_field.json \
  stock_additional/tests/__init__.py \
  stock_additional/tests/test_uom_resolver.py \
  stock_additional/tests/test_barcode_scanner.py \
  stock_additional/tests/test_item_validation.py \
  stock_additional/tests/test_hooks.py
git diff --cached --name-status
git commit -m "fix: fail closed on invalid barcode UOM"
```

Expected: only target stock paths are staged.

### Task 4: Add Read-Only Stock Preflight

**Files:**
- Create: `stock_additional/stock_additional/migration/__init__.py`
- Create: `stock_additional/stock_additional/migration/preflight.py`
- Create: `stock_additional/stock_additional/tests/test_preflight.py`

**Interfaces:**
- `collect_invalid_custom_uom_items() -> list[dict]` returns stable rows sorted by Item name.
- `collect_custom_field_contract() -> dict` compares the exact database Custom Field with the fixture definition.
- `collect_scanner_providers() -> list[dict]` enumerates every installed app's declaration for the core scanner method.
- `collect_legacy_references() -> list[dict]` returns stable references to unsupported old stock paths.
- `run(phase: Literal["staged_upgrade", "final"] = "final") -> dict` returns the complete stable report and records `phase`.
- `assert_clean(report: dict, phase: str) -> None` raises when any section violates that phase's exact contract.
- `check(phase: Literal["staged_upgrade", "final"] = "final") -> dict` calls `run()`, calls `assert_clean()`, and returns the report for one operational command.
- Preflight writes no database row, file, or log row and commits nothing.

- [ ] **Step 1: Write failing preflight tests**

Create tests for each blocking section:

```python
class TestStockPreflight(IntegrationTestCase):
	def test_invalid_item_blocks_cutover(self):
		report = clean_report()
		report["custom_uom_items"] = {
			"ok": False,
			"invalid": [{"item_code": "ITEM-1", "reason": "non_positive"}],
		}
		with self.assertRaises(frappe.ValidationError):
			preflight.assert_clean(report, phase="final")

	def test_duplicate_provider_blocks_cutover(self):
		report = clean_report()
		report["scanner_hook"]["providers"] = [
			{"app": "bakery_manufacturing", "path": BAKERY_SCANNER},
			{"app": "stock_additional", "path": STOCK_SCANNER},
		]
		report["scanner_hook"]["ok"] = False
		with self.assertRaises(frappe.ValidationError):
			preflight.assert_clean(report, phase="final")

	def test_fixture_definition_mismatch_blocks_cutover(self):
		report = clean_report()
		report["custom_field"]["mismatches"] = {"module": [None, "Stock Additional"]}
		report["custom_field"]["ok"] = False
		with self.assertRaises(frappe.ValidationError):
			preflight.assert_clean(report, phase="final")
```

Also cover wrong effective method, signature mismatch, wrong fixture owner, and each supported legacy-reference DocType.

- [ ] **Step 2: Run and verify RED**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_preflight
```

Expected: FAIL because the preflight module does not exist.

- [ ] **Step 3: Implement bounded custom-UOM reads**

Fetch Items with non-empty `custom_default_uom_warehouse`. Fetch their UOM child rows in one query. Classify in memory. Do not call the database once per Item.

Stable invalid row shape:

```python
{
	"item_code": item.name,
	"stock_uom": item.stock_uom,
	"custom_uom": item.custom_default_uom_warehouse,
	"conversion_factor": factor,
	"reason": "missing" | "non_positive",
}
```

Sort by `item_code`. A custom UOM equal to stock UOM is valid without a matching child row.

- [ ] **Step 4: Implement exact field, fixture, and hook ownership checks**

Phase contracts:

- `staged_upgrade` runs after coordinated source deployment and before model sync. It requires exactly one scanner declaration, the stock path, because that source revision already removed bakery's hook. Bakery's lazy shim may remain importable but must not register.
- `final` requires the same one-provider contract after migration.
- Both phases require valid Item data, exact `module: null` field definition, one target fixture owner, signature compatibility, and zero unsupported references.

Use this report shape with stable key and list ordering:

```python
{
	"custom_uom_items": {"ok": bool, "invalid": list[dict]},
	"custom_field": {
		"ok": bool,
		"name": "Item-custom_default_uom_warehouse",
		"database_exists": bool,
		"mismatches": dict,
		"fixture_owners": list[str],
	},
	"scanner_hook": {
		"ok": bool,
		"method": "erpnext.stock.utils.scan_barcode",
		"providers": list[{"app": str, "path": str}],
		"effective": str,
		"expected": "stock_additional.overrides.barcode_scanner.custom_scan_barcode",
		"signature_matches_core": bool,
	},
	"legacy_references": {"ok": bool, "references": list[dict]},
}
```

Compare exact field properties from bakery's current fixture, including `module: null`. Enumerate hook providers with `frappe.get_hooks(..., app_name=app)` for every installed app. Do not infer uniqueness from aggregate order or only from `frappe.override_whitelisted_method()`.

Inspect exact-name `Server Script`, `Client Script`, and `Scheduled Job Type` content fields for these unsupported paths:

```text
bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode
bakery_manufacturing.overrides.barcode_scanner.resolve_batch_uom
```

The executor also runs a repository reference scan for first-party files because site preflight cannot inspect source files outside database records. Every result includes `kind`, `name`, and `path` or field name. Allow only the one-release bakery shim and documentation that explicitly marks the path deprecated.

- [ ] **Step 5: Prove preflight is read-only and reviewable**

Snapshot `modified` values for all candidate Items, UOM child rows, the Custom Field, and scanned script/job rows. Assert snapshots remain equal. Patch `frappe.db.commit`, `set_value`, `delete`, document `save`, and document `insert` to fail if called.

`run()` returns the report. `check()` validates and returns it. The operational command prints validated JSON to captured stdout:

```bash
bench --site development.localhost execute \
  stock_additional.migration.preflight.check \
  --kwargs '{"phase": "final"}' \
  > "$CLAUDE_JOB_DIR/tmp/stock-preflight.json"
python3 -m json.tool "$CLAUDE_JOB_DIR/tmp/stock-preflight.json" >/dev/null
```

The report stays outside Git. Record its SHA-256 in the execution transcript.

- [ ] **Step 6: Run and verify GREEN**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_preflight
```

Expected: tests pass. A pre-handoff legacy report may describe bakery ownership but cannot pass either cutover phase. `staged_upgrade` starts only after coordinated source deployment removes bakery's hook.

- [ ] **Step 7: Stop for preflight commit approval**

After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/stock_additional
git add stock_additional/migration stock_additional/tests/test_preflight.py
git diff --cached --name-status
git commit -m "feat: add stock ownership preflight"
```

### Task 5: Add the Existing-Site Safety Patch

**Files:**
- Modify: `stock_additional/stock_additional/patches.txt`
- Verify existing scaffold file: `stock_additional/stock_additional/patches/__init__.py`
- Create: `stock_additional/stock_additional/patches/v1_0/__init__.py`
- Create: `stock_additional/stock_additional/patches/v1_0/assert_stock_cutover_ready.py`
- Create: `stock_additional/stock_additional/tests/test_stock_cutover_patch.py`

**Interfaces:**
- Patch entry: `stock_additional.patches.v1_0.assert_stock_cutover_ready` under `[pre_model_sync]`.
- `execute() -> None` runs stock preflight against the staged-upgrade phase contract.
- Patch is read-only and idempotent.

- [ ] **Step 1: Write failing patch tests**

```python
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from stock_additional.patches.v1_0 import assert_stock_cutover_ready


class TestStockCutoverPatch(IntegrationTestCase):
	@patch("stock_additional.patches.v1_0.assert_stock_cutover_ready.preflight.assert_clean")
	@patch(
		"stock_additional.patches.v1_0.assert_stock_cutover_ready.preflight.run",
		return_value={"phase": "staged_upgrade"},
	)
	def test_execute_checks_staged_upgrade_contract(self, run, assert_clean):
		assert_stock_cutover_ready.execute()
		run.assert_called_once_with(phase="staged_upgrade")
		assert_clean.assert_called_once_with(
			run.return_value,
			phase="staged_upgrade",
		)

	@patch(
		"stock_additional.patches.v1_0.assert_stock_cutover_ready.preflight.run",
		side_effect=frappe.ValidationError("blocked"),
	)
	def test_execute_propagates_preflight_failure(self, _run):
		with self.assertRaisesRegex(frappe.ValidationError, "blocked"):
			assert_stock_cutover_ready.execute()
```

Also assert `patches.txt` contains exactly:

```text
[pre_model_sync]
stock_additional.patches.v1_0.assert_stock_cutover_ready

[post_model_sync]
```

- [ ] **Step 2: Run and verify RED**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_stock_cutover_patch
```

Expected: FAIL because patch module does not exist.

- [ ] **Step 3: Implement the read-only assertion patch**

```python
from stock_additional.migration import preflight


def execute() -> None:
	report = preflight.run(phase="staged_upgrade")
	preflight.assert_clean(report, phase="staged_upgrade")
```

The staged-upgrade contract runs only after coordinated source deployment. It requires stock as the sole registered and effective scanner provider. Bakery's old Python path may exist only as an unregistered lazy shim. It also blocks invalid Item data, a mismatched field, an unexpected fixture owner, an unsupported legacy reference, a signature mismatch, or missing target source.

Fresh install does not execute this patch. Its safety comes from exact target source, fixture sync, `before_install`, and fresh-install tests. Do not add `after_migrate` or a data-writing patch.

- [ ] **Step 4: Run and verify GREEN**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_stock_cutover_patch
```

Expected: PASS. Run `execute()` twice in one test and assert identical reports and no writes.

- [ ] **Step 5: Stop for patch commit approval**

After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/stock_additional
git add stock_additional/patches.txt stock_additional/patches \
  stock_additional/tests/test_stock_cutover_patch.py
git diff --cached --name-status
git commit -m "fix: block unsafe stock ownership cutovers"
```

### Task 6: Remove Bakery Stock Ownership and Keep a Lazy Shim

**Files:**
- Modify: `bakery_manufacturing/bakery_manufacturing/hooks.py`
- Modify: `bakery_manufacturing/bakery_manufacturing/fixtures/custom_field.json`
- Modify: `bakery_manufacturing/bakery_manufacturing/overrides/barcode_scanner.py`
- Remove: `bakery_manufacturing/bakery_manufacturing/tests/test_barcode_scanner.py`
- Modify: `bakery_manufacturing/README.md`
- Do not modify: `bakery_manufacturing/bakery_manufacturing/public/js/bakery_manufacturing.bundle.js`
- Do not modify: `bakery_manufacturing/bakery_manufacturing/tests/test_desk_sidebar.py`

**Interfaces:**
- Bakery no longer registers `erpnext.stock.utils.scan_barcode`.
- Bakery no longer declares `Item-custom_default_uom_warehouse` as a fixture.
- Legacy imports may call `bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode` for one release.
- Shim imports `stock_additional` lazily inside the function.

- [ ] **Step 1: Extend exact-one-provider tests and verify RED**

Add to `stock_additional/tests/test_hooks.py`:

```python
def test_exactly_one_scanner_provider(self):
	providers = frappe.get_hooks("override_whitelisted_methods").get(
		SCANNER_METHOD,
		[],
	)
	self.assertEqual(providers, [STOCK_SCANNER])
	self.assertEqual(frappe.override_whitelisted_method(SCANNER_METHOD), STOCK_SCANNER)
```

Run:

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_hooks
```

Expected: FAIL because bakery and stock both register the scanner.

- [ ] **Step 2: Remove only bakery's stock hook and fixture object**

In bakery `hooks.py`, remove only the scanner override entry. Preserve the past-order entry until selling cutover. Replace the broad fixture filter with exact walk-in names:

```python
required_apps = ["erpnext"]

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"POS Invoice-custom_walk_in_customer_name",
					"Sales Invoice-custom_walk_in_customer_name",
				],
			]
		],
	},
]
```

In bakery `fixtures/custom_field.json`, remove only the Item object. Preserve both walk-in objects byte-for-byte. Add a test that bakery's fixture hook no longer selects `Item-custom_default_uom_warehouse`.

- [ ] **Step 3: Replace barcode business logic with a lazy shim**

Use:

```python
def custom_scan_barcode(search_value: str, ctx: dict | str | None = None):
	try:
		from stock_additional.overrides.barcode_scanner import (
			custom_scan_barcode as implementation,
		)
	except ImportError as error:
		raise ImportError("stock_additional is required for the legacy bakery barcode path") from error

	return implementation(search_value, ctx)
```

Do not decorate the shim with `@frappe.whitelist()`. Do not register it as a hook.

- [ ] **Step 4: Remove moved bakery tests**

Delete bakery's barcode test because target tests now own behavior. Do not move or delete manufacturing tests.

- [ ] **Step 5: Verify protected bakery paths remain byte-identical**

Compare protected paths with the global baseline:

```bash
cd /workspace/development/frappe-bench/apps/bakery_manufacturing
shasum -a 256 bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git diff --numstat -- bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
```

Expected: bundle hash remains `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8`, numstat remains `14 0`, and sidebar test remains untracked and unstaged.

- [ ] **Step 6: Run exact provider, shim, and bakery tests**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost clear-cache
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_hooks
bench --site development.localhost run-tests --app bakery_manufacturing
```

Expected: stock is the only provider. Legacy shim delegates when called. Bakery manufacturing tests pass.

- [ ] **Step 7: Stop for bakery commit approval**

After explicit approval:

```bash
cd /workspace/development/frappe-bench/apps/bakery_manufacturing
git add bakery_manufacturing/hooks.py bakery_manufacturing/fixtures/custom_field.json \
  bakery_manufacturing/overrides/barcode_scanner.py \
  bakery_manufacturing/tests/test_barcode_scanner.py README.md
git diff --cached --name-status
git commit -m "refactor: move barcode ownership to stock additional"
```

Do not use `git add .` or `git add -A`.

### Task 7: Update `roti_ropi_pos` Dependency and Scanner Ownership

**Files:**
- Modify: `roti_ropi_pos/roti_ropi_pos/hooks.py`
- Modify: `roti_ropi_pos/roti_ropi_pos/tests/test_catalog.py`
- Modify: `roti_ropi_pos/roti_ropi_pos/tests/test_source_contracts.py`
- Modify: `roti_ropi_pos/roti_ropi_pos/tests/test_mobile_pos_flow.py`
- Modify: `roti_ropi_pos/docs/mobile-pos/architecture.md`
- Modify: `roti_ropi_pos/docs/mobile-pos/integration-boundaries.md`
- Modify: `roti_ropi_pos/docs/mobile-pos/testing-strategy.md`
- Modify: `roti_ropi_pos/docs/mobile-pos/implementation-plan.md`
- Modify: `roti_ropi_pos/README.md`
- Modify: `roti_ropi_pos/AGENTS.md`
- Do not modify: `roti_ropi_pos/roti_ropi_pos/mobile_pos/catalog.py`
- Do not modify: `roti_ropi_pos/docs/mobile-pos/api-contract.md`
- Do not modify: `roti_ropi_pos/roti_ropi_pos/tests/test_sales.py`

**Interfaces:**
- Stock-phase dependency list: `required_apps = ["erpnext", "stock_additional"]`. Selling cutover adds `selling_additional` only after its target fixture and hooks exist.
- Effective scanner path: `stock_additional.overrides.barcode_scanner.custom_scan_barcode`.
- Public Mobile POS success and error contracts remain unchanged.
- Roti keeps dynamic hook resolution and does not import stock resolver, scanner, or exception types.

- [ ] **Step 1: Write failing source-contract assertions**

Change the effective-scanner assertion to:

```python
self.assertEqual(
	frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode"),
	"stock_additional.overrides.barcode_scanner.custom_scan_barcode",
)
```

Retarget scanner delegation and signature tests from bakery to stock. Add:

```python
def test_roti_dependencies_use_extracted_apps(self):
	from roti_ropi_pos import hooks

	self.assertEqual(
		hooks.required_apps,
		["erpnext", "stock_additional"],
	)
```

Keep existing tests that prove `scan_value()` dynamically calls the effective method. Add one regression test where the scanner raises `InvalidCustomUOMError`. Build a local profile `SimpleNamespace` and patch `require_doc_permission` using the existing `test_catalog.py` pattern. Assert the error propagates as native `frappe.ValidationError` and transport returns HTTP 417, matching `ValidationError.http_status_code`. Do not add a `MobilePOSAPIError` mapping, new code, or new details shape.

Retarget every bakery-pinned source contract in `TestBarcodeOverride` to `stock_additional.overrides.barcode_scanner`. Assert stock's app-specific hook map owns `SCANNER_METHOD`, stock delegates to core, signatures match, and effective dispatch resolves to stock. Rename stale test labels and comments in `test_catalog.py` and `test_mobile_pos_flow.py` that still say bakery.

- [ ] **Step 2: Run and verify RED**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module roti_ropi_pos.tests.test_catalog
bench --site development.localhost run-tests \
  --module roti_ropi_pos.tests.test_source_contracts
```

Expected: ownership and dependency assertions fail before coordinated source handoff.

- [ ] **Step 3: Update dependency ownership only**

Set in `roti_ropi_pos/hooks.py`:

```python
required_apps = ["erpnext", "stock_additional"]
```

Do not change `mobile_pos/catalog.py`. Its current dynamic lookup is the correct boundary. `InvalidCustomUOMError` fails closed by raising before scan data returns. Existing Frappe handling uses the exception's native HTTP status. Because this type subclasses `frappe.ValidationError`, transport status is HTTP 417. This preserves the approved v1 contract and avoids inventing `ITEM_UOM_CONFIGURATION_INVALID`.

- [ ] **Step 4: Update ownership documentation without changing API contracts**

Update architecture, integration boundaries, testing strategy, implementation plan, README, and AGENTS:

- `stock_additional` owns Item custom UOM and scanner behavior;
- `selling_additional` owns Price Group and walk-in selling behavior;
- `roti_ropi_pos` consumes effective hooks from both apps;
- replace bakery scanner and Price Group source paths with target paths;
- keep bakery only for manufacturing behavior and temporary documented shims;
- use CodeGraph for code navigation in new text.

Do not change `api-contract.md`, DTO fields, warning codes, error codes, or status mappings.

- [ ] **Step 5: Run Roti tests**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module roti_ropi_pos.tests.test_catalog
bench --site development.localhost run-tests \
  --module roti_ropi_pos.tests.test_source_contracts
bench --site development.localhost run-tests --app roti_ropi_pos
```

Expected: all pass. Valid scan DTOs stay unchanged. Invalid custom-UOM configuration returns no scan payload and follows native Frappe HTTP 417 validation handling.

- [ ] **Step 6: Stop for Roti commit approval**

After explicit approval, stage only these paths:

```bash
cd /workspace/development/frappe-bench/apps/roti_ropi_pos
git add roti_ropi_pos/hooks.py \
  roti_ropi_pos/tests/test_catalog.py roti_ropi_pos/tests/test_source_contracts.py \
  roti_ropi_pos/tests/test_mobile_pos_flow.py \
  docs/mobile-pos/architecture.md docs/mobile-pos/integration-boundaries.md \
  docs/mobile-pos/testing-strategy.md docs/mobile-pos/implementation-plan.md \
  README.md AGENTS.md
git diff --cached --name-status
git commit -m "refactor: consume extracted stock ownership"
```

Confirm `mobile_pos/catalog.py`, `docs/mobile-pos/api-contract.md`, `tests/test_sales.py`, and unrelated documentation are not staged.

### Task 8: Run Stock Cutover Gates

**Files:**
- Verify: all intended stock, bakery, and Roti paths
- Verify only: ERPNext and Frappe source trees

**Interfaces:**
- Consumes: coordinated source revisions with all apps installed.
- Produces: evidence for the operational cutover plan.

- [ ] **Step 1: Run read-only preflight**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost execute \
  stock_additional.migration.preflight.check \
  --kwargs '{"phase": "final"}'
```

Expected: stable final report. Pass it to `assert_clean(..., phase="final")`. Any invalid custom-UOM Item or ownership mismatch blocks migration.

- [ ] **Step 2: Run full app and ERPNext scanner suites**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests --app stock_additional
bench --site development.localhost run-tests --app bakery_manufacturing
bench --site development.localhost run-tests --app roti_ropi_pos
bench --site development.localhost run-tests \
  --module erpnext.stock.tests.test_utils
```

Expected: all pass.

- [ ] **Step 3: Run static checks**

```bash
cd /workspace/development/frappe-bench/apps/stock_additional && pre-commit run --all-files
cd /workspace/development/frappe-bench/apps/bakery_manufacturing && pre-commit run --all-files
cd /workspace/development/frappe-bench/apps/roti_ropi_pos && pre-commit run --all-files
```

Expected: all configured checks pass. If host lacks pre-commit, run from the container environment that owns app dependencies. Report a missing tool as failure, not success.

- [ ] **Step 4: Verify exact ownership and no core source writes**

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-tests \
  --module stock_additional.tests.test_hooks
git -C apps/erpnext status --short
git -C apps/frappe status --short
```

Expected: one scanner provider. No new ERPNext or Frappe source diff.

- [ ] **Step 5: Run manual batch and Mobile POS smoke tests**

On existing `development.localhost`, using rollback-isolated fixtures only:

1. Scan a batch with a valid custom UOM. Confirm UOM and positive factor.
2. Use an invalid legacy record created through a test-only database fixture. Confirm scan raises and returns no unsafe mapping.
3. Confirm the transaction row stays unchanged after rejection.
4. Run Mobile POS search, scan, quote, sale, return, and closing checks.

Expected: barcode fails closed. Valid scan DTOs remain unchanged. Invalid custom-UOM configuration returns no scan payload and follows native Frappe HTTP 417 validation handling.

- [ ] **Step 6: Request independent review**

Use `superpowers:requesting-code-review` across all intended diffs. Fix confirmed Critical or Important findings. Rerun every affected test.

- [ ] **Step 7: Verify all three installation scenarios**

Use separately approved disposable sites or restored scratch sites only. Do not run these destructive lifecycle scenarios on `development.localhost`. Each scenario needs separate site-creation and deletion approval from the coordinated rollout plan.

1. **Fresh install:** install `stock_additional` directly without bakery metadata. Run migration, exact fixture, hook, scanner, and invalid-UOM tests. Confirm cutover patch is marked complete by fresh-install behavior and was not executed.
2. **Staged upgrade:** start with bakery plus shell `stock_additional`, then deploy coordinated target sources. Run one normal migrate. Confirm pre-model assertion passes, bakery provider disappears, and stock becomes the sole effective provider.
3. **Populated upgrade:** restore representative Items, valid and intentionally invalid UOM rows, batches, custom field, and database script references. Confirm preflight blocks invalid state without writes. Repair only approved fixture data, rerun, then confirm valid values and batch behavior stay unchanged.

For the populated scenario, record stable preflight hashes before and after approved remediation. Do not include Item names from an active site in Git.

- [ ] **Step 8: Prove patch idempotency**

On scratch state after a successful normal migrate:

```bash
cd /workspace/development/frappe-bench
bench --site development.localhost run-patch \
  stock_additional.patches.v1_0.assert_stock_cutover_ready --force
bench --site development.localhost run-patch \
  stock_additional.patches.v1_0.assert_stock_cutover_ready --force
```

Expected: both runs pass with identical stable preflight output and database checksums. A second normal migrate only proves Patch Log skip behavior and is not accepted as idempotency evidence.

- [ ] **Step 9: Stop before push or deployment**

Report repository SHAs, intended diffs, scenario results, tests, preflight, forced-patch evidence, static checks, and smoke results. Push and deployment belong to the coordinated rollout plan and need explicit approval.
