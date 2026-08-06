# Mobile POS Testing Strategy

## Evidence Legend

- **Verified**: Confirmed test infrastructure or installed behavior.
- **Approved**: A Phase 0 testing decision approved for implementation.
- **Proposed**: Tests and gates required for implementation.
- **Inferred**: Risk-based coverage derived from source behavior.

## Objectives

- **Proposed**: Prove the facade enforces identity and profile scope before exercising ERPNext.
- **Proposed**: Prove ERPNext remains authoritative for prices, taxes, payments, stock, serials, batches, returns, and closing.
- **Proposed**: Prove retries cannot duplicate business documents.
- **Proposed**: Detect installed Frappe/ERPNext source-contract changes before deployment.

## Test Layers

### Pure Unit Tests

- **Proposed**: Test request validation, decimal normalization, canonical request hashing, error mapping, response serialization, and capability calculation without database writes.
- **Proposed**: Use fixed timestamps and request IDs so complete envelopes can be asserted.
- **Proposed**: Reject unknown fields, floats for monetary values, negative normal-sale quantities, duplicate payment modes, malformed UUID keys, and client-controlled identity/account fields.

### Frappe Integration Tests

- **Proposed**: Use `IntegrationTestCase` and create isolated company, warehouse, users, profiles, opening balances, items, UOM conversions, prices, batches, serials, and stock.
- **Proposed**: Call app service functions for detailed state assertions and whitelisted endpoints for transport/envelope assertions.
- **Proposed**: Roll back test state through Frappe's test transaction behavior; do not use production records.

### Source-Contract Tests

- **Proposed**: Assert imported ERPNext call signatures and minimum returned keys for:
  - `scan_barcode(search_value, ctx)`
  - POS catalog search
  - item details and conversion factor
  - stock availability
  - return mapping
  - closing invoice retrieval
- **Proposed**: Assert the effective `scan_barcode` hook resolves to the bakery override when both apps are installed.
- **Inferred**: These tests are the earliest warning that a Frappe/ERPNext minor upgrade changed an assumed boundary.

### Android Contract Tests

- **Proposed**: Keep JSON fixtures for every success and stable error envelope in the Android repository.
- **Proposed**: Verify Kotlin serializers ignore additive unknown fields and retain decimal precision.
- **Proposed**: Use a mock HTTP server to test 401, 403, 409, 422, 429, 500, and queued closing responses.
- **Proposed**: Test Keystore-backed credential persistence, logout deletion, WorkManager retry, and process-death recovery.
- **Approved**: Test Authorization Code with PKCE S256 through a system browser/Custom Tab, including state, redirect, wrong verifier, code replay, refresh, local logout, disabled-user denial, and manager revocation. Prove no embedded client secret or shared credential exists.
- **Approved**: UI tests use Kotlin XML layouts and ViewBinding on API 23 and a current API. Compose tests are excluded unless Compose is separately approved.
- **Approved**: These tests belong to a separate plan at `/Users/rotiropi/DockerERPNext/POSERPNext/docs/mobile-pos/implementation-plan.md`.
- **Verified**: That plan does not currently exist, so Android implementation and Android release claims remain blocked.

## Required Backend Scenarios

### Authentication and Scope

- **Proposed**: Guest is rejected from every endpoint.
- **Proposed**: A valid OAuth bearer token establishes the individual cashier identity; API keys, Basic credentials, shared users, and Administrator credentials are rejected by policy tests.
- **Proposed**: Payload attempts to set `user`, `owner`, `company`, or an unauthorized profile are rejected.
- **Proposed**: A cashier cannot view another cashier's opening, sale, or closing.
- **Proposed**: A second-company user cannot infer whether a document exists.
- **Proposed**: A user without the exact `Mobile POS Cashier` Custom DocPerm receives `PERMISSION_DENIED`; the API does not bypass ERPNext business-document permission.
- **Proposed**: Known profile/document permission failures use the stable Mobile POS envelope, while an injected unknown exception is re-raised rather than converted to `PERMISSION_DENIED`.
- **Proposed**: A `Mobile POS Cashier` bearer token can call allowed v1 endpoints but is rejected from core `/api/method`, `/api/resource`, upload, and Desk API routes.
- **Proposed**: Every v1 endpoint rejects cookie, API-key, Basic, wrong-client bearer, disabled-user bearer, legacy `cmd`, generic method, encoded alternate path, and `/api/v2/method` dispatch.
- **Proposed**: Native pre-dispatch Frappe errors and stable in-endpoint Mobile POS envelopes are both parsed correctly by Android.

### Opening

