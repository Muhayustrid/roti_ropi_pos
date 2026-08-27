# App Ownership Rollout Operational Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to run this plan task-by-task with a human operator present. Steps use checkbox (`- [ ]`) syntax for tracking. This plan changes shared systems; every task marked **APPROVAL** halts until the user approves that exact phase.

**Goal:** Move Price Group, walk-in, past-order, navigation, Item custom-UOM, and barcode ownership into `selling_additional` and `stock_additional` on a real site, in one bounded maintenance window, with a verified backup, a rehearsed restore, and a rollback that never uninstalls an app.

**Architecture:** Two releases. Stage A publishes and installs inactive shells with no runtime ownership. Stage B stops traffic, backs up, proves the backup restorable on a scratch site, runs read-only preflight, obtains an exact POS Profile recovery map, deploys three exact SHAs plus one verified bakery source overlay, reverses one leaked ERPNext source line-set, runs exactly one `bench migrate` with no bypass flags, verifies invariants, rebuilds assets, runs gates, then reopens traffic. Rollback restores the verified backup, shell tags, prior Roti SHA, and prior bakery overlay state.

**Tech Stack:** Frappe 16.27.1, ERPNext 16.28.0, MariaDB, Python 3.14, git, the bench CLI, and the site's external ingress.

**Spec:** `docs/superpowers/specs/2026-08-14-app-ownership-extraction-design.md`

**Implementation plans this plan sequences:**
- `docs/superpowers/plans/2026-08-14-additional-app-shells.md`
- `docs/superpowers/plans/2026-08-14-stock-additional-cutover.md`
- `docs/superpowers/plans/2026-08-14-selling-additional-cutover.md`

---

## Placeholders

Use `development.localhost` whenever the plan names `<TEST_SITE>`. Substitute every other token at execution time. Never write those resolved values into this repository.

| Token | Meaning |
| --- | --- |
| `<BENCH>` | Absolute bench root inside the runtime container |
| `<SITE>` | Target site name |
| `<SCRATCH_SITE>` | Disposable restore-rehearsal site name |
| `<TEST_SITE>` | Existing `development.localhost` implementation test site |
| `<CONTAINER>` | Runtime container or host that owns bench processes |
| `<INGRESS_STOP>` | Exact operator command that stops public traffic to `<SITE>` |
| `<INGRESS_ALLOWLIST_ONLY>` | Exact operator command that restricts `<SITE>` to operator sources |
| `<INGRESS_OPEN>` | Exact operator command that restores normal public traffic |
| `<WORKER_STOP>` | Exact operator command that stops bench workers |
| `<WORKER_START>` | Exact operator command that starts bench workers |
| `<WEB_RESTART>` | Exact operator command that restarts the web and socketio processes |
| `<BACKUP_DIR>` | Absolute path of the verified backup copy outside the site directory |
| `<DB_ROOT_USER>` | Database root username, entered interactively only |
| `<SHA_FRAPPE>` `<SHA_ERPNEXT>` | Pinned framework SHAs, unchanged by this rollout |
| `<SHA_SELLING>` `<SHA_STOCK>` `<SHA_BAKERY>` `<SHA_ROTI>` | Coordinated cutover SHAs, full 40 characters |
| `<PREV_SHA_BAKERY>` `<PREV_SHA_ROTI>` | Pre-cutover committed SHAs used by rollback |
| `<BAKERY_OVERLAY_MANIFEST>` | Candidate path list excluding the protected bundle; generated and reviewed before rollout |
| `<PREV_REF_FRAPPE>` `<PREV_REF_ERPNEXT>` `<PREV_REF_BAKERY>` `<PREV_REF_ROTI>` | Baseline branch names or `DETACHED`, used only to restore checkout attachment state |
| `<TAG_SHELL>` | Shell release tag, `shell-v0.1.0` per the shells plan |
| `<WINDOW_ID>` | Operator record identifier for this window, format `ROLL-YYYYMMDD-NN` |
| `<OPERATOR_ID>` | Initials of the operator holding the window |

## Operator Record IDs

Create one record set per window. The record lives in the operator's runbook store, never in a git repository and never in a chat transcript that will be committed.

| Record ID | Content | Produced by |
| --- | --- | --- |
| `<WINDOW_ID>-DISC` | Discovery inventory: app SHAs, branches, installed-app list and order, scheduler state, pending job count, disk headroom | Task 1 |
| `<WINDOW_ID>-SHELL-PUB` | Shell branch SHAs, tag SHAs, review link, push confirmation | Task 2 |
| `<WINDOW_ID>-SHELL-INST` | Pre-install backup IDs, post-install `list-apps` output, ownership-unchanged proof | Task 3 |
| `<WINDOW_ID>-DRAIN` | Window open timestamp, ingress state, scheduler state, worker state, `ready-for-migration` output | Task 4 |
| `<WINDOW_ID>-BACKUP` | Four backup file names, SHA-256 of each, byte sizes, copy destination, free space after copy | Task 5 |
| `<WINDOW_ID>-REHEARSE` | Scratch site name, restore exit status, row-count spot checks, teardown confirmation | Task 6 |
| `<WINDOW_ID>-PRE-STOCK` | Stock preflight JSON SHA-256 and verdict | Task 7 |
| `<WINDOW_ID>-PRE-SELL-DRAFT` | Preliminary selling report hash and redacted counts before recovery approval | Task 7 |
| `<WINDOW_ID>-PRE-SELL` | Authoritative validated selling report hash and clean verdict | Task 8 |
| `<WINDOW_ID>-PRE-CROSS` | Cross-app hook and dependency verdict | Task 7 |
| `<WINDOW_ID>-RECOVERY` | Recovery-map input identifier, canonical SHA-256, entry count, approver, approval timestamp; never map content | Task 8 |
| `<WINDOW_ID>-DEPLOY` | Three deployed HEAD SHAs, bakery candidate and overlay hashes, prior bakery and Roti SHAs, shell tag SHAs | Task 9 |
| `<WINDOW_ID>-SIDEBAR` | Pre-revert `status --porcelain`, `--numstat`, post-revert verification | Task 10 |
| `<WINDOW_ID>-MIGRATE` | Exact migrate command, full output, exit code, wall-clock duration | Task 11 |
| `<WINDOW_ID>-INV` | Post-migration invariant results, one line per invariant | Task 12 |
| `<WINDOW_ID>-IDEMP` | Forced-patch rerun results from the scratch copy | Task 13 |
| `<WINDOW_ID>-ASSETS` | Asset build output, cache clear confirmation, restart confirmation | Task 14 |
| `<WINDOW_ID>-GATES` | Suite results, static-check results, manual smoke checklist with pass or fail per item | Task 15 |
| `<WINDOW_ID>-REOPEN` | Reopen timestamp, error-rate observation window, sign-off | Task 16 |
| `<WINDOW_ID>-ROLLBACK` | Only if executed: trigger, restore inputs, restored SHAs, verification | Task 17 |

## Redaction Rules

These apply to every artifact that leaves the operator record: chat transcripts, review comments, commit messages, plan updates, and issue reports.

- Replace site names, hostnames, domains, and cloudflare or tunnel names with `<SITE>` or `<TARGET_HOST>`.
- Replace database names, database users, and socket paths with `<DB_NAME>` and `<DB_ROOT_USER>`.
- Never record a password, an API key, an OAuth client secret, a backup encryption key, or the content of `site_config.json` or `common_site_config.json`. Never run `bench show-config`.
- Report the backup config file only by name and hash, never by content.
- Replace business identifiers from live data with counts and shapes. Report "17 POS Profiles need recovery entries", not the profile names. Report ambiguous Item Price rows by count plus a per-row hash, not by item code.
- The recovery map itself is live business configuration. Keep content only in the operator-owned protected loader input. The operator record stores only its input identifier, canonical SHA-256, count, approver, and timestamp. Never place map content in site config, Git, chat, review text, logs, or shell history.
- Preflight JSON reports stay outside git. Carry the SHA-256 forward as the evidence token.
- When quoting command output, keep the exit code and verdict lines and drop absolute paths that reveal the environment, except inside the operator record where full paths are required.
- Reference every environment fact by its placeholder token in this table. The token-to-value mapping exists only in `<WINDOW_ID>-DISC`.

## Global Constraints

- Run every bench command from `<BENCH>` inside `<CONTAINER>`. Pass `--site <SITE>` explicitly to every site command; never rely on `default_site`.
- Complete all three implementation plans on `<TEST_SITE>` first, with green suites, before Task 2 of this plan.
- Never run `bench --site <SITE> uninstall-app` or `bench --site <SITE> remove-from-installed-apps` against `<SITE>`, at any point, for any reason, including rollback. Uninstall drops the owner app's DocType tables.
- Never reorder, rewrite, or "repair" the installed-app order. It lives in the site's `installed_apps` global and is only ever appended by `install-app`. If a hook resolves to the wrong provider, fix the duplicate provider in source, not the order.
- Run exactly one `bench --site <SITE> migrate` in the window, with no flags. `--skip-failing`, `--skip-fixtures`, and `--skip-search-index` are forbidden. `bench bypass-patch` is forbidden.
- Never edit `apps/frappe`. The only permitted `apps/erpnext` change is the single guarded reverse in Task 10.
- Do not commit, push, tag, deploy, install, migrate, restore, or delete a site without the approval named in that task.
- Do not run `bench --site <SITE> run-tests`. Testing is gated on `allow_tests` in site config; setting it on a production site is out of scope. Automated suites run on `<TEST_SITE>` and on the restored `<SCRATCH_SITE>`.
- Do not run destructive verification on `<SITE>` or `<TEST_SITE>`. Forced patch reruns and uninstall lifecycle checks belong only on `<SCRATCH_SITE>`. Invalid-data fixtures may use `<TEST_SITE>` only when each test rolls back its own transaction and performs no shared-data cleanup.
- Record full 40-character SHAs from `git rev-parse HEAD`. `bench version -f json` reports only a 7-character prefix and is evidence, not the source of truth.
- Preserve every unrelated dirty path. The current verified state is: `apps/erpnext` has ` M banking/yarn.lock`, ` M erpnext/workspace_sidebar/selling.json`, `?? .codegraph/`, `?? graphify-out/`; `apps/bakery_manufacturing` has ` M bakery_manufacturing/public/js/bakery_manufacturing.bundle.js` plus untracked `AGENTS.md`, `bakery_manufacturing/tests/test_desk_sidebar.py`, `diference.md`, `graphify-out/`.
- Any unexpected diff, hash mismatch, or preflight ambiguity halts the rollout. Halting inside the window is always cheaper than proceeding.
- Bakery is the only overlay-deployed repository because protected uncommitted bundle content prevents a safe branch switch. Its candidate must be based on `<PREV_SHA_BAKERY>`. The reviewed overlay manifest, bundle hash, and canonical candidate comparison are its source identity. Never commit the overlay index from the shared checkout.

