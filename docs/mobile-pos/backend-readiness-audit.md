# Mobile POS Backend Readiness Audit

**Audit basis:** This report uses only the verified evidence in `docs/mobile-pos/backend-audit-checkpoint.md`.

**Audit scope:** The review covers the 16 Mobile POS v1 endpoints, OAuth boundary, ERPNext orchestration, recovery, contracts, and verified tests.

**Finding count:** 1 Critical, 17 Important, and 15 Minor.

## 1. Executive Verdict

| Area | Verdict | Reason |
| --- | --- | --- |
| Business fit | **READY WITH GAPS** | The backend covers the MVP flow from authentication through closing. Session-scoped history and lost-key closing recovery are missing. |
| Android API readiness | **NOT READY** | The endpoint surface exists, but authentication, mutation recovery, stable errors, and core sale and return verification have blockers. |
| Security | **NOT READY** | Equivalent Frappe routes can bypass the OAuth Bearer boundary for a Desk user who also has the cashier role. Closing also elevates to Administrator. |
| Reliability / recovery | **NOT READY** | Closing commits invalidate the common savepoint. Lost closing keys can strand an outlet. Idempotency contention can return unstable server errors. |
| Maintainability | **READY WITH GAPS** | Runtime ownership is mostly correct. Large modules, copied ERPNext calculations, internal imports, overrides, and stale documents increase upgrade risk. |

**Overall verdict:** **NOT READY** for a production Android rollout or cashier pilot.

ERPNext remains the source of truth for profiles, customers, sessions, pricing, stock, invoices, returns, closing, and accounting. The Android client can remain a thin cashier client after the blockers are fixed.

## 2. Business Flow Matrix

| Flow | Status | Gap | Severity |
| --- | --- | --- | --- |
| Authentication | **NOT READY** | PKCE S256 and client-bound Bearer checks exist on canonical routes. Equivalent Frappe aliases bypass that boundary for Desk users with the cashier role. Missing OAuth client configuration also lacks a clear diagnosis. | Critical |
| Bootstrap | **READY WITH GAPS** | User, profile, opening, closing, capabilities, and POS mode projections exist. The response has no deployment revision or minimum-client compatibility signal. | Important |
| Opening / session | **READY WITH GAPS** | Opening ownership and profile checks exist. Concurrent retries can escape the stable idempotency contract. An unresolved closing disables mutations without lost-key recovery. | Important |
| Customer | **READY WITH GAPS** | Search returns existing enabled customers and does not create records. Large client offsets amplify three database searches and an in-memory merge. | Important |
| Catalog / barcode / custom UOM | **READY WITH GAPS** | Profile-derived catalog, barcode, price, warehouse, and custom UOM behavior exist. Full-master permission filtering, pagination limits, and conversion-factor drift remain. | Important |
| Cart / pricing | **READY WITH GAPS** | The server recalculates item, UOM, stock, price, tax, and totals. Reachable quote errors and some configuration details are not fully documented. | Important |
| Payment / sale | **NOT READY** | The server requires authoritative zero outstanding amount and supports distinct payment modes. ERPNext validation errors escape the v1 envelope, and fresh sale tests did not execute. | Important |
| Idempotency / recovery | **NOT READY** | Durable request records and replay exist. Rollback races, lock timeouts, closing savepoint loss, and lost-key closing recovery violate safe retry expectations. | Important |
| History | **NOT READY** | List and detail endpoints enforce cashier, profile, and company scope. The list is not limited to the current session as FR-7 requires. | Important |
| Return / refund | **NOT READY** | POS Invoice return flow, limits, and server authority exist. Fresh return tests did not execute, core errors are unstable, and reloaded receipts lose the return reason. | Important |
| Closing | **NOT READY** | Preview, durable phases, polling, and queued consolidation exist. Transaction handling, Administrator elevation, and abandoned Draft recovery block release. | Important |

## 3. Android API Contract Readiness

All rows remain subject to Critical finding C-1 and the incorrect `meta.server_time` behavior in I-8.

