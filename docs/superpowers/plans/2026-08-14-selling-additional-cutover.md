# Selling Additional Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transfer Price Group, walk-in customer, past-order, and navigation ownership from `bakery_manufacturing` to `selling_additional`, and fix the confirmed Price Group, walk-in asset, and sidebar defects during the transfer.

**Architecture:** Explicit ownership Custom Fields replace the `PG-<name>` naming convention as the authority. One Price Group save locks its own row, all desired and currently owned POS Profiles in sorted order, its managed Price List, and existing managed Item Prices before checking ownership or mutating data. One `pre_model_sync` patch validates legacy state and moves exactly three DocType module values. One `post_model_sync` adoption patch validates the full post-sync state before marking ownership, storing operator-approved previous price lists, and deleting the exact legacy sidebar child row. Desk POS behavior moves from a global timer and prototype patches to one page-specific asset using delegated events and a scoped `MutationObserver`.

**Tech Stack:** Python 3.14, Frappe and ERPNext v16, MariaDB, unittest/Frappe `IntegrationTestCase`, Ruff, ESLint, pre-commit.

**Spec:** `docs/superpowers/specs/2026-08-14-app-ownership-extraction-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-08-14-additional-app-shells.md` first. The `selling_additional` shell tag must be installed on the target site before this release deploys.
- Complete `docs/superpowers/plans/2026-08-14-stock-additional-cutover.md` before coordinated bakery handoff in Task 10. Stock phase sets `required_apps = ["erpnext", "stock_additional"]`. Selling Task 11 adds `selling_additional` only after its target fixture and hooks exist.
- Use the dedicated site `selling-cutover.localhost` for every implementation test, migrate, and forced patch run. Run bench commands inside `/workspace/development/frappe-bench`. Pass `--site selling-cutover.localhost` to every site command. Keep `allow_tests = true`, keep the scheduler disabled, use rollback-isolated fixtures, and perform no destructive shared-data cleanup.
  This constraint supersedes the original "use existing `development.localhost`" wording, which contradicted the spec. Spec §17 (`spec:578`) requires "Use a dedicated test site. Do not use the active development site." The spec is the authority this plan argues from, so the spec wins. `development.localhost` holds the operator's real business data while Task 1 Step 5 mandates *committed* fixtures and committed deletes and Task 12 Step 5 force-runs patches — none of which may touch that site. `development.localhost` may be read for comparison only, never written.
- Keep the DocType names `Price Group`, `Price Group Item`, `Price Group Outlet` and every table, field, and business row unchanged.
- Keep the generated Price List naming convention `PG-<price_group_name>`.
- Never call `frappe.delete_doc(..., force=True)` in Price Group lifecycle code.
- Never call `WorkspaceSidebar.save()` in a patch, and never replace a sidebar parent's child table.
- Never save a Price List document when only Item Price rows must change. `PriceList.on_update` runs a blanket `UPDATE tabItem Price SET currency=..., buying=..., selling=...` for the whole price list and can set `Selling Settings.selling_price_list` — verified in `apps/erpnext/erpnext/stock/doctype/price_list/price_list.py`.
- The bakery bundle has one tracked walk-in import followed by 14 uncommitted prototype lines. The cutover may remove only that tracked import. The 14-line dirty suffix must remain byte-identical with SHA-256 `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`.
- Never modify or stage `bakery_manufacturing/bakery_manufacturing/tests/test_desk_sidebar.py`.
- Never edit `apps/frappe` or `apps/erpnext` except the one separately approved, path-scoped restore of `erpnext/workspace_sidebar/selling.json` in Task 10.
- Do not touch `apps/erpnext/banking/yarn.lock`, `apps/erpnext/.codegraph/`, or `apps/erpnext/graphify-out/`.
- Do not commit, push, tag, migrate an active site, or deploy without separate explicit approval per phase.

---

### Task 1: Pin Price Group Lifecycle Contracts as Failing Tests

**Files:**
- Create: `selling_additional/selling_additional/tests/__init__.py`
- Create: `selling_additional/selling_additional/tests/test_price_group_lifecycle.py`
- Create: `selling_additional/selling_additional/tests/test_price_group_concurrency.py`
- Create: `selling_additional/selling_additional/tests/test_hooks.py`
- Create: `selling_additional/selling_additional/tests/helpers.py`

**Interfaces:**
- Produces `selling_additional.selling_additional.doctype.price_group.price_group.PriceGroup` with `validate()`, `on_update()`, `on_trash()`.
- Produces ownership field constants in `selling_additional/ownership.py`. Three of the four names originally listed held the identical literal `"custom_selling_additional_price_group"`; the literal is now defined once and the other names alias it, so no future edit can change one and miss the others:
  - `OWNER_FIELD = "custom_selling_additional_price_group"` — the single definition
  - `PRICE_LIST_OWNER_FIELD = ITEM_PRICE_OWNER_FIELD = PROFILE_OWNER_FIELD = OWNER_FIELD` — per-DocType names retained for call-site readability
  - `PROFILE_PREVIOUS_PRICE_LIST_FIELD = "custom_selling_additional_previous_price_list"` — a genuinely different field
- Consumes ERPNext `Price List`, `Item Price`, `POS Profile` as verified in installed source.

- [ ] **Step 1: Verify the installed ERPNext contracts this task depends on**

Read and record:

- `apps/erpnext/erpnext/stock/doctype/price_list/price_list.py` — `on_update` calls `update_item_price()` (blanket SQL over all Item Prices) and `set_default_if_missing()` (may write `Selling Settings.selling_price_list`).
- `apps/erpnext/erpnext/stock/doctype/item_price/item_price.py` — `update_price_list_details()` throws when the Price List is missing or `enabled = 0`; `check_duplicates()` scopes uniqueness by `item_code, price_list, uom, valid_from, valid_upto, customer, supplier, batch_no, packing_unit`; `validate_item()` requires a `UOM Conversion Detail` row for a non-empty `uom`.
- `apps/erpnext/erpnext/accounts/doctype/pos_profile/pos_profile.py` — `validate_payment_methods()` requires at least one payment row with exactly one default; `validate_disabled()` blocks disabling with an open `POS Opening Entry`.

Stop and report if any of these differ.

- [ ] **Step 2: Write shared test helpers**

Create `selling_additional/selling_additional/tests/helpers.py` providing:

```python
def make_test_item(suffix: str, stock_uom: str = "Nos") -> str: ...
def make_test_warehouse(suffix: str, company: str) -> str: ...
def make_test_pos_profile(suffix: str, company: str, warehouse: str, *, payments=None) -> str: ...
def make_price_group(name: str, *, items, outlets=(), enabled=1, currency="IDR"): ...
def manual_item_price(item_code: str, price_list: str, **overrides) -> str: ...
```

`make_test_pos_profile` MUST populate the `payments` child table. `POSProfile.validate_payment_methods` (`apps/erpnext/erpnext/accounts/doctype/pos_profile/pos_profile.py:173-183`) throws both when `payments` is empty and when the rows do not carry exactly one `default = 1`. When `payments` is `None` the helper resolves one enabled `Mode of Payment` for the company from the site and inserts a single row with `default = 1`; it never hard-codes a mode name, because mode availability differs per site. Without this every profile fixture in Tasks 1, 3, 5, and 12 would throw before reaching the behavior under test.

Every ordinary helper uses a unique suffix and relies on `IntegrationTestCase` rollback. It never commits or uses `force=True`. Only the dedicated multi-connection test may commit isolated fixtures, with explicit committed cleanup in `addCleanup()`. This replaces bakery's shared-site `tearDown` plus `commit` plus `force=True` pattern.

**No hard-coded master data, currency included.** Resolve the company once with a stable `order_by` (many companies may exist on a populated site) and derive currency from that company's `default_currency` — never a literal `"IDR"` in a helper default, a POS Profile fixture, an Item Price fallback, or a lifecycle assertion. Assert the managed Price List's currency equals the resolved company currency rather than a literal. This is the same failure shape as the Phase 1 `"Nos"`/`"Products"` bug that broke every test on a fresh site.

Two further fixture rules:

- `custom_uom()` must assert it resolved a DIFFERENT record than `base_uom()`. A bare `frappe.db.get_value("UOM", {}, "name")` fallback can return the same UOM for both, silently collapsing every UOM-change test into a no-op.
- A helper must never mutate shared master data. Do not append a `Mode of Payment Account` row to an existing shared `Mode of Payment` and save it — on a site where no enabled mode has an account for the company that permanently edits shared data, and the concurrency test would then commit the edit. Resolve an already-usable mode, or create a test-owned mode registered for cleanup, or fail the fixture with a clear message.

- [ ] **Step 3: Write the failing enabled-lifecycle tests**

Create `test_price_group_lifecycle.py` with an `IntegrationTestCase` covering, in this order:

1. `test_enable_creates_marked_price_list` — save an enabled group; assert `Price List` `PG-<name>` exists, `selling = 1`, `buying = 0`, `enabled = 1`, currency matches, and owner marker equals the group.
2. `test_new_managed_price_list_does_not_become_global_default` — clear `Selling Settings.selling_price_list`, create the group, and assert the setting remains empty.
3. `test_managed_item_price_identity_is_item_and_uom` — two DIFFERENT items whose stock UOMs differ; assert two marked rows, each carrying its own item's resolved UOM, and assert the marked identity pair `(item_code, uom)` is distinct per row.

   Do NOT pass `uom` on the child rows. Passing it bypasses `_set_uom`'s derive-from-stock-UOM path, which is the behavior spec §8.6 fixes. Omit it and assert each resulting row's UOM equals `frappe.db.get_value("Item", item, "stock_uom")`.

   The original wording said "two rows, same item, different UOM". That test is unwritable and was removed: spec §8.6 (`spec:249-252`) fixes managed identity at `(item_code, uom)` with the UOM *derived* from the Item's stock UOM, so one Price Group cannot hold two UOMs for one item, and Task 3's ported duplicate-item rule rejects the second child outright. Test 16's `test_duplicate_item_is_rejected` already covers that rejection. The spec is the authority, so the test was wrong, not the design. `test_uom_change_creates_new_and_removes_old_managed_row` (test 9) covers identity moving when a UOM changes.
4. `test_rate_change_updates_managed_row_only` — change one item's rate; assert every OTHER row on the SAME managed Price List is byte-identical, `modified` included.

   Snapshot, before the save, `(name, price_list_rate, modified)` of (a) the marked row for an item whose rate is NOT changing and (b) a manual unmarked row on that same managed list. After the save, assert the changed item's marked row carries the new rate and both snapshot tuples are unchanged.

   Do NOT assert on a different Price Group's price list. The defect this test exists to catch is `PriceList.on_update` → `update_item_price()`, which runs `update tabItem Price set … modified=NOW() where price_list=%s` over every row of ITS OWN list (`price_list.py:47-52`) — measured moving both rows of a list on a no-op `Price List.save()`. A controller scopes its writes to its own list either way, so an assertion aimed at an unrelated list cannot fail and pins nothing.

5. `test_removed_item_deletes_only_marked_row` — remove one item; assert only its MARKED row is gone.

   The fixture must contain a manual unmarked row and one scoped row (e.g. `customer=`) on the same managed list, or "only marked" is untested. Filter the gone-row assertion by `{"price_list": pl_name, OWNER_FIELD: pg.name, "item_code": removed_item}`, and assert the manual and scoped rows still exist with unchanged `modified`. Without the marker filter this test passes against bakery's orphan sweep (`price_group.py:104-115`), which deletes by `price_list` with no ownership check and `force=True` — exactly the behavior the cutover removes.
6. `test_manual_unmarked_price_survives` — save with a manual unmarked row on the same list; assert it survives.
7. `test_scoped_and_null_uom_prices_survive` — customer-, batch-, date-, and packing-unit-scoped rows remain unmarked and unchanged, each with `(price_list_rate, modified, OWNER_FIELD)` snapshotted before the save and compared after. Asserting mere existence is not enough: a controller that rewrites an unmarked row still leaves it existing.

   **The supplier case is dropped — it is unwritable.** `ItemPrice.before_save` nulls `supplier` whenever `selling and not buying` (verified at `item_price.py:151-155`), and every managed list is `selling=1, buying=0`. A supplier-scoped row on a managed list cannot exist, so the original wording was wrong on that one case. The remaining four are all real fields `check_duplicates` scopes by (`item_price.py:87-112`).

   The batch case needs an item inserted with `has_batch_no: 1, is_stock_item: 1` — `Batch.item_has_batch_enabled` throws otherwise (`batch/batch.py:154-156`), so a generic test item cannot carry a batch.

   The NULL-UOM row cannot be created through the Document API: `Item Price.uom` carries `reqd: 1` (verified in `apps/erpnext/erpnext/stock/doctype/item_price/item_price.json`), so `insert()` raises `MandatoryError`. Legacy sites nevertheless hold such rows, and Task 7 Step 4 must classify them, so the case stays — constructed the only way it can be: insert a valid row, then null the column directly with

   ```python
   frappe.db.set_value("Item Price", name, "uom", None, update_modified=False)
   ```

   `update_modified=False` keeps the row's `modified` value usable as an untouched-by-the-controller baseline. That seed row must be scoped (a distinct `valid_from`, or a different item) or it collides with the managed row on `(item_code, price_list, uom)` and `check_duplicates` raises `ItemPriceDuplicateItem` before the UOM can be nulled. This direct-SQL construction is a test-only device for reproducing legacy state; production code never writes a NULL UOM.