---

### Task 1: Discovery and Baseline Record

**Artifacts:**
- Produce: `<WINDOW_ID>-DISC`
- Verify only: all app working trees, site app list, scheduler state, queue state, disk headroom

**Interfaces:**
- Consumes: nothing. This task is read-only and may run outside a maintenance window.
- Produces: the token-to-value mapping every later task references, and the prior-SHA set rollback depends on.

- [ ] **Step 1: Confirm the bench root**

```bash
cd <BENCH>
ls apps/ sites/ Procfile
```

Expected: all three exist. Stop if not; every later command assumes this root.

- [ ] **Step 2: Record exact app revisions and baseline branch names**

```bash
cd <BENCH>
for app in frappe erpnext bakery_manufacturing roti_ropi_pos; do
  printf '%s ' "$app"
  git -C "apps/$app" rev-parse HEAD
  git -C "apps/$app" symbolic-ref --quiet --short HEAD || printf 'DETACHED\n'
done
```

Record bakery and Roti SHAs as `<PREV_SHA_BAKERY>` and `<PREV_SHA_ROTI>`. Record all four branch states as `<PREV_REF_*>`; use `DETACHED` when no symbolic branch exists. Record Frappe and ERPNext as `<SHA_FRAPPE>` and `<SHA_ERPNEXT>`. The two new apps roll back to `<TAG_SHELL>`, whose resolved SHAs Task 2 records.

- [ ] **Step 3: Record every app working tree**

```bash
cd <BENCH>
for app in frappe erpnext bakery_manufacturing roti_ropi_pos; do
  printf '== %s\n' "$app"
  git -C "apps/$app" status --porcelain
done
```

Expected: exactly the dirty paths listed in Global Constraints and nothing else. Any additional entry halts the rollout until classified as pre-existing unrelated user work.

- [ ] **Step 4: Record protected-path hashes**

```bash
cd <BENCH>/apps/bakery_manufacturing
shasum -a 256 bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git diff --numstat -- bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
```

Expected: `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8`, numstat `14 0`, and `?? bakery_manufacturing/tests/test_desk_sidebar.py`. Re-verify, do not assume; a mismatch means the working tree moved since this plan was written and needs a fresh review before proceeding.

- [ ] **Step 5: Record the ERPNext sidebar leak shape**

```bash
cd <BENCH>/apps/erpnext
git status --porcelain
git diff --numstat -- erpnext/workspace_sidebar/selling.json
git diff --cached --numstat
git show HEAD:erpnext/workspace_sidebar/selling.json | grep -c "Price Group"
```

Expected: the four-line porcelain listed in Global Constraints, numstat exactly `13 1`, empty cached numstat, and grep count `0`. Store all four outputs; Task 10 compares against them.

- [ ] **Step 6: Record site app inventory and order**

```bash
cd <BENCH>
bench --site <SITE> list-apps
bench --site <SITE> list-apps --format json
bench version -f json
```

Record the ordered app list verbatim. This order decides which provider `frappe.override_whitelisted_method` returns, because it returns the last registered override. It is evidence, never something to edit.

- [ ] **Step 7: Record scheduler and queue baseline**

```bash
cd <BENCH>
bench --site <SITE> scheduler status
bench --site <SITE> show-pending-jobs
bench doctor --site <SITE>
```

Record the scheduler verdict and pending-job counts. Task 16 restores the recorded scheduler state exactly.

- [ ] **Step 8: Record capacity headroom**

```bash
cd <BENCH>
df -h sites <BACKUP_DIR>
du -sh sites/<SITE>
```

A database dump plus public and private file archives plus one copy outside the site directory needs roughly three times the site directory size free. Insufficient headroom halts the rollout before the window opens.

- [ ] **Step 9: Confirm the three implementation plans are green**

Confirm from the executing sessions, not from memory: all `<TEST_SITE>` suites for `selling_additional`, `stock_additional`, `bakery_manufacturing`, and `roti_ropi_pos` pass at the candidate SHAs; static checks pass in all four repositories; the fresh-install, staged-upgrade, and populated-upgrade scenarios in the two cutover plans all passed. Record the evidence references in `<WINDOW_ID>-DISC`.

Expected: every reference present. A missing scenario result is a blocking gap; do not open a window to discover it.

---

### Task 2: Stage A — Publish the Shell Releases

**APPROVAL: push and tag.** Nothing in this task runs before the user approves pushing to both target repositories and creating both tags.

**Artifacts:**
- Produce: `<WINDOW_ID>-SHELL-PUB`
- Verify only: both shell working trees

**Interfaces:**
- Consumes: green shell branches from `2026-08-14-additional-app-shells.md`, Task 5.
- Produces: `<TAG_SHELL>` on both remotes pointing at reviewed SHAs. Task 3 installs from these tags only.

- [ ] **Step 1: Re-verify both shells are clean and green**

```bash
cd <BENCH>/apps/selling_additional && git status --short && git diff --check && pre-commit run --all-files
cd <BENCH>/apps/stock_additional && git status --short && git diff --check && pre-commit run --all-files
cd <BENCH>
bench --site <TEST_SITE> run-tests --app selling_additional
bench --site <TEST_SITE> run-tests --app stock_additional
```

Expected: no unexpected diff, all checks pass, both suites pass. A missing `pre-commit` binary is a failure, not a pass.

- [ ] **Step 2: Record the candidate SHAs**

```bash
cd <BENCH>
git -C apps/selling_additional rev-parse HEAD
git -C apps/stock_additional rev-parse HEAD
git -C apps/selling_additional log --oneline -5
git -C apps/stock_additional log --oneline -5
```

Report both SHAs, both diffs, and both suite results to the user. Halt here.

- [ ] **Step 3: Push both shell branches**

After approval:

```bash
cd <BENCH>
git -C apps/selling_additional push -u origin feat/inactive-shell
git -C apps/stock_additional push -u origin feat/inactive-shell
```

- [ ] **Step 4: Create and push both annotated tags**

```bash
cd <BENCH>
git -C apps/selling_additional tag -a <TAG_SHELL> -m "Inactive selling additional shell"
git -C apps/stock_additional tag -a <TAG_SHELL> -m "Inactive stock additional shell"
git -C apps/selling_additional push origin <TAG_SHELL>
git -C apps/stock_additional push origin <TAG_SHELL>
```

- [ ] **Step 5: Verify the tags resolve to the reviewed SHAs**

```bash
cd <BENCH>
git -C apps/selling_additional rev-list -n 1 <TAG_SHELL>
git -C apps/stock_additional rev-list -n 1 <TAG_SHELL>
```

Expected: each equals the Step 2 SHA. Record both into `<WINDOW_ID>-SHELL-PUB`.

---

### Task 3: Stage A — Install the Shells on the Target Site

**APPROVAL: active-site install.** This writes to `<SITE>`: two `Module Def` rows and two `installed_apps` entries. It moves no ownership.

**Artifacts:**
- Produce: `<WINDOW_ID>-SHELL-INST`
- Modify: `<SITE>` installed-app list and Module Def table

**Interfaces:**
- Consumes: `<TAG_SHELL>` on both remotes.
- Produces: the precondition both cutover patches assert. `selling_additional.patches.v1_0.transfer_price_group_ownership` throws without the `Selling Additional` Module Def.

- [ ] **Step 1: Take a pre-install database backup**

```bash
cd <BENCH>
bench --site <SITE> backup
```

Record the printed summary paths and sizes. A shell install is low risk but is still a write; this backup is the cheap undo.

- [ ] **Step 2: Confirm both app source trees are at the shell tags**

```bash
cd <BENCH>
git -C apps/selling_additional rev-parse HEAD
git -C apps/stock_additional rev-parse HEAD
```

Expected: both equal the Task 2 Step 5 tag SHAs.

- [ ] **Step 3: Record pre-install ownership**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.get_value \
  --args '["DocType", "Price Group", "module"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.stock.utils.scan_barcode"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"]'
```

Expected: `Bakery Manufacturing`, and both overrides resolving to `bakery_manufacturing` paths. Record verbatim.

- [ ] **Step 4: Install both shells**

```bash
cd <BENCH>
bench --site <SITE> install-app selling_additional
bench --site <SITE> install-app stock_additional
bench --site <SITE> list-apps
```

Expected: both apps appear, appended after the existing apps. Do not pass `--force`.

- [ ] **Step 5: Prove no ownership moved**

Re-run Step 3 exactly. Expected: identical output. Additionally:

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.exists \
  --args '["Module Def", "Selling Additional"]'
bench --site <SITE> execute frappe.db.exists \
  --args '["Module Def", "Stock Additional"]'
```

Expected: both truthy. Record the whole set into `<WINDOW_ID>-SHELL-INST`.

- [ ] **Step 6: Observe the site under normal traffic**

Leave the shells installed and traffic normal for at least one full business day. Watch for new errors in the site error log and in the worker logs. Stage B does not start until this observation passes, because a shell that breaks boot is far cheaper to find outside a cutover window.

---

### Task 4: Stage B — Open the Window and Drain

**APPROVAL: outage.** This stops customer traffic on `<SITE>`.

**Artifacts:**
- Produce: `<WINDOW_ID>-DRAIN`
- Modify: `<SITE>` site config `maintenance_mode` and `pause_scheduler`; ingress state; worker processes

**Interfaces:**
- Consumes: `<WINDOW_ID>-DISC` scheduler and queue baseline.
- Produces: a site with no HTTP traffic, no scheduled enqueue, and no running background job. Task 11 requires exactly this state.

- [ ] **Step 1: Announce the window and record the start**

Record `<WINDOW_ID>`, `<OPERATOR_ID>`, planned duration, and the rollback decision deadline. The deadline matters: after traffic reopens, a restore discards real transactions, so rollback is only cheap inside the window.

- [ ] **Step 2: Stop public traffic at the ingress**

```bash
<INGRESS_STOP>
```

Confirm from an external client that `<SITE>` no longer serves. Ingress is the outer gate; maintenance mode is the inner gate. Use both.

- [ ] **Step 3: Enable maintenance mode**

```bash
cd <BENCH>
bench --site <SITE> set-maintenance-mode on
```

