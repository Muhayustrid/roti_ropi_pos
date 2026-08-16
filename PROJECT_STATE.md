# PROJECT_STATE.md — AI session resume checkpoint

**Last updated:** 2026-08-16, after Phase 2 Task 6 closed and the documentation checkpoint committed.
**Resume point:** Phase 2 Task 7.

This file is the current-state save game, not a history. Git, tests, and the live site override it.
If it conflicts with verified evidence, fix this file.

---

## 1. Objective

Extract generic stock and selling extensions out of `bakery_manufacturing` into two dedicated apps so
ownership follows feature boundaries:

- `stock_additional` — Item custom UOM, barcode scanner behaviour
- `selling_additional` — Price Group, walk-in selling, POS past-order override
- `bakery_manufacturing` — keeps only manufacturing behaviour plus documented temporary shims
- `roti_ropi_pos` — unchanged Mobile POS API facade; consumes the extracted apps through effective
  hooks and persisted ERPNext data only

Design authority: `docs/superpowers/specs/2026-08-14-app-ownership-extraction-design.md`.
No DocType name, Custom Field name, table, or business row may change. Do not infer requirements the
spec does not state.

---

## 2. Roadmap

| Phase | Plan | Status |
|---|---|---|
| 0 — app shells | `docs/superpowers/plans/2026-08-14-additional-app-shells.md` | Complete |
| 1 — stock cutover | `docs/superpowers/plans/2026-08-14-stock-additional-cutover.md` | Complete and closed |
| 2 — selling cutover | `docs/superpowers/plans/2026-08-14-selling-additional-cutover.md` | Tasks 1-6 complete; Task 7 next |
| 3 — production rollout | `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md` | Not started, not approved |

Phase 2 task state (12 tasks; titles are in the plan, do not invent them):

- Tasks 1-6: complete
- **Task 7 — One `post_model_sync` Adoption Patch: NEXT**
- Tasks 8-12: pending, in order

Execution ledger (authoritative per-task record, including every ruling):
`.superpowers/sdd/2026-08-14-selling-additional-cutover/progress.md`. A task is done only when that
file carries a `## Task <N>: complete` line. Per-task briefs, dispatch notes and implementer reports
live beside it.

---

## 3. Verified current ownership

Measured on `selling-cutover.localhost` after the Task 6 migrate:

- `Price Group`, `Price Group Item`, `Price Group Outlet` all report `module = Selling Additional`;
  each row's `migration_hash` matches the md5 of the **selling** JSON on disk.
- `get_controller("Price Group").__module__` is
  `selling_additional.selling_additional.doctype.price_group.price_group`.
- `selling_additional` owns the past-order override
  (`overrides.pos_overrides.custom_get_past_order_list`), walk-in `validate` doc_events for POS
  Invoice and Sales Invoice, and `page_js` for `point-of-sale`.
- Bakery still carries its own copy of the three DocType JSONs, its past-order registration, its
  walk-in bundle import, and its `after_migrate` sidebar hook. **This overlap is intentional** and
  bounded by Tasks 6-10; Task 10 removes bakery's side.
- The legacy ERPNext sidebar child `e8qdqgq5g0` (`parent='Selling'`, `idx 25`, label/link_to
  `Price Group`) is still present. Tasks 9 and 10 own it.

---

## 4. Non-negotiable contracts

Business and data identity:

- Keep the DocType names `Price Group`, `Price Group Item`, `Price Group Outlet` and every table,
  field, and business row unchanged.
- Keep the generated Price List naming convention `PG-<price_group_name>`.
- Deleting a Price Group KEEPS its generated Price List, disabled (spec §8.5) — a delete-based test
  cleanup can never restore the pre-test state.
- Never `frappe.delete_doc(..., force=True)` in Price Group lifecycle code.
- Never save a Price List document when only Item Price rows must change (`PriceList.on_update`
  raw-UPDATEs every row on the list, including manual ones).

Sidebar and source-tree safety:

- Never call `WorkspaceSidebar.save()` in a patch, never assign `sidebar.items`, never replace a
  sidebar parent's child table. `before_save` → `export_sidebar()` rewrites the owning app's JSON on
  disk when `developer_mode` is on — that is how the Price Group child leaked into
  `apps/erpnext/erpnext/workspace_sidebar/selling.json`. Delete child rows with
  `frappe.db.delete("Workspace Sidebar Item", {"name": row_name})` only.
- Never edit `apps/frappe` or `apps/erpnext`, except the one separately approved path-scoped restore
  of `erpnext/workspace_sidebar/selling.json` in Task 10.
