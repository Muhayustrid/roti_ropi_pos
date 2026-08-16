# PROJECT_STATE.md — AI session resume checkpoint

**Last updated:** 2026-08-16, after the authorized final migrate of `selling-cutover.localhost` and
its verification pass.
**Resume point:** Phase 2 is complete and the cutover site is migrated and fully green (zero RED
tests). Still open and still unapproved: the commit-approval window for the Phase 2 implementation
diffs, and Phase 3.

This file is the current-state save game, not a history. Git, tests, and the live site override it.
If it conflicts with verified evidence, fix this file.

---

## 1. Objective

Extract generic stock and selling extensions out of `bakery_manufacturing` into two dedicated apps so
ownership follows feature boundaries:

- `stock_additional` — Item custom UOM, barcode scanner behaviour (Phase 1, closed)
- `selling_additional` — Price Group, walk-in selling, POS past-order override, own navigation (Phase 2, complete)
- `bakery_manufacturing` — manufacturing behaviour plus documented temporary shims only
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
| 2 — selling cutover | `docs/superpowers/plans/2026-08-14-selling-additional-cutover.md` | **Complete — all 12 tasks, final gate, independent review, and the authorized cutover-site migrate all passed** |
| 3 — production rollout | `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md` | Not started, not approved |

Execution ledger (authoritative per-task record, including every ruling):
`.superpowers/sdd/2026-08-14-selling-additional-cutover/progress.md`. Every Phase 2 task
(1 through 12) carries a `## Task <N>: complete` line there, plus the final-gate and reviewer
record ("Phase 2 final gate and independent review") and the closure record
("Phase 2 closure — final authorized migrate on `selling-cutover.localhost`", including Ruling AJ).
Per-task briefs, dispatch notes, and implementer reports live beside it.

---

## 3. Verified current ownership (post-Phase-2, all measured)