| Endpoint | Purpose | Android-ready? | Gap |
| --- | --- | --- | --- |
| `GET roti_ropi_pos.api.v1.bootstrap.get` | Return user, assigned profiles, selected profile, current opening, closing state, capabilities, and POS mode. | **PARTIAL** | The response contract is useful for client startup. It lacks backend revision, contract revision, and minimum-client compatibility data. |
| `GET roti_ropi_pos.api.v1.sessions.current` | Return the current opening and closing projection for an authorized profile. | **PARTIAL** | The server owns profile and session scope. A stranded Closing Draft can disable mutations, and the client has no lost-key recovery operation. |
| `POST roti_ropi_pos.api.v1.sessions.open` | Create and submit an opening for the authenticated cashier and profile. | **NO** | The mutation uses durable idempotency, but contention can return `IDEMPOTENCY_INVARIANT` or a native lock-timeout response instead of retry guidance. |
| `GET roti_ropi_pos.api.v1.customers.search` | Search existing enabled, visible customers with pagination. | **PARTIAL** | The projection and no-create boundary are suitable. Unbounded high offsets can cause expensive database and memory work. |
| `GET roti_ropi_pos.api.v1.catalog.search` | Search profile-scoped sale items with price, stock, barcode, and UOM data. | **PARTIAL** | The server derives the price list and warehouse. Full-master filtering scales poorly, `has_more` can be false-positive, and the `start` cap is undocumented. |
| `GET roti_ropi_pos.api.v1.catalog.scan` | Resolve a scanned barcode within the authorized POS catalog. | **PARTIAL** | The server-authoritative scan projection is present. Production use remains blocked by the shared authentication and metadata defects. |
| `GET roti_ropi_pos.api.v1.catalog.quote_item` | Quote one item and selected UOM with authoritative profile pricing and stock rules. | **PARTIAL** | The core request and response path is present. Production use remains blocked by the shared authentication and metadata defects. |
| `POST roti_ropi_pos.api.v1.sales.quote_cart` | Recalculate a cart, customer, prices, taxes, stock, UOM, tracking data, and totals. | **PARTIAL** | The server remains authoritative. The endpoint documentation omits reachable stock, batch, and serial errors. Some profile error details are incomplete. |
| `POST roti_ropi_pos.api.v1.sales.submit` | Create and submit a fully settled POS Invoice under the current opening. | **NO** | Expected ERPNext validation failures can escape the stable envelope. Idempotency contention is incomplete, preflight conversion can differ, and fresh sale tests did not execute. |
| `POST roti_ropi_pos.api.v1.sales.quote_return` | Calculate remaining returnable quantities and a server-authoritative return quote. | **PARTIAL** | The operation exists, but the contract does not show the complete `return_quote` response wrapper. |
| `GET roti_ropi_pos.api.v1.sales.list` | List visible sales for cashier history. | **NO** | The query is not scoped to the current opening period. Status values are incomplete, history edge tests are missing, and pagination uses deprecated arguments. |
| `GET roti_ropi_pos.api.v1.sales.get` | Return sale or return detail for a visible POS Invoice. | **PARTIAL** | Normal sale detail is available. Reloaded returns lose the reason and use an inconsistent item projection. Status values are not fully defined. |
| `POST roti_ropi_pos.api.v1.sales.create_return` | Create and submit a POS Invoice return against an authorized source invoice. | **NO** | Expected ERPNext errors are unstable. Fresh return tests did not execute. Persisted receipt data and remarks do not preserve the documented contract. |
| `GET roti_ropi_pos.api.v1.closing.preview` | Calculate server-authoritative shift totals and expected payment amounts. | **PARTIAL** | The preview exists. Closing error codes and detail schemas are incomplete, and some profile error details omit the profile identity. |
| `POST roti_ropi_pos.api.v1.closing.submit` | Reserve, create, submit, and consolidate a closing with durable recovery phases. | **NO** | Phase commits invalidate the endpoint savepoint. Submission elevates to Administrator. A lost key can leave an outlet blocked indefinitely. |
| `GET roti_ropi_pos.api.v1.closing.status` | Poll the durable outcome of a known closing request. | **PARTIAL** | Recovery information exists only when Android retains the original key and request context. Error and retry details are not fully specified. |

### Contract conclusions

- **Request and response contract:** DTOs and stable envelopes exist for the main path. Several return, status, error-detail, and compatibility contracts remain incomplete.
- **Error codes:** Expected Mobile POS errors use a stable envelope. Sale and return core validation can bypass it. Closing and idempotency taxonomies are incomplete.
- **Retry safety:** Standard replay exists. Race loss, lock timeout, closing transaction boundaries, and lost-key recovery still violate deterministic retry handling.
- **Idempotency:** All mutations require a client key and use durable request records. Closing has extra phases, but its recovery requires the original key and body.
- **Server authority:** Profile, company, warehouse, price list, customer, price, stock, tax, payment, invoice, return, and closing values remain server-controlled.
- **Recovery information:** Closing status supports known requests. The API cannot adopt, cancel, or replace an abandoned closing when the original client key is lost.

## 4. Findings

## Critical

### C-1 — Equivalent Frappe routes bypass the Mobile POS Bearer boundary for Desk cashiers

- **File and function:** `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_api_scope`
- **Evidence:** The function applies client-bound Bearer checks only when the raw request path exactly matches `MOBILE_POS_PATHS`. `_is_mobile_only_account` fences only users without Desk access. Frappe also dispatches the same whitelisted method through `/api/v1/method/...`, `/api/v2/method/...`, suffix routes, and non-strict slash variants. Existing alternate-route tests cover a mobile-only cashier, while `test_desk_user_holding_cashier_role_is_not_scoped_to_mobile_api` preserves the Desk exemption.
- **Business impact:** A Desk cookie or credential can reach cashier operations without a token bound to the configured Mobile POS OAuth Client.
- **Android impact:** The documented OAuth-only trust boundary is false for all 16 endpoints. This blocks production launch.
- **Recommended direction:** Enforce authorization from the resolved Mobile POS method identity, not one raw path string. Deny all equivalent dispatch forms unless the request has the required client-bound Bearer token. Add Desk-plus-cashier alias tests.

## Important