Verified behavior in installed Frappe: `frappe/app.py` raises `SessionStopped` for every request when `maintenance_mode` is set, unless `allow_reads_during_maintenance` is configured. Do not add that key.

- [ ] **Step 4: Pause the scheduler**

```bash
cd <BENCH>
bench --site <SITE> scheduler pause
bench --site <SITE> scheduler status
```

Expected: status reports disabled. Verified in `frappe/utils/scheduler.py`: `is_scheduler_inactive` returns true for either `maintenance_mode` or `pause_scheduler`. `pause` writes `pause_scheduler` to site config and is the reversible half; do not use `disable-scheduler`, which writes a persistent System Settings flag and confuses restore.

- [ ] **Step 5: Drain and stop the workers**

```bash
cd <BENCH>
bench --site <SITE> show-pending-jobs
bench --site <SITE> ready-for-migration
```

`ready-for-migration` polls three times one second apart and exits non-zero when any job for `<SITE>` is queued or started. Wait for in-flight jobs to finish; do not purge a queue that may hold another site's work. When it exits zero:

```bash
<WORKER_STOP>
```

- [ ] **Step 6: Re-confirm the drained state**

```bash
cd <BENCH>
bench --site <SITE> ready-for-migration
bench --site <SITE> scheduler status
```

Expected: ready, and scheduler disabled. Record all outputs plus the window-open timestamp into `<WINDOW_ID>-DRAIN`.

---

### Task 5: Take and Verify the Backup

**Artifacts:**
- Produce: `<WINDOW_ID>-BACKUP`, four backup files, one copy under `<BACKUP_DIR>`

**Interfaces:**
- Consumes: the drained site from Task 4.
- Produces: the only sanctioned rollback input. Task 6 rehearses it; Task 17 uses it.

- [ ] **Step 1: Take a full backup with files**

```bash
cd <BENCH>
bench --site <SITE> backup --with-files
```

Verified in installed Frappe: this produces four artifacts in `sites/<SITE>/private/backups`, named `<YYYYMMDD_HHMMSS>-<site_slug>-database.sql.gz`, `-files.tar`, `-private-files.tar`, and `-site_config_backup.json`. An `-enc` infix appears when System Settings has `encrypt_backup` on, and the archives become `.tgz` only with `--compress`, which this plan does not pass. The command prints an absolute path and size per artifact.

- [ ] **Step 2: Check for backup encryption**

If the command printed the encryption notice, the dump is encrypted and restore needs the key. Record only that encryption is in effect and where the key is held. Never record or print the key. Verify the key is retrievable by the operator before continuing; an unrecoverable encrypted backup is not a backup.

- [ ] **Step 3: Hash all four artifacts**

```bash
cd <BENCH>/sites/<SITE>/private/backups
shasum -a 256 <TS>-<SLUG>-database.sql.gz \
  <TS>-<SLUG>-files.tar \
  <TS>-<SLUG>-private-files.tar \
  <TS>-<SLUG>-site_config_backup.json
ls -l <TS>-<SLUG>-database.sql.gz <TS>-<SLUG>-files.tar \
  <TS>-<SLUG>-private-files.tar <TS>-<SLUG>-site_config_backup.json
```

Record every hash and byte size into `<WINDOW_ID>-BACKUP`.

- [ ] **Step 4: Verify the dump is readable end to end**

```bash
cd <BENCH>/sites/<SITE>/private/backups
gzip -t <TS>-<SLUG>-database.sql.gz && echo "gzip ok"
tar -tf <TS>-<SLUG>-files.tar > /dev/null && echo "public files ok"
tar -tf <TS>-<SLUG>-private-files.tar > /dev/null && echo "private files ok"
```

Skip the `gzip -t` check when the dump is encrypted; Task 6 then proves readability by restoring with the key. Any failure halts the rollout and reopens traffic with no changes made.

- [ ] **Step 5: Copy the set off the site directory**

```bash
cp <TS>-<SLUG>-database.sql.gz <TS>-<SLUG>-files.tar \
   <TS>-<SLUG>-private-files.tar <TS>-<SLUG>-site_config_backup.json \
   <BACKUP_DIR>/
cd <BACKUP_DIR> && shasum -a 256 <TS>-<SLUG>-*
df -h <BACKUP_DIR>
```

Expected: the four hashes match Step 3 exactly. A backup that lives only inside the site it protects is not a backup. Record the destination and the post-copy free space.

---

### Task 6: Restore Rehearsal on a Scratch Site

**APPROVAL: scratch site creation.** This creates and later drops `<SCRATCH_SITE>` and requires the database root password, entered interactively only.

**Artifacts:**
- Produce: `<WINDOW_ID>-REHEARSE`, `<SCRATCH_SITE>`
- Verify only: `<SITE>`

**Interfaces:**
- Consumes: the four verified artifacts from Task 5.
- Produces: proof the rollback input restores, and the site Tasks 13 and 15 use for destructive verification. `<SCRATCH_SITE>` is kept until Task 15 completes, then dropped.

- [ ] **Step 1: Create the scratch site**

```bash
cd <BENCH>
bench new-site <SCRATCH_SITE> --db-root-username <DB_ROOT_USER>
```

Enter the root and admin passwords at the interactive prompts only. Never place a password on the command line, in an environment variable recorded in the transcript, or in this plan.

- [ ] **Step 2: Restore the verified backup into it**

```bash
cd <BENCH>
bench --site <SCRATCH_SITE> restore \
  <BACKUP_DIR>/<TS>-<SLUG>-database.sql.gz \
  --with-public-files <BACKUP_DIR>/<TS>-<SLUG>-files.tar \
  --with-private-files <BACKUP_DIR>/<TS>-<SLUG>-private-files.tar \
  --db-root-username <DB_ROOT_USER>
```

Add `--encryption-key` only when Task 5 Step 2 found encryption in effect, and supply it at the prompt or from the operator's secret store; do not echo it. Expected: exit code zero.

- [ ] **Step 3: Prove the restored site is the target site**

```bash
cd <BENCH>
bench --site <SCRATCH_SITE> list-apps
bench --site <SCRATCH_SITE> execute frappe.db.count --args '["Price Group"]'
bench --site <SCRATCH_SITE> execute frappe.db.count --args '["Price Group Item"]'
bench --site <SCRATCH_SITE> execute frappe.db.count --args '["Price Group Outlet"]'
bench --site <SCRATCH_SITE> execute frappe.db.count --args '["POS Profile"]'
bench --site <SCRATCH_SITE> execute frappe.db.count --args '["POS Invoice"]'
bench --site <SCRATCH_SITE> execute frappe.db.get_value \
  --args '["DocType", "Price Group", "module"]'
```

Expected: the same app list and order as `<WINDOW_ID>-DISC` plus the two shells, counts matching a fresh count on `<SITE>`, and `Price Group` still owned by `Bakery Manufacturing`. Record counts as counts only; no business names.

- [ ] **Step 4: Compare against the live site**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.count --args '["Price Group"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Item"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Outlet"]'
bench --site <SITE> execute frappe.db.count --args '["POS Profile"]'
bench --site <SITE> execute frappe.db.count --args '["POS Invoice"]'
```

Expected: identical to Step 3. A mismatch means the backup was not fully drained or the restore was partial. Either halts the rollout.

- [ ] **Step 5: Record the rehearsal verdict**

Record the restore exit status, the count comparison, and the wall-clock restore duration into `<WINDOW_ID>-REHEARSE`. The duration is the rollback time estimate the reopen decision in Task 16 depends on.

Keep `<SCRATCH_SITE>` for now. Task 15 Step 6 drops it, with its own approval.

---

### Task 7: Deploy Candidate Source Read-Only, Then Collect Preflight

**APPROVAL: candidate source deployment.** Traffic remains stopped. This task changes app source only and performs no site write.

**Artifacts:**
- Produce: `<WINDOW_ID>-PRE-STOCK`, `<WINDOW_ID>-PRE-SELL-DRAFT`, `<WINDOW_ID>-PRE-CROSS`, two JSON reports outside git
- Verify only: `<SITE>`

**Interfaces:**
- Consumes: reviewed coordinated SHAs and both read-only preflight modules.
- Produces: validated stock evidence, a read-only selling report that identifies recovery needs, and candidate source already deployed for Task 9 verification.

Shell tags do not contain preflight code. Deploy coordinated source now while traffic and workers remain stopped. Do not migrate. Roti uses an exact detached checkout. Bakery uses a reviewed overlay because its protected dirty bundle prevents a safe branch switch. The bakery candidate must be based on `<PREV_SHA_BAKERY>` and exclude protected user content. If deployment or preflight fails, restore the source state in Step 10 before reopening.

- [ ] **Step 1: Confirm target commits exist locally**

```bash
cd <BENCH>
git -C apps/selling_additional fetch origin
git -C apps/stock_additional fetch origin
git -C apps/bakery_manufacturing fetch origin
git -C apps/roti_ropi_pos fetch origin
git -C apps/selling_additional cat-file -e <SHA_SELLING>^{commit} && echo ok
git -C apps/stock_additional cat-file -e <SHA_STOCK>^{commit} && echo ok
git -C apps/bakery_manufacturing cat-file -e <SHA_BAKERY>^{commit} && echo ok
git -C apps/roti_ropi_pos cat-file -e <SHA_ROTI>^{commit} && echo ok
```

Expected: four `ok`. Fetch changes no working tree.

- [ ] **Step 2: Re-verify every protected working-tree path**

```bash
cd <BENCH>
git -C apps/bakery_manufacturing status --porcelain
git -C apps/roti_ropi_pos status --porcelain
git -C apps/bakery_manufacturing diff --cached --name-status
git -C apps/roti_ropi_pos diff --cached --name-status
shasum -a 256 \
  apps/bakery_manufacturing/bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git -C apps/bakery_manufacturing status --short -- \
  bakery_manufacturing/tests/test_desk_sidebar.py
git -C apps/roti_ropi_pos status --short -- roti_ropi_pos/tests/test_sales.py
```

Expected: Task 1 protected state, with nothing staged. Abort on drift. Never stash, reset, clean, or force-checkout.

- [ ] **Step 3: Check out the two clean target repositories**

```bash
cd <BENCH>
git -C apps/selling_additional checkout --detach <SHA_SELLING>
git -C apps/stock_additional checkout --detach <SHA_STOCK>
```

Expected: both clean trees now resolve to target SHAs.

- [ ] **Step 4: Check out Roti without overwriting protected work**

```bash
cd <BENCH>
git -C apps/roti_ropi_pos checkout --detach <SHA_ROTI>
```

Plain checkout must succeed without `--merge`, `--force`, stash, reset, or clean. A refusal means the candidate overlaps protected uncommitted work or uses the wrong base. Stop and rebuild the candidate. Verify `roti_ropi_pos/tests/test_sales.py` stays unchanged and unstaged.

- [ ] **Step 5: Validate and apply the bakery candidate overlay**

First prove candidate ancestry and exact changed paths:

```bash
cd <BENCH>
git -C apps/bakery_manufacturing merge-base --is-ancestor \
  <PREV_SHA_BAKERY> <SHA_BAKERY>
