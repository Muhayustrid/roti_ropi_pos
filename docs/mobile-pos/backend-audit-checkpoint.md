# Backend Audit Checkpoint

**Status:** Read-only audit complete. Findings below have been checked against current application code, installed Frappe and ERPNext source, contract documents, or fresh tests. This file is a handoff checkpoint, not the final audit report.

## Executive provisional verdict

- **Business fit:** The facade covers the required MVP flow from authentication through closing. ERPNext remains authoritative for Customer, POS Profile, Opening, catalog, pricing, taxes, payments, POS Invoice, returns, stock, and accounting. Android remains a cashier client rather than an accounting engine.
- **Android readiness:** **Not ready for production integration.** The 16-endpoint surface is present, but one authentication-boundary defect and several recovery and contract defects remain release blockers.
- **Security:** Profile, Company, cashier, source invoice, Opening, and Closing isolation are generally strong. The raw-path bearer gate can be bypassed through equivalent Frappe route aliases by a Desk account that also holds `Mobile POS Cashier`.
- **Reliability and recovery:** Standard mutation idempotency is strong on the normal path. Closing has durable recovery phases, but its explicit commits conflict with the common savepoint wrapper and can leave an abandoned Draft that blocks the outlet.
- **Maintainability:** Ownership boundaries are mostly correct in runtime code. Large mixed-responsibility modules, copied ERPNext calculations, controller overrides, and direct imports from ERPNext internals raise upgrade risk.
- **Provisional release decision:** Do not start production Android integration until the Critical finding and minimum Important recovery, error-contract, and verification blockers are resolved.

## Critical findings

### C-1 — Equivalent Frappe routes bypass the Mobile POS bearer boundary for Desk cashiers

- **Type:** Implementation defect, security.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_api_scope` applies the client-bound Bearer check only when `frappe.request.path` exactly matches `MOBILE_POS_PATHS`.
  - `roti_ropi_pos/mobile_pos/auth_hook.py:_is_mobile_only_account` applies the fallback route fence only to accounts without Desk access.
  - Installed `frappe/api/__init__.py:API_URL_MAP` mounts v1 rules under both `/api` and `/api/v1`, with non-strict slashes.
  - Installed `frappe/api/v1.py:handle_rpc_call` truncates a method path at the first `/`.
  - Installed `frappe/api/v2.py:url_rules` can dispatch the same whitelisted method through `/api/v2/method/<method>`.
  - `roti_ropi_pos/tests/test_authentication.py:test_desk_user_holding_cashier_role_is_not_scoped_to_mobile_api` explicitly preserves the Desk exemption. Existing alternate-route denial tests exercise a mobile-only cashier, not a Desk cashier with the role.
- **Failure case:** A Desk session for a user who also holds `Mobile POS Cashier` calls the same whitelisted v1 function through `/api/v1/method/...`, `/api/v2/method/...`, or a suffix route. The request misses the exact-path Bearer check and the account misses the mobile-only fallback fence.
- **Business impact:** The facade no longer has one enforceable authentication boundary. A Desk credential or cookie can reach cashier operations without a token bound to the configured Mobile POS OAuth Client.
- **Android impact:** The documented OAuth-only trust model is false. This is a production launch blocker even though downstream profile and document scope checks still limit horizontal access.
- **Affected endpoints and flows:** Authentication and authorization, plus all 16 v1 endpoints.

## Important findings

### I-1 — Closing commits invalidate the common endpoint savepoint

- **Type:** Implementation defect, recovery.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/responses.py:api_endpoint` creates one savepoint and rolls back to it for every `MobilePOSAPIError`.
  - `roti_ropi_pos/mobile_pos/closing.py:execute_closing_submit` commits the `Reserved`, `DraftCreated`, and `SubmitStarted` phases.
  - Installed `frappe/database/database.py:commit` runs `COMMIT` and starts a new transaction. The earlier savepoint no longer exists.
  - `roti_ropi_pos/mobile_pos/closing.py:_complete_from_persisted` can still raise `REQUEST_IN_PROGRESS` or `IDEMPOTENCY_INVARIANT` after those commits.