### I-1 — Closing commits invalidate the common endpoint savepoint

- **Status: RESOLVED (P0-4, commit `fix: keep closing responses correct across durable commits`).** The savepoint is now retired explicitly rather than named after it is gone. `responses.commit_durable_phase` marks the request before committing, and both `_rollback_to` and the `release_savepoint` in `api_endpoint`'s `finally` skip the savepoint once that mark is set; the mark is per-request and restored on exit, so one endpoint's durable commit cannot disarm the next endpoint's rollback. Measured on `mobile-pos-regression.localhost`: after a commit, MariaDB answers both `ROLLBACK TO SAVEPOINT` and `RELEASE SAVEPOINT` with `OperationalError(1305, 'SAVEPOINT ... does not exist')`, and the previous code hit exactly that (recorded before the fix as `('rollback-FAILED', 'mobile_pos_9eff6256e2', "OperationalError(1305, ...)")` plus a failing release). Post-commit failures now resolve from persisted state: a submit failure once the Closing Entry is durable returns that Closing rather than an error, a retry with the same key replays the same Closing, and no second Closing Entry is created. A consolidation failure on the deferred (`>= 10` invoice) path leaves the Closing `failed` for `v1.closing.status` instead of destroying the already-committed submission envelope. Breadth is bounded: with nothing durable, an unrecognised failure still propagates as a server error, and a known validation failure still returns the documented rejection. Evidence: `test_closing` `Ran 58 tests OK`, `test_api_foundation` `Ran 17 tests OK`. Mutations, each reverted: forcing `_savepoint_survives()` to `True` fails both savepoint gates, and dropping the `_durable_closing` guard fails `test_unknown_submit_failure_without_a_durable_entry_stays_a_server_error` with `RuntimeError not raised`.
- **File and function:** `roti_ropi_pos/mobile_pos/closing.py:execute_closing_submit`
- **Evidence:** `responses.py:api_endpoint` creates one savepoint and rolls expected errors back to it. Closing commits the `Reserved`, `DraftCreated`, and `SubmitStarted` phases. Frappe commit ends the transaction and invalidates that savepoint. Later recovery can still raise `REQUEST_IN_PROGRESS` or `IDEMPOTENCY_INVARIANT`.
- **Business impact:** Response handling can mask the correct durable closing state with a database savepoint error.
- **Android impact:** Android cannot tell whether it should retry, poll, or request manager help after the closing already progressed.
- **Recommended direction:** Give closing a transaction boundary that does not reuse a savepoint across commits. Preserve the stable business error after each durable phase.

### I-2 — Closing submission and consolidation run as Administrator

- **Status: RESOLVED (P0-3, commit `fix: run closing consolidation under cashier authority`).** Both `frappe.set_user("Administrator")` blocks are gone; `grep set_user` over production code returns nothing. Consolidation now runs as the requesting cashier because the role carries an owner-scoped `Sales Invoice` grant (`create`, `write`, `submit`, `if_owner = 1`) added to `roti_ropi_pos/fixtures/custom_docperm.json` — the exact permission the ERPNext chain needs, measured rather than assumed: `POSInvoiceMergeLog.process_merging_into_sales_invoice` calls `sales_invoice.save()`/`.submit()` without `ignore_permissions`, and a grant without `write` still failed. Evidence on `mobile-pos-regression.localhost`: `test_closing` `Ran 52 tests OK`; the consolidated Sales Invoice is owned by the cashier on the synchronous and the 10-invoice queued path; cashier B is denied read/write/submit/cancel/delete on cashier A's consolidated invoice; a missing grant still surfaces deterministically as `INVALID_REQUEST` with `details.reason = PermissionError`. Mutation: setting `if_owner = 0` grants a non-owner write and submit, which `test_cashier_sales_invoice_grant_is_owner_scoped_not_broad` fails on.
- **File and function:** `roti_ropi_pos/mobile_pos/closing.py:_submit_persisted_closing`, `roti_ropi_pos/mobile_pos/closing.py:ensure_committed_closing_job`
- **Evidence:** Both paths call `frappe.set_user("Administrator")` around POS Closing Entry work. The endpoint already checks cashier create and submit permission. Project policy requires normal permissions for ERPNext business documents.
- **Business impact:** Closing hooks run with broader authority than the authenticated cashier. Permission failures can be hidden.
- **Android impact:** The API can report success for work the cashier could not perform under the documented authorization model.
- **Recommended direction:** Run closing under the authenticated cashier and the exact required DocType permissions. Keep service-level privilege limited to Mobile POS Request records.

### I-3 — An abandoned committed Closing Draft can block the outlet indefinitely

- **File and function:** `roti_ropi_pos/mobile_pos/closing.py:execute_closing_submit`
- **Evidence:** Closing commits the Draft reference and writes `POS Opening Entry.pos_closing_entry` before submit. The service rejects another Draft and reports `CLOSING_IN_PROGRESS`. `sessions.py:has_unresolved_closing` then disables all mutations. Recovery requires the original key and identical body. No mobile adopt, cancel, or replace operation exists.
- **Business impact:** A crash plus lost client state can stop sales, returns, closing, and reopening until a manager repairs the records in Desk.
- **Android impact:** Reinstallation, local-data loss, or a discarded pending mutation can strand a shift.
- **Recommended direction:** Define a server-authoritative lost-key recovery operation. It must identify the unresolved closing and provide safe adopt, resume, or manager-escalation behavior.