- **Proposed**: Valid balances create and submit one Opening Entry.
- **Proposed**: `sessions.current` returns a prior-day opening when it remains submitted, Open, unclosed, owned by the current user, and linked to the selected authorized profile and Company.
- **Proposed**: The active-opening lookup applies no calendar-date filter.
- **Proposed**: Opening DTOs always include `posting_date`, `period_start_date`, and `warnings`.
- **Proposed**: A prior-day opening includes one `STALE_OPENING` warning with `opening_date` and `server_date`.
- **Proposed**: The stale warning is informational and does not block the shift.
- **Proposed**: Current-opening lookup explicitly proves POS Opening Entry read permission without broad roles or `ignore_permissions`.
- **Proposed**: A new opening is rejected when the same profile is Open for another user or the same user is assigned to another Open profile.
- **Proposed**: Disabled profiles, mismatched company, disabled users, unknown payment modes, and missing payment accounts are rejected.
- **Proposed**: Replay returns the original opening.
- **Proposed**: Opening and closing lifecycle succeeds with only `Mobile POS Cashier`; assert the user does not have Sales Manager, Accounts Manager, System Manager, or Administrator.

### Customer Selection

- **Proposed**: Search finds enabled visible registered Customers by customer name, identifier, or mobile number with bounded deterministic pagination.
- **Proposed**: Disabled and permission-inaccessible Customers are excluded without existence leakage.
- **Proposed**: When `profile.customer_groups` is non-empty, every Customer outside the configured groups' closure is excluded, including the configured default Customer.
- **Proposed**: When `profile.customer_groups` is empty, all enabled permission-visible Customers remain eligible; no synthetic Customer Company filter is added.
- **Proposed**: Omitted customer resolves to the POS Profile default walk-in Customer.
- **Proposed**: The configured default Customer passes the same existence, enabled, read-permission, and profile-group predicate tests as an explicit Customer.
- **Proposed**: A missing, disabled, permission-inaccessible, or predicate-ineligible default returns `PROFILE_CONFIGURATION_INVALID`.
- **Proposed**: Optional `walk_in_customer_name` is stored and returned only for the default walk-in Customer through bakery's existing field.
- **Proposed**: `walk_in_customer_name` is rejected for a registered non-walk-in Customer.
- **Proposed**: Search, quote, sale, and return create no Customer rows.

### Catalog, UOM, Batch, and Stock

- **Proposed**: Catalog respects profile item groups, warehouse, price list, disabled items, and pagination limits.
- **Proposed**: Exact barcode, serial, batch, and warehouse scan behavior matches ERPNext.
- **Proposed**: A bakery batch QR returns `custom_default_uom_warehouse` and conversion factor.
- **Proposed**: Missing batch UOM conversion produces a structured warning.
- **Proposed**: Expired, wrong-item, wrong-warehouse, and insufficient-quantity batches fail before or during invoice submission.
- **Proposed**: A concurrent stock change after quote is rejected by authoritative submit validation.

### Sale and Payment

- **Proposed**: A normal cash sale submits with core-calculated price, taxes, totals, stock, and payment rows.
- **Proposed**: Pricing rules and Price Group-generated price lists affect the authoritative result.
- **Proposed**: Every v1 endpoint rejects direct Sales Invoice mode with the same stable `UNSUPPORTED_POS_MODE` envelope and details.
- **Proposed**: Changed price causes `PRICE_CHANGED` and no submitted invoice.
- **Proposed**: Client-supplied rate, account, tax, total, and warehouse fields are rejected.
- **Proposed**: Underpayment is rejected and creates no invoice. Multiple distinct payment modes pass only when the final invoice is fully settled; overpayment/change follows ERPNext core rules.
- **Proposed**: Serialized and batched items require valid identifiers.
- **Proposed**: Twenty concurrent identical requests create exactly one invoice.

### History, Return, and Cancellation

- **Proposed**: Sale list includes only scoped POS Invoices and preserves walk-in display names.
- **Approved**: Full and partial returns create correctly negative items and server-selected refund payments; Android supplies no accounting values.
- **Approved**: Fresh sale detail projects cumulative submitted returns and remaining quantity. Exact-boundary creation succeeds; sequential and concurrent excess attempts return `RETURN_LIMIT_EXCEEDED` without artifacts.
- **Approved**: Return quote and create prove zero/one/multiple refund-mode rules, authoritative taxes/discounts/rounding/refund totals, exact quantity decimals, required reason, replay, rollback, and serial/batch permission behavior.
- **Proposed**: Return reason is trimmed, required, and appended as `Mobile POS Return Reason: <reason>` to standard remarks.
- **Proposed**: Existing remarks remain unchanged before the one-newline append.
- **Approved**: No Android `sales.cancel` endpoint exists in MVP; cashier corrections use returns and manager cancellation remains an ERPNext Desk test outside the mobile suite.
- **Proposed**: Consolidated invoices cannot be cancelled directly.

### Idempotency Retention