- **Business impact:** The durable closing state can be correct while response handling fails with a database savepoint error. The original stable business error can be masked.
- **Android impact:** Android can receive an unexpected native server failure after a closing has already progressed. It cannot safely distinguish retry, poll, or manager intervention from the response alone.
- **Affected endpoints and flows:** `POST closing.submit`, closing recovery, idempotent replay.

### I-2 — Closing submits and consolidation run as Administrator

- **Type:** Implementation defect, authorization and governance.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/closing.py:_submit_persisted_closing` calls `frappe.set_user("Administrator")` around `POS Closing Entry.submit()`.
  - `roti_ropi_pos/mobile_pos/closing.py:ensure_committed_closing_job` does the same around ERPNext consolidation.
  - `AGENTS.md` permits normal permissions for ERPNext documents and names `Mobile POS Request` as the sole `ignore_permissions=True` exception.
  - `roti_ropi_pos/api/v1/closing.py:submit` already checks cashier create and submit permission before entering the recovery executor.
- **Business impact:** Every hook called by Closing submit or consolidation executes with broader roles and user permissions than the cashier. Permission failures are masked rather than surfaced.
- **Android impact:** The API can report success for an operation the authenticated cashier was not authorized to complete under the documented model.
- **Affected endpoints and flows:** `POST closing.submit`, queued closing consolidation.

### I-3 — An abandoned committed Closing Draft can block the outlet indefinitely

- **Type:** Missing business capability, recovery.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/closing.py:execute_closing_submit` commits the Draft reference and writes `POS Opening Entry.pos_closing_entry` before submit.
  - `roti_ropi_pos/mobile_pos/closing.py:_create_closing_draft` rejects an Opening that already has that link.
  - `roti_ropi_pos/mobile_pos/closing.py:_raise_closing_unavailable` returns `CLOSING_IN_PROGRESS` for the linked Draft.
  - `roti_ropi_pos/mobile_pos/sessions.py:has_unresolved_closing` disables all cashier mutations.
  - Recovery adopts the request only when Android retains and reuses the original key and identical body. No mobile adopt, cancel, or replace operation exists.
- **Business impact:** A process crash plus a lost client key can stop sales, returns, closing, and reopening until a manager repairs state in Desk.
- **Android impact:** Android must retain the closing key and body indefinitely. Reinstall, local-data loss, or a discarded pending mutation can strand the shift.
- **Affected endpoints and flows:** `POST closing.submit`, `GET sessions.current`, `GET bootstrap.get`, all mutation capabilities.

### I-4 — ERPNext sale and return validation errors escape the stable v1 envelope