git -C apps/bakery_manufacturing diff --name-status \
  <PREV_SHA_BAKERY> <SHA_BAKERY>
git -C apps/bakery_manufacturing diff \
  <PREV_SHA_BAKERY> <SHA_BAKERY> -- \
  bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
```

Expected: ancestry command exits zero. Name-status equals the reviewed implementation diff. Bundle diff deletes only `import "./pos_walk_in_customer.js";`. Generate `<BAKERY_OVERLAY_MANIFEST>` from that exact diff, excluding the bundle. Compare its canonical SHA-256 with release evidence before using it.

Generate, review, and apply through the tested candidate tool:

```bash
cd <BENCH>/apps/bakery_manufacturing
python3 scripts/ownership_cutover.py manifest \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  > <BAKERY_OVERLAY_MANIFEST>
python3 scripts/ownership_cutover.py apply \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  --manifest <BAKERY_OVERLAY_MANIFEST>
python3 scripts/ownership_cutover.py verify \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  --manifest <BAKERY_OVERLAY_MANIFEST>
shasum -a 256 bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
git status --short -- bakery_manufacturing/tests/test_desk_sidebar.py
git diff --cached --name-status
```

Tool handles add, modify, and delete rows with path-scoped Git commands. It rejects rename, copy, conflict, unknown status, absolute path, `..`, protected bundle, protected sidebar test, and paths outside reviewed manifest. Do not improvise a shell loop in window.

Expected: bundle hash `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`, sidebar test byte-identical and untracked, and index exactly matching candidate overlay paths. Shared bakery `HEAD` remains `<PREV_SHA_BAKERY>` by design. Deployed bakery identity is candidate commit plus verified overlay manifest and bundle hash.

- [ ] **Step 6: Run stock preflight against coordinated source**

```bash
cd <BENCH>
bench --site <SITE> execute stock_additional.migration.preflight.check \
  --kwargs '{"phase": "staged_upgrade"}' \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-stock-preflight.json"
python3 -m json.tool "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-stock-preflight.json" > /dev/null
shasum -a 256 "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-stock-preflight.json"
```

`check()` validates before returning. Any invalid Item, field mismatch, provider mismatch, signature mismatch, or unsupported old reference blocks.

- [ ] **Step 7: Collect the selling preflight report without requiring a map yet**

```bash
cd <BENCH>
bench --site <SITE> execute selling_additional.migration.preflight.run \
  --kwargs '{"phase": "pre_model_sync"}' \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight.json"
python3 -m json.tool "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight.json" > /dev/null
shasum -a 256 "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight.json"
```

`run()` is read-only and does not assert cleanliness. Its report includes `doctypes`, `price_group_rows`, `custom_fields`, `generated_price_lists`, `profile_claim_conflicts`, `item_price_ambiguity`, `profile_recovery`, `legacy_sidebar_item`, `hook_owners`, and `old_path_references`. Task 8 supplies the missing recovery map and then calls `check()`. All other dirty sections already block this window. `legacy_sidebar_item` permits zero or one exact match per parent and blocks two or more.

Store full report only in protected operator storage as `<WINDOW_ID>-PRE-SELL-DRAFT`. Record its hash and redacted counts elsewhere. Never paste profile names, Item names, or map candidates into chat or Git.

- [ ] **Step 8: Run the cross-app ownership check**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.get_hooks \
  --args '["override_whitelisted_methods"]'
bench --site <SITE> execute frappe.get_hooks \
  --args '["override_doctype_class"]'
bench --site <SITE> execute frappe.get_installed_apps
```

Coordinated source must already provide exactly one scanner override from `stock_additional` and exactly one past-order override from `selling_additional`. `Serial and Batch Bundle` must have exactly one provider from `bakery_manufacturing`. A duplicate provider is a failure even when the effective method is correct.

Confirm no unexpected installed app registers a competing provider. If `roti_ropi_pos_task11` or another unexpected app is installed, inspect its hooks before proceeding. Record the provider table into `<WINDOW_ID>-PRE-CROSS`.

- [ ] **Step 9: Verify preflight wrote nothing and halt for the preliminary verdict**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.count --args '["Price Group"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Item"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Outlet"]'
bench --site <SITE> execute frappe.db.count --args '["Item Price"]'
bench --site <SITE> execute frappe.db.count --args '["POS Profile"]'
```

Expected: identical to Task 6 Step 4 and the pre-migrate baseline. Report the stock verdict, preliminary selling report hash, cross-app verdict, and every non-recovery problem count. Continue only when stock and cross-app checks pass and selling has no problem except missing approved recovery entries.

- [ ] **Step 10: Restore source if Task 7 cannot continue**

Do not reopen with candidate source after a failed preliminary gate. Restore Roti to `<PREV_SHA_ROTI>`. Restore selling and stock to `<TAG_SHELL>`:

```bash
cd <BENCH>
git -C apps/roti_ropi_pos checkout --detach <PREV_SHA_ROTI>
git -C apps/selling_additional checkout --detach <TAG_SHELL>
git -C apps/stock_additional checkout --detach <TAG_SHELL>
```

After source verification, restore Roti's baseline branch attachment only when `<PREV_REF_ROTI>` is not `DETACHED` and that branch still points to `<PREV_SHA_ROTI>`. Otherwise remain detached and record why. Restore selling and stock to their shell release branches only if the operator record contains verified branch names at those tag SHAs; otherwise detached tags are correct.

Run:

```bash
cd <BENCH>/apps/bakery_manufacturing
python3 scripts/ownership_cutover.py rollback \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  --manifest <BAKERY_OVERLAY_MANIFEST>
```

Verify full bakery bundle hash returns to `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8`, numstat returns to `14 0`, index is empty, and sidebar test stays byte-identical and untracked. Bakery `HEAD` remains `<PREV_SHA_BAKERY>` throughout.

Rebuild bakery assets, clear caches, restart web, revoke any recovery input, and follow Task 16 only after baseline ownership checks match Task 3 Step 3. A checkout or overlay reversal failure blocks reopen until protected diff review. Never use `--force`, stash, reset, or clean.

---

### Task 8: Approve and Install the POS Profile Recovery Map

**APPROVAL: exact recovery map.** The user must approve the map entry by entry. This is live pricing configuration; a wrong entry restores a profile to the wrong Price List after a later disable or delete.

**Artifacts:**
- Produce: `<WINDOW_ID>-RECOVERY`
- Modify: operator-owned protected recovery-map input outside Git and chat

**Interfaces:**
- Consumes: `profile_recovery` from `<WINDOW_ID>-PRE-SELL-DRAFT`, including advisory Version candidates.
- Produces: the exact map `selling_additional.migration.recovery_map.load()` reads during preflight and migration. The operator mechanism must expose it only to the bench process and must not print it.

- [ ] **Step 1: Review candidates inside the protected operator channel**

For each `profile_recovery` row from Task 7, review three fields inside the protected operator system: profile, current generated Price List, and proposed previous Price List with its evidence class. Never render these values in chat or a normal terminal transcript.

Evidence classes, strongest first:
1. `version` — a `Version` row suggests the pre-claim `selling_price_list`. It is advisory and still needs approval.
2. `operator` — no useful history exists; the operator supplies the value from business knowledge.

The old bakery controller overwrote `selling_price_list` and stored nothing, so class 2 is expected. The patch never invents a value. Approved protected content has shape `dict[str, str]`, with one profile key and one previous Price List value per entry.

- [ ] **Step 2: Halt for entry-by-entry approval**

The user approves each entry through the protected operator system. Store map content there only. Record only entry count, approver, approval timestamp, and canonical SHA-256 in `<WINDOW_ID>-RECOVERY`.

- [ ] **Step 3: Configure the approved loader input without printing it**

Choose one operator mechanism supported by `recovery_map.load()`. Record only its identifier and canonical SHA-256. Enter map content through an approved interactive secret channel. Never place JSON content in a command argument, environment dump, site config, repository file, shell history, plan, log, or transcript.

- [ ] **Step 4: Verify by hash and count only**

Run the tested digest helper and capture only count and hash:

```bash
cd <BENCH>
bench --site <SITE> execute \
  selling_additional.migration.recovery_map_digest.recovery_map_digest \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-recovery-map-digest.json"
python3 -m json.tool \
  "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-recovery-map-digest.json" > /dev/null
```

Compare `entries` and `sha256` with `<WINDOW_ID>-RECOVERY`. The helper must not emit keys or values.

- [ ] **Step 5: Confirm the map is complete and minimal**

Capture the validated report without printing sensitive rows:

```bash
cd <BENCH>
bench --site <SITE> execute selling_additional.migration.preflight.check \
  --kwargs '{"phase": "pre_model_sync"}' \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight-approved.json"
python3 -m json.tool \
  "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight-approved.json" > /dev/null
shasum -a 256 \
  "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-preflight-approved.json"
```

`check()` rejects unknown profiles, unknown Price Lists, extra entries, missing entries, and every non-recovery problem. Record only clean verdict, count, and report hash. This is the authoritative `<WINDOW_ID>-PRE-SELL` gate.

---

### Task 9: Verify Coordinated Candidate Source

**APPROVAL: coordinated deployment.** Three repositories use fixed SHAs. Bakery uses one verified source overlay while traffic is stopped.

**Artifacts:**
- Produce: `<WINDOW_ID>-DEPLOY`
- Modify: working trees of `selling_additional`, `stock_additional`, `bakery_manufacturing`, `roti_ropi_pos`; bakery index holds the reviewed overlay

**Interfaces:**
- Consumes: reviewed cutover SHAs, `<PREV_SHA_BAKERY>`, `<PREV_SHA_ROTI>`, and shell tag SHAs.
- Produces: verified exact source state Task 11 migrates. Task 7 checked out three SHAs and applied the reviewed bakery overlay. No overlap window serves requests.

- [ ] **Step 1: Confirm Task 7 and Task 8 evidence**

Verify four target commit objects still exist. Confirm `<WINDOW_ID>-PRE-STOCK`, authoritative `<WINDOW_ID>-PRE-SELL`, and `<WINDOW_ID>-PRE-CROSS` all pass. Compare recorded hashes with current report files. Do not rerun source checkout here.

- [ ] **Step 2: Re-verify protected paths after Task 7 deployment**

```bash
cd <BENCH>
git -C apps/bakery_manufacturing status --porcelain
git -C apps/roti_ropi_pos status --porcelain
git -C apps/bakery_manufacturing diff --cached --name-status
git -C apps/roti_ropi_pos diff --cached --name-status
```

Expected: bakery worktree and index exactly match the reviewed overlay plus protected paths. Roti contains only protected user work and nothing staged. Do not stash, reset, clean, or force-checkout.

- [ ] **Step 3: Record deployed candidate identities**

```bash
cd <BENCH>
for app in stock_additional selling_additional roti_ropi_pos; do
  printf '%s ' "$app"
  git -C "apps/$app" rev-parse HEAD
