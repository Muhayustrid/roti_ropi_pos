# PROJECT_STATE.md — AI session resume checkpoint

**Last updated:** 2026-08-18, after final Git integration completed in all four custom apps.
**Resume point:** Project complete. Phase 3 rollout and final review passed. All intended project source
is committed, every feature branch is published, and each expected history is integrated into
`origin/main` without force. Protected and unrelated local overlays remain deliberately uncommitted.

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
an ancestor of `origin/main`. No merge conflict occurred. The final Roti closeout documentation commit
advances `origin/main` once after this file is written. Its hash is recorded in the Phase 3 ledger and
final report instead of creating a self-referential commit loop.

The final focused Selling gate used Ruff 0.14.10. Migration ran 14 tests OK. Preflight initially exposed
three test-only failures caused by a removed site-global POS Profile fixture. The tests now construct the
profiles they judge. The final preflight run passed 39 integration tests and 9 unit tests. The final
migration rerun passed 14 tests.

All intended project source is committed. Deliberate local state remains outside Git:

- Bakery keeps the protected bundle overlay unstaged at SHA-256
  `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. The committed bundle is empty.
- Bakery keeps `test_desk_sidebar.py`, `diference.md`, and `graphify-out/` local.
- Roti keeps the pre-existing `test_sales.py` teardown and extraction-design status edit local.
- Tool directories, plan scratch files, and `skills-lock.json` remain local.
- ERPNext keeps its pre-existing `banking/yarn.lock` edit. Frappe and ERPNext received no project commit.

No migrate, deploy, restart, or business-data mutation ran during final Git integration.

PHASE 3 COMPLETE — MAIN-SITE ROLLOUT VERIFIED AND REVIEW PASSED

PROJECT COMPLETE — ALL INTENDED CHANGES COMMITTED, PUSHED, AND MERGED TO MAIN