- Do not touch `apps/erpnext/banking/yarn.lock`, `apps/erpnext/.codegraph/`, or
  `apps/erpnext/graphify-out/`.
- Never modify or stage `bakery_manufacturing/.../tests/test_desk_sidebar.py`.
- Bakery's bundle has one tracked walk-in import plus a 14-line uncommitted prototype suffix that
  must stay byte-identical: SHA-256
  `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1` (last 14 lines).

Cross-app boundaries:

- `roti_ropi_pos` must not import `stock_additional` / `selling_additional` private helpers or
  exception types. Integrate through registered hooks, persisted data, or public contracts.
- Mobile POS public request/response fields and error codes are unchanged, including
  `walk_in_customer_name`.
- Final Roti dependency list (Task 11): `required_apps = ["erpnext", "stock_additional", "selling_additional"]`.

Migration facts that shape every patch (measured in installed source, not assumed):

- **There is no whole-migrate transaction.** `patch_handler.execute_patch` commits before the patch
  and again on success, rolling back only that patch on failure; `migrate.py` commits per phase;
  `model/sync.py` commits per imported file. A later failure leaves earlier patches committed.
- `execute_patch` resolves `<module>.execute` via `frappe.get_attr` **before** running anything, so a
  registered patch with no `execute()` aborts the migrate at resolution time — nothing partial runs.
- `after_migrate` hooks run at the very END of migrate, after all patches. A patch cannot outlast a
  hook that recreates what it deleted in the same run.
- `import_file_by_path` skips a DocType whose stored `migration_hash` equals the file's md5, and
  otherwise compares `modified` timestamps; re-import uses `for_reload=True`, which is non-destructive
  to business data.
- `sync_fixtures` imports with `force=True` — fixture imports overwrite unconditionally, no hash skip.
- `IntegrationTestCase` in this bench has **no per-test rollback** (only
  `addClassCleanup(_rollback_db)`). Register `self.addCleanup(frappe.db.rollback)` first in `setUp`
  so it runs last.

---

## 5. Completed work, compressed

**Phase 0** — both app shells exist, installed, inactive.

**Phase 1 (stock)** — closed. `stock_additional` owns Item custom UOM and the barcode scanner;
`roti_ropi_pos.tests.test_source_contracts.TestBarcodeOverride` already asserts the effective scanner
is `stock_additional.overrides.barcode_scanner.custom_scan_barcode`, and `required_apps` is
`["erpnext", "stock_additional"]` — Task 11 extends that single assertion to three entries.

**Phase 2 Tasks 1-5:**

1. Price Group lifecycle contracts pinned as failing tests; several were vacuous and were rebuilt.
2. The three DocTypes were copied into `selling_additional` with `module = Selling Additional` and a
   newer `modified` stamp than bakery's; `ownership.py` defines the marker fields
   (`custom_selling_additional_price_group`, `custom_selling_additional_previous_price_list`),
   `MANAGED_PRICE_LIST_PREFIX = "PG-"`, and the Item Price scope fields.
3. `PriceGroup` reimplemented standalone (`PriceGroup(Document)`), with no bakery import and no hook —
   tests force controller resolution in `setUp` instead.
4. Walk-in validation and the Desk asset moved: `doc_events` validate on POS Invoice and Sales
   Invoice, `page_js` for `point-of-sale`.
5. Past-order override moved with a server-side projection
   (`selling_additional.overrides.pos_overrides.custom_get_past_order_list`).

Architectural decisions worth not rediscovering: no `frappe.db.commit()` in any test in this phase
(one did, and it turned a transient failure into permanent site residue); mutation testing is the
review technique of record here — reading found almost none of the real defects.

---

## 6. Phase 2 Task 6 — final state

**Objective:** a `pre_model_sync` patch that moves the three DocTypes' `module` from
`Bakery Manufacturing` to `Selling Additional`, guarded by a read-only preflight, plus the
`patches.txt` registration and the migrate that makes it real.

**Status: COMPLETE.**

Files (app `selling_additional`, all still uncommitted):

- `selling_additional/patches/v1_0/transfer_price_group_ownership.py` (new) — `preflight.check(...)`,
  fresh-site early return, already-transferred early return, validate all three modules, then
  `frappe.db.set_value(..., update_modified=False)` per DocType, then `clear_controller_cache` and
  `clear_doctype_cache` per DocType.
- `selling_additional/migration/preflight.py` — added `TARGET_DOCTYPES` / `SOURCE_MODULE` /
  `TARGET_MODULE` and `collect_doctype_transfer_state(phase)`, wired into the existing `doctypes`
  section. Still read-only. Rules: 0 of 3 present = fresh; 1-2 present = problem; 3 present with a
  module set that is neither all-source nor all-target = problem; plus an unconditional
  `Module Def "Selling Additional"` check. Only the `pre_model_sync` phase is evaluated.
