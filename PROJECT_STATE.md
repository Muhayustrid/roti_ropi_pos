# PROJECT_STATE.md — AI session resume checkpoint

**Last updated:** 2026-08-24, the Desk POS promotion picker batch is committed
(selling_additional `666f5de`, this checkpoint `0f743de`). The D12 incident is fully closed: a
2026-08-24 query found ZERO Item Price rows on either promotion parent — `28e53m5gfj` no longer
exists (removed outside that session, likely via desk), so PROMO-00001 re-saves are unblocked.
The MVP-vs-future boundary lives in design §16; the next phase awaits operator direction.
**Resume point:** Dynamic Promotion MVP (Tasks 1-7) complete and committed through `4eaebde`;
the operator-directed Desk POS promotion picker and parent-click interception committed as
`666f5de`: `overrides/pos_promo_api.py` (3 whitelisted wrappers outside the promotions package,
permission-gated), `public/js/pos_promotions.js` (page-scoped picker writing only the
pending-payload field; engine materializes at checkout draft save; intercepts parent-item clicks
into the picker with idempotent guard installation against the async controller timing),
`hooks.page_js` a 2-entry list with the `test_hooks` pin updated accordingly, guide §8,
`.eslintrc` global, new `test_pos_promo_api.py` (7 tests, GREEN ×2). E2E measured earlier:
PROMO-00001 sold at 27.000 via dialog quote inside a mixed cart → ACC-PSINV-2026-00001 submitted
at 35.000 with correct Model C rows and NO parent Item Price created; complete return
ACC-PSINV-2026-00002 (-35.000) passed the return guard and wrote negated facts for the same
instance id. Demo prep on promo-mvp stands: POS Profile "Kasir JURI" matching the promotion
outlet, customer Walk In JURI, prices for the four physical items, stock MAT-STE-2026-00002,
POS Settings invoice_type "POS Invoice". Measured ERPNext v16 facts recorded in AGENTS Keputusan
Kunci: a user may hold only one open POS Opening Entry (an operator shift left open fails every
suite's `_open_shift()`), closing cannot consolidate a sale together with its full return in one
shift, and merge logs run as background jobs requiring the committed closing entry — the demo
shift was therefore closed with an intentionally empty transaction list (invoices stay
Paid/unconsolidated).

The app-ownership extraction project (Phases 0-3) is complete; its record below stays as history.

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
| 2 — selling cutover | `docs/superpowers/plans/2026-08-14-selling-additional-cutover.md` | **Complete — all 12 tasks, final gate, independent review, the authorized cutover-site migrate, and packaging/commit all passed** |
| 3 — production rollout | `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md` | **Complete — main-site rollout verified, Critical 0, Important 0, PASS** |

Execution ledger (authoritative per-task record, including every ruling):
`.superpowers/sdd/2026-08-14-selling-additional-cutover/progress.md`. Every Phase 2 task
(1 through 12) carries a `## Task <N>: complete` line there, plus the final-gate and reviewer
record ("Phase 2 final gate and independent review"), the closure record
("Phase 2 closure — final authorized migrate on `selling-cutover.localhost`", including Ruling AJ),
and the packaging record ("Phase 2 packaging — Ruling AH resolved, implementation committed in three
repos"). Per-task briefs, dispatch notes, and implementer reports live beside it.

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

Working trees — **every intended Phase 2 change is committed; nothing is pushed**:

| Repo | Branch | Phase 2 commit | Paths |
| --- | --- | --- | --- |
| `selling_additional` | `feat/inactive-shell` | `0c45021` `feat: own Price Group, walk-in selling, and POS past orders` | 45 (3 M + 42 A) |
| `bakery_manufacturing` | `claude/instruction-guidance-20260810014002` | `f1aa55b` `refactor: hand selling ownership to selling_additional` | 20 (6 M + 14 D) |
| `roti_ropi_pos` | `patch/catalog-item-group-fallback` | `78a0708` `feat: depend on selling_additional and pin its contracts` | 3 M |

Documentation commits: `stock_additional` `d94f5bf`, `8422130`; `selling_additional` `5a11fd1`,
`2da49a6`; `roti_ropi_pos` `ccffc19`, `85302d2`, plus this checkpoint update.

Deliberate local overlays that stay uncommitted on purpose:

- `bakery_manufacturing/public/js/bakery_manufacturing.bundle.js` — the 14-line operator prototype,
  `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`, `git diff --numstat` = `14 0`
  against the now-empty HEAD blob. **Per Ruling AH (resolved as Option B) this file is carried to a
  deployment by the rollout overlay, never by Git.** Do not commit it and do not let a formatter
  touch it; the pre-commit hooks exclude that exact path.
- `bakery_manufacturing/bakery_manufacturing/tests/test_desk_sidebar.py` (untracked in every ref),
  `diference.md`, `graphify-out/` — protected or pre-existing operator artifacts.
- `roti_ropi_pos`: the extraction-design status line and the `tests/test_sales.py` teardown edit,
  plus untracked plan files and `skills-lock.json`.
- `apps/erpnext`: ` M banking/yarn.lock` and tool dirs only; `erpnext/workspace_sidebar/selling.json`
  has no diff. `apps/frappe`: tool dirs only. Neither core repo received a Phase 2 commit.
- Tooling output everywhere: `.codegraph/`, `.claude/`, `.agents/`.

Scratch sites created by Task 12 (safe to keep for evidence; safe to drop with approval):
`selling-fresh.localhost` (fresh-install proof), `selling-upgrade.localhost` (populated-upgrade
proof, migrated, final-clean).

Backups: `…/private/backups/20260816_213539-…` (pre-final-migrate — the current recovery boundary),
`…/20260816_195140-…` (pre-Task-7-migrate), `…/20260816_160438-…` (pre-Task-6-migrate; also the
rehearsal restore source).

---

## 7. Open items and deferred findings (none block Phase 2 closure)

1. **Ruling AH — RESOLVED as Option B.** The committed bundle blob is empty: the commit removes only
   the tracked `import "./pos_walk_in_customer.js";` line, applied index-only with `git apply
   --cached` so the worktree was never touched. The operator's 14-line prototype stays an uncommitted
   overlay and reaches deployments through the rollout's overlay step. The objection that an empty
   blob would break `test_desk_sidebar.py` on a fresh checkout does not apply — that test is untracked
   in every ref, so a fresh clone has neither the test nor the prototype. Committing the 14 lines
   (Option A) would publish operator-local work and break the rollout's bundle-excluded manifest;
   leaving the bundle at HEAD (Option C) would ship an import pointing at a file the same commit
   deletes.
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

- `development.localhost` holds shared real business data. Phase 3 rollout `ROLL-20260818-01` is the
  only authorized ownership-cutover mutation recorded here. Future mutation needs fresh authorization.
- `apps/erpnext/banking/yarn.lock`, `.codegraph/`, `graphify-out/` dirs in erpnext/frappe/bakery:
  not ours.
- Roti's spec status line and `test_sales.py` teardown edit stay deliberately uncommitted.

Phase 2 implementation is committed in all three implementation repositories (`0c45021`, `f1aa55b`,
`78a0708` — see §6 for branches and path counts), alongside the documentation commits listed there.
**No branch has been pushed.** `stock_additional`, `erpnext`, and `frappe` received no Phase 2 commit.

---

## 9. Authorization boundaries (unchanged — no new authority granted)

- No push, tag, deploy, or Phase 3 rollout without separate explicit approval per phase. The Task 6-7
  migrate approval, the 2026-08-16 final-migrate approval on `selling-cutover.localhost`, and the
  Phase 2 commit approval are all SPENT; any further migrate or a first push needs its own approval.
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

Phase 3 main-site rollout `ROLL-20260818-01` ran under explicit authorization on
`development.localhost` in `frappe_docker_devcontainer-frappe-1`.

Rulings AK through AM remain in force. Ruling AN records that Stage A and source deployment were already
complete. The target app order matched Rehearsal 2. All six rollout source identities and candidate-only
file hashes matched the validated Rehearsal 2 state. The rollout therefore skipped shell reinstall and
source reapplication, then ran every read-only identity and preflight gate.

Focused preflight passed after one burst worker drained 38 old dynamic-link jobs. The command did not
purge the queue. The scheduler was disabled, no workers or HTTP service were active, and disk headroom
was 177 GB. Stock staged preflight and selling pre-model-sync preflight passed. The recovery map needed
zero entries.

Recovery point `20260818_050304` contains database, public files, private files, and site config. The
database gzip and both archives passed readability checks. The protected copy outside the site directory
matches all source hashes. No secret or site-config content entered project files or chat.

Exactly one intended `bench --site development.localhost migrate` ran. It exited 0 after 14 seconds.
All three ownership patches executed with no skip, traceback, duplicate override warning, or orphan
removal error.

Current main-site state:

- `Price Group`, `Price Group Item`, and `Price Group Outlet` belong to `Selling Additional`.
- Their migration hashes match the owning JSON files.
- Parent and child counts stayed `1`, `1`, and `1`.
- Stored walk-in counts stayed `51` and `5`. The custom-UOM Item count stayed `42`.
- Selling and stock final preflights pass every section.
- Scanner, past-order, both walk-in validators, POS page asset, and Serial and Batch Bundle each have
  exactly one provider.
- The Selling Additional Workspace and Sidebar exist. ERPNext Selling has no legacy Price Group child.
- Selling, stock, and bakery asset builds passed. Site and website caches were cleared.
- Web, Socket.IO, scheduler process, and one worker are online.
- Root HTTP, `frappe.ping`, and the Desk login route pass.
- Maintenance mode and `pause_scheduler` are off. The site scheduler returned to its disabled baseline.
- The queue is empty.
- The bakery bundle remains exactly `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`.
- Frappe has no tracked diff. ERPNext retains only the known `banking/yarn.lock` tracked diff.

Known nonblocking tooling defect: `collect_business_checksums()` does not normalize Python `date` values
before `json.dumps()`. The Task 13 scratch-site idempotency evidence already passed in Rehearsal 2. The
main-site preservation gate used exact redacted counts and both final preflights. Do not fix this during
the live rollout review.

Protected evidence lives under `sites/phase3-main-rollout-records`. The Phase 3 ledger records hashes,
results, Ruling AN, and the final Git state without secret or business identifiers.

Independent final review returned Critical 0, Important 2, Minor 4, FAIL. The two Important findings
were missing Task 15 window evidence and missing durable per-file identity for uncommitted runtime source.
Exact runtime-source records now exist, and eleven Rehearsal 2 candidate files match their recorded hashes.

Fresh targeted gate status:

- Selling hooks 5, navigation 7, walk-in 10, walk-in asset 12, past orders 9, and Price Group lifecycle
  28 passed.
- Stock hooks 4, scanner 7 plus 5, and preflight 16 passed.
- Bakery scanner shims 3 passed.
- Roti source contracts 37, user override 2, catalog 19, API foundation 14, and bootstrap 9 passed.
- Fresh targeted total: 189 tests across 17 module runs.
- Selling, stock, bakery runtime package, and Roti runtime package Ruff checks passed.
- Reject the first targeted run because tests were disabled despite exit 0.
- `test_user_override` root cause was an unrelated core cache callback. The fixed assertion rejects any
  callback closure that captures `LazyUser`, which is the actual pickle hazard. Production code did not
  change.
- Bakery overlay-tool tests have pre-existing Ruff findings. Runtime package checks pass.

Exact source identity now includes eleven Rehearsal 2 file hash matches, a runtime-source record, and a
readable five-file runtime overlay archive. The archive records base commits, paths, byte sizes, modes,
and SHA-256 values, so the uncommitted running source can be reconstructed without a commit or push.

Main site remains migrated and serving. Ownership is `Selling Additional`. Maintenance mode and
`pause_scheduler` are off. The scheduler remains disabled per baseline. One worker is online. The queue
is empty. The protected bundle hash is unchanged. Recovery point `20260818_050304` remains valid.
Test-site temporary settings were restored.

Scoped re-review found I1 and I2 addressed. Final counts are Critical 0 and Important 0. Verdict: PASS.

Final evidence corrections:

- Valid fresh targeted total is 187 tests across 15 commands and 16 result groups. The earlier 189 count
  double-counted the two user-override tests and is superseded.
- Runtime Ruff checks used pinned version 0.14.10.
- All runtime source files match Rehearsal 2. Ten of eleven recorded files remain byte-identical. The
  only difference is the test-only `test_user_override.py` root-cause correction.
- The five-file runtime overlay archive and manifest reproduce the deployed uncommitted runtime tree
  from recorded base commits.

Nonblocking follow-up findings remain in the Phase 3 ledger and scoped review report. The main-site
rollout must not be repeated.

Final Git integration completed on 2026-08-18 under explicit authorization.

Final project commits:

| Repository | Final project commit | Project integration `origin/main` | Merge mode |
| --- | --- | --- | --- |
| `selling_additional` | `e4284f71f611505bc876026de43f5f2dfa059b70` | `e4284f71f611505bc876026de43f5f2dfa059b70` | Fast-forward |
| `stock_additional` | `8422130570085af5ca5aeb2ece6cee5f979d7d44` | `8422130570085af5ca5aeb2ece6cee5f979d7d44` | Fast-forward; no new Phase 3 commit |
| `bakery_manufacturing` | `847b6c6b8aa14aced6d05fb06262a970eb3226b9` | `077e5a3128d09c0a47c08c0848b21b51ba01e809` | Normal merge |
| `roti_ropi_pos` | `a99b0fc6963d75f0730432c33393a6506ead128a` | `a210a0cc3eb178ee12a2982002abbacc2960c3b4` | Normal merge |

Every feature branch was pushed without force. Fresh remote checks prove each expected project commit is
an ancestor of `origin/main`. No merge conflict occurred. The final Roti closeout documentation history
advances `origin/main` after this file is written. Its final merge hash is reported externally instead
of creating a self-referential commit loop.

The final focused Selling gate used Ruff 0.14.10. Migration ran 14 tests OK. Preflight initially exposed
three test-only failures caused by a removed site-global POS Profile fixture. The tests now construct the
profiles they judge. The final preflight run passed 39 integration tests and 9 unit tests. The final
migration rerun passed 14 tests.

All intended project source is committed. Deliberate local state remains outside Git:

- Bakery keeps the protected bundle overlay unstaged at SHA-256
  `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. The committed bundle is empty.
- Bakery keeps `test_desk_sidebar.py`, `diference.md`, and `graphify-out/` local.
- Roti keeps the extraction-design status edit local. The former local `test_sales.py` teardown edit is no
  longer local: it was folded into the P0-7 fixture commit `7c24cd2`.
- Tool directories, plan scratch files, and `skills-lock.json` remain local.
- ERPNext keeps its pre-existing `banking/yarn.lock` edit. Frappe and ERPNext received no project commit.

No migrate, deploy, restart, or business-data mutation ran during final Git integration.

PHASE 3 COMPLETE — MAIN-SITE ROLLOUT VERIFIED AND REVIEW PASSED

PROJECT COMPLETE — ALL INTENDED CHANGES COMMITTED, PUSHED, AND MERGED TO MAIN

---

## 11. Active workstream — Mobile POS backend P0 remediation

**Source of findings:** `docs/mobile-pos/backend-readiness-audit.md` (§ Critical, § Important, §7 plan).
Scope is P0 only. P1/P2 findings, core Frappe/ERPNext files, `development.localhost`,
`rotiropi-fresh.localhost`, and IMIN hardware work are all out of scope.

**Test sites (both dedicated to this workstream; no operational site is used).** Bench root
`/workspace/development/frappe-bench` in `frappe_docker_devcontainer-frappe-1`.

- `mobile-pos-regression.localhost` — P0-1 through P0-6. Installed apps: `frappe`, `erpnext`,
  `bakery_manufacturing`, `roti_ropi_pos` only, so any assertion needing `stock_additional` or
  `selling_additional` fails here as a missing-app baseline rather than a regression.
- `selling-cutover.localhost` — P0-7, the final integration gate. Installed apps: `frappe`, `erpnext`,
  `payments`, `hrms`, `bakery_manufacturing`, `stock_additional`, `selling_additional`,
  `pos_direct_print`, `roti_ropi_pos`; `allow_tests: true`, `throttle_user_limit: 5000`. This is the only
  site that carries all four owned apps, so it is the only site whose green run counts as I-16 evidence.

**Order (one finding per boundary, RED → minimal fix → GREEN → mutation → diff review → checkpoint):**

| # | Finding | Status |
|---|---|---|
| P0-1 | C-1 route-alias auth bypass | **Complete — green, reviewed, committed** |
| P0-2 | I-5 / I-6 idempotency contention and stable error behaviour | **Complete — green, mutation-verified, committed** |
| P0-3 | I-2 Administrator elevation in closing | **Complete — green, mutation-verified, committed** |
| P0-4 | I-1 closing transaction / savepoint boundary | **Complete — green, mutation-verified, committed** |
| P0-5 | I-3 lost-key closing recovery | **Complete — green, mutation-verified, committed** |
| P0-6 | I-4 ERPNext sale/return error mapping | **Complete — green, mutation-verified, committed** |
| P0-7 | I-16 money-path evidence restoration | **Complete — full suite green on the four-app site, committed** |

### P0-1 / C-1 — complete

Root cause, measured against installed Frappe 16.27.1 rather than inferred: `validate_mobile_api_scope`
compared only the raw `frappe.request.path` against a literal `/api/method/...` allowlist. Frappe mounts
the v1 rules under both `/api` and `/api/v1` with `strict_slashes=False`, truncates the v1 method at the
first `/` (`frappe/api/v1.py`), and also serves `/api/v2/method/<method>`; legacy `cmd` dispatch bypasses
the path entirely. The mobile-only fence (`_is_mobile_only_account`) exempts any account with Desk
access, which the Setup Wizard grants to the first System User along with every other role. A Desk
account holding `Mobile POS Cashier` could therefore call all 16 Mobile POS callables with no
client-bound Bearer token.

Fix, in `roti_ropi_pos/mobile_pos/auth_hook.py`:

- Authority is now the resolved dispatch identity, not the path. `MOBILE_POS_METHODS` holds the 16
  canonical method strings; `MOBILE_POS_PATHS` is derived from it, so the two cannot drift.
- `_dispatch_identities()` binds `frappe.api.API_URL_MAP` to `frappe.request.environ`, reproduces each
  dispatcher's own normalisation (v1 suffix truncation, v2 `<method>` without `<doctype>`, legacy `cmd`),
  and returns both the requested identity and its `frappe.override_whitelisted_method` target. Returning
  both closes the fail-open in either override direction.
- Any request whose identities intersect `MOBILE_POS_METHODS` runs `_validate_mobile_bearer` first
  (client, user, status, expiry, enabled, explicit `Has Role` row, `STANDARD_USERS` excluded), and only
  then the exact-route/no-`cmd` policy from `AGENTS.md`. Aliases therefore authenticate first and are
  still refused as alternate dispatch — `AuthenticationError` without a valid token, `PermissionError`
  with one.

Test changes: `roti_ropi_pos/tests/test_authentication.py` gained the alias/legacy-`cmd` groups, the
override fail-open pair, and the `/api/v2/method/<doctype>/<method>` fail-closed case; two pre-existing
alias tests changed expected exception class because the bearer gate now runs first.
`roti_ropi_pos/tests/helpers.py` builds a real WSGI environ for `FakeRequest` (the URL map needs one)
and wraps the extra `make_cashier` insert in `frappe.flags.in_import`, which is core's own escape hatch
from `throttle_user_creation` (default 60 users/hour). Both helper changes are test-only.

Evidence (all fresh, `mobile-pos-regression.localhost`):

- RED before the fix: 5 subtest failures on the alias group plus 1 on the legacy-`cmd` test,
  "AuthenticationError not raised".
- RED for the override fail-open test before widening `_dispatch_identities`: 1 failure, same message.
- GREEN: `Ran 36 tests in 18.399s OK`, exit 0.
- Mutation A — return only the override target: `test_overridden_mobile_pos_method_still_requires_mobile_bearer` fails.
- Mutation B — return only the requested identity: `test_override_target_of_a_generic_route_is_also_gated` errors.
  Both restored, suite green again.
- Adjacent modules unaffected: `test_api_foundation` 14 OK, `test_bootstrap` 9 OK, `test_sessions` 10 OK.
- Ruff 0.14.10 `check` all passed; `format --check` 3 files already formatted; `git diff --check` clean.
- Independent reviewer (read-only worktree): Critical 0, Important 0. It confirmed the environ read is
  safe at `validate_auth_via_hooks` time and that `except HTTPException` is the correct width.

Pre-existing, unrelated to this diff: `test_source_contracts` (2) and `test_catalog` (1) fail on this
site because `selling_additional` and `stock_additional` are not installed here, so the past-order and
barcode-scanner overrides resolve to the ERPNext originals. Both pass on `development.localhost`, which
has those apps. Do not "fix" these on the regression site.

Committed for this boundary in `fix: gate Mobile POS aliases by resolved dispatch identity`:
`roti_ropi_pos/mobile_pos/auth_hook.py`, `roti_ropi_pos/tests/test_authentication.py`,
`roti_ropi_pos/tests/helpers.py`, and this file. No migrate ran. `test_sales.py` and the
extraction-design status line remain the pre-existing local edits described in §8.

**Next action:** P0-3, P0-4, P0-5, and P0-6 were completed in later sessions (see their sections below).
The next boundary is P0-7 — I-16, restoring money-path evidence on a site that holds all four apps
(`stock_additional`, `selling_additional`, `bakery_manufacturing`, `roti_ropi_pos`). A missing-app failure
is not acceptable as final evidence, and fixture baselines may be corrected in test code only.

### P0-2 / I-5 + I-6 — complete

Root cause, measured on `mobile-pos-regression.localhost` rather than inferred
(`innodb_lock_wait_timeout = 50`, `innodb_rollback_on_timeout = 0`):

- I-5: `_resolve_committed_request` raised `IDEMPOTENCY_INVARIANT` at HTTP 500 when the row was absent
  after every attempt. Reaching that function proves a duplicate-key insert on the unique `scope_key`
  index, so an absent row can only mean the winning transaction aborted with nothing committed. That is
  retry-safe, not a server fault.
- I-6: only `frappe.QueryDeadlockError` was caught. A `SELECT ... FOR UPDATE` that hits the 50 s lock
  wait raises `frappe.QueryTimeoutError`, which escaped uncaught and left the client with a native 500
  instead of the documented retry contract.

Fix:

- `roti_ropi_pos/mobile_pos/idempotency.py`: the loop now tracks `contended` (deadlocked read) and
  `unresolved_row` (row present but not `Completed`). Either one at exhaustion is proven same-key
  contention and raises `REQUEST_IN_PROGRESS`; an absent row raises the new `_contention_unresolved`
  (`TEMPORARILY_UNAVAILABLE`, 503, `retryable=True`, `details={endpoint, retry_after_seconds: 1}`).
  `QueryTimeoutError` answers `REQUEST_IN_PROGRESS` immediately instead of retrying — the wait already
  cost `innodb_lock_wait_timeout`, so up to 5 × 50 s ≈ 250 s in one worker would contradict
  `retry_after_seconds: 1`. Every other database exception still propagates.
- `roti_ropi_pos/mobile_pos/responses.py` (scope addition, see note below): new `_rollback_to` falls back
  to a full rollback when `ROLLBACK TO SAVEPOINT` fails.

Scope note: `responses.py` was not in the original P0-2 file list. It is required because InnoDB discards
every savepoint on a transaction-level abort, verified directly in MariaDB
(`ERROR 1305 (42000): SAVEPOINT sp1 does not exist`). Without `_rollback_to`, `api_endpoint` raised 1305
while mapping the new retryable error and replaced the envelope with a native HTTP 500 — the opposite of
a deterministic retry contract.

Evidence (all fresh, `mobile-pos-regression.localhost`):

- RED before the fix: `Ran 6 tests ... FAILED (failures=3, errors=2)`, including
  `'IDEMPOTENCY_INVARIANT' != 'TEMPORARILY_UNAVAILABLE'`, `'IDEMPOTENCY_INVARIANT' != 'REQUEST_IN_PROGRESS'`,
  and `frappe.exceptions.QueryTimeoutError: lock wait timeout exceeded` escaping uncaught.
- RED for the savepoint defect: `MySQLdb.OperationalError: (1305, 'SAVEPOINT mobile_pos_04bfc4645f does not exist')`.
- GREEN: `test_idempotency` `Ran 32 tests OK` exit 0; `test_api_foundation` `Ran 15 tests OK` exit 0.
- Mutations, each restored afterwards: drop the `QueryTimeoutError` catch → 2 errors; drop `unresolved_row`
  from the final branch → 2 failures; widen the catch to bare `Exception` → 1 error; remove the
  `_rollback_to` fallback → `test_api_foundation` 1 error; remove `contended = False` from the `else`
  branch (sticky contention) → `test_idempotency` 1 failure.
- Regression by baseline diffing, not assumption: `git stash` of exactly the changed files produced
  before/after logs for `test_sales`, `test_closing`, `test_mobile_pos_flow`, `test_return_task10`,
  `test_sale_task9`. Each fails on this site with a byte-identical failure set in both states
  (pre-existing environmental gaps: `KeyError: 'data'`, `PERMISSION_DENIED` in place of domain codes,
  `AssertionError: Sale transaction deadlocked twice.`).
- Ruff 0.14.10 `check` all passed; `format --check` 4 files already formatted; `git diff --check` clean.
- One existing assertion was deliberately rewritten
  (`test_resolve_committed_request_missing_row_exhaustion_is_retryable`); the reason is recorded in the
  test's own docstring because the old contract was the defect.

Deferred out of this boundary, deliberately: `closing.py:106-112` repeats both defects and adds an
`AttributeError` on a `None` row — that belongs to P0-4/P0-5. A stranded `Processing` row still has no
exit path, and no `Retry-After` header is emitted; both are Minor, not P0-2.

Committed for this boundary in `fix: stabilize idempotency contention recovery`:
`roti_ropi_pos/mobile_pos/idempotency.py`, `roti_ropi_pos/mobile_pos/responses.py`,
`roti_ropi_pos/tests/test_idempotency.py`, `roti_ropi_pos/tests/test_api_foundation.py`,
`docs/mobile-pos/api-contract.md`, and this file. No migrate ran; no schema or DocType JSON changed.
`test_sales.py` and the extraction-design status line remain the pre-existing local edits from §8.

### P0-3 / I-2 — complete

Root cause, measured on `mobile-pos-regression.localhost` rather than inferred. `_submit_persisted_closing`
and `ensure_committed_closing_job` both wrapped ERPNext work in `frappe.set_user("Administrator")`. The
elevation existed because the consolidation chain ends in a permission check the cashier could not pass:
`POSClosingEntry.on_submit` → `consolidate_pos_invoices` → `create_merge_logs` → `merge_log.save(ignore_permissions=True)`
+ `merge_log.submit()` → `POSInvoiceMergeLog.on_submit` → `process_merging_into_sales_invoice` →
`sales_invoice.save()` / `.submit()` **without** `ignore_permissions`. Removing the elevation with no grant
returns `INVALID_REQUEST` with `details.reason = PermissionError`, traceback ending at
`frappe/model/document.py:check_permission`.

Fix (minimal, two files plus the fixture):

- `roti_ropi_pos/mobile_pos/closing.py`: both `frappe.set_user("Administrator")` blocks deleted. The
  submit and the deferred consolidation now run as the requesting cashier. `frappe.enqueue` records
  `frappe.session.user` and `execute_job` re-applies it, so the queued path keeps the same authority.
  `grep set_user` over production code (`roti_ropi_pos/*.py`, `mobile_pos/`, `api/`, `overrides/`) now
  returns nothing.
- `roti_ropi_pos/fixtures/custom_docperm.json` (+130 lines, additive only — `git diff --numstat` shows
  `130 0`): the four standard ERPNext `Sales Invoice` DocPerm rows mirrored (required because
  `frappe/model/meta.py` replaces `permissions` wholesale once any `Custom DocPerm` exists for a DocType,
  so adding one row without mirroring would delete Accounts User/Manager access), plus one cashier row:
  `create`, `write`, `submit`, `if_owner = 1`. No `read`, `cancel`, `delete`, `amend`, `report`, `export`,
  or `share`. The permission set is measured, not guessed: `create + submit + if_owner` without `write`
  still fails.
- `roti_ropi_pos/hooks.py`: `"Sales Invoice"` added to the `Custom DocPerm` fixture filter so the rows
  export and sync.
- `AGENTS.md`: the cashier table row changed from `Sales Invoice | none` to
  `create, write, submit (owner-scoped: if_owner = 1)`, with the integration-test justification that
  `AGENTS.md` itself requires, and an explicit "never elevate to Administrator" rule.

Tests (`roti_ropi_pos/tests/test_closing.py`, +7 tests, 45 → 52):

- `test_sync_closing_never_switches_to_administrator` — patches `frappe.set_user` and asserts
  `"Administrator"` never appears.
- `test_sync_closing_consolidates_sales_invoice_owned_by_cashier` and
  `test_queued_consolidation_completes_and_consolidates_under_cashier_authority` — real consolidation on
  both the `< 10` and the `>= 10` invoice path; the consolidated Sales Invoice is `docstatus = 1` and
  owned by the cashier.
- `test_queued_consolidation_runs_under_cashier_authority` — replaces
  `test_queued_consolidation_uses_internal_identity_and_restores_cashier`, whose assertion
  (`users == ["Administrator"]`) *was* the defect.
- `test_cashier_cannot_write_another_cashiers_consolidated_invoice` — cashier B is denied read, write,
  submit, cancel, and delete on cashier A's consolidated invoice.
- `test_closing_submit_is_scoped_to_the_requesting_cashier_and_profile` — cashier B closing cashier A's
  opening returns `PROFILE_SCOPE_MISMATCH` and creates no closing.
- `test_missing_sales_invoice_permission_fails_deterministically` — a `PermissionError` from submit stays
  `INVALID_REQUEST` / `details.reason = PermissionError` and replays identically.
- `test_cashier_sales_invoice_grant_is_owner_scoped_not_broad` — mutation gate on the grant itself.
- `roti_ropi_pos/tests/test_authentication.py`: the fixture contract test now expects 9 cashier rows and
  asserts the exact `Sales Invoice` permission shape.

Evidence (all fresh, `mobile-pos-regression.localhost`):

- RED before the fix: `test_sync_closing_never_switches_to_administrator`
  (`'Administrator' unexpectedly found in [...]`), `test_queued_consolidation_runs_under_cashier_authority`
  (`['Administrator'] != ['closing-…@rotiropi.test']`), both consolidation-owner tests
  (`'Administrator' != 'closing-…@rotiropi.test'`).
- GREEN: `test_closing` `Ran 52 tests in 143.618s OK`; `test_authentication` `Ran 36 tests in 42.929s OK`.
- Mutation, applied in a console transaction and rolled back: `if_owner = 0` on the cashier row makes a
  non-owner evaluate to `write = 1, submit = 1` and `has_if_owner_enabled = False`, which
  `test_cashier_sales_invoice_grant_is_owner_scoped_not_broad` asserts against. Restored to `if_owner = 1`.
- Neighbours: `test_sessions` 10 OK, `test_api_foundation` 15 OK, `test_bootstrap` 9 OK,
  `test_sale_task9` 58 OK, `test_return_task10` 21 OK, `test_user_override` 2 OK, `test_customers` 7 OK,
  `test_opening_amounts` 21 OK, `test_idempotency` 32 OK.
- Ruff 0.14.10 `check` all passed; `format` reformatted `test_closing.py` once, then 5 files already
  formatted; `git diff --check` clean.

Environment repairs made on the dedicated site only (test-code / site-config, no production change):

- `roti_ropi_pos/tests/test_sessions.py:make_plain_user` now wraps its insert in `frappe.flags.in_import`,
  the same guard `helpers.make_cashier` already used. Core throttles user creation to
  `throttle_user_limit` per hour (`frappe.core.doctype.user.user.throttle_user_creation`) and repeated
  suite runs on one site had reached 93 users/hour, so `test_authentication` errored with
  `ValidationError: Throttled` — an environmental limit, not a regression.
- `sites/mobile-pos-regression.localhost/site_config.json` gained `throttle_user_limit: 5000`, because
  `test_idempotency.test_twenty_concurrent_attempts_...` calls core's own `create_user`, which no test-code
  guard can reach. Site config only; no other site touched.

Pre-existing neighbour failures, proved baseline by stash diff rather than assumed. `git stash push` of
exactly the eight changed files, then the same four suites, then `git stash pop` and the same four suites
again, produced identical failure sets before and after:

- `test_sales` 4 failures both times: `test_batch_tracked_item_requires_batch_selection`,
  `test_distinct_keys_cannot_oversell_same_stock`, `test_insufficient_stock_rolls_back_invoice_and_request`,
  `test_serialized_item_requires_serial_selection`. All four are one shared-site data condition, not a code
  fault: `_Test Item` stock in `_Test Warehouse - _TC` has drifted to `available_qty = -5909.0` from
  accumulated suite runs, so the oversell guard reports `INSUFFICIENT_STOCK` before the batch and serial
  validators can run, and the "insufficient stock" case cannot construct a shortage large enough to fail.
  The evidence is in the failure payloads themselves (`available = -5909.0`,
  `'INSUFFICIENT_STOCK' != 'INVALID_SERIAL_NUMBER'`). Nothing in the P0-3 diff touches sales, stock, or
  the oversell path. Fixing these fixtures belongs to P0-7, which owns fixture baselines.
- `test_mobile_pos_flow` 2 errors, `test_catalog` 1 failure
  (`test_effective_scanner_is_stock_override`), `test_source_contracts` 2 failures
  (`test_effective_past_order_provider_is_selling_additional`,
  `test_frappe_dispatch_resolves_effective_stock_scanner`) — identical before and after, and the same
  missing-app baseline already recorded in §8: this site carries only `frappe`, `erpnext`,
  `bakery_manufacturing`, `roti_ropi_pos`, so the `stock_additional` and `selling_additional` dispatch
  contracts cannot resolve. Not accepted as P0-7 evidence; P0-7 runs on a site holding all four apps.

Committed for this boundary in `fix: run closing consolidation under cashier authority`:
`roti_ropi_pos/mobile_pos/closing.py`, `roti_ropi_pos/fixtures/custom_docperm.json`,
`roti_ropi_pos/hooks.py`, `roti_ropi_pos/tests/test_closing.py`,
`roti_ropi_pos/tests/test_authentication.py`, `roti_ropi_pos/tests/test_sessions.py`, `AGENTS.md`,
`docs/mobile-pos/backend-readiness-audit.md`, and this file. `bench migrate` ran on
`mobile-pos-regression.localhost` only, to sync the fixture; no schema or DocType JSON changed.
`test_sales.py` and the extraction-design status line remain the pre-existing local edits from §8.

**Correction to the P0-2 section:** P0-2 was already committed *and* pushed before this session started
(`e34e373`, `git rev-list --left-right --count origin/main...HEAD` = `0 0`). Any note implying it was
uncommitted is wrong.

### P0-4 / I-1 — complete

Root cause, measured on `mobile-pos-regression.localhost` rather than inferred. `api_endpoint` opens one
savepoint per request and rolls expected errors back to it, but closing deliberately commits its
`Reserved`, `DraftCreated`, and `SubmitStarted` phases so a crashed request stays recoverable from the
database alone. MariaDB drops every savepoint at `COMMIT`, so after the first phase commit both
`ROLLBACK TO SAVEPOINT` and `RELEASE SAVEPOINT` answer `OperationalError(1305, 'SAVEPOINT ... does not
exist')` — confirmed directly, and confirmed inside the endpoint before the fix, where a diagnostic
recorded `('rollback-FAILED', 'mobile_pos_9eff6256e2', "OperationalError(1305, ...)")` followed by a
failing release. The old code only swallowed those failures, so the savepoint error could still displace
the durable closing state, and a failure raised after ERPNext's own internal commit had no stable
recovery envelope at all.

Fix (two production files):

- `roti_ropi_pos/mobile_pos/responses.py`: new `commit_durable_phase()` marks the request
  (`frappe.flags["mobile_pos_durable_commit"]`) and then commits. `_rollback_to` and the
  `release_savepoint` in `api_endpoint`'s `finally` both skip the savepoint once the mark is set, so a
  retired savepoint is never named again. The mark is initialised per request and restored on exit, so
  one endpoint's durable commit cannot disarm the next endpoint's savepoint rollback. The deadlock
  fallback is unchanged.
- `roti_ropi_pos/mobile_pos/closing.py`: every phase commit goes through `commit_durable_phase()`. A
  submit failure that is not one of `_KNOWN_SUBMIT_ERRORS` rolls back and then asks the database:
  `_durable_closing()` returns True only for `docstatus = 1` with status `Queued`, `Submitted`, or
  `Failed`, in which case the response is derived from the persisted closing; otherwise the exception
  propagates untouched. `ensure_committed_closing_job` now contains its own failure: consolidation runs
  after the response is committed, so a failure there sets the closing to `Failed` for
  `v1.closing.status` instead of destroying the committed envelope.

No duplicate closing is possible on any of these paths: the recovery always resolves the closing already
referenced by the request row, and the count assertion is part of three of the new tests.

Tests (`test_closing` 52 → 58, `test_api_foundation` 15 → 17):

- `test_expected_error_after_a_durable_phase_never_touches_a_dead_savepoint` — no `mobile_pos_*`
  savepoint is named for rollback or release once a phase is committed.
- `test_api_endpoint_after_a_durable_commit_never_names_the_retired_savepoint` — the same contract at the
  decorator level.
- `test_durable_commit_does_not_retire_the_next_endpoint_savepoint` — the flag does not leak across
  requests.
- `test_submit_failure_after_the_entry_became_durable_reports_the_closing` and
  `test_post_commit_failure_replays_the_same_closing_without_creating_a_second` — durable state is
  reported and replayed, with exactly one closing for the Opening.
- `test_post_commit_consolidation_failure_keeps_the_committed_envelope` — the queued path keeps its
  committed success envelope.
- `test_unknown_submit_failure_without_a_durable_entry_stays_a_server_error` (mutation gate) and
  `test_known_validation_failure_without_a_durable_entry_still_rejects` — the recovery is not too broad.

Evidence (all fresh, `mobile-pos-regression.localhost`):

- RED before the fix: 1 failure + 3 errors across the six new closing tests
  (`AssertionError: Lists differ: ['mobile_pos_db951363fa'] != []`, and `RuntimeError` escaping the three
  post-commit tests).
- GREEN: `test_closing` `Ran 58 tests in 208.465s OK`; `test_api_foundation` `Ran 17 tests in 0.041s OK`.
- Mutations, each applied then reverted: forcing `_savepoint_survives()` to `True` fails both savepoint
  gates (`['mobile_pos_3078ca9685', None] != [None]` and `['mobile_pos_f731da5762'] != []`); replacing
  the `_durable_closing` guard with `if False` fails
  `test_unknown_submit_failure_without_a_durable_entry_stays_a_server_error` with
  `AssertionError: RuntimeError not raised`.
- Neighbours, all OK: `test_idempotency` 32, `test_sessions` 10, `test_bootstrap` 9,
  `test_authentication` 36, `test_sale_task9` 58, `test_return_task10` 21, `test_opening_amounts` 21.
- Ruff 0.14.10 `check` all passed; `format` reformatted 3 files once; `git diff --check` clean.

Committed for this boundary in `fix: keep closing responses correct across durable commits`:
`roti_ropi_pos/mobile_pos/closing.py`, `roti_ropi_pos/mobile_pos/responses.py`,
`roti_ropi_pos/tests/test_closing.py`, `roti_ropi_pos/tests/test_api_foundation.py`,
`docs/mobile-pos/api-contract.md`, `docs/mobile-pos/backend-readiness-audit.md`, and this file. No
migrate ran; no schema or DocType JSON changed. `test_sales.py` and the extraction-design status line
remain the pre-existing local edits from §8, and the `test_sales` /
`test_mobile_pos_flow` / `test_catalog` / `test_source_contracts` failures remain the baseline set proved
by stash diff under P0-3.

### P0-5 / I-3 — complete

Root cause, reproduced live on `mobile-pos-regression.localhost` before any fix rather than inferred. A
`Mobile POS Request` row left `Processing` / `Reserved` with a long-dead lease projected
`{"status": "processing", "phase": "Reserved"}`, `has_unresolved_closing` returned `True`, and all five
bootstrap capabilities were false — while the route allowlist exposed only `closing.preview`,
`closing.submit`, and `closing.status`. There was no recovery operation at all, so a cashier who lost the
idempotency key (reinstall, wiped storage, discarded pending mutation) could not resolve the shift from
the app under any input. Two distinct defects sat behind that: no server-authoritative recovery, and a
reservation with nothing durable behind it blocking sales, returns, and closing for ever.

Fix (three production files plus the route allowlist):

- `roti_ropi_pos/mobile_pos/closing.py`: `execute_closing_recovery(profile)` resolves the unresolved
  Closing from server state only — the authenticated session, the authorized POS Profile, and the
  persisted Opening and Closing rows. It locks the Opening, re-reads the Closing `for_update`, and calls
  `_require_adoptable_closing`, which escalates unless cashier, POS Profile, company, Opening reference,
  docstatus/status, and the stored `custom_mobile_pos_transaction_id` all agree. Escalation is HTTP 409
  `CLOSING_RECOVERY_REQUIRES_MANAGER` with a coarse `reason` that never names the other cashier, profile,
  or document. Recovery **never creates a Closing Entry**: it reuses the `v1.closing.submit` operation
  identity keyed by the Closing's own transaction id, so `_adopt_closing_request` rebuilds the lost
  control row against the same identity, a second call replays, and no second Closing is possible. The
  post-commit submit branch of `execute_closing_submit` was extracted to `_resume_draft_closing`, so the
  keyed path and the recovery path resolve a post-commit failure identically. The live-lease rule is
  defined once, in `_claim_expired_request`.
- `roti_ropi_pos/mobile_pos/sessions.py`: `unresolved_closing_request()` is the single definition of "a
  Closing request still strands this cashier", shared by `closing_projection` and recovery. A reservation
  with no `reference_name` and an expired lease is skipped; a live lease still blocks.
- `roti_ropi_pos/api/v1/closing.py`: `POST recover(pos_profile)` — deliberately no `X-Idempotency-Key`,
  since the lost key is the defect; unknown fields are rejected and `POS Closing Entry` submit permission
  is required. `roti_ropi_pos/mobile_pos/auth_hook.py` adds the route (16 → 17 allowlist entries).

Tests (`test_closing` 58 → 67, `test_authentication` allowlist set updated):

- `test_recover_resumes_the_abandoned_draft_closing_without_creating_a_second` — the stranded Draft is
  adopted and submitted; exactly one Closing for the Opening; the control row ends `Completed` on
  `v1.closing.submit`.
- `test_recover_reports_a_durable_queued_closing_without_resubmitting_it` — a durable Queued Closing is
  reported, `_submit_persisted_closing` is never called.
- `test_recover_replays_its_recorded_outcome_instead_of_redoing_the_work` — second call is `replayed`,
  still one Closing.
- `test_recover_reports_nothing_to_recover_when_no_closing_is_unresolved` —
  `CLOSING_RECOVERY_NOT_AVAILABLE`, zero Closings created.
- `test_recover_defers_to_a_request_that_still_holds_a_live_lease` — retryable `REQUEST_IN_PROGRESS`.
- `test_recover_adopts_an_expired_request_row_instead_of_creating_another` — one request row for
  `v1.closing.submit`, ending `Completed` against the same Closing.
- `test_recover_escalates_a_closing_that_belongs_to_another_cashier` and
  `test_recover_escalates_a_closing_bound_to_a_different_opening` (mutation gates) — coarse reasons, no
  disclosure, Closing left at `docstatus 0`.
- `test_dead_reservation_with_an_expired_lease_stops_blocking_the_outlet` — a live lease blocks
  (`closing_in_progress`); once the lease dies the session is `active` and both capabilities return.

Evidence (all fresh, `mobile-pos-regression.localhost`):

- RED before the fix: `Ran 67 tests`, `FAILED (failures=1, errors=8)` — eight
  `AttributeError: module 'roti_ropi_pos.api.v1.closing' has no attribute 'recover'` plus the projection
  failure `{'status': 'processing', 'phase': 'Reserved', ...} is not None`.
- A first GREEN attempt failed with six `INVALID_REQUEST` / `client_accepted_grand_total is invalid`
  responses. That was a test-harness defect, not production: the recovery tests inherited the previous
  call's `form_dict`, so the endpoint's unknown-field rejection fired on the leftover sale body. Fixed in
  test code only with a `_recover()` helper that sets the request body an HTTP client actually sends.
- GREEN: `test_closing` `Ran 67 tests in 289.190s OK`.
- Mutations, each applied then reverted: removing the cashier check and removing the Opening check each
  submit work that is not provably this cashier's
  (`AssertionError: Expected '_submit_persisted_closing' to not have been called. Called 1 times.`);
  removing the expired-lease skip re-strands the outlet
  (`{'status': 'processing', 'phase': 'Reserved', ...} is not None`); removing the lease guard inside
  `_claim_expired_request` lets recovery race a live request (same `Called 1 times` failure). A fifth
  probe removed the duplicated lease check in `execute_closing_recovery` and the test still passed —
  that duplicate was genuinely redundant, so it was deleted and replaced with a comment pointing at the
  single owner of the rule.
- Ruff 0.14.10 `check` all passed; `format --check` reported all six touched files already formatted;
  `git diff --check` clean.
- Neighbours, all OK after the mutations were reverted: `test_closing` 67 (re-run,
  `Ran 67 tests in 305.518s OK`), `test_authentication` 36, `test_sessions` 10, `test_bootstrap` 9,
  `test_idempotency` 32, `test_api_foundation` 17, `test_opening_amounts` 21, `test_sale_task9` 58,
  `test_return_task10` 21.

Committed for this boundary in `feat: recover an unresolved closing without the client key`:
`roti_ropi_pos/mobile_pos/closing.py`, `roti_ropi_pos/mobile_pos/sessions.py`,
`roti_ropi_pos/api/v1/closing.py`, `roti_ropi_pos/mobile_pos/auth_hook.py`,
`roti_ropi_pos/tests/test_closing.py`, `roti_ropi_pos/tests/test_authentication.py`,
`docs/mobile-pos/api-contract.md`, `docs/mobile-pos/backend-readiness-audit.md`, and this file. No
migrate ran; no schema or DocType JSON changed. `test_sales.py` and the extraction-design status line
remain the pre-existing local edits from §8.

### P0-6 / I-4 — complete

Root cause, reproduced live on `mobile-pos-regression.localhost` before any fix. `submit_sale` and
`create_return` both ended with bare `insert()` / `submit()`. Every app-side rule already raised
`MobilePOSAPIError`, but a rule only ERPNext knows escaped the envelope entirely: submitting a cart whose
qty is fractional for a whole-number UOM returned Frappe's native HTTP 500 with the raw traceback
`erpnext.utilities.transaction_base.UOMMustBeIntegerError: Row 1: Quantity (0.5) cannot be a fraction.`
(`-0.5` on the return side). `_Test Item.stock_uom = "_Test UOM"` has `must_be_whole_number = 1`, and the
payload parser accepts a fractional qty by design, so this is reachable from a normal Android request.

Fix (one production file, one new shared function):

- `roti_ropi_pos/mobile_pos/invoices.py`: `_persist_invoice(invoice)` wraps `insert()` + `submit()` and
  maps a declared ERPNext rejection class to HTTP 422 `DOCUMENT_VALIDATION_FAILED` with
  `details.doctype`, `details.exception` (the class name Android routes on), and
  `details.display_message` (`strip_html_tags` output, display only, never parsed). `submit_sale` and
  `create_return` both call it, so sale and return cannot disagree about the code for one rejection.
- The mapped set is `_ERPNEXT_DOMAIN_REJECTIONS = (UOMMustBeIntegerError,)` — measured, not guessed.
  `UOMMustBeIntegerError` (`erpnext/utilities/transaction_base.py:16`, subclass of
  `frappe.ValidationError`) is the one declared class reachable through this API.
  `ProductBundleStockValidationError`, the POS Invoice module's only other declared class, stays unmapped
  because `_validate_total_stock` expands bundle components against the same availability ERPNext checks
  and already returns `INSUFFICIENT_STOCK` before insert; a mapping would be unreachable code. A bare
  `frappe.ValidationError` stays unmapped on purpose: ERPNext and the framework raise it both for rules
  this app already enforces and for a document this app built incorrectly, and the two are
  indistinguishable, so mapping it would convert a server defect into a cashier-facing domain code.
  There is no `except Exception` anywhere on this path; unmapped exceptions still reach
  `responses.py:api_endpoint`, its request-ID logging, and Frappe's native HTTP 500.

Verification (all on `mobile-pos-regression.localhost`):

- RED: both new mapping tests failed with the raw `UOMMustBeIntegerError` traceback escaping the endpoint.
- GREEN: `test_sale_task9` `Ran 60 tests in 149.787s OK` (58 → 60), `test_return_task10`
  `Ran 23 tests in 96.459s OK` (21 → 23).
- Mutations, each applied then reverted:
  - adding `frappe.ValidationError` to the mapped tuple (mapping too broad) →
    `AssertionError: MandatoryError not raised` on the sale side and the `TimestampMismatchError`
    equivalent on the return side;
  - removing `UOMMustBeIntegerError` from the tuple → both mapping tests fail with the raw traceback;
  - returning `str(error)` instead of `strip_html_tags(str(error))` →
    `AssertionError: '<' unexpectedly found in "… disable '<strong>Must be Whole Number</strong>' …"`;
  - reverting the return path to bare `insert()`/`submit()` (breaking sale/return symmetry) → the return
    mapping test fails while the sale one still passes.
- No ERPNext or Frappe file was touched, no ERPNext calculation changed, and no schema or DocType JSON
  changed. The server remains authoritative for price, tax, grand total, payable, and refund amount.
- Neighbouring-suite sweep, ten modules run one at a time on `mobile-pos-regression.localhost`:
  `test_sale_task9` 60 OK, `test_return_task10` 23 OK, `test_closing` 67 OK, `test_authentication` 36 OK,
  `test_sessions` 10 OK, `test_bootstrap` 9 OK, `test_idempotency` 32 OK, `test_api_foundation` 17 OK,
  `test_opening_amounts` 21 OK, `test_catalog` 19 run / 1 failure. The single failure is
  `test_effective_scanner_is_stock_override`:
  `AssertionError: 'erpnext.stock.utils.scan_barcode' != 'stock_additional.overrides.barcode_scanner.custom_scan_barcode'`.
  It is a missing-app baseline, not a regression: `mobile-pos-regression.localhost` has only
  `frappe, erpnext, bakery_manufacturing, roti_ropi_pos`, so no app registers the `scan_barcode` override
  the assertion requires. The same module is `Ran 19 tests in 0.126s OK` on `selling-cutover.localhost`,
  which does have `stock_additional` installed. The test asserts a barcode-scanner override registration
  and touches no part of the invoice persistence path changed by P0-6.

### P0-7 / I-16 — complete

**Qualifying site.** I-16 asks for money-path evidence on a site that carries every app Roti depends on,
so `mobile-pos-regression.localhost` (only `frappe, erpnext, bakery_manufacturing, roti_ropi_pos`) cannot
produce it. P0-7 ran on `selling-cutover.localhost`: `frappe, erpnext, payments, hrms,
bakery_manufacturing, stock_additional, selling_additional, pos_direct_print, roti_ropi_pos`,
`allow_tests: true`. That site holds all four owned apps (`stock_additional`, `selling_additional`,
`bakery_manufacturing`, `roti_ropi_pos`), so a missing-app failure can no longer be mistaken for
evidence.

**Four fixture faults, all measured, all fixed in test code** (commit `7c24cd2`, 5 files, +152/-24 — no
production file, no Frappe or ERPNext core file, no schema or DocType JSON):

1. *Test discovery died before a single test ran.* `erpnext/tests/utils.py:2989` instantiates
   `BootStrapTestData()` at module import scope; `__init__` → `make_master_data` → `make_price_list` →
   `make_records(["price_list_name", "enabled", "selling", "buying", "currency"], ...)`. The existence
   check includes `currency` and ERPNext hardcodes `"INR"`, so on a site whose `Standard Buying` /
   `Standard Selling` carry `IDR` the check misses and the insert collides:
   `DuplicateEntryError: ('Price List', 'Standard Buying', ...)`. Any Roti test module importing an
   ERPNext *test* module inherits that import-time side effect. Fixed by owning
   `helpers.set_default_account_for_mode_of_payment` (14 lines), and guarded by the new
   `test_source_contracts.TestNoERPNextTestModuleImports` AST contract. Frappe's own test modules are
   deliberately out of that contract's scope: `frappe/tests/utils/generators.py:282` `_try_create` guards
   on `frappe.db.exists`, so the Frappe generator is currency-safe.
2. *`INSUFFICIENT_STOCK` masked `INVALID_BATCH` and `INVALID_SERIAL_NUMBER`.*
   `get_stock_availability` (`erpnext/accounts/doctype/pos_invoice/pos_invoice.py:901`) returns
   `get_bin_qty - get_pos_reserved_qty`, and `get_pos_reserved_qty` sums `stock_qty` over submitted,
   unconsolidated POS Invoices — so availability drifts downwards on a shared site with every committed
   sale. Measured: bin 658 / reserved 1248 → available **-590** on `selling-cutover`, bin -735 /
   reserved 12 → **-747** on `mobile-pos-regression`. A fixed `make_stock_entry` seed cannot guarantee a
   sellable fixture. Fixed by `helpers.ensure_pos_availability`, which measures what ERPNext itself
   reports and tops up the shortfall.
3. *The oversell guard was silently disabled.* `is_negative_stock_allowed`
   (`erpnext/stock/stock_ledger.py:2357`) returns True if `Stock Settings.allow_negative_stock` **or**
   `Item.allow_negative_stock`, and ERPNext's bootstrap ships `_Test Item` with
   `"allow_negative_stock": True` (`erpnext/tests/utils.py:1341`). `TestSaleSubmit` now clears the flag
   for its duration and restores the saved value in tearDown. The write is committed because the
   concurrency test reads it from separate connections; a suite killed mid-run therefore leaves the flag
   at 0 on the test site, which is the safe direction (guard on, not off).
4. *Lifecycle ordering plus a site-specific Stock Setting.*
   `validate_allow_to_set_serial_batch`
   (`erpnext/stock/doctype/serial_and_batch_bundle/serial_and_batch_bundle.py:147-152`) throws unless
   `Stock Settings.enable_serial_and_batch_no_for_item` is set; measured 0 on `selling-cutover`, 1 on
   `mobile-pos-regression`. `TestMobilePOSLifecycle` now saves, sets, and restores it, and the
   Mode-of-Payment account setup moved ahead of `profile.save` because ERPNext's POS Profile validate
   rejects a payment mode with no default Cash or Bank account for the profile's company.

**Two site-state gaps closed on the test site only** (no production site, no operational site touched):

- The `Mobile POS Cashier` owner-scoped Sales Invoice grant was absent. `selling-cutover.localhost` had
  not been fixture-synced since commit `9c0b7c7 fix: run closing consolidation under cashier authority`
  added `mobile-pos-cdp-sales-invoice` to `roti_ropi_pos/fixtures/custom_docperm.json`, so
  `test_closing` failed 15 / errored 4, nearly all reducing to `details: {'reason': 'PermissionError'}`.
  Resolved with `frappe.utils.fixtures.sync_fixtures("roti_ropi_pos")` on that site — the app's own
  fixture set, not a hand-edited permission. Before / after snapshot diff: **5 rows added, 0 removed,
  0 changed** — the four standard `Sales Invoice` rows the fixture carries plus
  `mobile-pos-cdp-sales-invoice` (`read 0, write 1, create 1, submit 1, if_owner 1`). No Administrator
  elevation was introduced; the resulting effective grant is exactly the owner-scoped one AGENTS.md
  documents, and `test_cashier_sales_invoice_grant_is_owner_scoped_not_broad` holds it.
- `throttle_user_limit` was unset, so core's `throttle_user_creation`
  (`frappe/core/doctype/user/user.py:1353`) defaulted to 60 and
  `test_twenty_concurrent_attempts_create_one_opening_and_one_request` hit
  `ValidationError: Throttled`. Set to `5000` in that site's `site_config.json`, matching the remedy
  already recorded for P0-3 on `mobile-pos-regression.localhost`. The test calls core's own
  `create_user`, which no test-code guard can reach.

**Final evidence — all 15 Mobile POS modules run one at a time on `selling-cutover.localhost`, 370 tests,
zero failures, zero errors:** `test_api_foundation` 17, `test_authentication` 36, `test_bootstrap` 9,
`test_catalog` 19, `test_closing` 67, `test_customers` 7, `test_idempotency` 32, `test_mobile_pos_flow` 1,
`test_opening_amounts` 21, `test_return_task10` 23, `test_sale_task9` 60, `test_sales` 28,
`test_sessions` 10, `test_source_contracts` 38, `test_user_override` 2 — every one `OK`. `test_catalog`
19 OK is the same module that fails as a missing-app baseline on `mobile-pos-regression.localhost`, which
confirms the four-app site is the one supplying real coverage.

The server remains authoritative for price, tax, grand total, payable, return amount, and closing values.
Ruff 0.14.10 check and format clean, `git diff --check` clean.

---

## 12. Active workstream — Dynamic Promotion / Combo MVP (selling_additional)

**Authorities:**
- Design authority: `apps/selling_additional/docs/2026-08-18-dynamic-promotion-combo-design.md`
- Plan authority: `apps/selling_additional/docs/2026-08-18-dynamic-promotion-combo-implementation-plan.md` (commit `7984e2e`)
- Dedicated test site: `promo-mvp.localhost` (Installed apps: `frappe`, `erpnext`, `selling_additional` only).

**Gate G1 (Model C Spike) Status:** **G1 PASS**. **Gates G2 and G7 (Task 4): PASS.** All six
Task 7 hardening gates PASS (2026-08-22) — see the Task 7 section below.

### Task 1 / G1 Evidence Summary (compressed — Task 4 has superseded this engine):

G1 PASS on `promo-mvp.localhost`: 12/12 Model C proof points, 4/4 framework measurements, 3 mutation
checks, rollback Cases A and B, and static analysis all GREEN, twice consecutively. Preflight
confirmed A11 (`required_apps = ["erpnext"]`, zero foreign-app imports) and all 7 candidate DocType
names CLEAR. Scaffolding created 6 DocTypes, 4 Custom Fields, and the minimal engine.

The four measurements are the load-bearing record and remain encoded as live assertions in
`selling_additional/tests/test_promotion_expansion.py`'s sibling module
`selling_additional/tests/test_g1_model_c_spike.py`:

1. `before_validate` must materialize before `AccountsController.validate`, otherwise
   `set_total_in_words()` raises `abs(None)`.
2. POS price-list rewrites do reach promotion rows, so engine re-assertion is mandatory.
3. POS closing consolidation copies `0.0` rates and amounts verbatim to the Sales Invoice.
4. `make_sales_return` copies the promotion role and instance Custom Fields to return rows.

Full point-by-point evidence: `docs/2026-08-18-dynamic-promotion-combo-implementation-plan.md` §5 and
the `test_g1_model_c_spike.py` assertions themselves.

### Task 2 / Promotion Master Validations Evidence Summary (selling_additional):

- **Scope:** Promotion master contract (design section 4.1, plan Task 2): I11, I12, D3-D5, D12, D15, D19, and A6/A7/A9 fence checks, plus lifecycle (D15/D3) and the tax-template advisory (frozen decision 1). All validations live in the parent `Promotion` controller — measured framework behaviour (frappe/model/document.py: `db_insert`/`db_update` for children, no child hooks on parent save), so child controllers carry no validation. `group_key` is generated once in `_ensure_group_keys()` (idempotent, never regenerated on re-save) and child-type controllers exist only as pass-throughs with documented rationale.
- **Production files:** `selling_additional/selling_additional/doctype/promotion/promotion.py` (full `validate`/`on_trash` per plan items 1-7); `selling_additional/selling_additional/doctype/promotion_choice_group/promotion_choice_group.py` plus `promotion_component`/`promotion_option`/`promotion_outlet` (pass-through with dead-code removal and measured-behaviour comment). `promotion_choice_group.json` `group_key` stays `read_only=1` with server fill.
- **RED -> GREEN (Task 2 site `promo-mvp.localhost`):**
  - `bench --site promo-mvp.localhost run-tests --module selling_additional.tests.test_promotion_master` first RED: 27 failures (`ValidationError not raised` for every guard) + 9 positive controls GREEN; 2 tax-template tests initially errored via non-Tax `Debtors` account (Receivable) — fixture fixed to query `account_type in {Tax, Chargeable, Income Account, Expense Account, Expenses Included In Valuation}`. Warehouse fixture fixed to return `doc.name` (autoname appends `- ABBR`). Buying `Item Price` fixture fixed to use a buying Price List (`Standard Buying`, `buying=1`), because `ItemPrice.update_price_list_details()` overwrites `buying`/`selling` from the Price List.
  - GREEN after `promotion.py` fix: **Ran 36 tests in 37.484s OK** (second run 36.888s OK, third confirm 37.115s OK). 36-test module: 27 guard tests, 8 positive controls, 1 lifecycle - `test_referenced_promotion_delete_is_blocked` / `test_label_edit_preserves_group_key_and_selection_snapshots`.
- **Mutation / guard pairing (representative, each exactly one failure when its guard is disabled):** base_price, duplicate `group_key`, `pick_count`, `valid_from > valid_to`, `max_instances_per_invoice < 0`, component/option stock/sellable/batch/serial, component qty>0 and whole-number, adjusted total >=0, parent stock/sellable/fixed-asset/selling-Item-Price, at-most-one enabled promotion per `parent_item`, duplicate outlet identity `(company,warehouse)`, `Warehouse.company` ownership, nested-set `lft/rgt` root-company fence, currency uniformity, and `on_trash` submitted-selection block. `ItemPrice` selling lookup is conservative (`selling=1` anywhere, regardless of `valid_upto`).
- **Adjacent regressions on `promo-mvp.localhost` (all GREEN, no production regression):**
  - `test_g1_model_c_spike` 7 OK (fixture updated to a single valid save: `group_key` supplied up-front with 3 options, satisfying the Task 2 `>=2 options` guard — the former two-step group-then-options flow would now fail).
  - `test_walk_in` 10 OK, `test_hooks` 5 OK, `uvx ruff check .` and `uvx ruff format --check .` clean.

### Task 3 / Eligibility and Pricing Domain Evidence Summary:

31 tests GREEN on `promo-mvp.localhost`: `test_promotion_eligibility` 17, `test_promotion_pricing` 13,
`test_promotion_contracts` 1 (AST scan proving zero `@frappe.whitelist()` anywhere in
`selling_additional/promotions/`). Covers every fail-closed eligibility dimension, `resolve_outlet_context`,
quote math, and parent/component row descriptors. `max_instances_per_invoice` is deliberately not an
eligibility dimension — enforcement belongs to Task 4.

Production files: `selling_additional/promotions/eligibility.py`, `pricing.py`, `api.py`.

### Task 4 / POS Invoice Expansion and Enforcement Evidence Summary:

**Scope:** plan Task 4 — I1, I2, I8, I13, I15, I16 and gates G2, G7. The engine was rewritten onto the
Task 3 contracts: `eligibility.resolve_outlet_context` is now the only warehouse source (D14),
`eligibility.check` gates every Promotion named by a payload, and `pricing.quote` computes the total and
the row descriptors. No inline duplicate of either domain remains.

**Production file:** `selling_additional/promotions/engine.py` only. No DocType JSON, fixture, `hooks.py`,
`patches.txt`, or core file changed. No migrate ran.

**Ruling — I3 immutability is framework-enforced, not re-implemented.** All four promotion Custom Fields
carry `allow_on_submit = 0`, so Frappe's own `validate_update_after_submit`
(`frappe/model/document.py`) raises `UpdateAfterSubmitError` on any post-submit change to a promotion
field, row, or selection. A second engine-side guard would cover the same condition and pin neither, so
the engine deliberately carries none; the two immutability tests assert `UpdateAfterSubmitError` and then
re-read the stored value from the database.

**Ruling — I15 is row-driven, not selection-driven.** `_validate_promotion_row_integrity` judges the item
rows present on the document, never the selection table. Judging selections would reject a return that
legitimately carries a subset of rows; return completeness is Task 5's rule.

**RED → GREEN.** First run: `Ran 20 tests FAILED (errors=20)`, all fixture faults, then 8 genuine
implementation failures once the fixtures were correct. Four fixture faults, all fixed in test code only:

1. No `Fiscal Year` for 2026 on this site → `FiscalYearError` on the `Stock Entry` submit. Fixed the same
   way `test_g1_model_c_spike` and `test_promotion_master` already do.
2. `POSInvoice.validate` requires an open `POS Opening Entry` even for a draft insert
   (`erpnext/accounts/doctype/pos_invoice/pos_invoice.py:210`), so the shift is now opened in `setUp`.
3. `POS Settings.invoice_type` was `Sales Invoice`, which rejects a POS Invoice outright. Pinned to
   `POS Invoice`.
4. ERPNext raises `PartialPaymentValidationError` when `paid_amount` is below the total, so the new
   `_submit_paid` helper sets the payment row from the server-calculated `grand_total` rather than a
   hardcoded number.

**GREEN:** `Ran 27 tests OK`, twice consecutively (48.795s, 49.293s). The module grew 20 → 27: seven new
guard tests were added because seven engine guards had no independent test.

**Mutation ledger — 13 mutations, each guard independently killed, every one restored:**

| Guard disabled | Failing test(s) |
| --- | --- |
| instance cap (`cap > 0 and requested > cap`) | 6 cap tests fail |
| backing-selection check | `test_bare_parent_with_role_but_no_selection_fails`, `test_manual_duplicate_rows_cannot_bypass_selection_count` |
| bare-parent-item check | `test_bare_parent_row_fails_closed` |
| I8 second-payload check | `test_second_payload_on_draft_with_selections_fails_closed`, `..._g7_point_11` |
| parent rate re-assertion | `test_parent_rate_reassertion_after_manual_rewrite` |
| component zero-rate re-assertion | `test_component_zero_rate_reassertion_after_manual_rewrite` |
| warehouse re-assertion | `test_warehouse_reassertion_after_manual_change` |
| instance-and-role pairing | `test_promotion_row_with_instance_but_no_role_fails` |
| duplicate-parent-per-instance | `test_duplicate_parent_row_for_one_instance_fails` |
| unknown-role rejection | `test_unknown_promotion_role_fails` |
| parent-without-components | `test_parent_instance_without_component_rows_fails` |
| eligibility gate | `test_disabled_promotion_in_payload_is_rejected`, `test_promotion_without_an_enabled_outlet_row_is_rejected` |
| pending-payload clear | 17 errors (infinite re-expansion) |

The eligibility-gate mutation initially survived — the suite passed with the gate disabled. That gap was
closed by adding the two tests above, and the mutation was re-run and confirmed killing.

**Measured framework behaviour worth not rediscovering.** At `before_validate` the POS Invoice's own
`currency` still holds the field default (`INR` on this site), because ERPNext rewrites it from the POS
Profile later in its own `set_missing_values`. Reading `doc.currency` there compared the promotion
against a currency the transaction never uses and broke `test_g1_model_c_spike` and
`test_promotion_master`. `_resolve_transaction_currency` now reads the POS Profile, then the outlet
Company, and never the half-built document.

**Test-pin updates required by Task 1's fixture growth (test code only, no production change).** Four
modules pinned the fixture at exactly six Custom Fields and the POS Invoice `validate` hook at exactly
one handler. Task 1 legitimately made both false; these were failing before this session's work and are
now corrected to the current owned set:

- `test_install_paths.py`: `SIX_FIELD_NAMES` → `OWNED_FIELD_NAMES` (10 entries, promotion fields appended
  after the six cutover identities); `test_hooks_resolve_solely_to_targets` now asserts the walk-in
  handler stays **first** on POS Invoice with the promotion handler appended after it.
- `test_migration.py`: fixture length 6 → 10, with the first six names still order-pinned and the two
  walk-in objects still byte-compared against the recorded bakery records.
- `test_preflight.py`: same rename; `collect_custom_fields` derives its expectation from the fixture file,
  so the test tuple had to follow it.
- `test_shell_contract.py`: `doc_events` and `fixtures` expectations updated to the current shape.

**Adjacent regressions on `promo-mvp.localhost`, twice each, all GREEN:** `test_promotion_expansion` 27,
`test_g1_model_c_spike` 7, `test_promotion_master` 36, `test_promotion_eligibility` 17,
`test_promotion_pricing` 13, `test_promotion_contracts` 1, `test_hooks` 5, `test_walk_in` 10,
`test_walk_in_asset` 12, `test_navigation` 7, `test_shell_contract` 7+1, `test_install_paths` 10,
`test_checksums` 6, `test_module_transfer_patch` 11, `test_sidebar_cleanup` 9,
`test_recovery_map_digest` 8.

**Pre-existing failures on this site, proved baseline by neutralizing all three promotion hooks and
re-running — identical failure sets with the engine on and off. Not regressions, not this task's to
fix:**

- `test_past_orders` 7 errors — `FiscalYearError` for `_Test Selling Company`; this site has no Fiscal
  Year and the module's fixture does not create one.
- `test_price_group_lifecycle` 1 error — `Abbreviation already used for another company`, accumulated
  site residue.
- `test_price_group_concurrency` 1 error — `LinkValidationError: Could not find Company: _Test Selling
  Company`, missing site fixture.
- `test_migration` 5 errors — `preflight.check(phase="post_model_sync")` fails its `profile_recovery`
  section: the recovery map names a Price List that does not exist on this site (this site has **zero**
  Price List rows).
- `test_preflight` 4 failures — three `TestProfileRecovery` cases and
  `test_missing_walk_in_blocks_on_legacy_site`, both rooted in the same missing site fixtures
  (`Standard Selling` absent; `bakery_manufacturing` not installed here, so the legacy-site branch cannot
  fire). `test_preflight` improved 5 → 4 because the field-tuple correction fixed one of them.

`promo-mvp.localhost` carries only `frappe`, `erpnext`, `selling_additional`, so any assertion needing
`bakery_manufacturing` or the cutover site's business fixtures cannot pass here by construction. The
Phase 2 baseline for those modules is `selling-cutover.localhost`.

**Static checks:** `uvx ruff@0.14.10 check selling_additional` all passed; `format --check` 67 files
already formatted; `git diff --check` clean. `apps/frappe` and `apps/erpnext` carry no feature diff
(ERPNext keeps only its known `banking/yarn.lock` edit); `roti_ropi_pos` untouched apart from this
checkpoint; `patches.txt` byte-identical.

### Cross-Task Audit Remediation (Tasks 1-4, 2026-08-20)

A pre-commit audit across Tasks 1-4 found two real defects. Both are fixed, RED-first, with mutation
proof. Nothing else changed.

**A. Preflight `final` phase rejected a legitimate registration.**
`collect_hook_owners("final")` asserted `paths == [WALK_IN_SELLING]` over every provider on
`doc_events[<dt>]["validate"]`. Task 1 appended `promotions.engine.on_validate` to POS Invoice
`validate`, so the rule read the engine as a second walk-in provider and returned `ok=False`.
Measured `False` on `promo-mvp.localhost`, `selling-cutover.localhost`, and the live
`development.localhost`; `pre_model_sync` and `post_model_sync` were unaffected. This is
operator-facing: `AGENTS.md` treats `preflight.check()` as a bench-invokable interface used by the
rollout runbook, and design §17 assumed preflight was untouched by the MVP.

Fix: `preflight.NON_WALK_IN_VALIDATE_PROVIDERS` lists the exact `(app, path)` pairs this app
deliberately registers on the shared `validate` event; the collector routes those into a separate
`other_validate_providers` bucket and leaves the walk-in assertion otherwise unchanged. Any pair not
listed — a foreign app's handler, or a missing walk-in registration — still counts and still blocks,
so the rule stays fail-closed.

Three tests, each killed by its own mutation and by no other:
- `test_final_passes_against_real_registrations` — real hooks, no mock. The existing
  `test_final_requires_single_walk_in_provider` patches `frappe.get_hooks`, which is precisely why it
  could not catch this.
- `test_final_ignores_a_non_walk_in_provider_on_the_same_event` — mocked equivalent.
- `test_final_requires_the_walk_in_provider_to_be_present` — pins the presence half of the
  assertion, which the filter could otherwise have weakened silently.

Mutations: removing the exclusion filter failed exactly the two allow-tests (2 → 6 failures);
relaxing `paths != [WALK_IN_SELLING]` to `len(paths) > 1` failed exactly the presence test.

Phase results after the fix, all three phases `ok=True` with empty problems, on all three sites:
`promo-mvp.localhost`, `selling-cutover.localhost`, `development.localhost` (read-only console call,
no writes).

**B. `Promotion` permissions did not match design §18.**
`promotion.json` shipped one permission row (`System Manager`). Design §18 requires create/write for
**System Manager** and **Sales Manager** and read for **Sales User**, with no cashier role. No task
in the implementation plan owns §18, so this was unallocated rather than deferred.

Fix: two permission rows added; `Promotion` is not submittable (`is_submittable = 0`), so no submit
permission is expressible and none was invented. Delete stays System-Manager-only. `modified` bumped
`2026-08-19` → `2026-08-20`, keeping this app's stamp newest. Child tables keep zero permission rows
and inherit the parent's.

`test_promotion_contracts` grew 1 → 5 tests: JSON role set and per-right values, no-extra-role,
child tables carry no permission rows, and the live `DocPerm` rows on the site (so a JSON that never
synced still fails). Mutations: JSON role swap `Sales User` → `Accounts User` failed the JSON and
extra-role tests; a stale-database condition (correct JSON, DB left at `Sales Manager.write = 0`)
failed only the live test; a permission row added to `promotion_outlet.json` failed only the child
test. `bench --site promo-mvp.localhost execute frappe.reload_doc` synced the definition on the
dedicated test site only — no migrate, and no write to any other site.

**Verification after both fixes** (`promo-mvp.localhost`, changed modules twice each):
`test_promotion_contracts` 5 OK ×2, `test_preflight` 42 tests / 4 pre-existing failures ×2 (was 4
before these fixes too — the two new hook-owner failures are gone), `test_promotion_master` 36 OK,
`test_promotion_eligibility` 17 OK, `test_promotion_pricing` 13 OK, `test_promotion_expansion` 27 OK,
`test_g1_model_c_spike` 7 OK, `test_hooks` 5 OK, `test_shell_contract` 7+1 OK, `test_install_paths`
10 OK, `test_walk_in` 10 OK, `test_walk_in_asset` 12 OK, `test_navigation` 7 OK, `test_checksums` 6
OK, `test_module_transfer_patch` 11 OK, `test_sidebar_cleanup` 9 OK, `test_recovery_map_digest` 8 OK.
`test_migration` keeps its 5 pre-existing `profile_recovery` errors; the `hook_owners` section inside
those same reports is now `ok=True`, confirming the failure is the recovery-map fixture and not this
change. Ruff 0.14.10 check passed, format 67 files already formatted.

**Tasks 1-4 are committed.** `selling_additional` commit `7bf8dd9` ("feat: add Dynamic Promotion /
Combo MVP (Tasks 1-4)") carries the promotion DocTypes, the `promotions/` package, the fixture and
`hooks.py` changes, the preflight remediation, and every Task 1-4 test module, on branch
`docs/dynamic-promotion-implementation-plan`. The audit remediation record for those tasks is committed
in this repo as `de4db45`. Tool output (`.agents/`, `.claude/`, `.codegraph/`, `.superpowers/`,
`.zcode/`, `skills-lock.json`) stayed excluded, as intended.

### Task 5 / Return Semantics Evidence Summary

**Scope:** plan Task 5 — invariant I6, decision D11, gate G3's return half, plus G7 point 10.

**Production file:** `selling_additional/promotions/engine.py` only, `+121 −0`. No DocType JSON, fixture,
`hooks.py`, `patches.txt`, permission, or core file changed. No migrate ran. No new whitelisted endpoint.

**Implementation.** `_validate_return_completeness` plus its reader `_source_promotion_rows`. A return
carrying promotion rows without `return_against` throws. Otherwise the guard rejects a promotion row that
carries no instance id and a promotion row with positive quantity, then groups return rows by
`(instance_id, item_code)`, compares each returned instance against the source invoice's own child rows,
and throws when an instance is unknown to the source, when any item's quantity differs from what was
sold, or when the return carries an item that instance never sold. Instances absent from the return are
untouched — absent is as valid as complete. The sale-side instance cap is never consulted.

**Ruling — the guard runs on `before_validate` only.** Hooks registered on `validate` run *after*
`POSInvoice.validate` itself (`frappe/model/document.py:1403` runs the composed method and ERPNext's own
body executes first inside it). An incomplete return therefore hit ERPNext's own
`At least one item should be entered with negative quantity in return document` and
`Paid amount + Write Off Amount can not be greater than Grand Total` before the engine ever saw the
document, hiding the real reason from the cashier. `before_validate` runs before any of that
(`document.py:1396-1397`) and is already this engine's materialization point. It is also not a
submit-time gap: `run_before_save_methods` runs `before_validate` for `_action in ("save", "submit")`,
so a draft that is later submitted re-enters the guard. `test_partial_return_is_blocked_at_submit_too`
pins exactly that — a complete draft is inserted, a component is then removed, and `submit()` throws the
named error with the document left at `docstatus 0`. A second call at `before_submit` would cover the
same condition and pin nothing, so the guard deliberately has one call site. Measured, not assumed: with
the guard on `validate` the suite reported the two ERPNext messages instead of the named errors.

**Ruling — promotion rows on a return are selected on instance *or* role.** Selecting on the instance
field alone let a crafted row carrying only the role slip past this guard; it was still rejected, but by
`_validate_promotion_row_integrity` on `validate`, which is behind ERPNext's own return errors — the very
masking the placement above avoids. The guard now selects on either field and throws its own named error
for a promotion row with no instance id.

**Ruling — the sign is checked, not absorbed.** An earlier version accumulated `abs(flt(row.qty))`, so a
positive component row satisfied the returned quantity of a negative one; only ERPNext's later
`validate_return_items_qty` stopped the document, after the guard had already approved it. The guard now
throws on any promotion row with `qty > 0` and accumulates the plain sign flip.

**Ruling — completeness is measured from the source child table, not the source document.**
`_source_promotion_rows` reads `tabPOS Invoice Item` filtered by parent and a set instance field. A
controller default or a later amendment of the source document cannot then change what completeness is
compared against. The instance filter narrows the read and is documented in source as not being a guard.

**Stock and refund reversal stay native.** No custom reversal code exists. The pass-path test asserts the
negated component demand on the return rows (`bread_a −2`, `bread_b −1`) and that the parent item is
non-stock, so it contributes no stock movement; the consolidated Stock Ledger Entry evidence for the same
path is `test_g1_model_c_spike` point 11, still 7 OK.

**RED → GREEN.** `selling_additional/tests/test_promotion_returns.py`, 19 tests. First run: 14 errors,
all fixture faults (one POS Opening Entry per invoice is rejected — `<profile> is open`; a manually built
return needs `paid_amount` set, otherwise `validate_change_amount` raises `TypeError` on `None`). After
the fixtures were correct, 4 genuine failures drove the placement ruling above and one test-only
correction: mapped child rows from `make_sales_return` are unsaved and share an empty `name`, so the
"drop one component" test selects by object identity, not by name. An independent review then added four
tests (role-only row, positive quantity, zero quantity, blocked-at-submit) and widened the
source-untouched test to cover `modified`, the source item rows, and the invoice totals rather than the
selection table alone. GREEN twice consecutively: 19 OK in 38.389s and 37.047s.

**Mutation ledger — 12 mutations, engine restored and verified byte-identical after each:**

| Mutation | Failing test(s) |
| --- | --- |
| guard call removed from `on_before_validate` | all 11 fail-path tests |
| `is_return` early return removed | 17 errors (guard runs on ordinary sales) |
| no-promotion-rows early return removed | `test_standalone_return_without_promotion_rows_is_allowed` |
| row selection narrowed to instance-only | `test_return_row_carrying_only_a_role_throws_the_return_error` |
| standalone-return throw | `test_standalone_return_with_promotion_rows_throws`, `..._carrying_its_own_selections_still_throws` |
| missing-instance throw | `test_return_row_carrying_only_a_role_throws_the_return_error` |
| positive-quantity throw | `test_positive_promotion_row_cannot_stand_in_for_returned_quantity` |
| unknown-instance throw | `test_return_row_for_instance_absent_from_source_throws` |
| quantity-mismatch throw | 5 tests: 3 partial-return, zero-quantity, blocked-at-submit |
| extra-item throw | `test_return_carrying_an_item_never_sold_under_the_instance_throws` |
| sign flip reverted to `abs()` | **survived** — equivalent expression, not a guard |
| source-row instance filter removed | **survived** — narrows the read, not a guard |

The two survivors are deliberate and documented in `engine.py`: with the positive-quantity throw in
place, `- flt(row.qty)` and `abs(flt(row.qty))` are the same value, and dropping the source filter only
adds an entry keyed on the empty instance that no returned instance can match. Reporting them as
survivors rather than adding tests that pin an equivalence is the honest outcome. Earlier doc text
claiming "6 mutations each killing exactly their own guard" overstated isolation and has been corrected.

**Adjacent regressions on `promo-mvp.localhost`, all GREEN:** `test_promotion_expansion` 27,
`test_g1_model_c_spike` 7, `test_promotion_master` 36, `test_promotion_eligibility` 17,
`test_promotion_pricing` 13, `test_promotion_contracts` 5, `test_hooks` 5, `test_shell_contract` 1+7,
`test_install_paths` 10, `test_walk_in` 10.

**Pre-existing, not caused by Task 5:** `test_preflight` 42 tests / 4 failures — three
`TestProfileRecovery` cases and `test_missing_walk_in_blocks_on_legacy_site`, the same site-fixture gap
recorded above. Proved baseline by restoring `engine.py` to its committed `7bf8dd9` content and
re-running: identical 4 failures with and without the Task 5 change.

**Site hygiene.** `POS Settings.invoice_type` is a Single, and `set_single_value` also clears a document
cache that `frappe.db.rollback` cannot undo, so the test module now records the previous value and
restores it via `addCleanup`. Verified after a full run: the site still reads `Sales Invoice`, its
original value.

**Static checks:** `uvx ruff@0.14.10 check selling_additional` all passed; `format --check` 68 files
already formatted.

**Reviewed independently before commit.** A separate adversarial review read the full diff, the whole
test module, and the relevant installed Frappe and ERPNext source. It found no path to `docstatus 1`
that bypasses the guard, confirmed the cap is never re-checked by reading rather than by test, and
confirmed `["is", "set"]` excludes empty strings in this Frappe version. Its two Should-fix findings —
the role-only row selection and the `abs()` sign weakness — are both fixed above with a test each. It
also judged the `_repay` test helper legitimate rather than defect-masking: `make_return_doc` negates the
source's full payment, so a deliberately reduced return must restate the refund, and having the engine
restate it would silently change money on an operator's document.

### Task 6 / Reporting Projection Evidence Summary

**Scope:** plan Task 6 — design §11 (D16), invariant I14, gate G5. The paused-session handoff record
(`.superpowers/sdd/2026-08-14-selling-additional-cutover/promo-task6-facts-handoff.md`) drove the
implementation; none of its investigation was repeated.

**Production files:** new `selling_additional/doctype/promotion_selection_fact/` (DocType JSON,
pass-through controller, `__init__`), new `promotions/facts.py`, `hooks.py` (+2 lines: POS Invoice
`on_submit`/`on_cancel` → `promotions.facts`). Both `doc_events` pinning tests (`test_hooks.py`,
`test_shell_contract.py`) updated in the same change. New `tests/test_promotion_facts.py` (15 tests).
No patch registered; `patches.txt` byte-identical. The DocType arrives via model sync only.

**Measured ruling — reported disagreement with design §11's literal return-side SQL.** A mapped
return (`make_sales_return`) copies EVERY `POS Promotion Selection` row (`no_copy = 0`), so a return
repaying one instance out of two still carries both selections; §11's "same join restricted to
`is_return = 1`" counts 2 and refunds 43,000 where the truth is 1 and 20,000 (measured in the paused
session). Correctness wins: instance presence is derived from the document's promotion item rows,
and every return-side figure comes from the fact/parent-row data, never the copied selection table.
The disagreement is documented in `facts.py`'s module docstring and was reported to the operator.

**Encoded rulings in `facts.py`.** Per-line descriptors come from the selection snapshot (rows cannot
express the fixed-vs-option split — one Item may be both in one instance, two invoice lines, no kind
marker); `qty`/`promotion_total` negated iff `is_return` (magnitude from snapshot, exactness
guaranteed by the Task 5 guard); `price_adjustment` is a unit-price attribute, never negated;
`item_name` live Item lookup for every line (uniform rule; snapshot carries it only for options);
`warehouse` from the instance's component rows (uniform by I13); identity is `autoname: "hash"`
because no deterministic composite key survives the fixed+option overlap — tests compare by canonical
semantic equality. Reporting helpers normalize the return side to a positive magnitude with
`net = gross − returned`. `standalone_split()` reads `tabPOS Invoice Item` directly (empty instance
vs role `Promotion Component`, `docstatus = 1`) and omits zero-zero items — promotion parents are in
neither bucket. Permissions per design §18: exactly System Manager / Sales Manager / Sales User with
read+report only, nobody create/write; rows are written by `insert(ignore_permissions=True)` from
doc-events/system code only.

**RED → GREEN.** First module run (pre-migrate): 15 tests — 12 errors (`tabPromotion Selection Fact`
doesn't exist), 1 failure (live DocPerm absent), 2 contract tests GREEN by design. After the authorized
migrate (backup first, path above): GREEN, and GREEN again on the second consecutive run; further
GREEN runs after each later edit. Two test-code corrections on the way: `get_all` returns
`posting_date` as a `date` object while the document carries the string (normalize with `getdate`;
the canonical string projection was never affected), and the standalone split omits items whose both
buckets sum to zero (pinned by test).

**Mutation ledger — 18 mutations, 17 killed, every restore verified byte-identical by sha256:**

| Mutation | Failing test(s) |
| --- | --- |
| on_cancel delete removed | 3 cancel/exclusion tests + rebuild |
| return sign removed (`sign = 1.0`) | 6: signed facts, adjustment-not-negated, revenue/outlet/itemqty/optionfreq |
| `return_against` dropped | signed-facts test |
| `promotion_total` not negated | signed facts, adjustment, revenue, outlet |
| presence from selections union (finding-2 guard) | 7 incl. units and rebuild |
| rebuild `docstatus` filter removed | rebuild test |
| units / revenue / outlet `DISTINCT` removed | each own query test (+exclusion for units/revenue) |
| option `kind` filter removed | option-frequency test |
| standalone role filter / instance filter removed | standalone-split test |
| `on_submit` hook registration removed (hooks.py) | 9 failures + 2 errors |
| `price_adjustment` negated | adjustment-not-negated test |
| item/units/revenue `is_return` returned-split removed | each own query test |
| `_project` delete-first removed | **survived** — documented in source as untestable defense-in-depth |

M9/M10 were first killed via SQL parameter errors; both were re-run with parameter-preserving
mutations and killed by their assertions instead.

**Adjacent regressions on `promo-mvp.localhost`, all GREEN:** `test_promotion_facts` 15 (×2),
`test_promotion_returns` 19, `test_promotion_expansion` 27, `test_g1_model_c_spike` 7,
`test_promotion_master` 36, `test_promotion_eligibility` 17, `test_promotion_pricing` 13,
`test_promotion_contracts` 5, `test_hooks` 5, `test_shell_contract` 1+7, `test_install_paths` 10.
`test_preflight`: 42 tests / the same 4 pre-existing failures (site-fixture gap, unchanged).
Static: `uvx ruff@0.14.10 check` passed, `format --check` 72 files clean. `apps/frappe`/`apps/erpnext`
untouched.

**Independent adversarial review: PASS with notes (0 must-fix).** Its two should-fix findings are
applied and re-verified GREEN: (a) the I14 source-contract scan now also matches `promotions.facts` /
`promotions import facts` so a symbol-import breach cannot stay green (hooks.py allowlisted as writer
wiring); (b) `test_query_outlet_totals` now scopes its assertion to the run's own POS Profile instead
of whole-list equality. Its three notes, recorded: (1) on installed-but-unmigrated sites every POS
Invoice submit/cancel fails closed and loud (missing table) until each site migrates — atomic, no
partial state (reviewer verified no `frappe.db.commit()` in the ERPNext submit/cancel path), but
deployment ordering must migrate before shipping this tree to `development.localhost` /
`selling-cutover.localhost`; (2) the only `on_cancel` skip path is banned `delete_doc(force=True)`
orphaning rows — recoverable via `rebuild()`, no standard flow does it; (3) `rebuild()` is non-atomic
(drop-then-reproject; an interruption leaves a partial table until re-run) — acceptable under I14,
worth a rollout-runbook awareness line.

**Task 6 was subsequently committed as `754017f`** ("feat: add Promotion Selection Fact reporting
projection (Task 6)") — exact-path staging; tool output stayed excluded.

### Task 7 / Hardening and Release Gates Evidence Summary

**Scope:** plan Task 7 — final MVP gate. No production behavior change: `engine.py` gained 9
comment lines only (the independent reviewer verified comment-only by stripped-byte diff).

**Guard→test audit (mutation review of record).** Five parallel read-only audits (engine
expansion, master validation, return guard, facts projection, cross-app contracts and permissions)
re-verified every §12 ledger pair directly against source. Findings: three engine payload-input
guards and two master exists-guards had no killing test; the return guard's role-branch selection
and missing-instance throw share one killer. Cross-app contracts: all PASS (zero whitelist in
`promotions/`, I14 enforced incl. symbolic-import scan, permissions per design §18 pinned incl.
live DocPerm rows, no sibling-app imports, fixture order 6+4 intact, facts written only by system
paths).

**Hardening tests added (test files only), each mutation-killed with the engine/controller
restored byte-identical afterwards:**

- `test_promotion_expansion.py` +2: malformed-JSON payload guard (mutation → raw
  `json.JSONDecodeError` escapes — killed), missing-`promotion`-key guard (mutation → "Promotion
  None not found" — killed). Module 27 → 29 GREEN.
- `test_promotion_master.py` +2: component/parent exists-guards under `ignore_links` — the only
  reachable path, because `Document.insert` runs `_validate_links` before `validate`
  (frappe/model/document.py:472/479) and both fields are Links; mutation → `AttributeError` on
  `None` — killed. Module 36 → 38 GREEN.

**Two documented non-independent pairs (source comments in `engine.py`; honest survivors, not
gaps):** the payload exists-check duplicates `frappe.get_doc`'s own `DoesNotExistError`
(`ValidationError` subclass, identical message — no honest killer exists); the return role-branch
and the missing-instance throw form one causal guard — every killer of one kills the other by
construction.

**Run-twice.** All 8 promotion modules twice consecutive, all OK: facts 15, returns 19, expansion
29, g1 7, master 38, eligibility 17, pricing 13, contracts 5. Full `--app selling_additional`
suite twice consecutive — identical both passes: 334 tests, 18 failures, the same failing tests.
All 18 attribute exactly to the documented site-fixture baseline: `test_migration` 5,
`test_past_orders` 7, `test_preflight` 4, `test_price_group_concurrency` 1,
`test_price_group_lifecycle` 1. No new failure, no regression. A `test_preflight` module-run
reproduces the recorded 42/4 exactly (the suite total of 51 = 42 + the 9 plain `unittest.TestCase`
tests the suite path also runs).

**Adjacent regressions (gate 3):** all green in both suite passes, counts matching the Task 6
baseline — walk_in 10, walk_in_asset 12, navigation 7, hooks 5, shell 1+7, install 10, checksums 6,
module_transfer_patch 11, sidebar 9+1, recovery_map_digest 8, g1 7.

**Model-sync/patches (gate 4):** DocType `modified` stamps unchanged and newest (fact 2026-08-22;
Promotion 2026-08-20; promotion children 2026-08-19; Price Group trio 2026-08-16);
`patches.txt` byte-identical to HEAD, byte-pin tests green in the suite; no other app defines any
promotion DocType (grep across all bench apps). The optional scratch fresh-install site remains
the operator's approval-gated choice — not created.

**Preflight (gate 5):** `bench --site promo-mvp.localhost execute
selling_additional.migration.preflight.check` for all three phases (`pre_model_sync`,
`post_model_sync`, `final`) — every section `ok=true` with empty problems, confirmed with real
output, not "considered".

**Static (gate 6):** `uvx ruff@0.14.10 check .` all passed; `format --check .` 72 files clean,
re-run after every edit.

**Independent review (gate 7):** frappe-reviewer **PASS — Critical 0 / Important 0**. It verified
the engine diff comment-only, the tests additive and convention-clean (rollback-first, no commit,
unique names, one guard per assertRaisesRegex), the `ignore_links` legitimacy (ordering confirmed
in installed source), and the `DoesNotExistError` equivalence. One should-fix applied: the
ignore_links test comments now name framework-internal callers/patches as the real path (Data
Import does not use ignore_links in this Frappe); `test_promotion_master` re-run GREEN (38 OK)
after the reword.

**Repo hygiene:** `apps/frappe` carries tool output only; `apps/erpnext` only its known
`banking/yarn.lock` edit; `roti_ropi_pos` untouched apart from this checkpoint. Exact Task 7
working set: `selling_additional/promotions/engine.py` (comments only),
`selling_additional/tests/test_promotion_expansion.py`,
`selling_additional/tests/test_promotion_master.py`.

**Closed out (2026-08-22).** The operator declined the optional scratch fresh-install site —
`promo-mvp.localhost` was itself created fresh in Task 1, so install-from-zero is already proven;
gate 4 stands on the recorded stamp / patches-byte-pin / no-foreign-copy evidence. The three code
files are committed as `8893996` ("test: add Task 7 hardening tests and guard-pairing docs",
exact-path staging; tool output stayed excluded). The Dynamic Promotion MVP (Tasks 1-7) is
complete. Still uncommitted in `selling_additional`'s working tree, awaiting their own
authorization: the plan-doc Status line and the AGENTS.md/CLAUDE.md Project State update, plus
this checkpoint in `roti_ropi_pos`.

### Post-Task-7 operator-directed changes (2026-08-22, same day)

Two operator requests after Task 7 closed; both executed and verified.

**A. Promotion added to the Selling Additional sidebar (operator override of design §16's
deferred navigation item).** Production changes: `workspace_sidebar/selling_additional.json`
gains a third item (Promotion, DocType link, ERPNext's exact ten-key child shape, `modified`
bumped 2026-08-16 → 2026-08-22) and the workspace Home card gains a matching Promotion Link row
(`selling_additional/workspace/selling_additional/selling_additional.json`). Pin updates in
`test_navigation.py` only (`EXPECTED_PROMOTION_ITEM`, items 2 → 3, workspace links list) — a
scope change authorized by the operator, not a weakening. Applied on `promo-mvp.localhost` via an
authorized migrate (backup first:
`private/backups/20260822_221844-promo-mvp_localhost-database.sql.gz`); DB verified Home/Price
Group/Promotion idx 1-3 plus three workspace Link rows. Verified: `test_navigation` 7 OK ×2,
`test_sidebar_cleanup` 9 OK ×2, ruff clean. Other sites get the sidebar at their own future
migrate.

**B. Port 8000 permanently unpinned.** Root cause of the operator's "Page promotion not found"
and failed logins: `sites/common_site_config.json` carried `default_site:
selling-fresh.localhost`, and `bench serve` pins `_site` from `get_sites()` — every hostname on
port 8000 was served as selling-fresh.localhost (since 2026-08-16). Fix: `default_site` removed
(surgical JSON edit) + the operator's werkzeug reloader restarted in place (touch
`apps/frappe/frappe/app.py`; honcho undisturbed). Verified per-hostname: promo-mvp login 200 and
DocType Promotion 200 on port 8000. Side effect to remember: bench commands without `--site` no
longer default to selling-fresh — pass `--site` explicitly. A temporary `bench serve --port 8001
--site promo-mvp.localhost` ran during the investigation; it dies with the session, port 8000 is
canonical again.

**Measured baseline change (explained, not anomalous): `test_preflight` 4 → 1 failures on
promo-mvp.** During the access fix the operator logged in and used the desk (serve log: session
ropierpnext@gmail.com opened `/desk/promotion`, searched parent items on the new form); that
activity created the missing `Standard Buying`/`Standard Selling` Price Lists (both rows created
2026-08-22 22:13:07, Administrator), healing the three documented TestProfileRecovery site-fixture
failures. The remaining failure is exactly the documented promo-mvp baseline entry
(`test_missing_walk_in_blocks_on_legacy_site`, bakery not installed here).

**Commits done (operator-authorized, 2026-08-22).** The sidebar/workspace/test changes are
committed as `c940790` ("feat: surface Promotion in the Selling Additional sidebar"), and the
Task 7 + post-Task-7 documentation (plan-doc Status, AGENTS/CLAUDE Project State) as `3ee7c2e`
("docs: record Task 7 completion and post-Task-7 navigation changes"). `selling_additional`'s
tracked working tree is clean (tool output only remains untracked). This checkpoint file in
`roti_ropi_pos` is still uncommitted, awaiting that repo's own authorization.

### Operator-directed Promotion form UX overhaul (2026-08-22/23, uncommitted in selling_additional)

Operator found the Promotion form confusing; requested a user-friendly layout, worked examples,
and an MD fill-in guide. Display-layer only: no fieldname, permission, hooks, or `patches.txt`
changes; `choice_group_key` Data→Select is column-compatible (both varchar(140), verified in
mariadb type map) and `_validate_selects` skips empty static options (verified base_document.py).

**Changes (5 DocType JSONs, stamps → 2026-08-22 17:30):** intro HTML field `intro_help` (no-value
type, no column); section relabels with descriptions (Promotion Details / Promo Product & Price /
Fixed Components / Customer Choices — Groups / — Options / Where Active (Outlets)); per-field
descriptions everywhere; `max_instances_per_invoice` label → "Max Packages Per Invoice" +
`non_negative` (framework `_validate_non_negative` runs AFTER controller validate — document.py
:587/:590 — so controller messages still fire first; negative-value tests unaffected, verified);
`base_price`/`price_adjustment` get `options: "currency"` (symbol via `get_field_currency`; the
`parent.` prefix does NOT resolve — plain fieldname falls through to `cur_frm.doc`); Choice Group
grid hides `group_key` from list view; Option grid `choice_group_key` → Select "Choice Group".

**New `doctype/promotion/promotion.js`:** Options-grid Choice Group column becomes a dropdown of
this document's groups — `{label, value}` objects are supported by `ControlSelect.parse_option`
(verified select.js) — showing labels, storing keys, "Untitled group" fallback, duplicate labels
disambiguated by appending the key, disabled "Add a choice group first" hint when empty. Group keys
are client-pre-generated at row add (`grp_`+8hex, same format as the server's; server only fills
missing keys) so groups + options save in ONE pass. Outlet warehouse link filters by row company
(Price Group pattern). Two framework facts cost debugging time and are now pinned in AGENTS
Keputusan Kunci: (1) grid `<table>_add`/`_remove` handlers must be registered on the CHILD doctype
(`get_handlers` looks up `handlers[child_doctype][event]`; ERPNext's `items_add` follows this) —
first version registered on Promotion and silently never fired, found via live
`frappe.ui.form.handlers` introspection; (2) FormMeta is served from `client_cache`
(`doctype_form_meta::<dt>`, bypassed only in developer_mode) — a `.js` edit on non-developer-mode
promo-mvp needed `bench --site promo-mvp.localhost clear-cache` before the server served it.

**Verification:** prettier (pre-commit pin v2.7.1) clean; ruff clean; authorized migrate on
promo-mvp (backup `20260822_234353-promo-mvp_localhost-database.sql.gz`) — all five metas synced
on-site; browser-verified via IAB: form renders with new sections/descriptions, PROMO-00001 grid
shows label columns, adding a group auto-assigned `grp_61cef387` and the Options dropdown listed
"Pilih Roti" + the new group by label immediately. Worked examples created on promo-mvp (committed
data): items Roti Coklat/Keju/Kismis, Kopi Susu Kotak, parents Paket Hemat Sarapan / Bundling 2
Roti Hemat; PROMO-00001 "Paket Hemat Sarapan" (enabled, base 25.000, Kopi Susu ×1 fixed, group
"Pilih Roti" pick 1 with +0/+2.000/+3.000 adjustments, max 2/invoice, outlet JURI/Stores-JURI)
and PROMO-00002 "Bundling 2 Roti Hemat" (draft/disabled, pure fixed bundling). Guide:
`selling_additional/docs/promotion-fill-in-guide.md`, deliberately Bahasa Indonesia (operator
audience, noted in-file).

**Promotion module test state after the migrate — resolved 2026-08-23 (operator decision).**
Immediately after the migrate, contracts/eligibility/pricing/facts were GREEN ×2 while
master/expansion/returns each failed exactly 1 test deterministically ×2. Root cause measured and
NOT the layout change: the operator's 22-08 22:13:12 desk session enabled
`Stock Settings.auto_insert_price_list_rate_if_missing` (ERPNext default 0), and
`erpnext/stock/get_item_details.py:insert_item_price` auto-creates a selling Item Price for any
transaction item without one — including promotion parent rows. Separately, on 23-08 01:19 a
manual Item Price `4e6pith2hd` (Rp26.000, Standard Selling) was created for parent "Paket Hemat
Sarapan" during desk use, making every Promotion re-save fail D12 ("must not have any selling
Item Price"). Operator chose: delete the row + disable the flag. Executed and verified 23-08: no
selling Item Price remains on either parent, flag 1→0, and the three previously failing modules
are GREEN twice in a row (master 38 / expansion 29 / returns 19, both passes OK). Submitting promo
invoices on promo-mvp is safe again. Standing ruling recorded in AGENTS Keputusan Kunci: promo
sites must keep the flag off; engine hardening (parent rows must not trigger `insert_item_price`)
remains a separate future task for sites/production that need the flag on.




### Desk POS promotion picker (2026-08-23, uncommitted in selling_additional)

Operator-directed early activation of design §16's "Desk POS picker (page-scoped asset in this
app)". Plan approved via ExitPlanMode before implementation. Server contracts were already in
`promotions/api.py`; only a facade + client asset were missing. No engine/domain/DocType/fixture/
patch changes; no migrate needed (`page_js` files are read live via `get_js`).

**Files:** `selling_additional/overrides/pos_promo_api.py` — three `@frappe.whitelist()` wrappers
(`get_available_promotions`, `get_promotion_detail`, `quote_promotion`) gating on Promotion read +
POS Profile read then delegating to the pure contracts (wrappers must stay outside the promotions
package per the AST contract test). `selling_additional/public/js/pos_promotions.js` — page-
scoped asset mounted like the walk-in script (wraps `frappe.pages["point-of-sale"].on_page_load`,
MutationObserver): Promo button beside the cart label, eligible-promotions dialog, per-group qty
steppers with live pick counters and `max_per_option` enforcement, package quantity with cap
hint, server quote via `quote_promotion`, pending-payload chips (per-round remove, promo total),
payload written to `custom_selling_additional_pending_promotions`; guards disable the button for
non-POS-Invoice mode / submitted / already-materialized drafts and block edits or removals of
rows carrying a promotion instance field. `hooks.py` `page_js` → 2-entry list (list support
verified in `get_code_files_via_hooks`); `test_hooks` pin updated to the ordered list with the
reason stated. `.eslintrc` gains the `selling_additional` global (the committed walk-in file had
been failing eslint's no-undef identically). Guide §8 (Indonesian POS simulation walkthrough).
New `tests/test_pos_promo_api.py`: permission gate, outlet filtering, JSON-string normalization,
quote equality with the domain, ineligible rejection, and end-to-end materialization from a
wrapper-quoted payload — 7 tests GREEN ×2 on promo-mvp.

**Browser E2E (promo-mvp, Administrator, profile Kasir JURI):** opening entry created via the UI;
PROMO-00001 listed (disabled PROMO-00002 excluded); Roti Keju picked → server quote Rp27.000 →
chip shown; mixed cart with regular Roti Coklat; Checkout draft save materialized Model C rows
(parent 27.000 + Kopi Susu 0 + Roti Keju 0), grand total 35.000, Promo button auto-locked;
ACC-PSINV-2026-00001 submitted Paid; selections row `inst_b9a76de5d8a7` total 27000 frozen; fact
rows written (Option + Fixed Component); NO parent Item Price was created (D12 fix held under a
real submit). Recent Orders → Return loaded the complete negative cart, return guard passed,
ACC-PSINV-2026-00002 (-35.000) submitted; facts show negated qty/promotion_total with
is_return=1 for the same instance id. Stock does not move per invoice in this ERPNext line — it
consolidates at closing (consistent with Task 1's Model C proof).

**Demo prep on promo-mvp (authorized by the plan):** customer Walk In JURI; Standard Selling
prices for Roti Coklat/Roti Keju/Roti Kismis/Kopi Susu Kotak (never the parents); Material
Receipt MAT-STE-2026-00002 (50 each into Stores - JURI); POS Profile "Kasir JURI" on
PT. Juara Roti Indonesia / Stores - JURI with Cash payment and Walk In JURI default; POS Settings
invoice_type flipped from "Sales Invoice" back to "POS Invoice" (engine is POS-Invoice-only —
the picker disables itself otherwise).

**Measured ERPNext v16 facts (recorded in AGENTS Keputusan Kunci):**
1. A user may hold only ONE open POS Opening Entry ("Cashier is currently assigned to another
   POS") — an operator shift left open fails every suite's `_open_shift()` with mass errors.
2. Consolidation cannot merge a sale together with its full return inside one closing entry:
   netted rows vanish so return-item validation fails ("Returned Item Roti Coklat does not exist
   in Sales Invoice ...").
3. Merge logs run as enqueued background jobs — the closing entry must be committed BEFORE
   submit or the job dies on LinkValidationError against the uncommitted closing.
Consequence on promo-mvp: the demo shift was closed with an intentionally empty transaction list
(POS-CLO-2026-00003); ACC-PSINV-2026-00001/-00002 remain Paid/Credit Note Issued unconsolidated
(demo data), bins still show pre-sale stock. Regression after cleanup: all nine promotion-related
modules green (hooks 5, contracts 5, eligibility 17, pricing 13 once; pos_promo_api 7 ×2, master
38 ×2, expansion 29 ×2, returns 19 ×2, facts 15 ×2).

### Parent-item click interception + page-asset caching (2026-08-23 evening, same uncommitted batch)

Operator report: clicking the promotion parent item in the item selector added it as a plain
cart row and the engine rejected it ("Row 1: Item Paket Hemat Sarapan is a Promotion parent item
and cannot be sold on its own") instead of offering the choices.

**Fix (pos_promotions.js only, uncommitted):**
- `install_row_guards()` now wraps `pos.on_cart_update`: if the clicked item_code maps to an
  eligible promotion parent (parent_map built from `get_available_promotions`), the click is
  routed to `open_picker(promotion)` and never reaches the cart. Non-parent items pass through
  to the original handler.
- Timing bug found and fixed: `wrapper.pos` is created asynchronously inside `frappe.require`
  AFTER `on_page_load` returns (point_of_sale.js line 11-14), so guard installation at mount
  time always no-opped. `render()` now retries `install_row_guards()` (idempotent via
  `__promo_guards`).
- `get_parent_map` promise is now keyed per POS Profile (stale-promise edge on profile change).
- Parent cards carry a "Promo" badge (`.pos-promo-badge` inside `.item-qty-pill`).

**Serving root cause found (measured, important for all future page_js work):** Frappe desk
pages are cached by the CLIENT in `localStorage["_page:<name>"]` (pageview.js line 23-26) and
served from there whenever `frappe.boot.developer_mode != 1`. `bench clear-cache`, tab reload,
and new tabs do NOT invalidate it; the only client-side invalidation is `sync_pages()` comparing
the Page record's `modified` (2020 for point-of-sale — never changes). The browser therefore ran
the ORIGINAL picker build for days despite the server serving newer files. Resolution on
promo-mvp: `set-config developer_mode 1` (matches development.localhost convention; dev-mode-on
sites always fetch fresh). Operator browsers against developer-mode-ON sites are unaffected;
any browser that hit a dev-mode-OFF site keeps its stale `_page:` entry until site data is
cleared — flag this when the picker ships to a dev-mode-off environment.

**Browser verification (promo-mvp, IAB):** badge renders on the parent card; single click opens
exactly one "Pick choices — Paket Hemat Sarapan" dialog, cart stays empty; Roti Keju picked →
group status 1/1; Quote & Add → server quote Rp27.000, chip + "Promo total: Rp 27.000,00", draft
payload `{"instances":[{"promotion":"PROMO-00001","selections":[{"choice_group_key":"grp_demo01",
"options":[{"option_id":"qm5flg1cl5","qty":1}]}]}]`; Escape closes without side effects.
Automation quirk (not a product bug): Playwright locator click times out inside the IAB despite
visible elements; CUA coordinate clicks work — operator's physical clicks were already proven
to reach the handler before this fix.

**Resolved 2026-08-24:** Item Price `28e53m5gfj` no longer exists — a direct query found ZERO
Item Price rows on either promotion parent (`Paket Hemat Sarapan`, `Bundling 2 Roti Hemat`), so
the D12 predicate is clean and PROMO-00001 re-saves are unblocked. The row was removed outside
the implementing session (likely by the operator via desk); no action was needed.