done
git -C apps/bakery_manufacturing rev-parse HEAD
git -C apps/bakery_manufacturing diff --cached --name-status
git -C apps/bakery_manufacturing diff --name-status
git -C apps/frappe rev-parse HEAD
git -C apps/erpnext rev-parse HEAD
```

Expected: stock, selling, and Roti equal target SHAs. Bakery `HEAD` remains `<PREV_SHA_BAKERY>`, while its cached and working diffs match `<SHA_BAKERY>` through the reviewed overlay manifest and bundle hash. Frappe and ERPNext equal `<SHA_FRAPPE>` and `<SHA_ERPNEXT>`. Never commit the bakery overlay index. Preserve it until rollback or the separately approved post-window checkout cleanup.

- [ ] **Step 4: Compare bakery overlay content with the candidate tree**

Run `scripts/ownership_cutover.py verify` with the recorded base, target, and manifest. Compare its canonical candidate hash, manifest hash, bundle hash, and path counts with release evidence. This is bakery's deployed identity proof; `git rev-parse HEAD` alone is intentionally not enough.

- [ ] **Step 5: Verify the required-apps graph**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.get_hooks \
  --args '["required_apps", null, "roti_ropi_pos"]'
bench --site <SITE> execute frappe.get_hooks \
  --args '["required_apps", null, "bakery_manufacturing"]'
```

Expected: `roti_ropi_pos` requires `erpnext`, `stock_additional`, `selling_additional` and no longer `bakery_manufacturing`; `bakery_manufacturing` requires only `erpnext`.

- [ ] **Step 6: Re-verify protected paths after approved candidate changes**

Bakery bundle must now equal protected suffix SHA-256 `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`, because candidate source removes only the tracked walk-in import. Confirm `test_desk_sidebar.py` remains byte-identical and unstaged. ERPNext porcelain still matches Task 1 until Task 10. Record three deployed HEAD SHAs, bakery candidate SHA and overlay hashes, prior bakery and Roti SHAs, and shell tag SHAs into `<WINDOW_ID>-DEPLOY`.

---

### Task 10: Guarded ERPNext Sidebar Source Cleanup

**APPROVAL: working-tree discard in a shared checkout.** The leaked content is uncommitted, so this discard is not recoverable from git.

**Artifacts:**
- Produce: `<WINDOW_ID>-SIDEBAR`
- Modify: `apps/erpnext/erpnext/workspace_sidebar/selling.json` only

**Interfaces:**
- Consumes: the leak shape recorded in Task 1 Step 5.
- Produces: a clean ERPNext sidebar source file. Task 11 removes the matching database child through `selling_additional.patches.v1_0.adopt_legacy_selling_state`.

- [ ] **Step 1: Re-read the diff immediately before reversing**

```bash
cd <BENCH>/apps/erpnext
git status --porcelain
git diff --numstat -- erpnext/workspace_sidebar/selling.json
git diff -- erpnext/workspace_sidebar/selling.json
git diff --cached --numstat
git show HEAD:erpnext/workspace_sidebar/selling.json | grep -c "Price Group"
```

Abort unless every one of these holds:
- porcelain is exactly ` M banking/yarn.lock`, ` M erpnext/workspace_sidebar/selling.json`, `?? .codegraph/`, `?? graphify-out/` and nothing else;
- numstat for the sidebar file is exactly `13 1`;
- the diff contains only the 12-line Price Group child object plus the single `"modified"` timestamp line;
- `git diff --cached --numstat` is empty;
- the committed file grep count is `0`.

- [ ] **Step 2: Halt for the discard approval**

Show the full diff and the five checks. Explain plainly: this permanently discards uncommitted content in a shared ERPNext checkout, it is not reversible from git, and it is safe only because the committed file is already clean.

- [ ] **Step 3: Reverse only that one file**

```bash
git -C <BENCH>/apps/erpnext checkout -- erpnext/workspace_sidebar/selling.json
```

Do not use `git restore .`, `git reset --hard`, `git clean`, or `git checkout --` with any other path.

- [ ] **Step 4: Verify the reverse and the survivors**

```bash
cd <BENCH>/apps/erpnext
git status --porcelain
git diff --numstat
```

Expected: `banking/yarn.lock` still modified, `.codegraph/` and `graphify-out/` still untracked, no sidebar diff, nothing staged. Do not `git add` and do not commit anything in `apps/erpnext`.

- [ ] **Step 5: Record the outcome**

Record the pre-revert diff summary, the five check results, the approval, and the post-revert verification into `<WINDOW_ID>-SIDEBAR`.

---

### Task 11: One Migrate, No Bypass

**APPROVAL: active-site migration.**

**Artifacts:**
- Produce: `<WINDOW_ID>-MIGRATE`
- Modify: `<SITE>` schema, metadata, ownership markers, fixtures, and the one legacy sidebar child row

**Interfaces:**
- Consumes: the verified coordinated source state, approved recovery map, clean preflight verdict, and drained site.
- Produces: `Selling Additional` ownership of the three Price Group DocTypes, six ownership Custom Fields, marked Price Lists and Item Prices, stored previous price lists, reconciled profiles, and the app-owned Workspace and Workspace Sidebar.

- [ ] **Step 1: Confirm every runtime precondition in one pass**

```bash
cd <BENCH>
bench --site <SITE> ready-for-migration
bench --site <SITE> scheduler status
bench --site <SITE> list-apps
git -C apps/selling_additional rev-parse HEAD
git -C apps/stock_additional rev-parse HEAD
git -C apps/bakery_manufacturing rev-parse HEAD
git -C apps/roti_ropi_pos rev-parse HEAD
```

Expected: ready, scheduler disabled, both shells installed, selling, stock, and Roti at target SHAs, and bakery at `<PREV_SHA_BAKERY>` with Task 9 overlay identity proof matching `<SHA_BAKERY>`. Confirm Task 5 backup hashes, Task 6 rehearsal, Task 8 approved preflight, and recovery-map hash/count verification. Any gap halts here.

- [ ] **Step 2: Assert one authoritative source copy per Price Group DocType**

```bash
cd <BENCH>/apps
python3 - <<'PY'
from pathlib import Path

apps = Path(".")
expected = {
    "price_group.json": Path(
        "selling_additional/selling_additional/selling_additional/"
        "doctype/price_group/price_group.json"
    ),
    "price_group_item.json": Path(
        "selling_additional/selling_additional/selling_additional/"
        "doctype/price_group_item/price_group_item.json"
    ),
    "price_group_outlet.json": Path(
        "selling_additional/selling_additional/selling_additional/"
        "doctype/price_group_outlet/price_group_outlet.json"
    ),
}
for filename, wanted in expected.items():
    matches = sorted(path.relative_to(apps) for path in apps.rglob(filename))
    assert matches == [wanted], (filename, matches)
    assert '"module": "Selling Additional"' in (apps / wanted).read_text()
print("one authoritative Price Group source set")
PY
```

Expected: exactly one JSON file for each DocType, all under `selling_additional`. This gate runs immediately before first migrate. Any extra bakery or third-party copy blocks.

- [ ] **Step 3: Run exactly one migrate with no flags**

```bash
cd <BENCH>
bench --site <SITE> migrate 2>&1 | tee "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-migrate.log"
```

No `--skip-failing`, no `--skip-fixtures`, no `--skip-search-index`. A failing patch must fail the migrate; that is the safety property this whole plan is built around. `bench bypass-patch` is forbidden here and forever for these patches.

Verified execution order in installed `frappe/migrate.py`: `before_migrate` hooks, then all `pre_model_sync` patches, then `frappe.model.sync.sync_all()`, then all `post_model_sync` patches, then scheduled-job sync, then fixture sync, then dashboards, then customizations, then orphan-doctype removal, then `after_migrate` hooks. Two consequences the patches depend on: the DocType module transfer must be `pre_model_sync` so sync imports one authoritative JSON copy, and the ownership patches must create their own Custom Fields because fixtures sync after them.

- [ ] **Step 4: Read the migrate output for warnings, not just for the exit code**

Scan the log for:
- a yellow multi-app controller-override warning; any doctype overridden by more than one app is a failure signal;
- any patch that reported a skip;
- errors from `Removing orphan doctypes`, which is where a leftover duplicate DocType JSON would surface.

- [ ] **Step 5: Record the migrate evidence**

Record the exact command, the exit code, the wall-clock duration, and the full log into `<WINDOW_ID>-MIGRATE`. Redact absolute paths outside the operator record.

If migrate failed: do not rerun it, do not add a skip flag, and do not bypass the patch. Go to Task 17.

---

### Task 12: Post-Migration Invariants

**Artifacts:**
- Produce: `<WINDOW_ID>-INV`
- Verify only: `<SITE>` and the source trees

**Interfaces:**
- Consumes: the migrated site.
- Produces: the gate that decides between Task 14 and Task 17. Every invariant is read-only.

Run every check. Record one line per invariant with its command output and a pass or fail verdict. Any fail is a rollback trigger, not a fix-forward opportunity, because traffic has not reopened.

- [ ] **Step 1: DocType ownership moved, business rows intact**

```bash
cd <BENCH>
for dt in "Price Group" "Price Group Item" "Price Group Outlet"; do
  bench --site <SITE> execute frappe.db.get_value --args "[\"DocType\", \"$dt\", \"module\"]"
done
bench --site <SITE> execute frappe.db.count --args '["Price Group"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Item"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group Outlet"]'
```

Expected: three times `Selling Additional`, and three counts identical to the pre-migrate baseline. Task 6 must capture all three counts before migrate. The migration deletes no parent or child business row.