- **Type:** Implementation defect, API contract.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/invoices.py:submit_sale` and `create_return` call `insert()` and `submit()` without mapping expected ERPNext validation exceptions.
  - Installed `erpnext/accounts/doctype/pos_invoice/pos_invoice.py:POSInvoice.validate` raises ordinary Frappe validation errors for stock, batch, serial, payment, Opening, Company, and other business rules.
  - `roti_ropi_pos/mobile_pos/responses.py:api_endpoint` re-raises every non-`MobilePOSAPIError` as a native Frappe response.
  - `roti_ropi_pos/mobile_pos/closing.py:_KNOWN_SUBMIT_ERRORS` proves the Closing path already recognizes this class of expected core failures.
- **Business impact:** A deterministic business rejection can appear as a framework error instead of an actionable stock, batch, serial, payment, or request error.
- **Android impact:** Android can retry a permanently invalid mutation or show a generic server failure. Same-key recovery guidance becomes ambiguous.
- **Affected endpoints and flows:** `POST sales.submit`, `POST sales.create_return`, payment, stock, batch, serial, and return submission.

### I-5 — A lost idempotency race can return `IDEMPOTENCY_INVARIANT` when retry is safe

- **Type:** Implementation defect, idempotency.
- **Evidence:** `roti_ropi_pos/mobile_pos/idempotency.py:_resolve_committed_request` performs five locking reads after a duplicate insert. If the winning transaction rolls back, every read can correctly return no row and the function raises `IDEMPOTENCY_INVARIANT` HTTP 500.
- **Business impact:** A normal concurrency outcome is classified as an internal invariant failure.
- **Android impact:** Android receives a non-retryable-looking server error although the same mutation key is safe to retry.
- **Affected endpoints and flows:** `POST sessions.open`, `POST sales.submit`, `POST sales.create_return`; concurrent same-key retry.

### I-6 — Lock-wait timeout is not handled in the idempotency conflict resolver

- **Type:** Implementation defect, idempotency.
- **Evidence:** `roti_ropi_pos/mobile_pos/idempotency.py:_resolve_committed_request` catches `frappe.QueryDeadlockError` but not `frappe.QueryTimeoutError` around the contended `SELECT ... FOR UPDATE`.
- **Business impact:** A duplicate request that waits behind a slow invoice transaction can fail through the native framework path.
- **Android impact:** The response does not carry retryable `REQUEST_IN_PROGRESS`, so the pending-mutation state machine cannot follow the documented rule.
- **Affected endpoints and flows:** All standard idempotent mutations under concurrent retry.

### I-7 — Sale history does not implement the product requirement for current-session scope

- **Type:** Missing business capability and documentation conflict.
- **Evidence:**
  - `docs/mobile-pos/product-requirements.md:FR-7` requires history scoped to the cashier's current session.
  - `roti_ropi_pos/mobile_pos/invoices.py:list_sales` filters by owner, POS Profile, and Company only. It does not bind results to the current Opening period or Opening reference.
  - Ordering is deterministic: `posting_date desc, posting_time desc, name desc`.
- **Business impact:** A cashier sees all of their historical invoices for the outlet, not only the active shift.
- **Android impact:** Android cannot meet FR-7 from the current response and has no server field that reliably identifies the active Opening scope.
- **Affected endpoints and flows:** `GET sales.list`, sale history, shift reconciliation UX.

### I-8 — `meta.server_time` can carry the wrong UTC offset

- **Type:** Implementation defect, API contract.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/responses.py:success` and `api_endpoint` call `frappe.utils.now_datetime().astimezone().isoformat()`.
  - Installed `frappe/utils/data.py:now_datetime` returns a naive wall-clock datetime already converted to the site timezone.
  - Calling `astimezone()` on that naive value attaches the container timezone, not the site timezone.
  - `roti_ropi_pos/mobile_pos/sessions.py:_iso` separately attaches `ZoneInfo(get_system_timezone())` correctly for Opening timestamps.
- **Business impact:** Response metadata can describe a site-local wall clock with a container offset, producing a false instant.
- **Android impact:** Clock-skew checks, elapsed-time displays, logs, and recovery diagnostics can be wrong by the site offset.
- **Affected endpoints and flows:** Success and expected-error metadata for all 16 endpoints.

### I-9 — Catalog search performs work proportional to the full Item master