- `selling_additional/patches.txt` — both sections registered, byte-pinned by
  `test_patches_file_has_both_migration_sections`.
- `selling_additional/tests/test_module_transfer_patch.py` (new) — 11 tests.
- `selling_additional/tests/test_shell_contract.py` —
  `test_module_exists_without_ownership_transfer` renamed `test_module_owns_transferred_doctypes`,
  now asserting all three DocTypes report `Selling Additional`.

**Verification (all measured by the controller, not read from a report):**

- `mutation_task6.py`: baseline `Ran 11 tests OK`, **12 of 12 mutations caught, zero survivors**;
  source restored and re-verified by grep.
- Transfer suite green on three consecutive runs; site residue probe clean after each.
- `uvx ruff check .` → `All checks passed!`; `uvx ruff format --check .` → `35 files already formatted`.
  (`uvx` is at `/home/frappe/.local/bin/uvx`; plain `ruff` is not installed.)
- `bench migrate` run twice on `selling-cutover.localhost`. All three modules are
  `Selling Additional` after both, `migration_hash` matches selling's files, and run 2 skipped the
  patch entirely via its `Patch Log` row while still re-syncing DocTypes — migrate-level idempotency
  that no unit test can show.
- The two RED-until-migrate assertions turned GREEN:
  `test_hooks.test_price_group_doctypes_belong_to_selling_additional` and
  `test_shell_contract.test_module_owns_transferred_doctypes`.

**Known issue, accepted by ruling, not a defect:** both migrate runs exit 1 at `post_model_sync` with
`AttributeError: module 'selling_additional.patches.v1_0.adopt_legacy_selling_state' has no attribute
'execute'`. Task 6's brief mandates registering that patch AND migrating in the same task, while
Task 7 is the task that writes its `execute()`. A stub was rejected: it would record a `Patch Log`
row and make Task 7's real patch skip on the next migrate. **Task 7 closes this.** Full reasoning:
Ruling AE in the ledger.

**Expected baseline failures right now** (all named, all owned by a later task):

- `test_hooks`: `failures=3` — `test_exact_custom_field_fixture_identity` (Task 7 adds
  `hooks.fixtures`), `test_no_global_desk_asset` and `test_exactly_one_past_order_provider` (Task 10).
- `test_shell_contract`: `failures=1` — `test_shell_registers_no_moved_runtime_ownership`, RED since
  Task 5, retired by Task 7 Step 7.
- `roti_ropi_pos.tests.test_source_contracts` → `Ran 33 tests OK`.

---

## 7. Blockers and dependencies

- Task 7 is unblocked. Task 6 delivered exactly its precondition: all three DocTypes report
  `Selling Additional` in the DB.
- Task 7 must also restore a clean-exit migrate by adding `execute()` to
  `adopt_legacy_selling_state.py`.
- Tasks 9 and 10 are coupled: bakery's `after_migrate` recreates the sidebar row that adoption
  deletes, and `after_migrate` runs last. So the `legacy_sidebar_item` preflight rule must treat
  **zero or one** exact row per parent as clean and block only on two or more. Do not write a test
  asserting the row stays absent across a migrate before Task 10.
- Task 8's DB-state assertions stay RED until a migrate imports its JSON (Task 12).
- **Task 11 Step 3 as written cannot pass on this site.** `bench run-tests --app roti_ropi_pos` dies
  during *discovery*: `roti_ropi_pos/tests/test_return_task10.py:8` imports an ERPNext test module
  whose `erpnext/tests/utils.py` ends in a module-scope `BootStrapTestData()`; its `Standard Buying`
  guard compares `currency` and hardcodes `INR`, while this site's row is `IDR`, so it re-inserts and
  hits `Duplicate entry 'Standard Buying' for key 'PRIMARY'`. Pre-existing, unrelated to Phase 2.
  Run Roti per-module instead. Do not "fix" it by editing the site's Price List currency — that is
  operator business data. Full detail: Ruling AF.

---

## 8. Pre-existing / unrelated state — do not modify

- `apps/erpnext` porcelain is exactly ` M banking/yarn.lock`,
  ` M erpnext/workspace_sidebar/selling.json` (diff exactly `13 1`), `?? .codegraph/`,
  `?? graphify-out/`. The sidebar diff is Task 10's to revert; the rest is not ours.