- [ ] **Step 2: Exactly one provider per moved hook**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.get_hooks --args '["override_whitelisted_methods"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.stock.utils.scan_barcode"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"]'
bench --site <SITE> execute frappe.get_hooks --args '["override_doctype_class"]'
```

Expected: the scanner list holds exactly one entry, the `stock_additional` path; the past-order list holds exactly one entry, the `selling_additional` path; `Serial and Batch Bundle` has exactly one provider, `bakery_manufacturing`. A list with two entries is a fail even when the effective method looks right, because `override_whitelisted_method` returns the last entry and the answer would then depend on app order.

- [ ] **Step 3: Ownership fields exist with the exact names**

```bash
cd <BENCH>
for f in "Price List-custom_selling_additional_price_group" \
         "Item Price-custom_selling_additional_price_group" \
         "POS Profile-custom_selling_additional_price_group" \
         "POS Profile-custom_selling_additional_previous_price_list" \
         "POS Invoice-custom_walk_in_customer_name" \
         "Sales Invoice-custom_walk_in_customer_name" \
         "Item-custom_default_uom_warehouse"; do
  printf '%s ' "$f"
  bench --site <SITE> execute frappe.db.exists --args "[\"Custom Field\", \"$f\"]"
done
```

Expected: all seven exist. Custom Field names are `dt + "-" + fieldname`, which is why exact-name checks are meaningful and `fieldname`-only checks are not.

- [ ] **Step 4: Field values preserved**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.count \
  --args '["POS Invoice", {"custom_walk_in_customer_name": ["is", "set"]}]'
bench --site <SITE> execute frappe.db.count \
  --args '["Sales Invoice", {"custom_walk_in_customer_name": ["is", "set"]}]'
bench --site <SITE> execute frappe.db.count \
  --args '["Item", {"custom_default_uom_warehouse": ["is", "set"]}]'
```

Expected: identical to the same counts taken before migrate. Record these as counts, per the redaction rules. The migration moves fixture ownership, never stored values.

- [ ] **Step 5: Ownership markers are consistent**

```bash
cd <BENCH>
bench --site <SITE> execute selling_additional.migration.preflight.check \
  --kwargs '{"phase": "final"}' \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-postflight.json"
python3 -m json.tool "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-postflight.json" > /dev/null
shasum -a 256 "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-selling-postflight.json"
bench --site <SITE> execute stock_additional.migration.preflight.check \
  --kwargs '{"phase": "final"}' \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-stock-postflight.json"
shasum -a 256 "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-stock-postflight.json"
```

Expected: every section clean, no profile claimed by two Price Groups, no ambiguous Item Price, no profile missing a recovery value, zero legacy sidebar items. Both modules are read-only, so this is safe post-migration.

- [ ] **Step 6: Navigation ownership**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.db.exists \
  --args '["Workspace", "Selling Additional"]'
bench --site <SITE> execute frappe.db.exists \
  --args '["Workspace Sidebar", "Selling Additional"]'
bench --site <SITE> execute frappe.db.count \
  --args '["Workspace Sidebar Item", {"link_to": "Price Group"}]'
```

Expected: the workspace and sidebar exist, and exactly one Price Group sidebar item remains — the one owned by `Selling Additional`. Zero means the app sidebar failed to import; two means the ERPNext leak survived.

- [ ] **Step 7: Migrate wrote nothing into framework source**

```bash
cd <BENCH>
git -C apps/erpnext status --porcelain
git -C apps/frappe status --porcelain
```

Expected: `apps/frappe` clean; `apps/erpnext` showing only ` M banking/yarn.lock`, `?? .codegraph/`, `?? graphify-out/`. A reappeared `erpnext/workspace_sidebar/selling.json` diff means something called `save()` on ERPNext's sidebar under developer mode, which is the exact defect this rollout removes. That is a fail.

- [ ] **Step 8: Halt for the invariant verdict**

Report every invariant with its verdict into `<WINDOW_ID>-INV`. All pass continues to Task 13. Any fail goes to Task 17.

---

### Task 13: Forced Patch Rerun on the Scratch Copy

**Artifacts:**
- Produce: `<WINDOW_ID>-IDEMP`
- Modify: `<SCRATCH_SITE>` only

**Interfaces:**
- Consumes: `<SCRATCH_SITE>` from Task 6 and the verified coordinated source state from Task 9.
- Produces: idempotency evidence with no risk to `<SITE>`.

Never force-rerun a patch on `<SITE>`. A forced rerun re-executes a completed patch against live data; the patches are written to be idempotent, but the place to prove that is a disposable copy.

- [ ] **Step 1: Bring the scratch copy to the same state**

```bash
cd <BENCH>
bench --site <SCRATCH_SITE> migrate 2>&1 \
  | tee "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-scratch-migrate.log"
```

The scratch site was restored from the pre-cutover backup and now sees the verified coordinated source state, so this reproduces the populated upgrade. Expected: same patch sequence, exit zero.

- [ ] **Step 2: Snapshot deterministic business state**

Run `selling_additional.migration.checksums.collect_business_checksums`. It canonicalizes sorted business columns for these tables:

- `tabPrice Group`;
- `tabPrice Group Item`;
- `tabPrice Group Outlet`;
- `tabPrice List`;
- `tabItem Price`;
- `tabPOS Profile`;
- `tabCustom Field`;
- `tabWorkspace Sidebar Item`.

It emits only one SHA-256 per table and a row count. Exclude volatile metadata only where the helper names it explicitly. Exclude `tabPatch Log` entirely. Capture output before rerunning any patch:

```bash
cd <BENCH>
bench --site <SCRATCH_SITE> execute \
  selling_additional.migration.checksums.collect_business_checksums \
  > "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-business-before.json"
python3 -m json.tool \
  "$CLAUDE_JOB_DIR/tmp/<WINDOW_ID>-business-before.json" > /dev/null
```

- [ ] **Step 3: Force-rerun every registered patch**

```bash
cd <BENCH>
for p in selling_additional.patches.v1_0.transfer_price_group_ownership \
         selling_additional.patches.v1_0.adopt_legacy_selling_state \
         stock_additional.patches.v1_0.assert_stock_cutover_ready; do
  echo "== $p"
  bench --site <SCRATCH_SITE> run-patch "$p" --force