- **Type:** Implementation defect, performance.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/catalog.py:_visible_item_groups` runs permission-aware `frappe.get_list("Item", fields=["name", "item_group"])` with no limit on every search.
  - `roti_ropi_pos/mobile_pos/catalog.py:search_items` then post-filters ERPNext pages through that full projection.
  - Installed `erpnext/selling/page/point_of_sale/point_of_sale.py:get_items` also performs per-row stock, price, and UOM work.
- **Business impact:** Catalog latency and worker memory grow with the entire Item master, including items irrelevant to the selected page.
- **Android impact:** Search keystrokes can become slow or time out as catalog size grows.
- **Affected endpoints and flows:** `GET catalog.search`, catalog browsing and text search.

### I-10 — Customer text search has unbounded high-offset query amplification

- **Type:** Implementation defect, performance.
- **Evidence:** `roti_ropi_pos/mobile_pos/customers.py:search_customers` calculates `end = start + limit + 1`, runs three `LIKE` queries each with `limit=end`, merges them in memory, sorts, then slices. `start` has no maximum.
- **Business impact:** A large client-controlled offset causes three increasingly large database reads plus an in-memory merge and sort.
- **Android impact:** Deep or malformed pagination requests can create long waits and server pressure. Normal early pages remain logically ordered.
- **Affected endpoints and flows:** `GET customers.search`, customer lookup.

### I-11 — A reloaded return receipt loses return reason and has an inconsistent item contract

- **Type:** Implementation defect, receipt and history contract.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/invoices.py:create_return` passes the request reason directly to `sale_detail`, so the immediate response contains it.
  - `roti_ropi_pos/mobile_pos/invoices.py:get_sale` reloads a return and calls `sale_detail` without a persisted `return_reason`, producing `return_reason: null`.
  - `roti_ropi_pos/mobile_pos/invoices.py:sale_detail` first adds `returnability`, then replaces all item rows with `return_item_dto` when `doc.is_return`.
- **Business impact:** Receipt reprints and later audit views do not reproduce the return explanation from the submitted transaction.
- **Android impact:** The immediate return response and a later `sales.get` response have different useful information. Android cannot reconstruct one stable return receipt after restart.
- **Affected endpoints and flows:** `POST sales.create_return`, `GET sales.get`, return history and receipt reprint.

### I-12 — The contract has no deployment or minimum-client compatibility signal

- **Type:** Missing capability.
- **Evidence:** `roti_ropi_pos/mobile_pos/responses.py` exposes only hardcoded `meta.api_version = "v1"`. `roti_ropi_pos/api/v1/bootstrap.py:get` exposes business capabilities but no backend build, deployment revision, contract revision, or minimum supported Android version.
- **Business impact:** A partially deployed or incompatible backend cannot fail early with a clear compatibility decision.
- **Android impact:** Android can discover incompatibility only after parsing a changed field or hitting a missing behavior.
- **Affected endpoints and flows:** `GET bootstrap.get`, startup and rollout compatibility.

### I-13 — Missing OAuth client configuration is not diagnosed as configuration failure

- **Type:** Missing capability, configuration reliability.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_oauth_request` disables Mobile POS client detection when `mobile_pos_oauth_client_id` is empty, so Mobile POS-specific PKCE policy is not selected.
  - `roti_ropi_pos/mobile_pos/auth_hook.py:validate_mobile_api_scope` still requires every v1 token's client to equal that empty value, so the data plane fails closed.
- **Business impact:** A deployment mistake makes the Android API unusable without a targeted startup or bootstrap diagnosis.
- **Android impact:** Login or first API use fails as a generic authentication problem rather than an actionable backend configuration error.
- **Affected endpoints and flows:** OAuth authorize, approve, token exchange, and every v1 endpoint.

### I-14 — The exact permission policy omits a grant that runtime code needs

- **Type:** Documentation and governance gap.
- **Evidence:**
  - `AGENTS.md:Exact Cashier DocType Permissions` omits `Serial and Batch Bundle` and says permissions must match the exact table.
  - `roti_ropi_pos/fixtures/custom_docperm.json` grants cashier read, create, write, and submit for `Serial and Batch Bundle`.
  - Installed `erpnext/stock/serial_batch_bundle.py:make_serial_and_batch_bundle` saves and submits the bundle without `ignore_permissions=True`, so the grant is technically required for batch and serial POS submission.
- **Business impact:** The shipped permission fixture and the governing least-privilege policy disagree. A future cleanup following the policy can break serialized or batched sales.
- **Android impact:** Batch or serial checkout can fail after a permission sync that appears compliant with the documented table.
- **Affected endpoints and flows:** `POST sales.submit`, `POST sales.create_return`, batch and serial stock posting.

### I-15 — Stable error taxonomy and detail schemas are incomplete

- **Type:** Documentation gap.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/idempotency.py` and `closing.py` emit `IDEMPOTENCY_INVARIANT`, but the main stable-code table in `docs/mobile-pos/api-contract.md` omits it.
  - Closing emits `CLOSING_PREVIEW_STALE`, `CLOSING_PAYMENT_MODE_UNKNOWN`, `CLOSING_PAYMENT_MODE_DUPLICATE`, `CLOSING_PAYMENT_MODE_MISSING`, `CLOSING_DECIMAL_MALFORMED`, `CLOSING_DECIMAL_SCALE_EXCEEDED`, `CLOSING_AMOUNT_OUT_OF_BOUNDS`, `CLOSING_IN_PROGRESS`, and `CLOSING_ALREADY_CLOSED`. The document lists them in prose but does not define complete HTTP and `details` schemas.
  - The main table documents unused `SESSION_ALREADY_CLOSED`, `DOCUMENT_STATE_CONFLICT`, and `TEMPORARILY_UNAVAILABLE` codes.