8. `test_invalid_item_uom_fails_before_mutation` — a UOM that EXISTS but has no `UOM Conversion Detail` row on that Item raises, while Price List, Item Prices, and profiles remain unchanged.

   Use a real second UOM resolved from the site, never a nonexistent name. A nonexistent UOM raises `frappe.LinkValidationError` from `Document._validate_links()` BEFORE `run_before_save_methods()`, which never reaches the rule under test — and since `LinkValidationError` subclasses `ValidationError`, a bare `assertRaises(frappe.ValidationError)` swallows the difference. The contract here is `ItemPrice.validate_item` (`item_price.py:55-58`), which throws mid-mutation AFTER the Price List already exists; that is precisely what "fails before mutation" must prove. Assert with `assertRaisesRegex` against the controller's own message text, and snapshot `selling_price_list`, `PROFILE_OWNER_FIELD`, and the full `(name, price_list_rate, modified)` set of the list's Item Prices before, comparing all of it after.
9. `test_uom_change_creates_new_and_removes_old_managed_row` — add required conversion, change UOM, and assert marked identity moves.
10. `test_outlet_claim_marks_profile_and_saves_previous` — assert current list is captured once before claim.
11. `test_reclaim_does_not_overwrite_stored_previous` — a second save retains the original previous list. Also assert `PROFILE_OWNER_FIELD` still equals the group after the second save; retaining the previous list while losing the marker is a different bug that this test would otherwise miss.
12. `test_outlet_removal_restores_owned_profile` — remove outlet and assert restoration plus marker clear.
13. `test_cross_group_claim_is_rejected` — group B cannot overwrite group A.
14. `test_no_pos_profile_sets_outlet_status_without_throwing` — preserve the existing `No POS Profile` status behavior. Assert the status FROM THE DATABASE: `frappe.db.get_value("Price Group Outlet", pg.outlets[0].name, "status")`, and assert `pos_profile` is empty. Reading `pg.outlets[0].status` off the in-memory object passes against a controller that sets the attribute and never persists it — bakery persists it with a separate `frappe.db.set_value` precisely because a normal save would recurse (`price_group.py:162-168`).
15. `test_warehouse_company_mismatch_is_rejected`, `test_duplicate_item_is_rejected`, `test_non_positive_rate_is_rejected`, and `test_duplicate_outlet_is_rejected` — port bakery validations. These four may be GREEN from the start; they pin behavior the cutover preserves unchanged, and each traces to a real controller throw (`price_group.py:26-30`, `:36-40`). Assert with `assertRaisesRegex` against each rule's own message so an unrelated core error cannot satisfy them.

    For `test_warehouse_company_mismatch_is_rejected`, resolve a SECOND existing company from the site (create-if-missing) and pair its warehouse with the first company. A nonexistent company name raises `frappe.LinkValidationError` from `_validate_links()` before the ported rule at `price_group.py:43-49` ever runs, and because that subclasses `ValidationError` a bare `assertRaises` cannot tell the two apart.

- [ ] **Step 4: Write the failing disable and delete tests**

In the same module:

16. `test_disable_restores_profiles_and_clears_markers`.
17. `test_disable_disables_price_list_and_skips_item_price_writes` — assert every marked Item Price value and `modified` timestamp stays unchanged. Note when this fails that `modified` may move BACKWARD, not forward: `update_item_price`'s `modified=NOW()` uses the DB server timezone while Frappe writes `modified` in site-local time. The equality assertion is still the right one — say in the failure message that any change in either direction means a Price List save stamped the row.
18. `test_reenable_after_disable_restores_managed_prices` — the RETAINED rows become active again, not re-created ones. Snapshot `(name, price_list_rate, modified)` of the marked row before disable; after re-enable assert the same `name`, the same `price_list_rate`, and `OWNER_FIELD` still equal to the group. Also assert the row still existed WHILE disabled, between the two saves — that is what makes the skip-Item-Price-writes path observable. Asserting only that `enabled == 1` and some row exists passes against a controller that deletes on disable and re-creates on re-enable, which spec §8.4 step 4 forbids.
19. `test_delete_restores_profiles_and_keeps_price_list` — keep disabled Price List, delete only marked rows, and preserve manual, scoped, and NULL-UOM rows.
20. `test_delete_keeps_price_list_and_preserves_unmarked_rows` — the behavioral no-force test. Spec §8.5 (`spec:232-246`) requires the delete to SUCCEED: restore profiles, delete only marked Item Prices, clear the Price List marker, disable the Price List, and KEEP the Price List record. So assert success, not a raise:

    - `frappe.db.exists("Price List", pl_name)` is truthy and `enabled == 0`;
    - a manual unmarked Item Price on that same managed list still exists, its `price_list` still resolves, and its `(price_list_rate, modified)` are unchanged;
    - `frappe.get_all("Item Price", {"price_list": pl_name, OWNER_FIELD: pg.name})` is empty.

    The Price List IS the link the constraint protects — `Item Price.price_list` is a reqd Link to it, so a `force=True` Price List delete is exactly what strands history (Verified Caveat 9). Do NOT write this test as `assertRaises`. An earlier draft said the delete may "either succeed without orphaning the link or raise a `LinkExistsError`-family error"; that either/or was wrong, because spec §8.5 mandates the success branch. A test asserting a raise can never go green against a correct controller. There is also nothing else to strand: no `DocField` or `Custom Field` in any installed app is a Link to `Item Price`.

    Keep the grep as a second, clearly-labelled source-contract test, `test_controller_source_has_no_force_delete`. It is cheap and catches a reintroduction, but it must not be the only evidence — asserting on source text is not asserting on behavior. Walk the whole `doctype/price_group/` package and `ownership.py`, not one module, or a `force=True` moved into a sibling helper escapes it.
21. `test_delete_fails_before_mutation_when_profile_owned_by_other_group` — all snapshots remain unchanged.

- [ ] **Step 5: Write the failing lock-order and concurrency tests**

Create `test_price_group_concurrency.py`:

- `test_lock_order_covers_current_and_desired_profiles` — record every `for_update=True` read and assert the FULL sequence as one list, not a prefix:

  ```python
  expected = (
    [("Price Group", pg.name)]
    + sorted([("POS Profile", pos1), ("POS Profile", pos2)])
    + [("Price List", pl_name)]
    + [("Item Price", n) for n in sorted(managed_ip_names)]
  )
  self.assertEqual(lock_log, expected)
  ```

  Asserting `len(lock_log) >= 3` plus `lock_log[0] == "Price Group"` plus "profile locks are sorted" is not enough: with one profile in the log the sort assertion is trivially true, so an implementation that locks the DESIRED profile and forgets the CURRENTLY OWNED one passes — the exact defect the test's name claims to cover. The fixture must therefore set up one currently-owned profile being dropped and one new profile being claimed.

  Normalize the logged row name to a string. `frappe.db.get_value("Price List", {"name": x}, …, for_update=True)` passes a dict, and sorting tuples containing dicts raises `TypeError`. Also state in the failure message that the probe only observes `frappe.db.get_value` — a lock taken via `frappe.qb(...).for_update()` logs nothing and would be reported as "no locks", which is a limitation of the probe, not proof of a missing lock.

- `test_ownership_checked_after_all_locks` — use an ordered call log. Assert no Price List, Item Price, or POS Profile ownership value is read before its row lock.

  Two floor assertions are mandatory, or the test is vacuous: `assertTrue(any(kind == "LOCK" for kind, _ in events), msg=...)` and the same for the ownership-read kind. Without them an empty event log makes the verification loop iterate zero times and the test passes against an implementation that locks nothing and checks nothing.

  Key the "already locked" set on `(doctype, name)`, not on doctype alone — locking `POS Profile A` then reading ownership of `POS Profile B` must fail. Match the ownership fieldname against the whole read, allowing for list form: `OWNER_FIELD in (fieldname if isinstance(fieldname, list | tuple) else [fieldname])`, and track `PROFILE_PREVIOUS_PRICE_LIST_FIELD` too. Comparing against `[OWNER_FIELD, PROFILE_OWNER_FIELD]` is a one-element list, since those names are the same literal by design.
- `test_concurrent_claim_yields_one_owner` — use committed isolated fixtures plus `IntegrationTestCase.primary_connection()` and `secondary_connection()`. Primary locks the shared profile and writes group A's marker without committing. Secondary attempts `for_update=True, wait=False` and must receive `frappe.QueryTimeoutError`, proving the row lock serializes claims. Primary commits. Secondary retries group B's save and must receive `frappe.ValidationError` after reading group A's committed marker. Assert group A remains the sole owner.

`secondary_connection()` cannot see ordinary uncommitted fixtures. This one test may commit unique fixtures. Call `frappe.db.rollback()` immediately BEFORE the fixture commit, so the commit captures only this test's own rows — `IntegrationTestCase` has no per-test rollback, only `addClassCleanup(_rollback_db)`, so a bare commit would also commit whatever uncommitted state earlier tests in the class left behind.

Register explicit cleanup for every committed row: Price Group, the managed Price Lists `PG-<group>` for BOTH groups, their Item Prices, POS Profile, Item, Warehouse, Customer, and any Mode of Payment the fixture created. Roll back both connections before cleanup, then delete only unique test records and commit cleanup even when an assertion fails. Wrap each delete in its own `try/except` and put the commit in a `finally` — one failing `delete_doc` inside a bare loop aborts the rest and the trailing commit never runs, leaving both a partial cleanup and an uncommitted delete.

Cleanup must NOT use `force=True`. The commit exemption granted to this test is not a force exemption, and forcing masks exactly the stranding this phase exists to eliminate. Delete in dependency order instead: Item Price, then Price List, then POS Profile, then Warehouse, then Item.

Use this exact Price Group lock:

```python
frappe.db.get_value(
	"Price Group",
	self.name,
	"modified",
	for_update=True,
)
```

Use the same `for_update=True` shape for POS Profile, Price List, and Item Price rows. Do not treat the implicit document update as sufficient evidence of lock order.

- [ ] **Step 6: Write the failing hook and fixture ownership tests**

Create `test_hooks.py`:

```python
PAST_ORDER_METHOD = "erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"
SELLING_PAST_ORDER = "selling_additional.overrides.pos_overrides.custom_get_past_order_list"
```

- `test_target_hooks_have_exact_shape` — `required_apps == ["erpnext"]`; `override_whitelisted_methods == {PAST_ORDER_METHOD: SELLING_PAST_ORDER}`; `doc_events` maps `POS Invoice.validate` and `Sales Invoice.validate` to `selling_additional.walk_in.validate_walk_in_customer_name`; `page_js == {"point-of-sale": "public/js/pos_walk_in_customer.js"}`; `after_migrate` absent or empty.
- `test_exact_custom_field_fixture_identity` — `fixtures` filters by exact `name`, never by `fieldname` alone. Use this target order:

```python
[
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"POS Invoice-custom_walk_in_customer_name",
					"Sales Invoice-custom_walk_in_customer_name",
					"Price List-custom_selling_additional_price_group",
					"Item Price-custom_selling_additional_price_group",
					"POS Profile-custom_selling_additional_price_group",
					"POS Profile-custom_selling_additional_previous_price_list",
				],
			]
		],
	}
]
```

Also parse fixture JSON. Assert the two moved walk-in objects retain `module is None`. Assert only the four new ownership objects use `module == "Selling Additional"`.

- `test_no_global_desk_asset` — assert TWO distinct facts, because the original single assertion was vacuous. It read only `selling_additional.hooks`, an app that has never set `app_include_js`, so it could not fail for the reason it claimed ("the walk-in asset must not load on every Desk route").
  - `selling_additional.hooks.app_include_js` is absent or empty — a real forward guard that Task 4 must satisfy when it adds `page_js`.
  - Bakery's Desk bundle does not import the walk-in asset. Assert this by FOLLOWING the bundle, not by pattern-matching the hook value:

    ```python
    bundle = Path(
        frappe.get_app_path("bakery_manufacturing"), "public", "js", "bakery_manufacturing.bundle.js"
    ).read_text()
    self.assertNotIn("pos_walk_in_customer", bundle, "bakery bundle still imports the walk-in asset globally")
    ```

    Asserting `"walk_in" not in bakery_manufacturing.hooks.app_include_js` does NOT work: that value is the string `"bakery_manufacturing.bundle.js"`, which contains no `walk_in`, so the assertion cannot fail — while `bakery_manufacturing.bundle.js:1` is literally `import "./pos_walk_in_customer.js";`, meaning bakery DOES load the walk-in asset on every Desk route today. Checking the hook string reproduces the same vacuity one indirection down. Keep the filename check as a cheap second net. This half stays RED until Task 10 Step 3 removes the hook and Step 5 deletes the import.