### I-4 — ERPNext sale and return validation errors escape the stable v1 envelope

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:submit_sale`, `roti_ropi_pos/mobile_pos/invoices.py:create_return`
- **Evidence:** Both functions call `insert()` and `submit()` without mapping expected ERPNext validation exceptions. ERPNext raises ordinary Frappe errors for stock, batch, serial, payment, opening, company, and related rules. `responses.py:api_endpoint` re-raises non-Mobile POS exceptions as native responses.
- **Business impact:** Deterministic business rejection can appear as an unknown framework error.
- **Android impact:** Android can retry a permanent rejection or show a generic failure without item-level recovery guidance.
- **Recommended direction:** Map expected ERPNext validation classes into documented stable codes, HTTP statuses, details, and retry flags. Preserve unknown exceptions as server failures.

### I-5 — A lost idempotency race can return `IDEMPOTENCY_INVARIANT` when retry is safe

- **File and function:** `roti_ropi_pos/mobile_pos/idempotency.py:_resolve_committed_request`
- **Evidence:** After a duplicate insert, the resolver performs five locking reads. If the winning transaction rolls back, all reads can correctly find no row. The function then raises `IDEMPOTENCY_INVARIANT` with HTTP 500.
- **Business impact:** A normal concurrency result becomes an internal invariant failure.
- **Android impact:** Android sees a non-retryable-looking server failure although the same key is safe to retry.
- **Recommended direction:** Classify the disappeared winner as a retry-safe outcome. Return a documented retryable response or retry reservation within a bounded policy.

### I-6 — Lock-wait timeout is not handled by the idempotency conflict resolver

- **File and function:** `roti_ropi_pos/mobile_pos/idempotency.py:_resolve_committed_request`
- **Evidence:** The contended locking read catches `frappe.QueryDeadlockError` but not `frappe.QueryTimeoutError`.
- **Business impact:** A duplicate request behind a slow invoice transaction can escape through the native framework path.
- **Android impact:** The response lacks retryable `REQUEST_IN_PROGRESS` guidance for the pending-mutation state machine.
- **Recommended direction:** Map lock-wait timeout to the same documented retry contract as other in-progress contention outcomes.

### I-7 — Sale history does not implement current-session scope

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:list_sales`
- **Evidence:** Product requirement FR-7 requires the cashier history for the current session. The query filters owner, POS Profile, and Company, but not the current Opening period or reference.
- **Business impact:** A cashier sees all of their outlet invoices instead of only the active shift.
- **Android impact:** Android cannot implement FR-7 because the response has no reliable current-Opening scope field.
- **Recommended direction:** Bind history to the authorized current Opening using a server-owned relation or period rule. Document the exact boundary and empty-session behavior.

### I-8 — `meta.server_time` can carry the wrong UTC offset

- **File and function:** `roti_ropi_pos/mobile_pos/responses.py:success`, `roti_ropi_pos/mobile_pos/responses.py:api_endpoint`
- **Evidence:** Both paths call `frappe.utils.now_datetime().astimezone().isoformat()`. Frappe returns a naive wall-clock datetime in the site timezone. `astimezone()` then attaches the container timezone. Session timestamp code already uses the configured site timezone correctly.
- **Business impact:** Metadata can represent a false instant.
- **Android impact:** Clock-skew checks, elapsed-time display, logs, and recovery diagnostics can be wrong by the site offset.
- **Recommended direction:** Attach the configured site timezone before ISO serialization. Use one timestamp helper for success and expected-error envelopes.

### I-9 — Catalog search work grows with the full Item master

- **File and function:** `roti_ropi_pos/mobile_pos/catalog.py:_visible_item_groups`, `roti_ropi_pos/mobile_pos/catalog.py:search_items`
- **Evidence:** Every search loads permission-aware Item names and groups without a limit. The service then filters ERPNext result pages through that full projection. ERPNext also calculates stock, price, and UOM data per result row.
- **Business impact:** Catalog latency and worker memory grow with all Items, including Items outside the requested page.
- **Android impact:** Search keystrokes can slow down or time out as the catalog grows.
- **Recommended direction:** Apply authorization and item-group filtering in bounded database queries before expensive ERPNext row calculations.

### I-10 — Customer text search has unbounded high-offset query amplification

- **File and function:** `roti_ropi_pos/mobile_pos/customers.py:search_customers`
- **Evidence:** The function sets each of three `LIKE` query limits to `start + limit + 1`. It merges and sorts all returned rows in memory. `start` has no maximum.
- **Business impact:** A large client offset causes three large database reads and a large in-memory merge.
- **Android impact:** Deep or malformed pagination can cause long waits and server pressure.
- **Recommended direction:** Add a documented offset bound or use bounded keyset pagination while preserving permission checks and deterministic order.