- **Business impact:** Backend and client teams cannot distinguish the intended stable contract from implementation leftovers.
- **Android impact:** A strict error enum or details parser can fail on real responses. Retry and UI action rules remain incomplete.
- **Affected endpoints and flows:** Idempotent mutations and all Closing endpoints.

### I-16 — Core money-path verification remains incomplete in the fresh test run

- **Type:** Test gap and environment blocker.
- **Evidence:**
  - Fresh tests passed for ten modules and 219 tests total.
  - Fresh discovery of `roti_ropi_pos.tests.test_sale_task9` and `roti_ropi_pos.tests.test_return_task10` failed before test execution with `Duplicate entry 'Standard Buying' for key 'PRIMARY'` while ERPNext test utilities initialized fixtures.
  - Existing tests cover many sale and return cases in source, including quote-to-submit rounding, exact settlement, replay, return limits, and concurrency, but they did not execute in this audit run.
  - No verified integration test races twenty identical real `sales.submit` requests through the long invoice transaction. No test asserts stable mapping of an expected ERPNext `ValidationError` from sale or return submit.
- **Business impact:** The two highest-value accounting mutation suites lack fresh executable evidence in this audit environment.
- **Android impact:** Sale and return should not be declared release-ready until these suites run and the missing recovery/error cases are covered.
- **Affected endpoints and flows:** `POST sales.submit`, `POST sales.create_return`, sale and return idempotency.

### I-17 — Large modules and copied ERPNext behavior increase upgrade risk

- **Type:** Maintainability finding.
- **Evidence:**
  - `roti_ropi_pos/mobile_pos/invoices.py` is 1,004 lines and mixes quote, sale, stock, payment, history, return, and DTO logic.
  - `roti_ropi_pos/mobile_pos/closing.py` is 620 lines and mixes recovery phases, transaction control, financial aggregation, DTOs, and job scheduling.
  - `roti_ropi_pos/mobile_pos/idempotency.py` is 366 lines, `api/v1/sales.py` is 332 lines, and `mobile_pos/catalog.py` is 298 lines.
  - Closing duplicates ERPNext payment, change, tax, and invoice aggregation. Several paths import internal ERPNext helpers directly. Controller overrides reproduce selected core behavior.
- **Business impact:** ERPNext upgrades can silently change calculations or lifecycle behavior on one side of the copied boundary.
- **Android impact:** Contract regressions can appear without a version change and can affect totals, closing, or receipt fields.
- **Affected endpoints and flows:** Catalog, sale, return, history, and closing.

## Minor findings

### M-1 — Return remarks normalization changes existing audit text