done
```

`run-patch --force` adds Patch Log history. Patch Log changes are expected and excluded from business-state checks.

- [ ] **Step 4: Prove no business row changed**

Capture `collect_business_checksums()` again into `<WINDOW_ID>-business-after.json`. Compare canonical JSON exactly with the before file. Include both Price Group child tables. Exclude `tabPatch Log` explicitly. A second plain migrate proves only Patch Log skip behavior.

- [ ] **Step 5: Record the verdict**

Record the forced-rerun output and the before-and-after snapshots into `<WINDOW_ID>-IDEMP`.

---

### Task 14: Build Assets and Clear Caches

**Artifacts:**
- Produce: `<WINDOW_ID>-ASSETS`
- Modify: `sites/assets`, site cache, bench web and worker processes

**Interfaces:**
- Consumes: the migrated site and the verified coordinated source state.
- Produces: the `selling_additional` page asset and Price Group form script served to browsers, and caches consistent with the new metadata.

- [ ] **Step 1: Build assets for the two new apps**

```bash
cd <BENCH>
bench build --app selling_additional
bench build --app stock_additional
```

Verified in installed Frappe `frappe/commands/utils.py`: `--app` feeds the same `apps` argument as `--apps`, `developer_mode` forces development mode and disables cached artifacts, and `--force` skips the remote-asset download path. Add `--force` only if the build reports it reused a cached artifact.

- [ ] **Step 2: Rebuild bakery assets only if its bundle is referenced**

`bakery_manufacturing` keeps `app_include_js = "bakery_manufacturing.bundle.js"`. Candidate source removes only the tracked walk-in import and preserves the 14-line user suffix. Build it so served assets drop the old global poll:

```bash
cd <BENCH>
bench build --app bakery_manufacturing
git -C apps/bakery_manufacturing status --porcelain
shasum -a 256 apps/bakery_manufacturing/bakery_manufacturing/public/js/bakery_manufacturing.bundle.js
```

Expected: source bundle hash is `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`. A build writes to `sites/assets`, never app source. Any other hash fails.

- [ ] **Step 3: Verify the asset manifest resolves**

```bash
cd <BENCH>
ls sites/assets/selling_additional sites/assets/stock_additional
grep -c "selling_additional" sites/assets/assets.json
```

Expected: both asset directories exist and the manifest references `selling_additional`.

- [ ] **Step 4: Clear site and website caches**

```bash
cd <BENCH>
bench --site <SITE> clear-cache
bench --site <SITE> clear-website-cache
```

`clear-cache` runs `frappe.clear_cache()` plus the website cache clear, which drops `doctype_modules`, `app_modules`, `module_app`, the per-user desk sidebar items, and bootinfo. The module transfer and the sidebar child-row delete both need this.

- [ ] **Step 5: Restart web and socketio processes**

```bash
<WEB_RESTART>
```

Restart before smoke testing so long-lived workers pick up the new hooks. Leave background workers stopped until Task 16; smoke tests must not enqueue work into a stopped queue and then look like failures.

- [ ] **Step 6: Record the outputs**

Record build output, manifest checks, cache clears, and the restart confirmation into `<WINDOW_ID>-ASSETS`.

---

### Task 15: Gates — Suites, Static Checks, Manual Smoke

**Artifacts:**
- Produce: `<WINDOW_ID>-GATES`
- Verify only: `<SITE>`; run automated suites on `<TEST_SITE>` and `<SCRATCH_SITE>`

**Interfaces:**
- Consumes: everything above.
- Produces: the evidence set spec section 20 requires, and the go decision for Task 16.

- [ ] **Step 1: Run all four full suites on the test site**

```bash
cd <BENCH>
bench --site <TEST_SITE> run-tests --app selling_additional
bench --site <TEST_SITE> run-tests --app stock_additional
bench --site <TEST_SITE> run-tests --app bakery_manufacturing
bench --site <TEST_SITE> run-tests --app roti_ropi_pos
```

Expected: all four pass against the verified coordinated source state. Suites do not run on `<SITE>`: `run-tests` refuses unless the site config has `allow_tests`, and setting that on a live site is out of scope.

- [ ] **Step 2: Run the related ERPNext regression modules**

```bash
cd <BENCH>
bench --site <TEST_SITE> run-tests --module erpnext.stock.tests.test_utils
bench --site <TEST_SITE> run-tests --module erpnext.stock.doctype.item_price.test_item_price
bench --site <TEST_SITE> run-tests --module erpnext.stock.doctype.price_list.test_price_list
bench --site <TEST_SITE> run-tests --module erpnext.accounts.doctype.pos_invoice.test_pos_invoice
bench --site <TEST_SITE> run-tests --module erpnext.accounts.doctype.pos_closing_entry.test_pos_closing_entry
```

These five module paths exist in installed ERPNext. Its POS Page directory has no test module.

- [ ] **Step 3: Run the populated-upgrade suite on the scratch copy**

```bash
cd <BENCH>
bench --site <SCRATCH_SITE> set-config allow_tests true
bench --site <SCRATCH_SITE> run-tests --app selling_additional
bench --site <SCRATCH_SITE> run-tests --app stock_additional
```

This is the only place suites run against real-shaped data. `<SCRATCH_SITE>` is disposable, so enabling `allow_tests` there is acceptable; never do it on `<SITE>`.

- [ ] **Step 4: Run static checks in all four repositories**

```bash
cd <BENCH>/apps/selling_additional && pre-commit run --all-files && git diff --check
cd <BENCH>/apps/stock_additional && pre-commit run --all-files && git diff --check
cd <BENCH>/apps/bakery_manufacturing && pre-commit run --all-files
cd <BENCH>/apps/roti_ropi_pos && pre-commit run --all-files
```

A missing `pre-commit` binary is a failure, not a pass. Run from the environment that owns the app dependencies.

- [ ] **Step 5: Run the manual smoke checklist on the target site**

Restrict access to operator sources, then take maintenance mode off so the app actually serves for the smoke test:

```bash
<INGRESS_ALLOWLIST_ONLY>
cd <BENCH>
bench --site <SITE> set-maintenance-mode off
bench --site <SITE> scheduler status
```

Leave background workers stopped and the scheduler paused. Record a pass or fail for each item:

1. Batch scan with a valid custom UOM returns the custom UOM and a positive conversion factor.
2. Batch scan on an Item with an invalid conversion fails closed, returns no scan payload, and leaves the transaction row unchanged. Do not create invalid data on `<SITE>` for this; verify it on `<SCRATCH_SITE>` and record which site produced the evidence.
3. Price Group: create, enable, add and remove an item, change a rate, add and remove an outlet, disable, re-enable, delete. A manual Item Price on the managed Price List survives every step.
4. Two Price Groups targeting one POS Profile: one owner, one clear rejection, no silent overwrite.
5. Price Group delete leaves the managed Price List present and disabled, with no dangling POS Profile link.
6. Desk POS: a walk-in name on the profile default Customer is accepted; on a registered Customer it is rejected; a Customer reset clears the field; exactly one walk-in input renders.
7. No one-second polling on any other Desk route; the walk-in asset loads only on the point-of-sale page.
8. Recent Orders: a walk-in name displays through the standard renderer, searching it finds the invoice, and the stored `customer` id is unchanged.
9. Navigation: the `Selling Additional` workspace and sidebar show Price Group; ERPNext's Selling sidebar shows none.
10. Mobile POS end to end: bootstrap, customer search, catalog, scan, quote, sale, return, closing. All DTOs and error codes stay unchanged. Invalid default-UOM configuration returns no scan payload and follows native Frappe HTTP 417 validation handling.

- [ ] **Step 6: Halt for the gate verdict, then drop the scratch site**

Report the full evidence set: suite results, ERPNext module results, populated-upgrade results, static checks, invariants, idempotency, preflight and postflight hashes, and the smoke checklist. Every spec section 20 gate must be satisfied.

**APPROVAL: scratch site deletion.** Only after the verdict is recorded:

```bash
cd <BENCH>
bench drop-site <SCRATCH_SITE> --db-root-username <DB_ROOT_USER> --no-backup
```

Keep `<SCRATCH_SITE>` if any gate failed; it is the cheapest place to diagnose.

---

### Task 16: Reopen Traffic

**APPROVAL: reopen.** Only after every Task 15 gate passes.

**Artifacts:**
- Produce: `<WINDOW_ID>-REOPEN`
- Modify: `<SITE>` scheduler state; worker processes; ingress

**Interfaces:**
- Consumes: the passed gate verdict.
- Produces: the site back in normal service, with the scheduler state recorded in `<WINDOW_ID>-DISC` restored exactly.

Reopen reverses the drain in the reverse order it was applied.

- [ ] **Step 1: Confirm maintenance mode is off**

```bash
cd <BENCH>
bench --site <SITE> execute frappe.conf.get --args '["maintenance_mode"]'
```

Expected: falsy or absent, from Task 15 Step 5.

- [ ] **Step 2: Restart the background workers**

```bash
<WORKER_START>
cd <BENCH>
bench doctor --site <SITE>
```

Expected: the recorded worker count is present.

- [ ] **Step 3: Restore the scheduler to its recorded state**

```bash
cd <BENCH>
bench --site <SITE> scheduler resume
bench --site <SITE> scheduler status
```

Expected: the exact state recorded in `<WINDOW_ID>-DISC`. If the scheduler was already disabled before the window, leave it disabled; `resume` only clears `pause_scheduler`.

- [ ] **Step 4: Confirm scheduled jobs enqueue and drain**

```bash
cd <BENCH>
bench --site <SITE> show-pending-jobs
```

Watch one scheduler tick. Jobs should appear and clear. A queue that only grows means workers did not come back.

- [ ] **Step 5: Open the ingress**

```bash
<INGRESS_OPEN>
```

Confirm from an external client that `<SITE>` serves normally.

- [ ] **Step 6: Watch for one observation period**

Watch the site error log, worker error log, and ingress error rate for at least thirty minutes of real traffic. Watch specifically for: barcode scan errors, Price Group save failures, POS Profile validation errors, Desk POS asset errors, and Mobile POS 4xx or 5xx changes.

- [ ] **Step 7: Close the window**

Record the reopen timestamp, the observation results, and the operator sign-off into `<WINDOW_ID>-REOPEN`. State explicitly in the record: after this point, rollback by restore would discard real business transactions, and the response to a defect is a forward fix.

---

### Task 17: Rollback

**APPROVAL: rollback.** Executed only on a failure in Tasks 11, 12, 14, or 15, and only while traffic is still stopped.

**Artifacts:**
- Produce: `<WINDOW_ID>-ROLLBACK`
- Modify: `<SITE>` database, files, site config; the four app working trees

**Interfaces:**
- Consumes: verified backup, rehearsal result, `<PREV_SHA_BAKERY>`, `<PREV_SHA_ROTI>`, baseline branch states, and shell tags.
- Produces: the pre-cutover state.

Two rules that override everything else in this task. Never use `uninstall-app` as rollback: uninstalling an owner app can drop its DocType tables and destroy Price Group data. Never use `remove-from-installed-apps` and never reorder the installed-app list: the order is append-only bookkeeping, and rewriting it to change which hook wins hides the real problem.

- [ ] **Step 1: Keep the outage in place**

Confirm maintenance mode on, ingress stopped, scheduler paused, workers stopped. If Task 15 already turned maintenance off, turn it back on before restoring:

```bash
cd <BENCH>
bench --site <SITE> set-maintenance-mode on
bench --site <SITE> ready-for-migration
```

- [ ] **Step 2: Capture forensic state before overwriting it**

```bash
cd <BENCH>
bench --site <SITE> backup --with-files
```

Record the new artifact names and hashes as the failure snapshot. Restoring discards the evidence otherwise.

- [ ] **Step 3: Re-verify the rollback input**

```bash
cd <BACKUP_DIR>
shasum -a 256 <TS>-<SLUG>-database.sql.gz <TS>-<SLUG>-files.tar \
  <TS>-<SLUG>-private-files.tar <TS>-<SLUG>-site_config_backup.json
```

Expected: hashes match `<WINDOW_ID>-BACKUP` exactly. A mismatch means do not restore; escalate.

- [ ] **Step 4: Restore database and files**

```bash
cd <BENCH>
bench --site <SITE> restore \
  <BACKUP_DIR>/<TS>-<SLUG>-database.sql.gz \
  --with-public-files <BACKUP_DIR>/<TS>-<SLUG>-files.tar \
  --with-private-files <BACKUP_DIR>/<TS>-<SLUG>-private-files.tar \
  --db-root-username <DB_ROOT_USER>
```

Add `--encryption-key` only when the backup is encrypted. This is the same command shape Task 6 rehearsed, so its duration is known.

- [ ] **Step 5: Restore prior app source**

```bash
cd <BENCH>
git -C apps/roti_ropi_pos checkout --detach <PREV_SHA_ROTI>
git -C apps/selling_additional checkout --detach <TAG_SHELL>
git -C apps/stock_additional checkout --detach <TAG_SHELL>
```

After source verification, restore Roti's baseline branch attachment only when `<PREV_REF_ROTI>` is not `DETACHED` and that branch still points to `<PREV_SHA_ROTI>`. Otherwise remain detached and record why. Restore selling and stock to their shell release branches only if the operator record contains verified branch names at those tag SHAs; otherwise detached tags are correct.

Run:

```bash
cd <BENCH>/apps/bakery_manufacturing
python3 scripts/ownership_cutover.py rollback \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  --manifest <BAKERY_OVERLAY_MANIFEST>
```

Verify bakery `HEAD` remains `<PREV_SHA_BAKERY>`, index is empty, bundle full hash is `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8`, numstat is `14 0`, and protected sidebar test remains byte-identical and untracked.

The two new apps roll back to the shell tag, not to nothing. They stay installed; the restored database still lists them, and their shell releases own no runtime behavior. This is exactly why Stage A is a separate release.

- [ ] **Step 6: Restore the ERPNext sidebar working-tree state**

The restored database no longer contains the app-owned sidebar, and the source file is already at HEAD from Task 10. Leave it at HEAD. The pre-cutover leak was a defect; rollback does not restore a defect into source. Confirm:

```bash
cd <BENCH>/apps/erpnext
git status --porcelain
```

Expected: ` M banking/yarn.lock`, `?? .codegraph/`, `?? graphify-out/`. Record that the source leak stays reversed while the database row returns with the restore, and that the next cutover attempt handles the row again.

- [ ] **Step 7: Revoke the operator recovery-map input**

Disable or remove the protected loader input configured in Task 8. Verify only that `recovery_map.load()` reports no configured input. Do not print old content. Database and file restore do not revoke an external operator secret automatically.

- [ ] **Step 8: Rebuild prior assets and clear caches**

```bash
cd <BENCH>
bench build --app selling_additional
bench build --app stock_additional
bench build --app bakery_manufacturing
bench build --app roti_ropi_pos
bench --site <SITE> clear-cache
bench --site <SITE> clear-website-cache
<WEB_RESTART>
```

Selling and stock now run shell source, while bakery and Roti run previous source. Rebuild all four so no candidate manifest or JS remains served.

- [ ] **Step 9: Verify the restored state matches the baseline**

```bash
cd <BENCH>
bench --site <SITE> list-apps
bench --site <SITE> execute frappe.db.get_value \
  --args '["DocType", "Price Group", "module"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.stock.utils.scan_barcode"]'