- `test_exactly_one_past_order_provider` — `frappe.get_hooks("override_whitelisted_methods")[PAST_ORDER_METHOD] == [SELLING_PAST_ORDER]` and `frappe.override_whitelisted_method(PAST_ORDER_METHOD) == SELLING_PAST_ORDER`. Stays RED until Task 10 removes the bakery registration.
- `test_price_group_doctypes_belong_to_selling_additional` — all three DocTypes report `module == "Selling Additional"`. Stays RED until Task 6's migrate, which is where the DB value changes.

`test_target_hooks_have_exact_shape` cannot reach GREEN in one task: its assertions span `doc_events` and `page_js` (Task 4), `override_whitelisted_methods` (Task 5), and `fixtures` (Task 7). Task 7 Step 7 owns its final GREEN. No task before Task 7 may report it passing.

- [ ] **Step 7: Run and verify RED**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_price_group_lifecycle
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_price_group_concurrency
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_hooks
```

Expected: FAIL — no controller, ownership module, or target hooks exist yet.

**RED verification is not a headcount.** `Price Group` already exists on the site and resolves to `bakery_manufacturing…price_group.PriceGroup` — the controller carrying the defects this phase removes. So a lifecycle test that PASSES here proves nothing about the controller Task 3 will write. Classify every green test before declaring this step done:

- **Legitimately green** — pins behavior the cutover preserves unchanged and would fail if that behavior regressed. Only the four ported validations (tests 15) plus test 14 qualify.
- **Vacuously green** — passes because its assertions cannot distinguish the old controller from the new one. Every such test is a defect in THIS task, not a finding for later.
- **Green but asserting the wrong contract** — should be reading the ownership marker (which does not exist yet, so it should be RED) and instead asserts something marker-free.

Any test in the second or third category must be strengthened before Task 1 closes. A RED that comes from a BROKEN FIXTURE — a batch on an item without `has_batch_no`, a hard-coded record name, an Item Price that collides on `check_duplicates` — is also a defect in this task, not contract RED. Distinguish the two in the report and fix the fixture bugs. Report the exact per-module pass and fail counts; an inaccurate count hides exactly the green tests that need classifying.

Every assertion needs a `msg=`. `assertTrue(exists(...))` failing with "None is not true" tells a future reader nothing about which contract broke.

---

### Task 2: Move the Three Price Group DocTypes into `selling_additional`

**Files:**
- Create: `selling_additional/selling_additional/selling_additional/doctype/__init__.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group/__init__.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group/price_group.json`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group/price_group.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group/price_group.js`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_item/__init__.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_item/price_group_item.json`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_item/price_group_item.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_outlet/__init__.py`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_outlet/price_group_outlet.json`
- Create: `selling_additional/selling_additional/selling_additional/doctype/price_group_outlet/price_group_outlet.py`
- Create: `selling_additional/selling_additional/ownership.py`
- Create: `selling_additional/selling_additional/patches/v1_0/__init__.py`
- Create: `selling_additional/selling_additional/patches/v1_0/adopt_legacy_selling_state.py` (only `ensure_ownership_fields()`; `execute()` arrives in Task 7)
- Create: `selling_additional/selling_additional/migration/__init__.py`
- Create: `selling_additional/selling_additional/migration/preflight.py` (module skeleton; phase logic arrives in Task 7)
- Modify: `selling_additional/selling_additional/tests/test_shell_contract.py`

**Resequencing note (was blocking).** Three modules originally created in Tasks 6 and 7 are consumed earlier, making the plan unexecutable as ordered:

- Task 6 Step 2 calls `preflight.run(phase="pre_model_sync")` from `migration/preflight.py`, which Task 7 creates.
- Task 3 Step 7 imports `ensure_ownership_fields()` from `patches/v1_0/adopt_legacy_selling_state.py`, which Task 7 creates inside the `patches/v1_0/` package, which Task 6 creates.

Both now originate here, in the task that already establishes the app skeleton. Tasks 6 and 7 consume and extend them rather than creating them. No interface changes — the signatures in Tasks 6 and 7 stand exactly as written there.

**Interfaces:**
- Each JSON keeps `"name"`, `"autoname": "field:price_group_name"` (parent), `"istable": 1` (children), field order, fieldnames, options, `unique`, `read_only`, permissions, `title_field`, `sort_field`, `sort_order`, and `track_changes` byte-equivalent to bakery. Change only `module`, `modified`, and the parent `allow_rename` value. Set `Price Group.allow_rename` to `0`; do not copy bakery's unsafe `1`.
- `selling_additional.ownership` exports the four field-name constants, plus `owner_filters(price_group: str) -> dict` and `MANAGED_PRICE_LIST_PREFIX = "PG-"`.

- [ ] **Step 1: Copy the three DocType JSON files**

Copy from `bakery_manufacturing/bakery_manufacturing/bakery_manufacturing/doctype/{price_group,price_group_item,price_group_outlet}/*.json`. Change `module` and `modified` in all three files. Also change only the parent `Price Group` value from `"allow_rename": 1` to `"allow_rename": 0`. Renaming would break the stable DocType name, the `PG-<name>` convention, owner links, and migration classification.

`modified` must be strictly later than the value stored on the target site, because `frappe.modules.import_file.import_file_by_path` skips a non-DocType import when the DB timestamp is newer, and for DocTypes compares a `migration_hash`. Since the module value changes in `pre_model_sync` (Task 6) before sync, the hash differs and the import proceeds; a later `modified` removes ambiguity.

- [ ] **Step 2: Write `ownership.py`**

```python
PRICE_LIST_OWNER_FIELD = "custom_selling_additional_price_group"
ITEM_PRICE_OWNER_FIELD = "custom_selling_additional_price_group"
PROFILE_OWNER_FIELD = "custom_selling_additional_price_group"
PROFILE_PREVIOUS_PRICE_LIST_FIELD = "custom_selling_additional_previous_price_list"
MANAGED_PRICE_LIST_PREFIX = "PG-"


def managed_price_list_name(price_group_name: str) -> str:
	return f"{MANAGED_PRICE_LIST_PREFIX}{price_group_name}"
```

No abstraction beyond constants and one formatter.

- [ ] **Step 3: Copy the child controllers verbatim**

Both child controllers are `pass` bodies in the bakery source. Copy them unchanged except the import path.

- [ ] **Step 4: Copy the form script and keep it app-owned**

Copy `price_group.js` unchanged. It sets the outlet warehouse `get_query` filter by company and clears dependent child fields on company change. No behavior change is in scope for this task.

- [ ] **Step 5: Create the shared migration and patch modules Tasks 3, 6, and 7 consume**

Create the `patches/v1_0/` and `migration/` packages here, so no later task imports a module that does not yet exist.

`patches/v1_0/adopt_legacy_selling_state.py` gets `ensure_ownership_fields()` and nothing else in this task. It creates only the four missing owner Custom Fields with `module = "Selling Additional"`, never touching the two moved walk-in fields' `module`, field type, placement, label, or stored values. It is idempotent — a second call inserts nothing. Task 3 Step 7 calls it from test setup; Task 7 Step 5 calls the same helper from `execute()`.

`migration/preflight.py` gets `run(phase)` and `assert_clean(report, phase)` with the section keys Task 7 Step 1 pins, each reporting `ok` plus sorted `problems`. In this task both functions may return empty-but-well-formed sections; Task 7 fills in every phase rule. `run()` is read-only from the first commit — no `db.commit`, `set_value`, `delete`, or `delete_doc`, matching the proven `stock_additional/migration/preflight.py`.

Do not create `patches/v1_0/transfer_price_group_ownership.py` here, and do not register anything in `patches.txt`. Task 6 owns the pre-sync patch and its `patches.txt` entry; Task 7 owns the post-sync patch and its entry. `patches.txt` must still read exactly `[pre_model_sync]\n\n[post_model_sync]\n` when this task ends, because `test_shell_contract.test_patches_file_has_both_migration_sections` asserts that and no earlier task may break it.

- [ ] **Step 6: Amend the now-invalidated shell-contract assertion**

`test_shell_contract.test_shell_contains_no_target_doctype_json` asserts `selling_additional/doctype/price_group/price_group.json` is ABSENT. Step 1 of this task creates exactly that file, so the assertion becomes false the moment this task lands — and Task 10 Step 8 plus Task 12 Step 6 both run `--app selling_additional` expecting PASS.

Convert the assertion instead of deleting it: the shell test now asserts the JSON EXISTS and declares `"module": "Selling Additional"`, which is the property that actually matters once the shell is intentionally no longer inert. Rename it `test_target_doctype_json_is_app_owned`.

Two sibling assertions in the same file expire later and are amended by the tasks that invalidate them, not here:

- `test_shell_registers_no_moved_runtime_ownership` — Task 4 adds `doc_events` and `page_js`, Task 5 adds `override_whitelisted_methods`, Task 7 adds `fixtures`. Task 7, the last of these, replaces it with an assertion that each key holds its expected target value. `after_migrate` must stay absent or empty throughout, per Task 1's `test_target_hooks_have_exact_shape`.
- `TestInstalledSellingAdditionalShell.test_module_exists_without_ownership_transfer` — asserts the DB still reports `Price Group` under `Bakery Manufacturing`. Task 6's migrate makes that false; Task 6 amends it to assert `Selling Additional`.

This mirrors Phase 1, where three inactive-shell assertions were retired for the same reason as the shell stopped being inert; that precedent was independently reviewed and upheld.

- [ ] **Step 7: Run the DocType-presence subset**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_hooks
```

Expected: still RED on module ownership (`Price Group` module is still `Bakery Manufacturing` in the DB until Task 6) and on hook shape. The JSON files existing is not enough.

---

### Task 3: Implement the Corrected Price Group Controller

**Files:**
- Modify: `selling_additional/selling_additional/selling_additional/doctype/price_group/price_group.py`
- Modify: `selling_additional/selling_additional/ownership.py`
- Modify: `selling_additional/selling_additional/tests/test_price_group_lifecycle.py`
- Modify: `selling_additional/selling_additional/tests/test_price_group_concurrency.py`

**Interfaces:**

```python
class PriceGroup(Document):
	def validate(self) -> None: ...
	def on_update(self) -> None: ...
	def on_trash(self) -> None: ...

	def _desired_profiles(self) -> list[str]: ...
	def _currently_owned_profiles(self) -> list[str]: ...
	def _lock_managed_state(self) -> ManagedState: ...
	def _validate_managed_state(self, state: ManagedState) -> None: ...
	def _sync_price_list(self, state: ManagedState) -> None: ...
	def _sync_item_prices(self, state: ManagedState) -> None: ...
	def _sync_profiles(self, state: ManagedState) -> None: ...
```

`ManagedState` is an immutable dataclass containing the managed Price List name, sorted desired profiles, sorted currently owned profiles, their union, and sorted existing managed Item Price names. It prevents later helpers from issuing a second unlocked ownership query.

- [ ] **Step 1: Implement validation, unchanged in behavior**

Port `_validate_items` and `_validate_outlets` from bakery. Correct `_set_uom`: fetch each Item's current `stock_uom` on every save and assign it to the managed child row. This makes the next save move managed identity after an Item stock-UOM change, as required by spec §8.6. Validate every changed UOM before mutation. Keep existing validation messages and warehouse-company check.

- [ ] **Step 2: Lock the complete managed state before validation or mutation**

Use this order for `on_update()` and `on_trash()`:

1. Lock the Price Group row with `frappe.db.get_value("Price Group", self.name, "modified", for_update=True)`.
2. Resolve desired profile names and currently owned profile names without mutating anything.
3. Lock the sorted union of those profile rows.
4. Lock the managed Price List row when it exists.
5. Query existing marked Item Price names, sort them, and lock every row.
6. Read ownership values again from the locked rows.
7. Validate every collision and invariant.
8. Start mutation only after every check passes.

Lock currently owned profiles even when outlets no longer desire them. Otherwise removal, disable, and delete can race another claim while restoring the profile. Lock the Price List and managed Item Prices after profiles so all Price Group transactions use one global order.

- [ ] **Step 3: Create or update the managed Price List without leaking global settings**

For an existing owned Price List, update only `enabled` and `currency` with `frappe.db.set_value(..., update_modified=False)`. Then call `frappe.cache().hdel("price_list_details", name)`. Never call `PriceList.save()`.

For a missing Price List, insert one document with `price_list_name`, `selling=1`, `buying=0`, `currency`, `enabled`, and the owner marker. `PriceList.on_update` calls `set_default_if_missing`, which writes `Selling Settings.selling_price_list` ONLY when that setting is currently empty (verified at `price_list.py:39-43`).

The original instruction was to read the setting before insert and, if it was empty and the insert claimed it, restore it to empty afterwards. That read-then-restore is unsafe: between the read and the restore, another transaction can legitimately configure a default, and the restore then blanks a setting this Price Group never owned. Lock the singleton row for the whole read-insert-restore instead, so the sequence is serialized rather than optimistic:

```python
frappe.db.sql(
	"""select value from tabSingles
       where doctype = 'Selling Settings' and field = 'selling_price_list'
       for update""",
)
```

Take that lock immediately before reading the setting, and hold it through the insert and the conditional restore. Any concurrent Price Group insert or Selling Settings save then waits rather than interleaving. Restore to empty only when the pre-insert read was empty AND the post-insert value is exactly this managed list — never unconditionally.

Add a regression test that starts with an empty Selling default and proves it stays empty.

Reject an existing Price List with a different owner. Reject an unmarked existing list on a populated site. Task 7 is the only path that adopts a legacy list.

`# ponytail: targeted writes avoid PriceList.on_update, which rewrites all Item Prices and may claim the global Selling default.`

- [ ] **Step 4: Validate UOMs, then upsert only marked Item Prices**

Desired identity is `(item_code, uom)`. Before any Item Price mutation, verify every non-empty UOM has a `UOM Conversion Detail` row for that Item, matching ERPNext `ItemPrice.validate_item()`. Fail before mutation and name the Item and UOM.

Use only already locked marked rows for stale detection. Update a matching marked row's rate with `frappe.db.set_value`. Insert a missing marked row with `frappe.get_doc({...}).insert(ignore_permissions=True)`. Delete only marked rows not in the desired set with `frappe.delete_doc(..., ignore_permissions=True)`. Never delete or mark manual, customer-, supplier-, batch-, date-, packing-unit-, or NULL-UOM legacy rows.

When `self.enabled` is false, do not insert, update, or delete Item Prices. Keep all marked rows for re-enable.

- [ ] **Step 5: Claim and restore the already locked profiles**

For each desired profile, read `selling_price_list`, owner, and previous-list fields after locking. An empty owner stores the current list once, sets the owner, and assigns the managed list. The same owner updates only the assigned list. Another owner raises before any mutation.

For each currently owned profile not desired, restore the stored previous list and clear both markers. Use one targeted `frappe.db.set_value` call. Do not call `POS Profile.save()`, because unrelated legacy validation must not block recovery.

`# ponytail: targeted restore bypasses unrelated POS Profile validation while preserving the recorded prior list.`

- [ ] **Step 6: Implement disable and delete from the same locked snapshot**

Disable restores every currently owned profile, clears its markers, disables the Price List, retains all marked Item Prices, and performs no Item Price write.

Delete locks and validates the same complete state, restores every owned profile, deletes only marked Item Prices, clears the Price List marker, disables and retains the Price List, then returns. No `force=True` and no Price List delete.

- [ ] **Step 7: Run and verify GREEN for lifecycle and concurrency**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_price_group_lifecycle
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_price_group_concurrency
```

Expected: PASS, except `test_price_group_doctypes_belong_to_selling_additional` in `test_hooks.py`, which needs Task 6.

These integration tests need ownership Custom Fields. Test setup calls `selling_additional.patches.v1_0.adopt_legacy_selling_state.ensure_ownership_fields()`, the same idempotent helper used by Task 7. The helper creates only missing owner fields and preserves moved walk-in fields.

---

### Task 4: Move Desk POS Walk-In Validation and Client Behavior

**Files:**
- Create: `selling_additional/selling_additional/walk_in.py`
- Create: `selling_additional/selling_additional/public/js/pos_walk_in_customer.js`
- Create: `selling_additional/selling_additional/tests/test_walk_in.py`
- Create: `selling_additional/selling_additional/tests/test_walk_in_asset.py`
- Modify: `selling_additional/selling_additional/hooks.py`

**Interfaces:**
- `validate_walk_in_customer_name(doc, method=None) -> None`, registered on `POS Invoice.validate` and `Sales Invoice.validate`.
- `page_js = {"point-of-sale": "public/js/pos_walk_in_customer.js"}`.
- Client code uses the Page lifecycle, delegated customer events, and one observer scoped to the Page wrapper. It does not patch any ERPNext prototype.

- [ ] **Step 1: Write the failing server validation tests**

`test_walk_in.py`, using `IntegrationTestCase`:

- Empty or `None` walk-in name passes for POS Invoice and POS-created Sales Invoice.
- A non-empty name with a missing `pos_profile`, a nonexistent profile, a disabled profile, or a profile without `customer` raises `frappe.ValidationError`.
- A missing or disabled profile Customer raises.
- `doc.customer != profile.customer` raises.
- An enabled profile, enabled default Customer, and matching invoice Customer pass while preserving the exact field value.
- A Sales Invoice with `is_created_using_pos = 1` follows all rules above.
- An ordinary Sales Invoice with `is_created_using_pos = 0` returns immediately, even when the custom field is non-empty. Non-POS Sales Invoices remain outside this behavior.

- [ ] **Step 2: Implement the exact server boundary**

```python
import frappe
from frappe import _
from frappe.utils import cint


def validate_walk_in_customer_name(doc, method=None) -> None:
	if doc.doctype == "Sales Invoice" and not cint(doc.get("is_created_using_pos")):
		return

	name = (doc.get("custom_walk_in_customer_name") or "").strip()
	if not name:
		return

	profile_name = doc.get("pos_profile")
	profile = (
		frappe.db.get_value(
			"POS Profile",
			profile_name,
			["customer", "disabled"],
			as_dict=True,
		)
		if profile_name
		else None
	)
	if not profile:
		frappe.throw(_("A walk-in customer name requires an existing POS Profile."))
	if cint(profile.disabled):
		frappe.throw(_("POS Profile {0} is disabled.").format(profile_name))
	if not profile.customer:
		frappe.throw(_("POS Profile {0} has no default Customer.").format(profile_name))

	customer_disabled = frappe.db.get_value("Customer", profile.customer, "disabled")
	if customer_disabled is None:
		frappe.throw(_("Default Customer {0} does not exist.").format(profile.customer))
	if cint(customer_disabled):
		frappe.throw(_("Default Customer {0} is disabled.").format(profile.customer))
	if doc.get("customer") != profile.customer:
		frappe.throw(
			_("A walk-in customer name applies only to default Customer {0}.").format(profile.customer)
		)
```

`roti_ropi_pos.mobile_pos.customers.resolve_customer` keeps its Mobile POS-specific validation. Do not change it.

- [ ] **Step 3: Write the failing asset contract test**

`test_walk_in_asset.py` reads the source and asserts:

- `setInterval`, `setTimeout`, `.prototype`, `get_invoice_html`, `String.replace`, and `.replace(` do not appear.
- `MutationObserver` appears exactly once.
- Delegated handlers target `.customer-field input` and `.reset-customer-btn` under the Page wrapper.
- A `.selling-additional-walk-in` guard prevents duplicate input controls.
- The mount selector is scoped to the cart panel — the source contains `.customer-cart-container .customer-section` and never a bare `.customer-section` query.
- The observer is disconnected around the control insertion and reconnected after.
- `hooks.page_js` has the exact Page mapping and `app_include_js` is absent.

- [ ] **Step 4: Implement one Page-scoped controller**

Frappe evaluates `page_js` before `on_page_load`. Save the existing Page handler, call it first, then mount the app-owned observer and delegated events on that Page wrapper. Do not call `frappe.require()` again and do not patch `ItemCart` or any renderer.

Two defects in the original code block are corrected below, both verified against installed ERPNext source:

1. **The selector matched two different panels.** `wrapper.querySelector(".customer-section")` matches the cart's section (`pos_item_cart.js:32`, inside `.customer-cart-container` created at `:21-23`) AND the past-order summary's section (`pos_past_order_summary.js:84`, inside `.left-section`). Since `querySelector` returns whichever comes first in document order, the walk-in input could mount into the past-order summary panel — violating spec:281, "render one walk-in input on the POS page". The query is now scoped to `.customer-cart-container .customer-section`.

2. **The observer was structurally re-entrant.** `render` appended a node into the very subtree the observer watches, so every insertion re-triggered the callback. The original plan's answer was a `setTimeout` debounce, which its own Step 3 forbids. The correct fix needs no timer: disconnect the observer before mutating, reconnect after. This is exact rather than probabilistic — a debounce only makes the loop less frequent, while disconnecting makes it impossible.

```javascript
frappe.provide("selling_additional.pos");

selling_additional.pos.mount = function (wrapper) {
	if (wrapper.__selling_additional_walk_in) return;

	const state = { customer: undefined, initialized: false };
	const get_frm = () => wrapper.pos && wrapper.pos.frm;
	const clear = () => {
		const frm = get_frm();
		if (frm && frm.doc.custom_walk_in_customer_name) {
			frm.set_value("custom_walk_in_customer_name", "");
		}
	};
	const observer = new MutationObserver(() => render());
	const observe = () => observer.observe(wrapper, { childList: true, subtree: true });
	const render = () => {
		const frm = get_frm();
		const section = wrapper.querySelector(".customer-cart-container .customer-section");
		if (!frm || !section) return;

		const customer = frm.doc.customer || "";
		if (state.initialized && customer !== state.customer) clear();
		state.customer = customer;
		state.initialized = true;

		if (section.querySelector(".selling-additional-walk-in")) return;

		observer.disconnect();
		try {
			const parent = document.createElement("div");
			parent.className = "selling-additional-walk-in";
			section.appendChild(parent);
			const control = frappe.ui.form.make_control({
				df: {
					fieldtype: "Data",
					label: __("Walk-in Customer Name"),
					fieldname: "custom_walk_in_customer_name",
					onchange() {
						frm.set_value("custom_walk_in_customer_name", this.get_value());
					},
				},
				parent: $(parent),
				render_input: true,
			});
			control.set_value(frm.doc.custom_walk_in_customer_name || "");
		} finally {
			observe();
		}
	};

	$(wrapper)
		.on("change.selling_additional", ".customer-field input", clear)
		.on("click.selling_additional", ".reset-customer-btn", clear);

	observe();
	wrapper.__selling_additional_walk_in = { observer, render };
	render();
};

const core_on_page_load = frappe.pages["point-of-sale"].on_page_load;
frappe.pages["point-of-sale"].on_page_load = function (wrapper) {
	core_on_page_load(wrapper);
	selling_additional.pos.mount(wrapper);
};
```

The `finally` matters: if `make_control` throws, the observer still reconnects, so a single failed render does not permanently deafen the control. The observer watches only `wrapper`, not `document`. ERPNext replaces `.customer-section` contents during customer select and reset (`pos_item_cart.js:36-39`, `:154`). Each replacement triggers `render()`, which clears stale state on customer change and inserts exactly one control. No polling, delayed callback, HTML replacement, or prototype mutation is allowed.

- [ ] **Step 5: Register the hooks**

```python
doc_events = {
	"POS Invoice": {"validate": "selling_additional.walk_in.validate_walk_in_customer_name"},
	"Sales Invoice": {"validate": "selling_additional.walk_in.validate_walk_in_customer_name"},
}

page_js = {"point-of-sale": "public/js/pos_walk_in_customer.js"}
```

Do not set `app_include_js`.

- [ ] **Step 6: Run and verify GREEN**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_walk_in
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_walk_in_asset
```

Manually verify customer select, customer change, reset, new invoice, and returning to the Page. Each state has one input and no stale value.

---

### Task 5: Move the Past-Order Override with Server-Side Projection

**Files:**
- Create: `selling_additional/selling_additional/overrides/__init__.py`
- Create: `selling_additional/selling_additional/overrides/pos_overrides.py`
- Create: `selling_additional/selling_additional/tests/test_past_orders.py`
- Modify: `selling_additional/selling_additional/hooks.py`

**Interfaces:**
- `custom_get_past_order_list(search_term, status, limit=20) -> list[dict]`, whitelisted, registered as the override of `erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list`.

- [ ] **Step 1: Verify the installed ERPNext helpers**

Confirm `get_invoice_filters(doctype, status, name=None)`, `add_doctype_to_results(doctype, results)`, and `order_results_by_posting_date(results)` are importable from `erpnext.selling.page.point_of_sale.point_of_sale` and that core `get_past_order_list` uses field list `["name", "grand_total", "currency", "customer", "customer_name", "posting_time", "posting_date"]`. Verified at `point_of_sale.py:351`.

Confirm the client renderer escapes `invoice.customer_name` at `pos_past_order_list.js:117`, so a projected value is safe and renders through the standard path.

- [ ] **Step 2: Write the failing projection tests**

`test_past_orders.py`:

- A POS Invoice with a walk-in name returns a row whose `customer_name` equals the walk-in name and whose `customer` still equals the real Customer id. This is the projection that removes the client-side `String.replace()`.
- A POS Invoice with no walk-in name returns the untouched core `customer_name`.
- Searching a walk-in name substring returns the invoice; searching the real customer name still returns it; searching the invoice id still returns it.
- The response contains no extra key beyond the core field set plus `doctype` — assert the exact key set, so the client contract does not drift.
- Permission awareness: as a user without POS Invoice read permission, the result excludes the invoice. Use `frappe.set_user` and restore in `finally`. `frappe.db.get_list` is permission-aware; `frappe.db.get_all` is not — the override must keep `get_list`.
- Sales Invoice rows created through POS are included with the same projection.

- [ ] **Step 3: Implement the override, collapsing the duplicated branch**

Bakery's version (`bakery_manufacturing/bakery_manufacturing/overrides/pos_overrides.py`) loops `for dt in ["POS Invoice", "Sales Invoice"]` in BOTH the `search_term and status` branch and the `status`-only branch, with the same `get_list` call shape in each. Do not copy that structure. "Keep the bakery structure" was the original instruction, but carrying a duplicated logic block across an ownership move is not preserving behavior — it is preserving a defect the review rubric flags. Collapse it to one fetch helper both branches call:

```python
FIELDS = (
	"name",
	"grand_total",
	"currency",
	"customer",
	"customer_name",
	"custom_walk_in_customer_name",
	"posting_time",
	"posting_date",
)


def _fetch(dt, status, search_term, limit):
	rows = frappe.db.get_list(
		dt,
		filters=get_invoice_filters(dt, status),
		or_filters=(
			{
				"customer_name": ["like", f"%{search_term}%"],
				"customer": ["like", f"%{search_term}%"],
				"custom_walk_in_customer_name": ["like", f"%{search_term}%"],
			}
			if search_term
			else None
		),
		fields=list(FIELDS),
		page_length=limit,
	)
	if search_term:
		rows += frappe.db.get_list(
			dt,
			filters=get_invoice_filters(dt, status, name=search_term),
			fields=list(FIELDS),
			page_length=limit,
		)
	return add_doctype_to_results(dt, rows)
```

Behavior is identical to bakery's: with a search term, both the or-filter fetch and the by-name fetch run and concatenate; without one, only the plain fetch runs. Keep `frappe.db.get_list` — it is permission-aware where `get_all` is not (Verified Caveat 12).

The two changes relative to core remain exactly as scoped: `custom_walk_in_customer_name` joins the searched `or_filters` and the fetched fields, then is projected and dropped before returning:

```python
def _project(rows):
	for row in rows:
		walk_in = row.pop("custom_walk_in_customer_name", None)
		if walk_in:
			row["customer_name"] = walk_in
	return rows
```

Projection happens after `add_doctype_to_results` and before `order_results_by_posting_date`. `customer` is never rewritten.

- [ ] **Step 4: Register the hook**

```python
override_whitelisted_methods = {
	"erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list": "selling_additional.overrides.pos_overrides.custom_get_past_order_list",
}
```

- [ ] **Step 5: Run and verify**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_past_orders
```

Expected: projection tests pass. `test_exactly_one_past_order_provider` remains RED until Task 10 removes bakery's provider.

---

### Task 6: `pre_model_sync` Safety Assertion and DocType Transfer

**Files:**
- Create: `selling_additional/selling_additional/patches/v1_0/transfer_price_group_ownership.py`
- Modify: `selling_additional/selling_additional/patches.txt`
- Modify: `selling_additional/selling_additional/migration/preflight.py` (add the `pre_model_sync` phase rules to the Task 2 skeleton)
- Modify: `selling_additional/selling_additional/tests/test_shell_contract.py`
- Create: `selling_additional/selling_additional/tests/test_module_transfer_patch.py`

The `patches/__init__.py` and `patches/v1_0/__init__.py` packages and `migration/preflight.py` already exist from Task 2 Step 5. This task extends them.

**Interfaces:**
- `execute() -> None` validates the complete staged legacy contract before changing exactly three DocType `module` values.
- `TARGET_DOCTYPES = ("Price Group", "Price Group Item", "Price Group Outlet")`.
- `SOURCE_MODULE = "Bakery Manufacturing"`, `TARGET_MODULE = "Selling Additional"`.

- [ ] **Step 1: Write failing atomicity and fresh-install tests**

`test_module_transfer_patch.py` covers:

- all three legacy DocTypes at `Bakery Manufacturing` move to `Selling Additional`;
- target `Module Def` missing raises before any write;
- one missing DocType or any third-party module raises before any write;
- unreadable parent or child data, missing generated Price List, duplicate outlet claim, ambiguous Item Price, incomplete recovery map, unexpected fixture owner, unexpected active hook provider, or unsupported old-path reference raises before any write;
- every parent and child business value remains byte-identical;
- a forced second run changes no row and no `modified` timestamp;
- a fresh site with zero target DocTypes is a no-op. Fresh model sync creates them from target JSON and fresh fixture sync creates fields without running adoption logic;
- a half-present set of DocTypes is never treated as fresh and raises.

- [ ] **Step 2: Implement one pre-sync assertion and transfer**

Call `preflight.run(phase="pre_model_sync")`, then `preflight.assert_clean(report, phase="pre_model_sync")`. This phase permits exactly one staged ownership shape: all three DocTypes belong to bakery, every recovery-map and Item Price decision is complete, and shell `Module Def` exists. It also permits one fresh shape: none of the three DocTypes exists.

**Overlap-window corrections (was blocking).** The original text also required, at this phase, that "selling is the sole registered past-order provider in coordinated source" and that "bakery DocType JSON files are absent". Both are false at the moment this patch runs, and the second directly contradicts Step 3 of this same task, which mandates the bakery JSON stay in place until Task 10 — a self-deadlock. Task 10 is the task that removes bakery's JSON and its past-order registration, so both conditions belong to the `final` phase asserted there, not here. The `pre_model_sync` phase asserts only what must hold at transfer time. The overlap window in which the bench carries two copies of all three DocTypes is intentional and bounded by Tasks 6 through 10; its provider ambiguity is separately gated by `test_exactly_one_past_order_provider`, which Task 1 pins RED and Task 10 turns green.

Validate all three current module values before the first `db.set_value`. Then update only their `module` fields with `update_modified=False` and clear module caches. Never continue from a partially moved set.

```text
[pre_model_sync]
selling_additional.patches.v1_0.transfer_price_group_ownership

[post_model_sync]
selling_additional.patches.v1_0.adopt_legacy_selling_state
```

Both sections remain in `patches.txt`. No other adoption patch is registered.

- [ ] **Step 3: Back up, migrate, and amend the DB-ownership assertions**

`bench migrate` on `selling-cutover.localhost` is approved for this task. Take a backup FIRST and record its path:

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost backup
bench --site selling-cutover.localhost migrate
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_module_transfer_patch
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_hooks
```

The backup is not ceremony. Task 7 Step 5 claims "Frappe's migrate transaction rolls back all later writes if the final assertion fails" — that claim is FALSE and is corrected in Task 7. `frappe/modules/patch_handler.py` commits after each patch, so a Task 7 failure leaves this task's DocType module transfer committed with its own `Patch Log` row: exactly the half-migrated state the plan believes it prevents. The patch structure stays as designed, because the spec requires idempotency (`spec:415-416`) and the design delivers it; the backup is what converts an unrecoverable half-state into a restore.

After the migrate the DB reports all three DocTypes under `Selling Additional`. Two assertions become false and are amended here, in the task that invalidates them:

- `test_hooks.test_price_group_doctypes_belong_to_selling_additional` turns GREEN. Task 1 Step 6 and Task 3 Step 7 both say it needs Task 6; that is now literally true.
- `test_shell_contract.TestInstalledSellingAdditionalShell.test_module_exists_without_ownership_transfer` asserts `Price Group` still reports `Bakery Manufacturing`. Amend it to assert `Selling Additional` and rename it `test_module_owns_transferred_doctypes`.

Bakery's duplicate DocType JSON stays on disk until coordinated source handoff in Task 10. The transferred `module` value in the DB is what decides ownership; the leftover JSON is inert until a migrate re-imports it, which Task 10 removes before that can happen.

---

### Task 7: One `post_model_sync` Adoption Patch

**Files:**
- Create: `selling_additional/selling_additional/patches/v1_0/adopt_legacy_selling_state.py` — add `execute()` beside the `ensure_ownership_fields()` created in Task 2 Step 5
- Create: `selling_additional/selling_additional/fixtures/custom_field.json`
- Modify: `selling_additional/selling_additional/migration/preflight.py` — add the `post_model_sync` and `final` phase rules to the Task 2 skeleton
- Create: `selling_additional/selling_additional/migration/recovery_map.py`
- Modify: `selling_additional/selling_additional/hooks.py` — add `fixtures`
- Modify: `selling_additional/selling_additional/tests/test_shell_contract.py`
- Create: `selling_additional/selling_additional/tests/test_migration.py`
- Create: `selling_additional/selling_additional/tests/test_preflight.py`

`migration/__init__.py`, `migration/preflight.py`, `patches/v1_0/__init__.py`, and the `adopt_legacy_selling_state` module already exist from Task 2 Step 5.

**Interfaces:**
- `preflight.run(phase: Literal["pre_model_sync", "post_model_sync", "final"]) -> dict` is read-only.
- `preflight.assert_clean(report: dict, phase: str) -> None` validates the exact phase contract.
- `preflight.check(phase: Literal["pre_model_sync", "post_model_sync", "final"]) -> dict` runs, validates, and returns one operational report. This is NOT a dead interface: `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md:799` and `:1098` invoke it as `bench --site <SITE> execute selling_additional.migration.preflight.check`, mirroring `stock_additional`'s already-shipped `check()` (`stock_additional/migration/preflight.py:341`). It exists so an operator gets run-plus-assert in one bench command; keep it, and keep its signature bench-executable by dotted path.
- `recovery_map.load() -> dict[str, str]` receives an operator-supplied map through the rollout's approved secret-safe mechanism. The map never enters Git, plan output, logs, or transcript.
- `ensure_ownership_fields() -> None` creates missing owner fields and preserves both moved walk-in field definitions exactly.
- `execute() -> None` validates the complete post-sync state, then adopts all legacy ownership in one transaction.

- [ ] **Step 1: Pin the read-only preflight report**

`test_preflight.py` requires these stable sections, each with `ok`, sorted `problems`, and no writes:

- `doctypes` and `price_group_rows`;
- `custom_fields` with exact names, definitions, and fixture owners;
- `generated_price_lists`, including orphan unmarked `PG-` lists with no referencing group;
- `profile_claim_conflicts`;
- `item_price_ambiguity`;
- `profile_recovery`;
- `legacy_sidebar_item`;
- `hook_owners`;
- `old_path_references`.

Patch `frappe.db.commit`, `set_value`, `delete`, and `frappe.delete_doc` to raise during `run()`. Snapshot candidate `modified` values and prove they stay unchanged.

Define phase rules explicitly:

- `pre_model_sync`: staged bakery module ownership is expected, while coordinated source already makes selling the sole registered past-order provider. Every data ambiguity and recovery-map error blocks. An orphan unmarked `PG-` Price List also blocks until an operator either links it to the matching Price Group after proving ownership or renames it outside the reserved namespace in a separately approved remediation.
- `post_model_sync`: all three modules must already be `Selling Additional`, new source hooks must resolve to selling, and no ownership marker may conflict. Legacy unmarked rows are allowed only when the validated adoption plan identifies them exactly.
- `final`: one owner and provider only, all markers consistent, zero legacy sidebar rows, and no unsupported old reference.

- [ ] **Step 2: Preserve exact Custom Field contracts**

Create four new owner fields with `module = "Selling Additional"`:

- `Price List-custom_selling_additional_price_group`;
- `Item Price-custom_selling_additional_price_group`;
- `POS Profile-custom_selling_additional_price_group`;
- `POS Profile-custom_selling_additional_previous_price_list`.

Copy these two moved fixture records byte-for-byte, including `"module": null`:

- `POS Invoice-custom_walk_in_customer_name`;
- `Sales Invoice-custom_walk_in_customer_name`.

Fixture filters use the six exact `name` values. `ensure_ownership_fields()` must never change the moved fields' `module`, field type, placement, label, or stored values. Tests compare the two fixture objects against bakery's source objects and compare business values before and after adoption.

- [ ] **Step 3: Pin strict recovery-map authority**

The operator map is the authority for every POS Profile currently pointing at a generated list and missing a stored previous value. Validate every key and value. Missing, invalid, duplicate, and extra entries block before mutation. Version history is advisory evidence only because POS Profile does not enable `track_changes`; never auto-apply it and never accept it instead of an approved map entry.

Do not hard-code the injection transport in this implementation plan. The coordinated rollout records the approved mechanism and passes the map to `recovery_map.load()` without printing it. Tests patch `recovery_map.load()` directly.

- [ ] **Step 4: Pin Item Price classification, including NULL UOM**

Adopt only an unmarked, unscoped Item Price whose complete identity maps to exactly one current Price Group child `(item_code, resolved_uom)` on its generated list. Scope includes customer, supplier, batch, valid dates, and packing unit, with SQL NULL and empty treated equivalently.

Resolve child UOM from the Item's current stock UOM before classification. Normalize a legacy Item Price `uom` of NULL or empty to that same stock UOM only for collision detection. Never silently mark it. If a NULL/empty row collides with a concrete row or could represent a managed child, report every row as ambiguous and block. Manual, scoped, unmatched, and ambiguous rows stay untouched. Runtime lifecycle must detect the same normalized collision before inserting, so an ambiguous legacy row produces a clear validation error instead of ERPNext's late duplicate exception.

- [ ] **Step 5: Implement one validate-then-mutate adoption patch**

`execute()` follows this order:

1. Run and assert the full `post_model_sync` report.
2. Build immutable adoption lists for all six fields, Price Lists, Item Prices, profiles, and the optional exact sidebar child.
3. Revalidate every target identity and marker before the first write.
4. Create only missing ownership fields. Preserve moved fields.
5. Mark referenced generated Price Lists.
6. Mark only classified Item Prices.
7. Store every approved previous Price List.
8. Mark and reconcile owned POS Profiles.
9. Delete zero or one exact legacy sidebar child row directly.
10. Clear Price List, DocType, document, and sidebar caches.
11. Re-run `preflight.run(phase="post_model_sync")` and assert it is clean, proving the mutations landed as planned.

**The terminal assertion is `post_model_sync`, not `final`.** The original step 11 asserted the `final` phase from inside this patch. That cannot hold at the time this patch runs: `final` requires one owner and one provider with zero legacy references, and bakery still carries its past-order registration and its DocType JSON until Task 10 — which runs AFTER the Task 6-7 migrate. A patch that asserts a condition a later task creates fails every time it executes.

`final` is an operator gate, not a patch step. It is run out-of-band after the coordinated release, via `bench --site <SITE> execute selling_additional.migration.preflight.check --kwargs "{'phase': 'final'}"`, which is exactly how `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md:799` and `:1098` already invoke it, and how `stock_additional` shipped the same split (its patch asserts the staged phase; `final` is checked at release).

Any validation failure occurs before step 4, so a rejected report leaves this patch's own writes entirely undone. Do not split these operations across separately registered patches, which could leave `Patch Log` entries for half-adopted state.

**Correction to the original atomicity claim.** The plan previously asserted "Frappe's migrate transaction rolls back all later writes if the final assertion fails." That is FALSE. `frappe/modules/patch_handler.py` commits after each patch completes, so a failure here does NOT roll back Task 6's committed DocType module transfer, and Task 6's `Patch Log` row survives. The single-patch design is still correct — it keeps THIS patch's eleven steps atomic, which is what matters, and the spec requires only idempotency (`spec:415-416`), which a re-run satisfies. The cross-patch guarantee is provided by Task 6's mandatory pre-migrate backup, not by the transaction.

- [ ] **Step 6: Test idempotency and migration failure atomicity**

Run `execute()` twice and compare row checksums plus `modified` snapshots. Inject one failure before each mutation stage and assert rollback leaves every table unchanged. Run the forced patch proof on the dedicated `selling-cutover.localhost` site, using `bench --site selling-cutover.localhost run-patch selling_additional.patches.v1_0.adopt_legacy_selling_state --force`, then compare checksums before and after. Never run forced patches on `development.localhost`.

- [ ] **Step 7: Retire the last stale shell assertion and close the hook shape**

This task adds the final missing hook key, `fixtures`. With it, every key `test_shell_contract.test_shell_registers_no_moved_runtime_ownership` asserts is empty now holds a value: `doc_events` and `page_js` from Task 4, `override_whitelisted_methods` from Task 5, `fixtures` from here. Replace that assertion with `test_shell_registers_moved_runtime_ownership`, asserting each key equals its expected target value, and keep the one part that stays true for the whole phase — `after_migrate` absent or empty.

`test_hooks.test_target_hooks_have_exact_shape` also reaches full GREEN here, since its assertions span Tasks 4, 5, and 7 and this is the last of them. No earlier task may claim that test green.

- [ ] **Step 8: Run the preflight and migration suites**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_preflight
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_migration
```

---

### Task 8: App-Owned Workspace and Workspace Sidebar

**Files:**
- Create: `selling_additional/selling_additional/selling_additional/workspace/selling_additional/selling_additional.json`
- Create: `selling_additional/selling_additional/workspace_sidebar/selling_additional.json`
- Create: `selling_additional/selling_additional/tests/test_navigation.py`

**Interfaces:**
- One standard `Workspace` named `Selling Additional`, `module: "Selling Additional"`, `app: "selling_additional"`, `public: 1`, with a Price Group link.
- One app-level `Workspace Sidebar` named `Selling Additional`, `app: "selling_additional"`, `standard: 1`, `module: "Selling Additional"`, whose items are a `Home` link to the workspace plus a `Price Group` `Link`/`DocType` item.

- [ ] **Step 1: Verify the loading contract**

`frappe.model.sync.sync_for` imports app-level folders `["desktop_icon", "workspace_sidebar", "sidebar_item_group"]` from `<app>/<folder>/` (`frappe/model/sync.py:120-126`), and module-level `workspace` folders through `IMPORTABLE_DOCTYPES`. ERPNext places its sidebars at `erpnext/workspace_sidebar/*.json` and its workspaces at `erpnext/selling/workspace/selling/selling.json` — match both layouts.

`WorkspaceSidebar.before_save` re-exports the JSON to the owning app's folder when `app` and `standard` are set and `developer_mode` is on (`workspace_sidebar.py:52-62`). That is exactly the mechanism that leaked the Price Group edit into ERPNext's source tree. Because `selling_additional` owns this file, a re-export writes into `selling_additional`, which is acceptable; a re-export must never target `erpnext`.

- [ ] **Step 2: Write the failing navigation tests**

`test_navigation.py`:

- `Workspace` `Selling Additional` exists with `module == "Selling Additional"` and `app == "selling_additional"`.
- `Workspace Sidebar` `Selling Additional` exists with `app == "selling_additional"`, `standard == 1`.
- Its items contain exactly one `Price Group` item with `type == "Link"` and `link_type == "DocType"`.
- ERPNext's `Selling` sidebar and every per-user `Selling-*` copy contain **zero** exact legacy Price Group items.
- `bakery_manufacturing.hooks.after_migrate` is absent or empty — the old bakery `after_migrate` hook is gone. Assert it against BAKERY's hooks, which is the app that carries it (`bakery_manufacturing/hooks.py:36`). Reading `selling_additional.hooks.after_migrate` here would be vacuous: selling has never set that key, so the assertion could not fail for the reason it claims. Stays RED until Task 10 Step 3. Selling's own `after_migrate` staying absent is separately covered by `test_target_hooks_have_exact_shape`.
- No file under `apps/erpnext` changed. Do NOT assert this from inside a test: a test shelling out to `git` is brittle and couples the suite to the checkout's state. It is checked out-of-band in Task 12 Step 3, which runs `git -C apps/erpnext status --porcelain` and `git -C apps/frappe status --porcelain` and requires no new entries beyond the pre-existing unrelated work. The original text pointed at a "Task 11 gate"; Task 11 has no such gate, and Task 12 Step 3 is where it actually lives.

- [ ] **Step 3: Author both JSON files**

Copy the exact child-item key shape ERPNext uses (`child`, `collapsible`, `icon`, `indent`, `keep_closed`, `label`, `link_to`, `link_type`, `show_arrow`, `type`) so the import is well-formed. Set `header_icon` to a valid Frappe icon.

- [ ] **Step 4: Verify source now, import after coordinated handoff**

Run JSON structure tests without migrate. Task 12 owns the first dedicated-site migrate after Task 10 removes every bakery DocType copy. Immediately before that migrate, assert repository scan finds exactly one `price_group.json`, one `price_group_item.json`, and one `price_group_outlet.json`, all under `selling_additional`. The operational plan repeats this gate immediately before its active-site migrate.

After Task 12's populated migrate:

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_navigation
```

---

### Task 9: Legacy ERPNext Sidebar Child-Row Cleanup Contract

**Files:**
- Modify: `selling_additional/selling_additional/patches/v1_0/adopt_legacy_selling_state.py`
- Create: `selling_additional/selling_additional/tests/test_sidebar_cleanup.py`

**Interfaces:**
- `collect_legacy_sidebar_rows() -> list[dict]` returns exact child identities for ERPNext's `Selling` sidebar and every per-user `Selling-*` copy.
- Adoption deletes zero or one exact row per parent. More than one exact row under one parent blocks before mutation.

- [ ] **Step 1: Write the failing cleanup tests**

- Zero matches in every parent is an idempotent no-op.
- One exact row in standard `Selling` is deleted while unrelated child rows remain byte-identical.
- One exact row in a per-user `Selling-user@example.com` copy is also deleted.
- One row in each of several parents is allowed and all are deleted.
- Two exact rows under one parent raise before any deletion.
- Parent rows and `modified` values never change.
- Source contains no `.save()` and never assigns `sidebar.items`.

- [ ] **Step 2: Extend the adoption plan with all ERPNext Selling parents**

Query ERPNext-owned sidebars whose title is `Selling` or starts with `Selling-`. Filter names and titles in Python to reject unrelated prefixes. For each parent, query by the full legacy child shape from the leaked diff. Sort parents and rows. Validate the per-parent maximum before the first write. Add zero or one row name per parent to the immutable adoption plan.

During Task 7 adoption, delete each planned child directly with `frappe.db.delete("Workspace Sidebar Item", {"name": row_name})`. Never save or rewrite a parent. Clear sidebar and boot caches once after all deletions.

- [ ] **Step 3: Run and verify**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_sidebar_cleanup
```

---

### Task 10: Bakery Handoff and ERPNext Source Recovery

**Files:**
- Modify: `bakery_manufacturing/bakery_manufacturing/hooks.py`
- Delete: `bakery_manufacturing/bakery_manufacturing/fixtures/custom_field.json` (it holds exactly the two moved walk-in objects and becomes an empty list)
- Delete: all tracked files under `bakery_manufacturing/bakery_manufacturing/bakery_manufacturing/doctype/price_group/`
- Delete: all tracked files under `bakery_manufacturing/bakery_manufacturing/bakery_manufacturing/doctype/price_group_item/`
- Delete: all tracked files under `bakery_manufacturing/bakery_manufacturing/bakery_manufacturing/doctype/price_group_outlet/`
- Delete: `bakery_manufacturing/bakery_manufacturing/after_migrate.py`
- Delete: `bakery_manufacturing/bakery_manufacturing/public/js/pos_walk_in_customer.js`
- Modify: `bakery_manufacturing/bakery_manufacturing/public/js/bakery_manufacturing.bundle.js` by deleting only line 1
- Modify: `bakery_manufacturing/bakery_manufacturing/overrides/pos_overrides.py` as a temporary lazy Python shim
- Modify: `bakery_manufacturing/README.md`
- Restore (user-approved, path-scoped): `erpnext/erpnext/workspace_sidebar/selling.json`
- Do not modify: `bakery_manufacturing/bakery_manufacturing/tests/test_desk_sidebar.py`

`scripts/ownership_cutover.py` and `bakery_manufacturing/tests/test_ownership_cutover.py` were originally listed here and are dropped — see Step 9 for why.

**Interfaces:**
- Bakery keeps `required_apps = ["erpnext"]`, the `Serial and Batch Bundle` controller override, manufacturing code, and approved lazy Python shims only.
- Bakery keeps no Price Group DocType folder, past-order hook, moved fixture record, `after_migrate`, or walk-in source import.
- No DocType-folder compatibility shim is allowed. The one authoritative controller and JSON live in `selling_additional`.

- [ ] **Step 1: Record and verify the protected dirty suffix**

The bakery bundle consists of one tracked line followed by 14 uncommitted lines. Record both full-file and suffix hashes before editing. The approved suffix SHA-256 is `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. The observed full-file hash is `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8` with numstat `14 0`.

```bash
cd /workspace/development/frappe-bench/apps/bakery_manufacturing
shasum -a 256 bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
path = Path("bakery_manufacturing/public/js/bakery_manufacturing.bundle.js")
data = path.read_bytes()
first, separator, suffix = data.partition(b"\n")
assert separator and first == b'import "./pos_walk_in_customer.js";'
print(sha256(suffix).hexdigest())
PY
git diff --numstat -- bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
```

Abort on any mismatch. Never normalize line endings or rewrite the suffix.

- [ ] **Step 2: Verify the overlap tests are RED**

With both target hooks present and bakery unchanged, exact-one-provider tests must fail. This proves the coordinated handoff gate catches overlap.

- [ ] **Step 3: Strip active bakery ownership**

In `hooks.py`, remove the past-order method registration (`hooks.py:14-16`), the `fixtures` block (`:20-34`), `after_migrate` (`:36`), and `app_include_js = "bakery_manufacturing.bundle.js"` (`:56`). Keep `override_doctype_class` for `Serial and Batch Bundle` (`:10-12`), `required_apps = ["erpnext"]` (`:18`), and every unrelated bakery hook.

Two corrections to the original wording, both verified against the current file:

- It said to remove "barcode … registrations". There are none left — Phase 1 already removed bakery's `override_whitelisted_methods` entry for `erpnext.stock.utils.scan_barcode`. `override_whitelisted_methods` now holds exactly one key, the past-order method. Removing the whole dict is correct; looking for a barcode entry is not.
- It said to remove "the three moved fixture objects". `bakery_manufacturing/fixtures/custom_field.json` holds exactly TWO objects — `POS Invoice-custom_walk_in_customer_name` and `Sales Invoice-custom_walk_in_customer_name`, both with `"module": null` — because Phase 1 already moved the Item field out. Both objects move to selling, which leaves the file an empty list, so DELETE `bakery_manufacturing/fixtures/custom_field.json` rather than emptying it: an empty `fixtures` array with no `fixtures` hook is dead weight. Selling's `fixtures/custom_field.json` must carry these two objects byte-for-byte, `"module": null` included, per Task 7 Step 2.

`app_include_js` must go in the same edit, not later. Task 1's `test_no_global_desk_asset` asserts bakery's `app_include_js` carries no walk-in asset path, and Step 5 of this task deletes the file that bundle imports. Do not delete DB columns or stored values.

- [ ] **Step 4: Remove all three moved DocType folders**

Delete the parent and child DocType JSON, controllers, form script, tests, and package files. Do not leave a `price_group.py` shim under a DocType folder. Frappe model sync and orphan cleanup must see one authoritative DocType path only.

Keep a temporary lazy shim only for `bakery_manufacturing.overrides.pos_overrides.custom_get_past_order_list`. It must register no hook and no `@frappe.whitelist()` decoration. Stock plan owns the equivalent scanner shim.

- [ ] **Step 5: Remove only the tracked walk-in import**

Delete line 1 from `bakery_manufacturing.bundle.js`, then delete `public/js/pos_walk_in_customer.js`. Do not edit the remaining 14 lines.

Recompute the post-edit full-file hash and suffix hash. The full file now equals the prior suffix, so both must equal `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. Confirm the untracked sidebar test remains untouched and unstaged.

- [ ] **Step 6: Reverse only the known ERPNext sidebar leak**

Re-read the diff immediately before reversing:

```bash
cd /workspace/development/frappe-bench/apps/erpnext
git status --porcelain
git diff --numstat -- erpnext/workspace_sidebar/selling.json
git diff -- erpnext/workspace_sidebar/selling.json
```

Abort unless all of the following hold, which is the verified current state:

- `git status --porcelain` shows exactly ` M banking/yarn.lock`, ` M erpnext/workspace_sidebar/selling.json`, `?? .codegraph/`, `?? graphify-out/` and nothing else.
- `git diff --numstat` for the sidebar file is exactly `13 1`.
- The diff contains exactly the 12-line Price Group child object plus the single `"modified"` line change from `2026-04-28 14:38:37.179705` to `2026-07-22 15:30:25.063169`.
- Nothing is staged: `git diff --cached --numstat` is empty.
- `git show HEAD:erpnext/workspace_sidebar/selling.json | grep -c "Price Group"` is `0`, confirming the committed file is clean.

If and only if all hold, restore that single file to HEAD:

```bash
git -C /workspace/development/frappe-bench/apps/erpnext checkout -- \
  erpnext/workspace_sidebar/selling.json
git -C /workspace/development/frappe-bench/apps/erpnext status --porcelain
git -C /workspace/development/frappe-bench/apps/erpnext diff --numstat
```

Expected after: `banking/yarn.lock` still modified, `.codegraph/` and `graphify-out/` still untracked, no sidebar diff. Do not `git add`, do not commit anything in `apps/erpnext`, and do not touch any other path.

This is a destructive discard of working-tree content in a shared checkout. The user has approved this exact path-scoped restore for this task. The abort conditions above are still mandatory — approval covers this one file at this one state, not a restore of whatever the tree happens to hold when the step runs.

- [ ] **Step 7: Confirm only the approved bakery bundle change occurred**

Re-run Step 1. The edited bundle's full-file and suffix hashes must both equal `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. Diff must show deletion of only the import line plus the pre-existing 14-line suffix relative to HEAD. `test_desk_sidebar.py` stays untracked, byte-identical, and unstaged.

- [ ] **Step 8: Run cross-app suites**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost clear-cache
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_hooks
bench --site selling-cutover.localhost run-tests --app bakery_manufacturing
bench --site selling-cutover.localhost run-tests --app selling_additional
```

Expected: exactly one past-order provider; bakery manufacturing tests pass; the untracked bakery sidebar test still passes untouched.

- [ ] **Step 9: Verify the bundle edit with plain git — no overlay tool**

```bash
cd /workspace/development/frappe-bench/apps/bakery_manufacturing
git diff -- bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
```

Expected: the diff shows the deletion of `import "./pos_walk_in_customer.js";` plus the pre-existing 14-line addition, and the sidebar test stays `??` (untracked, unstaged).

**The `scripts/ownership_cutover.py` tool and its `test_ownership_cutover.py` are dropped.** The original Step 9 mandated a five-subcommand CLI (`manifest`, `apply`, `verify`, `rollback`, `finalize`) plus a fifteen-case test suite building temporary Git repositories. Its entire purpose was to switch a shared dirty checkout onto a candidate commit whose tracked bundle is EMPTY — a state only the rejected `git update-index --cacheinfo` fabrication in Step 10 creates. Step 10 no longer creates it, so the tool has no problem left to solve. What remains is a single one-off release handled by path-scoped git commands, exactly as Phase 1 handled this same file across nine commits and two source checkouts. A bespoke overlay CLI for one release, sitting beside a prose procedure that already describes the same operations, is code written to be deleted.

Remove `scripts/ownership_cutover.py` and `bakery_manufacturing/tests/test_ownership_cutover.py` from this task's Files list. The safety properties the tool was to enforce are not lost — they are the same abort conditions Steps 1, 6, and 7 already check by hand, before each command, with recorded hashes.

- [ ] **Step 10: Stage the bakery handoff with ordinary git**

Stage every handoff path explicitly by name. Stage the bundle's import deletion the same way, then leave the 14 protected lines as an ordinary unstaged modification:

```bash
cd /workspace/development/frappe-bench/apps/bakery_manufacturing
git add bakery_manufacturing/hooks.py
git rm -r --cached bakery_manufacturing/bakery_manufacturing/doctype/price_group \
  bakery_manufacturing/bakery_manufacturing/doctype/price_group_item \
  bakery_manufacturing/bakery_manufacturing/doctype/price_group_outlet
git rm --cached bakery_manufacturing/after_migrate.py \
  bakery_manufacturing/public/js/pos_walk_in_customer.js \
  bakery_manufacturing/fixtures/custom_field.json
git add bakery_manufacturing/overrides/pos_overrides.py README.md
git diff --cached --name-status
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
shasum -a 256 bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
```

The bundle needs no special handling at all. Its tracked content is one line and this task deletes that line, so the ordinary staged diff IS the intended change. Verify with `git diff --cached -- …bundle.js` that the staged diff is exactly the removal of `import "./pos_walk_in_customer.js";`, and that the working file still hashes to `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`.

**The `git update-index --cacheinfo` fabrication is rejected.** The original Step 10 mandated hashing an empty blob and writing it into the index so a commit would omit the 14 live worktree lines. Three consequences the original text did not account for:

1. The committed bundle becomes an EMPTY file. `bakery_manufacturing/tests/test_desk_sidebar.py` — which Global Constraint L25 protects and which Step 8 and Task 12 Step 6 both assert PASSES — would fail on any fresh checkout, because nothing would import the assets it checks. The plan mandates a change that breaks a test the same plan protects.
2. It leaves the index permanently divergent from the worktree in a shared checkout. One stray `git checkout`, `git reset`, or `git stash` by any tool or agent then destroys the operator's 14 uncommitted lines. The plan's own next paragraph admits "Git cannot safely switch the shared dirty checkout to that commit" — that is the fabrication's problem, not a fact about git.
3. It is unnecessary. Deleting the one tracked line and staging that deletion normally produces the correct commit, keeps the worktree suffix intact, and needs no index surgery.

Phase 1 handled this exact file this exact way across nine commits and two source checkouts, verifying the suffix hash by SHA-256 each time; the suffix constraint is honored better by ordinary git than by a fabricated index entry. Never use `git add` with a pathspec broader than the named paths, `git add .`, `git add -A`, `git stash`, `git reset`, or force checkout. Commit only after explicit bakery approval.

The paragraph about an "approved overlay procedure" and never claiming shared-checkout `HEAD == <SHA_BAKERY>` is dropped with it: no candidate commit with an empty bundle is created, so there is nothing to overlay. The rollout switches paths with ordinary path-scoped git commands.

- [ ] **Step 11: Stop for commit approval in every repository**

Stage every other approved path explicitly. Include `scripts/ownership_cutover.py` and `bakery_manufacturing/tests/test_ownership_cutover.py` in the bakery candidate. Include `roti_ropi_pos/hooks.py` in the Roti commit. Show cached name-status and cached diffs per repository. Confirm protected bakery and Roti paths remain unstaged.

---

### Task 11: `roti_ropi_pos` Contract Alignment

**Files:**
- Modify: `roti_ropi_pos/roti_ropi_pos/hooks.py`
- Modify: `roti_ropi_pos/roti_ropi_pos/tests/test_source_contracts.py`
- Modify: `roti_ropi_pos/AGENTS.md`
- Modify: `roti_ropi_pos/README.md`
- Do not modify: `roti_ropi_pos/roti_ropi_pos/mobile_pos/customers.py`
- Do not modify: `roti_ropi_pos/roti_ropi_pos/mobile_pos/invoices.py`
- Do not modify: `roti_ropi_pos/roti_ropi_pos/tests/test_sales.py`

**Interfaces:**
- Final dependency list is `required_apps = ["erpnext", "stock_additional", "selling_additional"]`.
- Public Mobile POS request and response fields are unchanged, including `walk_in_customer_name` and existing persistence.
- `roti_ropi_pos` imports no private `selling_additional` helper.

- [ ] **Step 1: Add the selling dependency and retarget source contracts**

Set `required_apps = ["erpnext", "stock_additional", "selling_additional"]`. Assert exact order in `test_source_contracts.py`.

After explicit Roti commit approval, stage `roti_ropi_pos/hooks.py`, `roti_ropi_pos/tests/test_source_contracts.py`, `AGENTS.md`, and `README.md` by exact path. Run `git diff --cached --name-status` and confirm `roti_ropi_pos/tests/test_sales.py` is absent before committing.



Two premises in the original text are already stale — Phase 1 fixed both. Verified against the current files:

- It said `test_source_contracts.py` "currently pins bakery in `TestBarcodeOverride` (three tests importing `bakery_manufacturing.overrides.barcode_scanner`)" and that the stock plan owns retargeting them. Already done: `TestBarcodeOverride` imports `stock_additional.overrides.barcode_scanner` (`:203`, `:215`, `:218`), reads hooks with `app_name="stock_additional"` (`:228`), and asserts the effective scanner is `stock_additional.overrides.barcode_scanner.custom_scan_barcode` (`:241`). Nothing to retarget. `required_apps` is asserted as `["erpnext", "stock_additional"]` at `:255` — that single assertion is what this task extends to three entries.
- Step 2 said `AGENTS.md` "currently states that `bakery_manufacturing` owns Price Group … and instructs integrating with bakery through hooks". Already rewritten: `AGENTS.md:16-17` reads "`stock_additional` owns Item custom UOM and barcode scanner behavior; `selling_additional` owns Price Group and walk-in selling behavior" and "`bakery_manufacturing` retains manufacturing behavior and temporary documented shims", and `:31` already routes the walk-in name to `selling_additional`. Step 2 is therefore a verification step, not a rewrite: confirm those lines still read that way and correct them only if they have drifted.

This task adds one new source contract:

```python
def test_effective_past_order_provider_is_selling_additional(self):
	self.assertEqual(
		frappe.override_whitelisted_method(
			"erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"
		),
		"selling_additional.overrides.pos_overrides.custom_get_past_order_list",
		"SOURCE CONTRACT: past-order override no longer owned by selling_additional",
	)
```

For the walk-in field persistence, EXTEND the existing `test_pos_invoice_has_walk_in_customer_name_field` to loop over `("POS Invoice", "Sales Invoice")` — do not add a second `test_walk_in_fields_remain_persisted`. The original text supplied that second test's full body and then, one line later, said "extend it to Sales Invoice rather than duplicating", mandating the duplication it forbade. Extending is the instruction that survives.

Also add the test for this task's third declared interface, "`roti_ropi_pos` imports no private `selling_additional` helper", which no step currently covers. Phase 1 has exactly this test for `stock_additional` and it caught real coupling, so mirror it: scan every `roti_ropi_pos` source file for imports from `selling_additional` and assert none names a private module member or an exception type. Roti consumes selling only through effective hooks and stable Frappe APIs. An interface stated in a task and asserted by no test is not an interface.

- [ ] **Step 2: Verify the ownership documentation still reads correctly**

`AGENTS.md:16-17` and `:31` already carry the post-cutover ownership statement, as recorded above. Confirm all three lines still read that way and that `README.md` names `selling_additional` as the owner of Price Group, walk-in behavior, past orders, and its navigation; `stock_additional` as the owner of Item custom UOM and scanning; and `bakery_manufacturing` as retaining only the Serial and Batch Bundle override plus documented temporary shims. Edit only what has drifted.

- [ ] **Step 3: Run the Roti suites**

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module roti_ropi_pos.tests.test_source_contracts
bench --site selling-cutover.localhost run-tests --app roti_ropi_pos
```

Expected: all pass with unchanged DTO and error contracts. Confirm `test_sales.py` is untouched and unstaged.

---

### Task 12: Fresh-Install, Populated-Upgrade, and Release Gates

**Files:**
- Create: `selling_additional/selling_additional/tests/test_install_paths.py`
- Create: `selling_additional/selling_additional/migration/checksums.py`
- Create: `selling_additional/selling_additional/tests/test_checksums.py`
- Create: `selling_additional/selling_additional/migration/recovery_map_digest.py`
- Create: `selling_additional/selling_additional/tests/test_recovery_map_digest.py`
- Verify only: all four app working trees

**Interfaces:**
- Consumes coordinated revisions of all four apps with the shell already installed.
- Produces the evidence set required by spec section 20.

- [ ] **Step 1: Add deterministic checksum and secret-safe map digest helpers**

Implement:

```python
def collect_business_checksums() -> dict[str, dict[str, str | int]]: ...


def recovery_map_digest() -> dict[str, str | int]: ...
```

`collect_business_checksums()` reads a fixed table-to-column allowlist for Price Group parents and both child tables, Price List, Item Price, POS Profile, Custom Field, and Workspace Sidebar Item. It sorts rows by stable primary identity, encodes canonical JSON with sorted keys and compact separators, and returns only `{table: {"rows": count, "sha256": digest}}`. Include every business field and ownership marker. Exclude only volatile framework columns listed beside each table. Never include `tabPatch Log`. The helper is read-only, executes no commit, and exposes no row values in output.

`recovery_map_digest()` calls `recovery_map.load()`, validates `dict[str, str]`, canonicalizes sorted keys with compact JSON, and returns only `{"entries": count, "sha256": digest}`. It never logs or returns keys or values. Tests patch logging, stdout, and exception paths to prove map content never escapes. Both helpers are bench-executable by dotted path.

Run:

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_checksums
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_recovery_map_digest
```

Expected: PASS. The operational plan uses these exact helpers.

- [ ] **Step 2: Fresh-install path**

Write `test_install_paths.py` with source and post-install assertions for the direct target path: shell guard permits zero Price Group DocTypes, `patches.txt` contains exactly two registered selling patches, all three target JSON files exist only under selling, and target fixtures contain exact six Custom Fields. After scratch install, assert patches are marked completed without executing adoption, all three DocTypes use `Selling Additional`, both moved fields retain `module: null`, ownership fields exist, hooks resolve solely to targets, and no legacy ownership marker or sidebar row is required.

On a scratch site with no Price Group metadata, install `erpnext`, then `stock_additional`, then `selling_additional` directly at target revisions. Task 6 must observe that none of the three DocTypes exists and perform no transfer. Fresh model and fixture sync must create all target metadata. Fresh install does not run cutover patches because Frappe marks app patches completed. Run:

```bash
cd /workspace/development/frappe-bench
bench --site selling-cutover.localhost run-tests \
  --module selling_additional.tests.test_install_paths
bench --site selling-cutover.localhost run-tests --app selling_additional
```

Expected: PASS.

- [ ] **Step 3: Populated-upgrade path**

Restore a database snapshot taken with bakery-owned Price Group data, install the `selling_additional` shell tag, then deploy the target revision and run one `bench migrate`. Assert afterwards:

- Every Price Group parent and child row is byte-identical in business fields.
- Every walk-in field value is unchanged.
- All three DocTypes report module `Selling Additional`.
- Every generated Price List, managed Item Price, and claimed profile carries the correct marker.
- Manual and scoped Item Prices are untouched.
- Zero Price Group items remain in ERPNext's `Selling` sidebar.
- `git -C apps/erpnext status --porcelain` and `git -C apps/frappe status --porcelain` show no new entries beyond the pre-existing unrelated work.

- [ ] **Step 4: Direct-target-install rejection path**

Extend `test_install_paths.py` with a populated bakery-owned metadata state and no selling shell Module Def. Call the shell guard directly and assert `frappe.ValidationError` before any Module Def, installed-app, DocType, or business-row write. Compare pre/post metadata and business checksums.

Do NOT re-implement the two guard cases `test_shell_contract.py` already covers and already passes — `test_direct_target_install_rejects_bakery_owned_price_group` and `test_fresh_target_install_without_legacy_metadata_passes` both patch `_target_price_group_json_exists` and `_bakery_owns_price_group` and assert exactly this. What this step adds beyond them is the unmocked, real-metadata path plus the checksum comparison. A second copy of an existing passing test is not extra coverage; it is a second thing to keep in sync.

Do not attempt a real direct target install on a disposable site as the original text directed: the guard is asserted directly and by the fresh-install path in Step 2, and creating another site to re-prove a `ValidationError` that two unit paths already prove buys nothing.

- [ ] **Step 5: Idempotency and forced-patch path**

Run a second normal migrate only to confirm Patch Log skip behavior. On the populated scratch site, snapshot checksums, then run both registered patches with exact CLI commands:

```bash
bench --site selling-cutover.localhost run-patch \
  selling_additional.patches.v1_0.transfer_price_group_ownership --force
bench --site selling-cutover.localhost run-patch \
  selling_additional.patches.v1_0.adopt_legacy_selling_state --force
```

Assert checksums and `modified` snapshots are unchanged. Never force-run these patches on an active site.

- [ ] **Step 6: Static checks, asset build, and full suites**

```bash
cd /workspace/development/frappe-bench/apps/selling_additional && pre-commit run --all-files && git diff --check
cd /workspace/development/frappe-bench/apps/stock_additional && pre-commit run --all-files && git diff --check
cd /workspace/development/frappe-bench/apps/bakery_manufacturing && pre-commit run --all-files && git diff --check
cd /workspace/development/frappe-bench/apps/roti_ropi_pos && pre-commit run --all-files && git diff --check
cd /workspace/development/frappe-bench && bench build --app selling_additional
bench build --app stock_additional
bench build --app bakery_manufacturing
bench --site selling-cutover.localhost run-tests --app selling_additional
bench --site selling-cutover.localhost run-tests --app stock_additional
bench --site selling-cutover.localhost run-tests --app bakery_manufacturing
bench --site selling-cutover.localhost run-tests --app roti_ropi_pos
bench --site selling-cutover.localhost run-tests --module erpnext.stock.tests.test_utils
bench --site selling-cutover.localhost run-tests --module erpnext.stock.doctype.item_price.test_item_price
bench --site selling-cutover.localhost run-tests --module erpnext.stock.doctype.price_list.test_price_list
bench --site selling-cutover.localhost run-tests --module erpnext.accounts.doctype.pos_invoice.test_pos_invoice
bench --site selling-cutover.localhost run-tests --module erpnext.accounts.doctype.pos_closing_entry.test_pos_closing_entry
```

Report a missing tool as a failure, not a pass.

The original text predicted that "the bakery Price Group source uses 4 spaces, so the copied controller will be reformatted to tabs — expected and acceptable." That prediction is FALSE and must not be used to wave through a reformat diff: `bakery_manufacturing/bakery_manufacturing/doctype/price_group/price_group.py` is already tab-indented (190 tab-indented lines, 0 space-indented). A copied controller therefore arrives already conforming to `ruff-format` with `indent-style = "tab"`. If `pre-commit` reports formatting changes to the copied controller, that is a real finding to investigate, not an expected reformat.

- [ ] **Step 7: Manual smoke tests**

1. Price Group: create, enable, add and remove items, change a rate, change an item's UOM, add and remove an outlet, disable, re-enable, delete. Verify a manual Item Price on the managed list survives every step.
2. Cross-group conflict: two groups targeting one profile — confirm one owner and a clear rejection.
3. Desk POS: walk-in name on the default customer accepted; on a registered customer rejected; a customer reset clears the field; only one input renders; no 1-second poll on other Desk routes.
4. Recent Orders: walk-in name displays through the standard renderer; searching it finds the invoice; the real Customer id is unchanged on the invoice.
5. Navigation: `Selling Additional` workspace and sidebar present with Price Group; ERPNext's Selling sidebar has no Price Group.
6. Mobile POS: bootstrap, search, scan, quote, sale, return, closing all behave unchanged.

- [ ] **Step 8: Independent review, then stop**

Use `superpowers:requesting-code-review` on every intended diff across the four repositories. Fix confirmed Critical and Important findings and rerun affected tests. Report SHAs, diffs, test output, preflight report, static checks, and smoke results. Push, tag, active-site install, and migration each require separate explicit approval.

---

## Verified Caveats

1. **`PriceList.on_update` is a landmine.** It runs a blanket `UPDATE tabItem Price SET currency, buying, selling` for the whole price list and can silently set `Selling Settings.selling_price_list` when none is configured. Verified at `apps/erpnext/erpnext/stock/doctype/price_list/price_list.py`. Every managed Price List field change after creation uses `frappe.db.set_value` plus `frappe.cache().hdel("price_list_details", name)`.

2. **`ItemPrice.update_price_list_details` throws on a disabled Price List.** Confirmed in `apps/erpnext/erpnext/stock/doctype/item_price/item_price.py`. This is the root cause of the disable-lifecycle defect, and the reason Item Price writes are skipped while disabled.

3. **`ItemPrice.validate_item` requires a `UOM Conversion Detail` row for a non-empty `uom`.** A managed Item Price for a custom UOM fails unless the Item carries that conversion row. The UOM-change test must add the row before asserting.

4. **`Item.validate` auto-appends a `conversion_factor = 1` row for the stock UOM.** Verified at `apps/erpnext/erpnext/stock/doctype/item/item.py:397`. Managed rows using the stock UOM therefore always satisfy caveat 3.

5. **Fixtures sync after `post_model_sync` patches.** `frappe/migrate.py:137-145` then `:169-171`. Ownership patches must create their own Custom Fields; they cannot depend on the fixture.

6. **Custom Field names are `dt + "-" + fieldname`.** `frappe/custom/doctype/custom_field/custom_field.py:128`. A `fieldname`-only fixture filter would sweep both walk-in fields plus anything else sharing the name — the exact mistake in bakery's current `fixtures` declaration.

7. **`page_js` runs before `on_page_load`.** `frappe/core/doctype/page/page.py:194` and `frappe/public/js/frappe/views/pageview.js:90` confirm this. The asset wraps the existing Page handler, calls it first, then mounts delegated wrapper events and one wrapper-scoped `MutationObserver`. It never patches `ItemCart` or re-requires ERPNext's bundle.

8. **`WorkspaceSidebar.before_save` re-exports JSON to the owning app's source tree under developer mode.** `frappe/desk/doctype/workspace_sidebar/workspace_sidebar.py:52-62`. This is how the Price Group edit leaked into `apps/erpnext`. No patch may call `save()` on ERPNext's sidebar.

9. **`delete_doc` runs `on_trash` before `check_if_doc_is_linked`.** `frappe/model/delete_doc.py:164-173`. A `force=True` Price List delete — the current bakery behavior — strands historical references. Keeping and disabling the Price List is the fix.

10. **Bakery's dirty bundle has a protected suffix.** The working tree starts with the tracked walk-in import and then 14 user lines. Cutover deletes only the import. The remaining file must equal approved suffix SHA-256 `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`.

11. **The ERPNext sidebar restore discards uncommitted content.** The current diff is exactly `13 1`, with nothing staged and clean committed source. Re-read the full diff and get explicit approval immediately before the one path-scoped checkout.

12. **`frappe.get_all` is not permission-aware; `frappe.db.get_list` is.** Keep `get_list` in the past-order override.

## Execution-Time Facts Still Required

1. **The shell must exist first.** Every `selling_additional` path is created by the shell and this cutover. Verify its generated `hooks.py` and `install.py` match the shell plan before applying this plan.

2. **Target-site app inventory is runtime data.** If `roti_ropi_pos_task11` or any unexpected app is installed, preflight must include its hooks and old-path references. Any competing provider blocks cutover.

3. **Recovery effort depends on live profiles.** POS Profile does not enable `track_changes`. Version rows are advisory only. Every affected profile still needs an approved operator-map entry.

4. **Recovery-map transport is an operator choice.** This plan defines the loader contract but does not print or persist the map. The coordinated rollout must record the approved secret-safe injection mechanism before migration.

5. **ERPNext regression paths must exist at execution time.** Use verified installed modules in Task 12. Do not rely on a nonexistent POS Page test module.

### Critical Files for Implementation

- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/bakery_manufacturing/bakery_manufacturing/bakery_manufacturing/doctype/price_group/price_group.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/bakery_manufacturing/bakery_manufacturing/hooks.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/bakery_manufacturing/bakery_manufacturing/overrides/pos_overrides.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/bakery_manufacturing/bakery_manufacturing/after_migrate.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/erpnext/erpnext/stock/doctype/item_price/item_price.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/erpnext/erpnext/stock/doctype/price_list/price_list.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/erpnext/erpnext/selling/page/point_of_sale/point_of_sale.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/erpnext/erpnext/selling/page/point_of_sale/pos_item_cart.js`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/erpnext/erpnext/workspace_sidebar/selling.json`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/frappe/frappe/desk/doctype/workspace_sidebar/workspace_sidebar.py`
- `/Users/rotiropi/DockerERPNext/frappe_docker/development/frappe-bench/apps/roti_ropi_pos/docs/superpowers/plans/2026-08-14-stock-additional-cutover.md`