- **Type:** Implementation defect.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:create_return` splits source and mapped remarks into lines, removes blank lines, and de-duplicates them before appending the Mobile POS reason. The contract requires preserving existing remarks and adding exactly one newline.
- **Business impact:** Persisted remarks can differ from the source formatting and can remove a repeated line.
- **Android impact:** Receipt or audit text can change unexpectedly.
- **Affected endpoints and flows:** `POST sales.create_return`.

### M-2 — Return item rows discard the computed `returnability` projection

- **Type:** Implementation defect, DTO consistency.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:sale_detail` builds rows with `returnability`, then replaces `detail["items"]` with `return_item_dto` rows when the document is a return.
- **Business impact:** Return document details do not follow the same item projection as ordinary sale details.
- **Android impact:** Kotlin DTO handling needs a return-specific exception or nullable fields not made explicit in the shared example.
- **Affected endpoints and flows:** `GET sales.get` for a return, immediate return receipt.

### M-3 — Preflight stock validation uses a different conversion-factor source

- **Type:** Implementation defect, duplicated business logic.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:_validate_total_stock` uses ERPNext `get_conversion_factor`, which can fall back to `1.0`, while `_append_items` obtains the effective factor through `quote_item`, including global UOM conversion behavior.
- **Business impact:** Preflight can undercount required stock for an item whose conversion exists only in the global UOM table. ERPNext submit remains authoritative and can reject later.
- **Android impact:** The expected `INSUFFICIENT_STOCK` preflight response can instead become the native core error described in I-4.
- **Affected endpoints and flows:** `POST sales.submit`, custom UOM stock validation.

### M-4 — Shared `reject_request` hardcodes the Closing reference type

- **Type:** Maintainability defect.
- **Evidence:** `roti_ropi_pos/mobile_pos/idempotency.py:reject_request` assigns `reference_doctype = "POS Closing Entry"` whenever a reference name exists. Closing is the only current caller.
- **Business impact:** Reuse for another operation can persist a false audit reference.
- **Android impact:** None on the current call graph.
- **Affected endpoints and flows:** Closing rejection storage.

### M-5 — Catalog pagination can report a false positive `has_more`

- **Type:** Implementation and documentation defect.
- **Evidence:** `roti_ropi_pos/mobile_pos/catalog.py:search_items` sets `core_may_have_more` after exhausting its fixed 11-page post-filter loop, even when no later authorized result exists. It also rejects `start > 1000`, but `docs/mobile-pos/api-contract.md` does not state that cap.
- **Business impact:** The API can expose an implementation ceiling as pagination state.
- **Android impact:** Android can request one empty extra page or encounter an undocumented validation error on deep browse.
- **Affected endpoints and flows:** `GET catalog.search`.

### M-6 — Sale read status values are not fully defined by the contract

- **Type:** Documentation gap.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:sale_summary` lowercases core `POS Invoice.status`, except `Credit Note Issued`, which maps to `paid`. Installed ERPNext can produce more statuses than the contract enumerates.
- **Business impact:** Backend lifecycle states and product labels can drift.
- **Android impact:** A strict status enum can reject or blank an otherwise valid history row.
- **Affected endpoints and flows:** `GET sales.list`, `GET sales.get`.

### M-7 — Some `PROFILE_CONFIGURATION_INVALID` details violate the documented schema

- **Type:** Implementation defect, API contract.
- **Evidence:** `roti_ropi_pos/mobile_pos/validation.py:sale_payment_amount_policy` and `closing_counted_amount_policy` can emit `PROFILE_CONFIGURATION_INVALID` without the required `pos_profile`. Other validation paths can use an empty profile value.
- **Business impact:** Outlet configuration diagnostics lack the affected profile identity.
- **Android impact:** Android cannot point support staff to the failing outlet configuration from the error alone.
- **Affected endpoints and flows:** Quote, sale, opening amount policy, closing preview and submit.

### M-8 — `sales.quote_return` response wrapper is not explicit in the contract