### I-11 — A reloaded return loses its reason and changes its item contract

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:create_return`, `roti_ropi_pos/mobile_pos/invoices.py:get_sale`, `roti_ropi_pos/mobile_pos/invoices.py:sale_detail`
- **Evidence:** The immediate response passes the request reason directly into `sale_detail`. A later read does not load a persisted reason and returns `return_reason: null`. For returns, `sale_detail` also replaces rows that contain `returnability` with `return_item_dto` rows.
- **Business impact:** A reprinted receipt or later audit view cannot reproduce the original return explanation and item shape.
- **Android impact:** Immediate and reloaded receipts do not have one stable DTO or the same useful data.
- **Recommended direction:** Persist the return reason in the approved transaction boundary. Make immediate and reloaded return details use one documented item projection.

### I-12 — The API has no deployment or minimum-client compatibility signal

- **File and function:** `roti_ropi_pos/api/v1/bootstrap.py:get`, `roti_ropi_pos/mobile_pos/responses.py:success`
- **Evidence:** Metadata exposes only hardcoded `api_version = "v1"`. Bootstrap has no backend build, deployment revision, contract revision, or minimum supported Android version.
- **Business impact:** A partial or incompatible deployment cannot fail early with a clear compatibility decision.
- **Android impact:** Android discovers incompatibility only after a parse failure or missing behavior.
- **Recommended direction:** Add a documented compatibility projection to bootstrap. Keep it additive within v1 and define client gating rules.

### I-13 — Missing OAuth client configuration lacks a configuration diagnosis

- **File and function:** `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_oauth_request`, `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_api_scope`
- **Evidence:** An empty `mobile_pos_oauth_client_id` disables Mobile POS client detection for OAuth policy selection. The data plane still compares every token client to the empty value and fails closed.
- **Business impact:** One deployment mistake makes the API unusable without a targeted configuration error.
- **Android impact:** Login or first use appears as a generic authentication failure instead of a backend configuration problem.
- **Recommended direction:** Validate the setting at deployment or startup and expose a safe, stable configuration failure without leaking secrets.

### I-14 — The permission policy omits a runtime-required grant

- **File and function:** `erpnext/stock/serial_batch_bundle.py:make_serial_and_batch_bundle`, `roti_ropi_pos/fixtures/custom_docperm.json:<Serial and Batch Bundle fixture>`
- **Evidence:** The exact policy table omits Serial and Batch Bundle. The fixture grants cashier read, create, write, and submit. ERPNext saves and submits that document without `ignore_permissions=True`, so batch and serial POS submission needs the grant.
- **Business impact:** A policy-driven permission cleanup can break serialized or batched sales.
- **Android impact:** Checkout can fail after a permission sync that appears compliant with project rules.
- **Recommended direction:** Add the exact required Serial and Batch Bundle permissions to the governing policy. Keep source-contract tests for the ERPNext permission path.

### I-15 — Stable error taxonomy and detail schemas are incomplete

- **File and function:** `roti_ropi_pos/mobile_pos/idempotency.py:_resolve_committed_request`, `roti_ropi_pos/mobile_pos/closing.py:execute_closing_submit`
- **Evidence:** Runtime emits `IDEMPOTENCY_INVARIANT`, but the main contract table omits it. Closing emits multiple validation, progress, and state codes without complete HTTP and `details` schemas. The table also lists codes that runtime does not use.
- **Business impact:** Backend and client teams cannot identify the intended stable contract.
- **Android impact:** Strict error enums and detail parsers can fail. Retry and user-action rules remain incomplete.
- **Recommended direction:** Reconcile runtime and documentation. Define every reachable code, HTTP status, details object, retry flag, and Android action. Remove or reserve unused codes explicitly.

### I-16 — Fresh core money-path verification is incomplete

- **File and function:** `roti_ropi_pos/tests/test_sale_task9.py:<sale suite>`, `roti_ropi_pos/tests/test_return_task10.py:<return suite>`
- **Evidence:** Ten modules passed 219 tests. Sale and return suites failed during discovery because ERPNext fixture setup raised `Duplicate entry 'Standard Buying' for key 'PRIMARY'`. No verified integration test races twenty identical real sale requests. No test verifies stable mapping of an expected ERPNext validation error.
- **Business impact:** The highest-value accounting mutation suites lack fresh executable evidence in this environment.
- **Android impact:** Sale and return cannot receive a release-ready declaration.
- **Recommended direction:** Repair the isolated test baseline without changing ERPNext core. Run both suites. Add one real high-contention sale test and expected validation-mapping tests.

### I-17 — Large modules and copied ERPNext behavior increase upgrade risk

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:<module>`, `roti_ropi_pos/mobile_pos/closing.py:<module>`
- **Evidence:** `invoices.py` has 1,004 lines and mixes quote, sale, stock, payment, history, return, and DTO work. `closing.py` has 620 lines and mixes recovery, transaction control, aggregation, DTOs, and jobs. Other large modules, copied ERPNext calculations, internal imports, and controller overrides add more coupling.
- **Business impact:** ERPNext upgrades can change calculations or lifecycle behavior on only one side of the copied boundary.
- **Android impact:** Totals, closing, or receipt fields can regress without an API version change.
- **Recommended direction:** Split only along stable responsibilities when making related changes. Replace copied behavior with supported ERPNext contracts where available. Protect remaining boundaries with source-contract and behavior tests.