- `apps/bakery_manufacturing`: ` M bakery_manufacturing/public/js/bakery_manufacturing.bundle.js`
  (the protected 14-line suffix), plus untracked `tests/test_desk_sidebar.py`, `diference.md`,
  `graphify-out/`.
- `apps/roti_ropi_pos`: two one-line tracked edits (spec status line; a `test_sales.py` teardown that
  closes an opening instead of deleting it) plus untracked tooling and plan directories.
- `development.localhost` holds shared real business data. Never delete data there, never commit in
  its tests, read-only comparison at most. All Phase 2 work happens on `selling-cutover.localhost`.
- Backup in place: `sites/selling-cutover.localhost/private/backups/20260816_160438-selling-cutover_localhost-database.sql.gz`.

Committed so far — documentation only, nothing pushed:

- `stock_additional` `d94f5bf` — `docs: add repository agent instructions` (`AGENTS.md`, `CLAUDE.md`).
- `selling_additional` `5a11fd1` — `docs: add repository agent instructions` (`AGENTS.md`, `CLAUDE.md`).
- `roti_ropi_pos` — this checkpoint plus `AGENTS.md` and `CLAUDE.md`, at the current `HEAD`.

No implementation work is committed in any app. No branch has been pushed. Roti's spec status line
and `test_sales.py` teardown edit stay deliberately uncommitted: they are not part of the
documentation set.

---

## 9. Authorization boundaries (unchanged — no new authority granted)

- No commit, push, tag, deploy, or Phase 3 rollout without separate explicit approval per phase.
- `bench migrate` on `selling-cutover.localhost` was approved for Tasks 6-7 only. Any other migrate
  needs its own approval. Never migrate an active site.
- `bench run-patch --force` runs on `selling-cutover.localhost` only, by the controller, never on
  `development.localhost`.
- The single-file restore of `apps/erpnext/erpnext/workspace_sidebar/selling.json` is authorized for
  Task 10 only, path-scoped.
- `sites/apps.txt` and site config are protected from agent edits.
- Never use `docker exec -it`. Never run two suites concurrently against one site (they deadlock on
  `tabSingles`); check for orphan `loadTestsFromName` processes first. The container is
  `frappe_docker_devcontainer-frappe-1`.
- Never probe Custom Field creation on a shared site — `ALTER TABLE` escapes rollback.
- Do not create HRMS master records or edit chart-of-accounts Accounts.
- The POS Profile recovery map is live business configuration: never place its content in Git, site
  config, logs, plan text, or shell history.
- Subagent models: Haiku/Sonnet for exploration and implementation; Opus for reviewer roles only.
- Tests may hardcode; production code must derive.

---

## 10. Resume here

Next task: **Phase 2 Task 7 — One `post_model_sync` Adoption Patch.** Do not repeat Task 6
investigation; its transfer is done, migrated, and mutation-verified.

1. Read, in order: this file; `AGENTS.md`; the ledger
   `.superpowers/sdd/2026-08-14-selling-additional-cutover/progress.md` (skim the Task 6 section and
   Rulings AA, AE, AF); then `task-7-brief.md` and `task-7-dispatch-notes.md` in the same directory —
   **the dispatch notes win wherever they disagree with the brief.**
2. Plan section that controls the task: `docs/superpowers/plans/2026-08-14-selling-additional-cutover.md`
   at `### Task 7: One post_model_sync Adoption Patch` (line ~852). Global Constraints are near the
   top of the same file.
3. Verify state before acting: `git status --porcelain` in `apps/selling_additional`,
   `apps/bakery_manufacturing`, `apps/erpnext`, `apps/roti_ropi_pos` against section 8 above; confirm
   all three DocTypes still report `Selling Additional`; check for orphan test processes in the
   container.
4. Navigation: use `codegraph_explore` first — e.g. `codegraph_explore "adopt_legacy_selling_state
   ensure_ownership_fields preflight run assert_clean"` — before grep or broad reads. Fall back to
   direct source reads for exact framework behaviour.
5. First meaningful action: read
   `selling_additional/patches/v1_0/adopt_legacy_selling_state.py` (currently
   `ensure_ownership_fields()` only, no `execute()`) together with `migration/preflight.py`, then
   compose the Task 7 dispatch from `task-7-brief.md` + `task-7-dispatch-notes.md`. Task 7's
   `execute()` is what makes `bench migrate` exit 0 again.
6. Two corrections already ruled on and carried in the notes: the terminal assertion inside the
   adoption patch is `post_model_sync`, never `final`; and the plan's claim that "Frappe's migrate
   transaction rolls back all later writes" is false — there is no such transaction.