- **Type:** Documentation gap.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:build_return_quote` returns fields under `return_quote`; `docs/mobile-pos/api-contract.md` describes the fields but does not show the complete wrapper shape.
- **Business impact:** Backend and Android teams can implement different DTO roots.
- **Android impact:** The endpoint cannot be implemented from the document alone without reading backend source.
- **Affected endpoints and flows:** `POST sales.quote_return`.

### M-9 — `sales.quote_cart` omits reachable stock and tracking errors from its endpoint section

- **Type:** Documentation gap.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:build_sale_quote` calls the shared item builder, which can emit `INSUFFICIENT_STOCK`, `INVALID_BATCH`, and `INVALID_SERIAL_NUMBER`. The `sales.quote_cart` contract section does not list them.
- **Business impact:** Quote failures lack a complete documented cashier response model.
- **Android impact:** Android may show a generic error instead of item-level correction UI.
- **Affected endpoints and flows:** `POST sales.quote_cart`.

### M-10 — Request ID format and log-correlation meaning are ambiguous

- **Type:** Documentation and observability gap.
- **Evidence:** `roti_ropi_pos/mobile_pos/responses.py:success` generates a random 26-character Frappe hash. The contract example resembles a ULID but defines no format, and the ID is not proven to match a framework request or server log identifier.
- **Business impact:** Support cannot rely on a cashier screenshot to locate one server request.
- **Android impact:** Android must treat the value as opaque and cannot assume ordering or ULID parsing.
- **Affected endpoints and flows:** All endpoint envelopes.

### M-11 — No cashier-facing token revoke or logout contract exists

- **Type:** Missing capability.
- **Evidence:** The exact Mobile POS route inventory contains authorize, approve, and token exchange support but no Mobile POS revoke endpoint. The 16-endpoint data surface has no logout operation.
- **Business impact:** Immediate token revocation from the device is not part of the current product flow. Manager-side disablement and token expiry remain the available controls.
- **Android impact:** Logout can clear local tokens but cannot prove server-side revocation through this facade.
- **Affected endpoints and flows:** Authentication and logout.

### M-12 — Closing triggers a redundant consolidation scheduling check

- **Type:** Maintainability defect.
- **Evidence:** `roti_ropi_pos/overrides/pos_closing_entry.py:MobilePOSClosingEntry.on_submit` registers `ensure_committed_closing_job` with `after_commit` for queued closings. `roti_ropi_pos/mobile_pos/closing.py:_complete_from_persisted` calls the same helper again when status is `Queued`. Installed ERPNext uses a deterministic merge job ID, so duplicate enqueue is normally suppressed.
- **Business impact:** The recovery boundary is harder to reason about, although current job deduplication prevents duplicate consolidation.
- **Android impact:** No proven current failure.
- **Affected endpoints and flows:** `POST closing.submit`, queued closing.

### M-13 — Several Mobile POS documents describe obsolete ownership or implementation state

- **Type:** Documentation gap.
- **Evidence:**
  - `docs/mobile-pos/architecture.md` still says the app has no Mobile POS API.
  - `docs/mobile-pos/integration-boundaries.md` still proposes `required_apps = ["erpnext", "stock_additional"]`.
  - `docs/mobile-pos/product-requirements.md` and related documents still describe generic selling ownership as current or targeted in `bakery_manufacturing`.
  - Runtime `roti_ropi_pos/hooks.py:required_apps` is `erpnext`, `stock_additional`, and `selling_additional`.
- **Business impact:** A new maintainer can deploy the wrong dependency set or modify the wrong app.
- **Android impact:** Handoff material can misstate which backend owns pricing and walk-in behavior.
- **Affected endpoints and flows:** Deployment, catalog pricing, Customer and walk-in sale integration.

### M-14 — History and configuration edge cases lack direct tests

- **Type:** Test gap.
- **Evidence:** No direct verified tests cover every `sales.list` status filter, `has_more`, and offset boundary. No direct verified test covers a Customer currency that differs from the POS Profile currency before payment-scale validation.
- **Business impact:** Pagination, status projection, and currency-policy drift can regress unnoticed.
- **Android impact:** History paging or payment validation can fail only in less common outlet configurations.
- **Affected endpoints and flows:** `GET sales.list`, `POST sales.submit`, `POST sales.quote_cart`.