## Minor

### M-1 — Return remarks normalization changes existing audit text

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:create_return`
- **Evidence:** The function splits source and mapped remarks into lines, removes blanks, and removes duplicate lines before adding the Mobile POS reason. The contract requires preserving existing remarks and adding exactly one newline.
- **Business impact:** Persisted remarks can lose formatting or repeated lines.
- **Android impact:** Receipt and audit text can change unexpectedly.
- **Recommended direction:** Preserve existing remarks byte-for-byte where the contract requires it. Append one normalized separator and one reason.

### M-2 — Return rows discard the computed `returnability` projection

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:sale_detail`
- **Evidence:** The function builds item rows with `returnability`, then replaces all rows with `return_item_dto` rows for a return document.
- **Business impact:** Return detail does not use the normal sale item projection.
- **Android impact:** Kotlin DTO handling needs an undocumented return-specific exception or nullable fields.
- **Recommended direction:** Define one shared item shape or an explicit return item type. Make immediate and reloaded responses match it.

### M-3 — Preflight stock validation uses a different conversion-factor source

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:_validate_total_stock`
- **Evidence:** Preflight uses ERPNext `get_conversion_factor`, which can fall back to `1.0`. `_append_items` gets the effective factor through `quote_item`, including global UOM conversion behavior.
- **Business impact:** Preflight can undercount stock when conversion exists only in the global UOM table. ERPNext submit can reject later.
- **Android impact:** Android can receive a native submit error instead of the expected `INSUFFICIENT_STOCK` preflight error.
- **Recommended direction:** Reuse the same authoritative conversion result for quote construction and stock preflight.

### M-4 — Shared `reject_request` hardcodes the Closing reference type

- **File and function:** `roti_ropi_pos/mobile_pos/idempotency.py:reject_request`
- **Evidence:** The function assigns `reference_doctype = "POS Closing Entry"` whenever a reference name exists. Closing is the only current caller.
- **Business impact:** Future reuse can store a false audit reference.
- **Android impact:** No current Android failure is proven.
- **Recommended direction:** Keep the helper closing-specific or require the caller to supply a validated reference DocType before reuse.

### M-5 — Catalog pagination can report false-positive `has_more`

- **File and function:** `roti_ropi_pos/mobile_pos/catalog.py:search_items`
- **Evidence:** The function can set `core_may_have_more` after exhausting a fixed 11-page post-filter loop even when no later authorized item exists. It rejects `start > 1000`, but the contract omits this cap.
- **Business impact:** Internal search limits leak into pagination state.
- **Android impact:** Android can request one empty extra page or receive an undocumented deep-page error.
- **Recommended direction:** Derive `has_more` from an authorized extra row. Document any supported pagination ceiling.

### M-6 — Sale read status values are not fully defined

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:sale_summary`
- **Evidence:** The function lowercases ERPNext POS Invoice status values and maps `Credit Note Issued` to `paid`. ERPNext can produce more statuses than the contract lists.
- **Business impact:** Backend lifecycle values and product labels can drift.
- **Android impact:** A strict status enum can reject or hide a valid history row.
- **Recommended direction:** Publish a closed v1 mapping with a documented unknown fallback or normalize all supported ERPNext states server-side.

### M-7 — Some `PROFILE_CONFIGURATION_INVALID` details violate the schema

- **File and function:** `roti_ropi_pos/mobile_pos/validation.py:sale_payment_amount_policy`, `roti_ropi_pos/mobile_pos/validation.py:closing_counted_amount_policy`
- **Evidence:** These paths can emit `PROFILE_CONFIGURATION_INVALID` without the required `pos_profile`. Other paths can use an empty value.
- **Business impact:** Outlet configuration diagnostics can omit the affected profile.
- **Android impact:** Android cannot direct support staff to the failing outlet from the error.
- **Recommended direction:** Make all emitters use one detail builder that always includes a non-empty authorized profile identity.

### M-8 — `sales.quote_return` lacks an explicit response wrapper contract

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:build_return_quote`
- **Evidence:** Runtime returns fields under `return_quote`. The contract describes the fields but does not show the complete wrapper.
- **Business impact:** Backend and Android teams can choose different DTO roots.
- **Android impact:** Android cannot implement the endpoint from the contract alone.
- **Recommended direction:** Add the complete success envelope and `data.return_quote` example to the v1 contract.

### M-9 — `sales.quote_cart` documentation omits reachable item errors

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:build_sale_quote`
- **Evidence:** The shared item builder can emit `INSUFFICIENT_STOCK`, `INVALID_BATCH`, and `INVALID_SERIAL_NUMBER`. The endpoint section does not list them.
- **Business impact:** Quote failures lack a complete cashier response model.
- **Android impact:** Android can show a generic failure instead of item correction UI.
- **Recommended direction:** Add each reachable code, details schema, HTTP status, retry flag, and client action to the endpoint section.

### M-10 — Request ID format and log correlation are ambiguous