- **Proposed**: Cleanup deletes terminal, unheld Mobile POS Request rows only after 90 days.
- **Proposed**: Cleanup preserves Processing, stale-processing, unresolved closing, failed-closing-under-review, incident-held, and audit-held rows.
- **Proposed**: Cleanup verifies the referenced ERPNext document retains the matching `custom_mobile_pos_transaction_id`; a mismatch creates a hold instead of deleting.
- **Proposed**: Cleanup never deletes or mutates POS Opening Entry, POS Invoice, POS Closing Entry, or return documents.

### Closing

- **Proposed**: Preview totals match the invoice/payment set and include opening balances.
- **Proposed**: Submit rejects stale, closed, mismatched, duplicated, or foreign-user invoices.
- **Proposed**: Fewer than ten invoices complete synchronously in the tested core behavior.
- **Proposed**: A boundary test patches ERPNext enqueue behavior and proves that at least ten `pos_invoices` child rows select the queued branch.
- **Verified**: `frappe.in_test` makes ERPNext's queued job run immediately, so the normal Frappe suite cannot prove production worker polling by invoice count alone.
- **Proposed**: A staging test with developer mode disabled, active workers, and at least ten POS Invoice rows proves real `queued` to `submitted` polling and recovery.
- **Proposed**: Failed consolidation is visible without creating a duplicate close.
- **Proposed**: Closing cancellation/reopen remains a manager ERPNext Desk workflow and is not exposed by Mobile POS MVP.

## Exact Backend Commands

Run inside the development container from `/workspace/development/frappe-bench`:

```bash
bench --site development.localhost run-tests --app roti_ropi_pos
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_authentication
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_idempotency
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sessions
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_customers
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_catalog
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sales
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_closing
```

Run app static checks from `apps/roti_ropi_pos`:

```bash
pre-commit run --all-files
```

Run dependency regression modules from the bench:

```bash
bench --site development.localhost run-tests --module bakery_manufacturing.tests.test_barcode_scanner
bench --site development.localhost run-tests --module bakery_manufacturing.bakery_manufacturing.doctype.price_group.test_price_group
bench --site development.localhost run-tests --module erpnext.tests.test_point_of_sale
bench --site development.localhost run-tests --module erpnext.stock.tests.test_utils
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_opening_entry.test_pos_opening_entry
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice.test_pos_invoice
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_closing_entry.test_pos_closing_entry
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice_merge_log.test_pos_invoice_merge_log
bench --site development.localhost run-tests --module frappe.tests.test_frappe_client
bench --site development.localhost run-tests --module frappe.tests.test_oauth20
```

- **Verified**: In this v16 environment, `bench run-tests --module` is the reliable targeted invocation; `--test` previously discovered zero tests.
- **Proposed**: CI setup must provide an isolated test site and workers without storing production credentials in repository configuration.

## Exact Android Commands

Run from `/Users/rotiropi/DockerERPNext/POSERPNext`:

```bash
./gradlew testDebugUnitTest
./gradlew lintDebug
./gradlew assembleDebug
./gradlew connectedDebugAndroidTest
```

- **Verified**: The Android project currently uses AGP `9.2.1`, Kotlin `2.2.10`, min SDK `23`, target SDK `36`, and an unapproved generated Compose starter.
- **Approved**: A future separately approved Android plan must replace the generated starter with Kotlin XML Views and ViewBinding. Jetpack Compose is not used without explicit approval.
- **Approved**: These commands are future product-level gates and are not part of Backend Final Task 9.

## Backend Final Release Gate

- **Proposed**: All `roti_ropi_pos` tests and static checks pass.
- **Proposed**: Bakery barcode and Price Group regressions pass.
- **Proposed**: Selected ERPNext/Frappe source-contract suites pass on the exact deploy image.
- **Proposed**: Backend staging smoke tests cover OAuth, opening, stale-opening warning, scan, sale, timeout replay, return, close, and close polling through contract-level API calls.
- **Proposed**: Security review confirms no Guest endpoint, credential logging, cross-profile access, or blanket permission bypass.

## Future Product-Level Delivery Gate

- **Approved**: This gate remains blocked until the separate Android plan exists and is approved.
- **Proposed**: Android unit, lint, build, and connected tests pass under that plan.
- **Proposed**: Android contract fixtures cover stable envelopes, native pre-dispatch errors, and `STALE_OPENING`.
- **Proposed**: Product-level staging smoke tests cover the complete Android-to-backend lifecycle.
- **Approved**: Passing Backend Final does not by itself establish final Mobile POS delivery.

## Test Evidence to Preserve

- **Proposed**: Record app versions, Git SHAs, commands, exit codes, failing test names, and staging request IDs for each release candidate.
- **Proposed**: Do not claim a release is verified from Graphify output or source inspection alone; executable test evidence is required.