### M-15 — `sales.list` uses deprecated Frappe pagination argument names

- **Type:** Maintainability defect.
- **Evidence:** `roti_ropi_pos/mobile_pos/invoices.py:list_sales` passes `start` and `page_length` to `frappe.get_list`. Fresh tests emitted Frappe's v17 deprecation warning for `limit_page_length` paths, and installed query code marks these aliases for removal.
- **Business impact:** A future Frappe upgrade can break history paging after the compatibility shim is removed.
- **Android impact:** History can repeat page zero or fail after an upgrade if not covered by source-contract tests.
- **Affected endpoints and flows:** `GET sales.list`.

## Test and evidence already run

Fresh tests ran inside `/workspace/development/frappe-bench` against dedicated test site `selling-cutover.localhost`. No test ran against `development.localhost`.

| Module | Result |
| --- | --- |
| `roti_ropi_pos.tests.test_api_foundation` | 14 passed |
| `roti_ropi_pos.tests.test_authentication` | 30 passed |
| `roti_ropi_pos.tests.test_bootstrap` | 9 passed |
| `roti_ropi_pos.tests.test_sessions` | 10 passed |
| `roti_ropi_pos.tests.test_customers` | 7 passed |
| `roti_ropi_pos.tests.test_catalog` | 19 passed |
| `roti_ropi_pos.tests.test_idempotency` | 27 passed |
| `roti_ropi_pos.tests.test_opening_amounts` | 21 passed |
| `roti_ropi_pos.tests.test_closing` | 45 passed |
| `roti_ropi_pos.tests.test_source_contracts` | 37 passed |
| **Fresh passing total** | **219 passed** |
| `roti_ropi_pos.tests.test_sale_task9` | Discovery blocked before execution |
| `roti_ropi_pos.tests.test_return_task10` | Discovery blocked before execution |

Other evidence checked:

- Current application source for all 16 v1 endpoints, authorization, response mapping, profiles, sessions, catalog, invoices, idempotency, closing, fixtures, and controller overrides.
- Installed Frappe route dispatch, transaction and savepoint behavior, query behavior, timezone utility, OAuth routing, and permission behavior.
- Installed ERPNext POS item lookup, POS Invoice validation and submission, return mapper, Closing behavior, consolidation job deduplication, and Serial and Batch Bundle creation.
- Mobile POS API contract, product requirements, architecture, project specification, integration boundaries, Android handoff, and project governance rules.
- Intended diff review confirmed this audit changed no production code or test code.

## Known baseline and environment issues

- The test environment uses Frappe `16.27.1`, ERPNext `16.28.0`, Python `3.14`, and MariaDB.
- Sale and return test discovery hit the known upstream ERPNext fixture baseline: `Duplicate entry 'Standard Buying' for key 'PRIMARY'` while importing ERPNext test utilities.
- This audit did not change ERPNext core to bypass that baseline.
- No migrate ran. No operational site was mutated. `development.localhost` was not touched. `allow_tests` was not enabled on `rotiropi-fresh.localhost`.
- Existing unrelated working-tree changes and untracked files were left untouched.
- IMIN hardware test remains **PENDING**.

## Work not finished

- The final executive audit report has not been synthesized.
- The final business-flow matrix has not been written.
- The final 16-endpoint Android API contract matrix has not been written.
- Final P0, P1, and P2 grouping and the minimum Android blocker list have not been formatted for delivery.
- No finding has been fixed. No migration, commit, push, or deployment has been performed.

## Exact next action

**Synthesize the final audit report only from this checkpoint and already verified evidence. Do not resume broad audit, dispatch agents, rerun tests, implement fixes, migrate, mutate a site, commit, or push.**