- **File and function:** `roti_ropi_pos/mobile_pos/responses.py:success`
- **Evidence:** Runtime generates a random 26-character Frappe hash. The contract example resembles a ULID but defines no format. Evidence does not prove that the value maps to a framework request or server log identifier.
- **Business impact:** Support cannot reliably use a cashier screenshot to find one server request.
- **Android impact:** Android must treat the value as opaque and cannot assume ULID parsing or ordering.
- **Recommended direction:** Define the value as opaque or connect it to a documented server log correlation field. Make examples match the format.

### M-11 — No cashier token revoke or logout contract exists

- **File and function:** `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_oauth_request`
- **Evidence:** The allowed OAuth inventory includes login, authorize, approve, and token exchange. The v1 endpoint surface has no logout or revoke operation.
- **Business impact:** Device logout cannot request immediate token revocation through this facade.
- **Android impact:** Logout can clear local tokens but cannot prove server-side revocation.
- **Recommended direction:** Define the required logout threat model. If immediate revocation is required, add a supported public-client revoke contract. Otherwise document expiry and manager disablement behavior.

### M-12 — Closing performs a redundant consolidation scheduling check

- **File and function:** `roti_ropi_pos/overrides/pos_closing_entry.py:MobilePOSClosingEntry.on_submit`, `roti_ropi_pos/mobile_pos/closing.py:_complete_from_persisted`
- **Evidence:** The override registers `ensure_committed_closing_job` after commit. Recovery calls the same helper again for `Queued`. ERPNext uses a deterministic job ID, so duplicate enqueue is normally suppressed.
- **Business impact:** The recovery boundary is harder to reason about, although current deduplication prevents duplicate consolidation.
- **Android impact:** No current failure is proven.
- **Recommended direction:** Keep one scheduling owner after transaction behavior is fixed. Retain deterministic job deduplication as defense.

### M-13 — Mobile POS documents contain obsolete ownership and implementation state

- **File and function:** `docs/mobile-pos/architecture.md:<current-state section>`, `docs/mobile-pos/integration-boundaries.md:<required-apps section>`
- **Evidence:** Architecture still says no Mobile POS API exists. Integration boundaries omit `selling_additional`. Product documents still assign generic selling ownership to `bakery_manufacturing`. Runtime requires ERPNext, `stock_additional`, and `selling_additional`.
- **Business impact:** A maintainer can deploy the wrong dependencies or change the wrong app.
- **Android impact:** Handoff documents can misstate ownership for pricing and walk-in behavior.
- **Recommended direction:** Update current-state and ownership documents to match runtime hooks and the approved app boundaries.

### M-14 — History and configuration edge cases lack direct tests

- **File and function:** `roti_ropi_pos/tests:<history and payment-policy coverage>`
- **Evidence:** No direct verified tests cover every `sales.list` status filter, `has_more`, and offset boundary. No direct test covers a Customer currency that differs from POS Profile currency before payment-scale validation.
- **Business impact:** History pagination, status projection, and currency policy can regress unnoticed.
- **Android impact:** Less common outlet configurations can fail during paging or payment validation.
- **Recommended direction:** Add focused tests for status filters, pagination boundaries, and customer/profile currency mismatch.

### M-15 — `sales.list` uses deprecated Frappe pagination argument names

- **File and function:** `roti_ropi_pos/mobile_pos/invoices.py:list_sales`
- **Evidence:** The function passes `start` and `page_length` to `frappe.get_list`. Fresh tests emitted the Frappe v17 deprecation warning, and installed query code marks these aliases for removal.
- **Business impact:** A future Frappe upgrade can break history pagination after the compatibility shim disappears.
- **Android impact:** History can repeat page zero or fail after an upgrade.
- **Recommended direction:** Use the current Frappe pagination argument names and keep a focused paging test.

## 5. Missing Business Capabilities

### Capabilities that do not exist

| Capability | Evidence | Priority |
| --- | --- | --- |
| Lost-key closing recovery | Android cannot adopt, resume, cancel, or replace an unresolved committed Closing Draft without the original key and body. | P0 |
| Current-session sale history | `sales.list` has no current Opening relation or period boundary required by FR-7. | P1 |
| Backend and minimum-client compatibility signal | Bootstrap has no deployment revision, contract revision, or minimum Android version. | P1 |
| Mobile POS configuration diagnosis | An empty OAuth client setting fails closed without a targeted configuration response. | P1 |
| Cashier token revoke or logout | The facade has no revoke or logout operation. | P2 unless the threat model requires immediate revocation |

### Implementation defects

- Authentication depends on exact raw paths and permits equivalent-route bypass for Desk cashiers.
- Closing commits conflict with the common savepoint and runs business operations as Administrator.
- Sale and return submission do not map expected ERPNext validation errors.
- Idempotency conflict resolution mishandles a rolled-back winner and lock-wait timeout.
- Response time serialization can attach the wrong timezone offset.
- Catalog and customer search have unbounded or full-master work.
- Reloaded returns lose the return reason and change item shape.
- Return remarks, stock conversion preflight, pagination state, profile details, and helper typing have smaller defects.