- `Price Group`, `Price Group Item`, `Price Group Outlet`: `module = Selling Additional`;
  `migration_hash` matches selling's JSON md5 on the cutover site; selling ships the only copies on
  disk (bakery's folders deleted).
- `selling_additional` owns: the past-order override (sole provider — enumerated across installed
  apps), walk-in `validate` doc_events on POS/Sales Invoice, `page_js` for `point-of-sale`, the
  six-Name Custom Field fixture, own Workspace + Workspace Sidebar (JSON-imported; live on
  `selling-cutover.localhost` with children `Home` idx 1 and `Price Group` idx 2).
- `bakery_manufacturing` retains: `override_doctype_class` for Serial and Batch Bundle,
  `required_apps = ["erpnext"]`, one plan-mandated lazy shim
  (`overrides/pos_overrides.custom_get_past_order_list` → selling's implementation; no hook, no
  whitelist), and the README deprecation notes.
- `roti_ropi_pos`: `required_apps = ["erpnext", "stock_additional", "selling_additional"]`; source
  contracts pin the sole past-order provider, both walk-in fields, and a zero-import boundary
  (ast scan) against selling.
- Cross-app import greps: selling production code imports nothing from bakery/stock/roti; roti
  production imports nothing from selling; stock imports nothing from selling.
- `preflight.check(phase="final")` exits 0 with all sections clean on `selling-cutover.localhost`
  AND on the fully migrated rehearsal site `selling-upgrade.localhost`.
- ERPNext's `Selling` sidebar carries **zero** legacy `Price Group` children on
  `selling-cutover.localhost`, and bakery's `after_migrate` no longer exists to recreate one.

---

## 4. Non-negotiable contracts

Business and data identity:

- Keep the DocType names `Price Group`, `Price Group Item`, `Price Group Outlet` and every table,
  field, and business row unchanged.
- Keep the generated Price List naming convention `PG-<price_group_name>`.
- Deleting a Price Group KEEPS its generated Price List, disabled (spec §8.5).
- Never `frappe.delete_doc(..., force=True)` in Price Group lifecycle code.
- Never save a Price List document when only Item Price rows must change (`PriceList.on_update`
  raw-UPDATEs every row on the list and can claim `Selling Settings.selling_price_list`).
- `SCOPE_FIELDS` deliberately excludes `valid_from` (meta default 'Today'); do not "complete" it.

Sidebar and source-tree safety:

- Never call `WorkspaceSidebar.save()` in a patch, never assign `sidebar.items`, never replace a
  sidebar parent's child table. Delete child rows with `frappe.db.delete("Workspace Sidebar Item",
  {"name": row_name})` only.
- Never edit `apps/frappe` or `apps/erpnext`. The one authorized Task 10 path-scoped restore of
  `erpnext/workspace_sidebar/selling.json` has been executed and verified.
- Do not touch `apps/erpnext/banking/yarn.lock`, `apps/erpnext/.codegraph/`,
  `apps/erpnext/graphify-out/`.
- Never modify or stage `bakery_manufacturing/.../tests/test_desk_sidebar.py`.
- The bakery bundle's 14-line suffix must stay byte-identical: SHA-256
  `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1` (numstat `14 1`, unstaged).
  `.pre-commit-config.yaml` excludes the bundle from prettier and eslint (Ruling AI).

Cross-app boundaries:

- No private cross-app imports in either direction (bakery's one mandated lazy shim excepted).
- Mobile POS public request/response fields and error codes unchanged, including
  `walk_in_customer_name`.
- The recovery map is live operator configuration: its keys and values never appear verbatim in
  code, logs, problem strings, or terminals — map-side identifiers surface only as 8-hex digests
  (`preflight._redact`); the needs side (DB-derived) may be named in the protected-storage report.

Migration facts that shaped every patch (measured, stable):

- No whole-migrate transaction; each patch commits before and after; a later failure leaves earlier
  patches committed. Backup is the recovery boundary.
- `post_model_sync` patches run BEFORE `sync_fixtures`; ownership patches create their own Custom
  Fields (Ruling AG).
- `after_migrate` hooks run last (why bakery's sidebar hook had to be removed at source, Task 10).
- `Patch Log` suppresses re-execution; forced re-runs and fresh installs still happen, so patches
  stay idempotent — proven by forced re-runs with identical checksums.

---

## 5. Completed work, compressed

**Phases 0-1** — shells installed; stock cutover closed (scanner + custom UOM with
`stock_additional`, Roti contract updated then extended in Phase 2 Task 11).

**Phase 2** — all twelve tasks complete; executed by the controller directly from Task 7 on
(no subagents for implementation; one read-only reviewer subagent at the end):

- Tasks 1-6 (pre-Task-7): lifecycle contracts pinned; DocTypes moved with newer `modified` stamps;
  standalone `PriceGroup` controller; walk-in validation + page-scoped asset; past-order override;
  `pre_model_sync` transfer patch + migrate.
- Task 7: adoption patch `execute()` (11 steps, terminal `post_model_sync`), six-object fixture,
  `hooks.fixtures`, `recovery_map.load()` (env-var file transport), real preflight sections with
  pre/post/final rules, runtime NULL-uom collision guard, migrate exit 0 twice. Ruling AG.
- Task 8: own Workspace + Workspace Sidebar JSONs (ERPNext-exact shapes, `module_onboarding`
  omitted), navigation tests (structure green from the start; DB-state green after the final
  authorized migrate imported the records).
- Task 9: `collect_legacy_sidebar_rows()` generalization (`Selling` + per-user `Selling-*`,
  Python-filtered), per-parent validation, bootinfo cache clear, 9-test cleanup suite.
- Task 10: bakery handoff (hooks stripped, DocType folders/after_migrate/fixtures/walk-in asset
  deleted via `git rm`, bundle line 1 removed byte-surgically, lazy shim, README), ERPNext sidebar
  leak restored under all abort conditions, staging by name. Rulings AH (bundle-staging
  contradiction — open decision for the commit window).
- Task 11: Roti `required_apps` + three-entry assertion, sole past-order provider contract,
  walk-in fields on both doctypes, ast no-private-import scan, README ownership. Ruling AF governs
  Roti suite limits.
- Task 12: `collect_business_checksums()` + `recovery_map_digest()` (+8 and +6 tests);
  `test_install_paths.py` (10 tests); fresh-install rehearsal on `selling-fresh.localhost`;
  populated-upgrade rehearsal on `selling-upgrade.localhost` (pre-cutover snapshot restored, ONE
  migrate exit 0, both patches executed for real, business checksums identical, sidebar zero with
  nothing to recreate it, preflight final clean); forced re-runs idempotent; static checks + builds
  clean. Ruling AI (prettier incident, oracle-exact recovery, hook exclusion).
- Final gate + reviewer: zero Critical; one Important (recovery-map redaction through `check()`
  raises) — FIXED, re-verified, mutation-caught; three Minors recorded and deferred (map read twice
  in `execute()`; sidebar parent title-only matching vs design §14.2; `diference.md` inventory).
- Closure: the authorized `selling-cutover.localhost` migrate (exit 0, backup
  `20260816_213539` first), a sanctioned forced adopt run to delete the legacy sidebar row that
  `Patch Log` suppression had left behind, and Ruling AJ — two test modules had encoded the
  pre-migrate sidebar row as a site constant and now construct it, with stronger assertions and
  both mutations still caught.

Architectural decisions worth not rediscovering: mutation testing is the review technique of record
(8/8 + 3/3 + 2/2 + 1/1 + 2/2 caught across tasks); no `frappe.db.commit()` in any Phase 2 test;
rollback-first cleanup ordering everywhere; fixture byte-identity pinned by recorded literals after
Task 10 deleted bakery's file; test fixtures construct the state they judge instead of depending on
a migrate-dependent live row.

---

## 6. Current expected state (verify against this before acting)

`selling-cutover.localhost` is **migrated and green**. The migrate ran under its own explicit
approval on 2026-08-16 (exit 0); both registered patches were skipped by `Patch Log` (rows from the
Task 6/7-era migrate), so the legacy ERPNext sidebar row was removed by a sanctioned
`run-patch … adopt_legacy_selling_state --force` on this dedicated site — see the ledger's closure
record. Fresh backup taken first:
`sites/selling-cutover.localhost/private/backups/20260816_213539-selling-cutover_localhost-database.sql.gz`.

Test baselines on `selling-cutover.localhost`:

- `run-tests --app selling_additional`: `Ran 159 tests OK` + `Ran 24 tests OK`. **No RED remains** —
  the four navigation DB-state tests turned green with the workspace/sidebar import and the sidebar
  row deletion. Confirmed on three consecutive runs.
- `--app stock_additional` 35 + 22 OK; `--app bakery_manufacturing` 4 OK (barcode shim ×3 plus the
  protected untracked sidebar test); `roti_ropi_pos.tests.test_source_contracts` 35 OK, and per
  module: api_foundation 14, authentication 24, bootstrap 9, catalog 19, customers 7, idempotency 27,
  opening_amounts 21, sessions 10 — all OK.
- Unchanged pre-existing blocks, none caused by Phase 2: `--app roti_ropi_pos` and ERPNext's
  `item_price` / `pos_invoice` modules fail at **discovery** on the INR/IDR `Standard Buying`
  duplicate (Ruling AF); `erpnext…test_price_list` exposes no tests here; `test_closing` is
  environment-limited by the site's empty `Selling Settings.selling_price_list`.
- `uvx ruff check .` clean. For the format gate **pin `ruff@0.14.10`** to match
  `.pre-commit-config.yaml`; the ambient `uvx ruff` is `0.16.3` and disagrees on line wrapping.

Two test modules were repaired during closure (Ruling AJ): `test_sidebar_cleanup` and
`test_preflight.TestLegacySidebarItem` had encoded the pre-migrate legacy sidebar row as a site
constant. They now construct the row they judge and assert exact identities. Test-side only; no
production change; both mutations still caught.

Working trees (**nothing implementation-committed anywhere; nothing pushed**):

- `selling_additional`: ` M hooks.py`, ` M patches.txt`, ` M tests/test_shell_contract.py` + the
  Phase 2 untracked set (migration/, patches/v1_0/, fixtures/, overrides/, ownership.py,
  doctype/, workspace JSONs, public/js, tests/*).
- `bakery_manufacturing`: staged handoff by name (3 M + 14 D); unstaged ` M .pre-commit-config.yaml`
  (bundle hook exclusion), ` M bakery_manufacturing.bundle.js` (protected suffix, `8b0431…`,
  `14 1`), ` M tests/test_barcode_scanner_shim.py` (ruff autoformat, semantics identical);
  untracked protected `tests/test_desk_sidebar.py`, `diference.md` (operator doc — keep out of any
  staging), `graphify-out/`.
- `roti_ropi_pos`: unstaged Phase 2 files (`hooks.py`, `tests/test_source_contracts.py`,
  `README.md`, `PROJECT_STATE.md`) + pre-existing unrelated edits (spec status line,
  `tests/test_sales.py` teardown) that stay uncommitted; untracked tooling/plan dirs.
- `apps/erpnext`: exactly ` M banking/yarn.lock`, `?? .codegraph/`, `?? graphify-out/` — the
  sidebar leak is gone and `erpnext/workspace_sidebar/selling.json` has no diff.
  `apps/frappe`: only untracked tool dirs.

Scratch sites created by Task 12 (safe to keep for evidence; safe to drop with approval):
`selling-fresh.localhost` (fresh-install proof), `selling-upgrade.localhost` (populated-upgrade
proof, migrated, final-clean).

Backups: `…/private/backups/20260816_213539-…` (pre-final-migrate — the current recovery boundary),
`…/20260816_195140-…` (pre-Task-7-migrate), `…/20260816_160438-…` (pre-Task-6-migrate; also the
rehearsal restore source).

---

## 7. Open items and deferred findings (none block Phase 2 closure)

1. **Ruling AH — bundle staging decision.** Plan Task 10 Step 10's mandated staged diff ("exactly
   the import removal" with the 14 lines unstaged) implies an empty committed bundle, which its own
   objection 1 rejects; plain `git add` would stage the protected lines, which the same step
   forbids. The bundle is left UNSTAGED; the commit-approval window must choose: commit the 14
   lines, commit an empty bundle, or keep the bundle as a per-checkout overlay (rollout language).
2. Deferred Minor findings (recorded in the ledger's final-gate section): double `recovery_map.load()`
   inside `execute()`; sidebar parent matching without an `app` filter; `diference.md` inventory.
3. Visual Desk smoke (input rendering, no-timer on other routes, sidebar appearance) deferred to
   the operator's smoke window — automated equivalents exist (`test_walk_in_asset`,
   `test_navigation`).
4. Both cutover patches now carry `Patch Log` rows on `selling-cutover.localhost`, so a future
   migrate of this site will skip them. That is correct framework behaviour and matters only for
   rehearsals: restore a pre-cutover snapshot onto a scratch site to exercise the patches for real.

---

## 8. Pre-existing / unrelated state — do not modify

- `development.localhost` holds shared real business data: read-only comparison at most, never
  written. Phase 2 work used `selling-cutover.localhost` plus the two Task 12 scratch sites.
- `apps/erpnext/banking/yarn.lock`, `.codegraph/`, `graphify-out/` dirs in erpnext/frappe/bakery:
  not ours.
- Roti's spec status line and `test_sales.py` teardown edit stay deliberately uncommitted.

Committed so far — documentation only, nothing pushed: `stock_additional` `d94f5bf` and `8422130`,
`selling_additional` `5a11fd1` and `2da49a6`, roti checkpoint + AGENTS/CLAUDE at `ccffc19`.
**No Phase 2 implementation work is committed in any app. No branch has been pushed.** A session
opened by stating the commit window was finished; Git contradicted that, and the discrepancy is
recorded in the ledger's closure record rather than reconciled — commit approval is still OPEN.

---

## 9. Authorization boundaries (unchanged — no new authority granted)

- No commit, push, tag, deploy, or Phase 3 rollout without separate explicit approval per phase.
  The Task 6-7 migrate approval and the 2026-08-16 final-migrate approval on
  `selling-cutover.localhost` are both SPENT; any further migrate needs its own approval.
- `bench run-patch --force` runs only on dedicated/scratch sites, by the controller, never on an
  active site (`development.localhost` never).
- `sites/apps.txt` and site config are protected from agent edits.
- Never use `docker exec -it`. Never run two suites concurrently against one site (tabSingles
  deadlock); check for orphan `loadTestsFromName` processes first. Container:
  `frappe_docker_devcontainer-frappe-1`.
- Never probe Custom Field creation on a shared site (`ALTER TABLE` escapes rollback).
- The recovery map never enters Git, site config, logs, plan text, shell history, or transcripts.
- Subagent models: Haiku/Sonnet for exploration and implementation; Opus for reviewer roles only.
- Tests may hardcode; production code must derive.

---

## 10. Resume here

Phase 2 is complete and closed on the cutover site: all twelve tasks, the final gate, the independent
review, and the authorized `selling-cutover.localhost` migrate have passed. That site now shows zero
RED tests, `preflight final` clean, selling owning the three DocTypes and every moved hook, its own
navigation imported, and ERPNext's `Selling` sidebar free of the legacy Price Group row with nothing
left to recreate it. Do NOT restart any Phase 2 task, do NOT re-run its investigations, and do NOT
begin Phase 3.

Next authorized step, in order:

1. **Commit-approval window** (plan Task 10 Step 11 / Task 12 Step 8) — still open and unspent. The
   user reviews the staged and unstaged diffs per repository and grants or withholds commit approval
   per repo. Resolve Ruling AH's bundle decision first (see §7.1). Staging is strictly by exact path;
   keep `diference.md`, `test_desk_sidebar.py`, the roti spec-status line, and `test_sales.py` out.
2. After commits: the user decides whether to begin Phase 3 (rollout plan, separately approved).
   Phase 3 is NOT started and NOT approved.