bench --site <SITE> execute frappe.override_whitelisted_method \
  --args '["erpnext.selling.page.point_of_sale.point_of_sale.get_past_order_list"]'
bench --site <SITE> execute frappe.db.count --args '["Price Group"]'
bench --site <SITE> execute frappe.db.count --args '["POS Invoice"]'
```

Expected: the app list and order from Task 3 Step 4, `Price Group` owned by `Bakery Manufacturing`, both overrides resolving to `bakery_manufacturing` paths, and counts matching `<WINDOW_ID>-BACKUP`.

- [ ] **Step 10: Run the previous release smoke test, then reopen**

Run the pre-cutover smoke set: batch scan, Price Group save, Desk POS walk-in, Recent Orders, and Mobile POS bootstrap through closing. Then follow Task 16 to reopen.

- [ ] **Step 11: Record the rollback**

Record the trigger, the failure snapshot IDs, the restore inputs and duration, the restored SHAs, the config decision, and the verification into `<WINDOW_ID>-ROLLBACK`. Do not retry the cutover in the same window; a rolled-back attempt needs a fresh preflight and a fresh backup.

---

### Task 18: Post-Rollout Follow-Up

**Artifacts:**
- Modify: `docs/superpowers/plans/2026-08-14-app-ownership-rollout.md` status notes, and the three implementation plans' status lines
- Verify only: `<SITE>`

**Interfaces:**
- Consumes: `<WINDOW_ID>-REOPEN`.
- Produces: the compatibility-shim removal precondition from spec section 21.

- [ ] **Step 1: Watch the first full business day**

Watch for barcode configuration errors, Price Group lifecycle errors, walk-in validation rejections, and Mobile POS error-rate changes. Record counts, not business identifiers.

- [ ] **Step 2: Record the shim inventory**

Bakery lazy shims for `custom_scan_barcode` and `custom_get_past_order_list` stay for one compatibility release. No Price Group DocType-folder shim exists. Use CodeGraph plus the final preflight report to scan first-party and site-record references. Store full results only in operator records. Expected: only two shim definitions and explicit deprecation documentation.

- [ ] **Step 3: Clean the shared bakery checkout after a stable window**

**APPROVAL: shared-checkout source switch.** Only after first business-day observation passes, run:

```bash
cd <BENCH>/apps/bakery_manufacturing
python3 scripts/ownership_cutover.py finalize \
  --base <PREV_SHA_BAKERY> --target <SHA_BAKERY> \
  --manifest <BAKERY_OVERLAY_MANIFEST>
```

Verify working file still equals suffix SHA-256 `8b04313861b211aa17cb4d0c87c372d32e2f8b0d642b94292e58a7865ae1bbf1`, candidate branch or detached target is attached as approved, no candidate path remains staged, and protected sidebar test remains byte-identical and untracked. Never stash, reset, clean, or force checkout.

If this step is not separately approved, leave the verified overlay state intact and document that the shared checkout intentionally remains at `<PREV_SHA_BAKERY>` plus overlay. Runtime behavior is already correct.

- [ ] **Step 4: Update plan status lines**

Mark the shells plan, the stock cutover plan, and the selling cutover plan complete with their commit references, and note this window's `<WINDOW_ID>` and outcome. Per `AGENTS.md`, this documentation update needs no separate approval.

- [ ] **Step 5: Open the follow-up release scope**

Record the spec section 21 items as the next release's scope: remove the shims, remove handoff-only checks, keep the idempotency guards, keep the exact-one-owner and exact-one-provider tests, and handle the unrelated bakery sidebar prototype as its own approved task.

---

## Verified Caveats

1. **`bench --site <SITE> run-tests` refuses without `allow_tests`.** Verified in installed `frappe/commands/testing.py`: it exits early unless the site config has `allow_tests` or `CI` is in the environment. Full automated suites therefore run on `<TEST_SITE>` and `<SCRATCH_SITE>`, never on `<SITE>`.

2. **ERPNext's POS Page directory has no test module.** Use the five verified regression paths in Task 15 Step 2.

3. **`override_whitelisted_method` returns the last provider.** Verified in installed `frappe/__init__.py`: it reads the aggregated hook list and returns `overrides[-1]`. With two providers registered, the winner depends on installed-app order. That is why every gate asserts the provider *list* has exactly one entry, and why the plan forbids ever editing app order.

4. **Installed-app order is append-only.** Verified in `frappe/installer.py`: `add_to_installed_apps` appends to the `installed_apps` global. There is no supported reorder operation, and `remove_from_installed_apps` plus reinstall is not a reorder — it is a data-loss risk. Order is evidence, not a knob.

5. **Backup artifact names are deterministic and hashable.** Verified in `frappe/utils/backups.py`: `set_backup_file_name` produces `<YYYYMMDD_HHMMSS>-<site_slug>-database.sql.gz`, `-files.tar`, `-private-files.tar`, and `-site_config_backup.json` under `sites/<site>/private/backups`, with an `-enc` infix when System Settings has `encrypt_backup` on and `.tgz` archives only with `--compress`. `print_summary` prints absolute paths and sizes.

6. **An encrypted backup is only a backup with its key.** `bench restore` needs `--encryption-key` or a resolvable site-config key. The plan verifies key retrievability in Task 5 Step 2, before anything depends on the backup.

7. **`maintenance_mode` hard-stops HTTP; `pause_scheduler` stops enqueue.** Verified in `frappe/app.py` (raises `SessionStopped` unless `allow_reads_during_maintenance`) and `frappe/utils/scheduler.py` (`is_scheduler_inactive` returns true for either flag). `bench scheduler pause` writes the reversible site-config flag; `disable-scheduler` writes a persistent System Settings flag and is not used here.

8. **`bench ready-for-migration` is a real drain check with a known cost.** Verified in `frappe/commands/scheduler.py`: it polls RQ three times, one second apart, for queued and started jobs whose id starts with the site name, and exits 1 when any is pending. It takes about three seconds and is worth running twice.

9. **Migrate order fixes two patch design constraints.** Verified in `frappe/migrate.py`: `before_migrate` hooks, all `pre_model_sync` patches, `sync_all()`, all `post_model_sync` patches, then jobs, then fixtures, then customizations, then orphan-doctype removal, then `after_migrate`. The DocType module transfer must be `pre_model_sync`, and the ownership patches must create their own Custom Fields because fixture sync runs after them.

10. **Migrate warns, rather than fails, on duplicate controller overrides.** Verified in `frappe/migrate.py`: it prints a yellow warning when more than one app overrides a doctype class. Treat that warning in the Task 11 log as a failure signal; nothing else will stop the migrate.

11. **`run-patch --force` re-executes a completed patch.** Verified in `frappe/commands/site.py` passing `force` to `frappe.modules.patch_handler.run_single`. A second plain `migrate` proves only `Patch Log` skip behavior, so idempotency evidence must come from the forced rerun — and on `<SCRATCH_SITE>`, not on `<SITE>`.

12. **`bench set-config <key> None` deletes the key.** Verified in `frappe/installer.py::_update_config_file`: the literal string `"None"` removes the key, and `"0"`/`"1"` are coerced to int. Both matter for restoring `developer_mode` in the shells plan and for clearing the recovery map in rollback.

13. **`bench build --app` is accepted.** Verified in `frappe/commands/utils.py`: `--app` feeds the same `apps` argument as `--apps`. `developer_mode` forces development mode and disables cached artifacts; `--force` skips the remote-asset download.

14. **`bench version` truncates the commit.** Verified in `frappe/commands/utils.py`: it reports `head.object.hexsha[:7]`. Every SHA this plan pins comes from `git rev-parse HEAD`; `bench version -f json` is corroborating evidence only.

15. **The current working-tree state matches what the plans assume, re-verified today.** `apps/erpnext`: ` M banking/yarn.lock`, ` M erpnext/workspace_sidebar/selling.json` at numstat exactly `13 1`, `?? .codegraph/`, `?? graphify-out/`, nothing staged, committed sidebar clean. `apps/bakery_manufacturing`: bundle sha256 `72ce8f92200720b0ebbfca98eedc64aeef02ef163342da3a41d87635a2d7bbb8` at numstat `14 0`, plus untracked `AGENTS.md`, `bakery_manufacturing/tests/test_desk_sidebar.py`, `diference.md`, `graphify-out/`. Re-verify at execution time; a drift means a fresh review, not a proceed.

16. **`bakery_manufacturing` still owns everything today.** Its `hooks.py` currently registers both moved overrides, the `after_migrate` hook, and a `fieldname`-only fixture filter covering `custom_default_uom_warehouse` and `custom_walk_in_customer_name`. `roti_ropi_pos/hooks.py` still declares `required_apps = ["erpnext", "bakery_manufacturing"]`. Nothing in this rollout has started.

17. **Neither new app exists on disk or on the site yet.** `apps/` holds `bakery_manufacturing`, `erpnext`, `frappe`, `hrms`, `payments`, `pos_direct_print`, `roti_ropi_pos`, `roti_ropi_pos_task11`. Stage A is genuinely the first step.

18. **`roti_ropi_pos_task11` is unaudited.** It sits in `apps/` and was never checked for competing Price Group or past-order hooks. If it is installed on `<SITE>`, Task 7 Step 8 must audit its `hooks.py`; the exact-one-provider gate would otherwise fail mid-window.

19. **Versions verified:** Frappe 16.27.1, ERPNext 16.28.0.

20. **Bench-tool commands could not be verified from installed source.** Only Frappe-provided commands were checked against `apps/frappe/frappe/commands/`. The bench CLI wrapper itself is not a Python package in this bench environment, and this bench has no `config/supervisor.conf` or `config/nginx.conf` — it runs from a `Procfile`. So `bench get-app`, `bench restart`, and any supervisor or nginx operation are unverified here, which is why every process and ingress action in this plan is a `<...>` placeholder for the operator's real command rather than a guessed one.

21. **Rollback source identities are incomplete until Task 1 runs.** Record live bakery and Roti SHAs, all baseline branch states, both shell tag SHAs, and framework SHAs at window time. Planning-time HEAD values can move before rollout.