### Contract and documentation gaps

- Error codes, HTTP statuses, details schemas, retry flags, and Android actions are incomplete.
- Return quote wrapper, quote-cart item errors, sale status values, catalog offset cap, and request ID semantics are incomplete.
- The exact permission policy omits Serial and Batch Bundle rights that runtime needs.
- Architecture, required-app, and ownership documents do not match current runtime state.

### Test gaps

- Fresh sale and return suites did not execute because ERPNext fixture setup failed during discovery.
- No verified real sale test races twenty identical requests through the invoice transaction.
- No verified test maps an expected ERPNext sale or return validation error into the stable v1 envelope.
- History filters, pagination edges, and customer/profile currency mismatch lack direct focused coverage.
- IMIN hardware testing remains pending.

## 6. Android Integration Decision

**May Android start integration now? Yes, but only for non-production contract development. No production rollout or cashier pilot may start.**

Android can start these limited flows against a controlled development site:

- OAuth Authorization Code with PKCE S256 through the canonical routes.
- `bootstrap.get` and `sessions.current` DTO integration.
- `customers.search` with normal early-page limits.
- `catalog.search`, `catalog.scan`, and `catalog.quote_item` with bounded paging.
- `sales.quote_cart` with tolerant handling for undocumented item-level quote errors.

Android must not treat these flows as production-secure until C-1 is fixed. It must not freeze a strict global error enum until the v1 taxonomy is reconciled.

Defer these flows as release contracts:

- `sessions.open` because contention responses are not stable.
- `sales.submit` because core errors, idempotency edges, and fresh verification are incomplete.
- `sales.list` because it violates current-session scope.
- Return receipt and `sales.create_return` because error mapping, persistence, DTO shape, and fresh verification are incomplete.
- `closing.submit` because transaction, privilege, and lost-key recovery defects can strand the outlet.

Minimum blockers before a production-capable Android build:

1. Close all equivalent-route authentication bypasses for every cashier account type.
2. Remove Administrator elevation from closing and define valid transaction boundaries across durable commits.
3. Add lost-key recovery for unresolved Closing Drafts.
4. Map expected sale and return validation failures into the stable v1 contract.
5. Make idempotency rollback races and lock timeouts return deterministic retry guidance.
6. Reconcile stable error codes, detail schemas, retry flags, and Android actions.
7. Run the blocked sale and return suites, then add the missing contention and validation-mapping tests.

The current-session history gap must also close before a full MVP cashier pilot that claims FR-7 compliance.

## 7. Remediation Plan

### P0 — Security, data, and recovery blockers

Dependencies matter. Complete these items in order.

1. **Freeze authentication semantics.** Fix C-1 first. Enforce the client-bound Bearer check by resolved endpoint identity across v1, v2, suffix, slash, and legacy dispatch forms.
2. **Freeze mutation error and retry semantics.** Reconcile I-15 before Android freezes enums. Define expected validation, in-progress, invariant, lock-timeout, and closing recovery responses.
3. **Repair standard idempotency contention.** Fix I-5 and I-6 against the approved retry contract.
4. **Repair closing authorization and transaction boundaries.** Fix I-1 and I-2 before changing recovery behavior. Do not keep a savepoint across a commit. Do not run ERPNext documents as Administrator.
5. **Add lost-key closing recovery.** Resolve I-3 after the closing state transitions and transaction boundaries are explicit.
6. **Map ERPNext sale and return failures.** Resolve I-4 without converting unknown exceptions into business errors.
7. **Restore executable money-path evidence.** Resolve I-16 after the contracts and implementation changes. Run sale and return suites. Add real contention and validation-mapping coverage.

### P1 — Required before cashier pilot

1. **Implement current-session history.** Resolve I-7 and define the Opening boundary first.
2. **Stabilize return receipts.** Resolve I-11, M-1, and M-2 with one persisted reason and one item contract.
3. **Align stock preflight.** Resolve M-3 by using the same conversion source as the authoritative quote path.
4. **Fix global response time.** Resolve I-8 with the configured site timezone.
5. **Bound read performance.** Resolve I-9 and I-10. Then correct catalog `has_more` and document its page limit from M-5.
6. **Add compatibility and configuration signals.** Resolve I-12 and I-13 in bootstrap and deployment checks.
7. **Align permissions and ownership documents.** Resolve I-14 and M-13 before fixture or deployment work.
8. **Complete endpoint contracts.** Resolve M-6 through M-10. Include status, profile details, wrappers, reachable errors, and request correlation.
9. **Add focused edge tests.** Resolve M-14 for history and currency-policy behavior.

### P2 — Improvement

1. **Reduce upgrade coupling when related code changes.** Address I-17 by separating stable responsibilities and reducing copied ERPNext behavior.
2. **Clarify rejection helper ownership.** Address M-4 before another operation reuses `reject_request`.
3. **Define logout policy.** Address M-11 according to the approved token revocation threat model.
4. **Remove redundant closing scheduling.** Address M-12 after P0 closing recovery work establishes one scheduling owner.
5. **Replace deprecated pagination aliases.** Address M-15 before the Frappe version that removes compatibility aliases.
