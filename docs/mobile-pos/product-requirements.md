# Roti Ropi Mobile POS — Product Requirements Document

> This document defines **what** the Mobile POS delivers and **why**.
> Technical architecture, API schemas, idempotency mechanics, and task-level
> instructions live in the companion documents listed in
> [Document Cross-References](#document-cross-references).

---

## 1. Product Vision

Give Roti Ropi bakery cashiers a purpose-built Android point-of-sale
application that is fast on low-end devices, secure by default, and fully
backed by the existing ERPNext accounting system — so every sale, return,
and shift settlement is accurate, auditable, and recoverable without manual
reconciliation.

---

## 2. Business Problem

Roti Ropi currently relies on the ERPNext web-based POS page, which is
designed for desktop browsers and broad administrative roles. This creates
several operational problems:

- **Device mismatch.** The web POS is heavy for the low-end Android tablets
  used at bakery counters. Page loads are slow, and the interface does not
  fit a cashier's workflow.
- **Over-privileged cashiers.** The web POS requires Sales Manager or
  Accounts User roles, granting cashiers access to reports, settings, and
  documents they should never see or modify.
- **No retry safety.** A network interruption during sale submission can
  produce duplicate POS Invoices because the web POS has no built-in
  idempotency mechanism.
- **No walk-in display name.** The bakery needs to attach a customer
  display name to walk-in transactions for order identification without
  creating a full Customer record.

---

## 3. Target Users

| Role | Description | MVP access |
| --- | --- | --- |
| **Cashier** | Bakery counter staff who open shifts, ring up sales, process returns, and close shifts. They use low-end Android tablets at the counter. | Full mobile app access with `Mobile POS Cashier` role. |
| **Manager** | Store or area managers who configure POS Profiles, review closing entries, handle cancellations, and manage user accounts in ERPNext Desk. | ERPNext Desk only; not a mobile app user in the MVP. |

---

## 4. User Journeys

### 4.1 Sign In

1. Cashier opens the app and taps **Sign In**.
2. The system browser opens to the ERPNext login and OAuth consent screen.
3. After consent, the app receives an authorization code and exchanges it
   for access and refresh tokens.
4. The app calls the bootstrap endpoint, receives the cashier's assigned
   POS Profile(s), current session state, and default walk-in customer.

### 4.2 Open Shift

1. Cashier selects a POS Profile (if more than one is assigned).
2. Cashier enters opening cash balances for each configured payment mode.
3. The app submits the opening request. ERPNext creates and submits a
   POS Opening Entry.
4. The cashier sees the sale screen with current session details.

> If a prior-day session is still open, the app displays a stale-session
> warning with the original opening date.

### 4.3 Ring Up a Sale

1. Cashier scans a barcode or searches the catalog by name.
2. The app displays item details, resolved UOM, and current price.
3. Cashier adjusts quantities, adds more items, or removes items.
4. Cashier optionally searches and selects a registered customer, or leaves
   the customer blank to use the default walk-in customer. For walk-in
   customers, the cashier may enter an optional display name.
5. Cashier reviews the order total and selects one or more payment methods
   (e.g., cash, card, transfer).
6. The app submits the sale. ERPNext creates, validates, and submits a
   POS Invoice. The app displays the confirmed receipt with authoritative
   server totals.

> The sale must be fully settled — outstanding amount must be zero.
> Multiple payment methods are allowed only when the combined total
> covers the invoice in full.

### 4.4 Return an Item

1. Cashier opens sale history and selects a previous sale.
2. Cashier selects item(s) to return and the return quantities.
3. Cashier enters a required return reason.
4. The app submits the return. ERPNext creates a negative return POS
   Invoice through its mapped return document.

> Cancellation is not available in the mobile app. A manager handles
> cancellations through ERPNext Desk.

### 4.5 Close Shift

1. Cashier taps **Close Shift** and reviews the preview of expected totals
   derived from submitted invoices and the opening balance.
2. Cashier enters counted cash and other balances.
3. The app submits the closing request. ERPNext creates and submits a
   POS Closing Entry.
4. If consolidation is asynchronous (≥10 invoices), the app polls the
   closing status until it resolves to **submitted** or **failed**.
5. On failure, the cashier sees a message directing a manager to review the
   closing in ERPNext.

### 4.6 Sign Out

1. Cashier taps **Sign Out**.
2. The app clears local tokens and credentials.
3. Manager-side token revocation or user disablement is handled in ERPNext
   Desk.

---

## 5. MVP Scope

The MVP delivers the end-to-end cashier workflow described in the user
journeys above:

| Capability | Included |
| --- | --- |
| Individual cashier authentication (OAuth 2.0 + PKCE S256) | ✓ |
| Bootstrap with assigned POS Profiles and session state | ✓ |
| Open shift with configurable opening balances | ✓ |
| Stale-opening warning for prior-day sessions | ✓ |
| Item catalog search scoped to POS Profile | ✓ |
| Barcode scanning with bakery UOM enrichment | ✓ |
| Registered customer search and selection | ✓ |
| Default walk-in customer with optional display name | ✓ |
| Fully settled POS Invoice submission | ✓ |
| Multiple payment modes (when fully settled) | ✓ |
| Idempotent transaction submission | ✓ |
| Safe timeout and process recovery | ✓ |
| Sale history scoped to cashier's session | ✓ |
| Item returns with required reason | ✓ |
| Closing preview, submission, and async status polling | ✓ |
| POS Invoice mode only | ✓ |
| Minimal `Mobile POS Cashier` role (not Sales Manager) | ✓ |

---

## 6. Out-of-Scope Items

The following are explicitly excluded from the MVP and require separate
approval before work begins:

| Item | Rationale |
| --- | --- |
| Partial payment (non-zero outstanding) | Complexity; requires policy decision on settlement rules |
| Mobile sale cancellation | Manager operation; remains in ERPNext Desk |
| Sales Invoice mode | MVP uses POS Invoice only |
| Offline ledger / offline accounting | ERPNext remains the sole ledger authority |
| Health check endpoint | No approved contract or task |
| Return-preview endpoint | Cashier uses direct return submission |
| Customer auto-creation | Business rule: never auto-create from POS |
| Maximum shift-duration policy | Future manager policy; not inferred from calendar days |
| Manager mobile role | Manager operations remain in ERPNext Desk |
| Jetpack Compose UI | Requires separate explicit approval |
| Production deployment automation | Staging and deployment planning is separate |

---

## 7. Business Rules

### 7.1 Authentication and Authorization

- Each cashier authenticates individually using OAuth 2.0 Authorization Code
  with PKCE S256. No shared accounts, API keys, or embedded secrets.
- Cashiers use the `Mobile POS Cashier` role with minimal, explicit
  permissions. Sales Manager, Accounts Manager, and System Manager roles
  are never assigned to mobile cashier accounts.
- The app is a public OAuth client — no client secret is distributed to
  the Android device.

### 7.2 POS Profile and Session

- A cashier may operate only on POS Profiles explicitly assigned to them.
- Only one open session per cashier per POS Profile is allowed.
- A session that started on a prior calendar day remains valid but triggers
  a stale-opening warning displayed to the cashier.
- There is no maximum shift-duration policy in the MVP.

### 7.3 Customer Handling

- Cashiers may search and select registered customers from the existing
  customer master.
- When no customer is selected, the POS Profile's default walk-in customer
  is used automatically.
- The configured default customer must pass the same existence, enabled,
  read-permission, and POS Profile Customer Group checks as an explicitly
  selected customer. Invalid default configuration is rejected with a stable
  configuration error.
- An optional display name may be attached only to walk-in customer
  transactions, never to registered customer transactions.
- The mobile app never creates, modifies, or deletes Customer records.

### 7.4 Sales and Payments

- Every submitted sale must be fully settled — the outstanding amount must
  be exactly zero.
- Multiple distinct payment modes are allowed only when they collectively
  settle the invoice in full.
- Client-provided totals, rates, taxes, and account references are not
  authoritative. The server recalculates all financial values.
- The POS Invoice is the only supported invoice type. Any other
  configuration returns an error.

### 7.5 Returns and Corrections

- Returns create a negative POS Invoice through ERPNext's mapped return
  document.
- A non-empty return reason is required and is appended to existing invoice
  remarks without overwriting them.
- Return quantities must not exceed the remaining returnable quantity for
  each item.
- Mobile cancellation is not supported. Completed sales are corrected
  through returns; manager cancellation remains in ERPNext Desk.

### 7.6 Closing and Consolidation

- Closing totals are derived server-side from submitted invoices and the
  opening balance. The cashier provides counted balances only.
- When consolidation is asynchronous, the app polls for terminal status.
- Failed consolidation requires manager review in ERPNext Desk. The mobile
  app has no retry mechanism for closing failures.

### 7.7 Idempotency and Recovery

- Every mutation must be safely retryable. Duplicate submission attempts
  must not create duplicate business documents.
- Idempotency keys are generated once per logical action and reused until
  a terminal response is received.
- Reusing a key with different data is rejected as a conflict.
- Completed and rejected idempotency records are retained for 90 days.
  Records under active processing, recovery, or audit hold are never
  deleted by age alone.

---

## 8. Functional Requirements

### FR-1: Authentication

The app must authenticate each cashier individually through OAuth 2.0
Authorization Code with PKCE S256, using the system browser or Custom Tab.
Embedded credential capture (WebView) is prohibited.

### FR-2: Bootstrap

After authentication, the app must retrieve the cashier's assigned POS
Profiles, current session state, default walk-in customer, and any
applicable warnings (e.g., stale opening).

### FR-3: Open Session

The app must allow the cashier to open a shift by selecting a POS Profile
and entering opening balances. The server creates and submits a POS Opening
Entry through ERPNext's controller.

### FR-4: Catalog and Scan

The app must provide item search scoped to the POS Profile and barcode
scanning that respects bakery UOM enrichment through the registered
ERPNext override.

### FR-5: Customer Selection

The app must support searching registered customers within the profile's
permitted scope, defaulting to the walk-in customer when none is selected,
and attaching an optional display name to walk-in transactions only.

### FR-6: Sale Submission

The app must submit fully settled POS Invoices with server-authoritative
pricing, taxes, and totals. Multiple payment modes are allowed only when
the invoice is fully settled.

### FR-7: Sale History

The app must display sale history scoped to the cashier's current session
and profile, including walk-in display names.

### FR-8: Returns

The app must allow item-level returns against previous sales with a required
reason, creating negative POS Invoices through ERPNext's return mapper.

### FR-9: Closing

The app must show a server-derived closing preview, allow the cashier to
submit counted balances, and handle both synchronous and asynchronous
closing resolution.

### FR-10: Idempotent Transactions

Every mutation must use an idempotency key to prevent duplicate document
creation across retries, timeouts, and process restarts.

### FR-11: Route Security

Cashier accounts must be restricted to the mobile POS API routes only.
Generic ERPNext API, Desk, and resource routes must be blocked for
`Mobile POS Cashier` accounts.

---

## 9. Non-Functional Requirements

### NFR-1: Performance

The app must be lightweight and responsive on low-end Android devices
(minSdk 23). API responses for common operations (bootstrap, catalog
search, sale submission) should target sub-second latency on a local
network.

### NFR-2: Security

- No client secrets, API keys, or credentials may be embedded in the APK
  or stored in plaintext.
- Tokens must be encrypted using Android Keystore.
- Internal server errors, stack traces, and debugging information must
  never be returned to the client.
- Credentials must be excluded from logs, crash reports, analytics,
  backups, and screenshots.

### NFR-3: Reliability

- Idempotent submissions must survive network interruptions, app restarts,
  and process kills without creating duplicate transactions.
- The app must handle unknown-result responses by retrying with the same
  idempotency key.

### NFR-4: Compatibility

- Android: Kotlin, XML Views, ViewBinding, minSdk 23.
- Backend: Frappe 16.x, ERPNext 16.x, Python 3.14.
- No Jetpack Compose without explicit approval.

### NFR-5: Auditability

- Every mobile transaction must carry a transaction ID that persists on
  the ERPNext business document for audit correlation.
- Idempotency records must be retained for at least 90 days after
  terminal resolution.

### NFR-6: Maintainability

- The Android app must not depend on Frappe document shapes or internal
  function names. It consumes only the versioned v1 API contract.
- The backend facade must not duplicate ERPNext business logic.

---

## 10. Product Acceptance Criteria

The MVP is accepted when:

1. A cashier can complete the full shift lifecycle (sign in → open →
   sell → return → close → sign out) using only the `Mobile POS Cashier`
   role on a low-end Android device.
2. Every submitted POS Invoice has zero outstanding amount.
3. Duplicate mutation attempts produce exactly one ERPNext business
   document.
4. Customer search works correctly and no Customer records are
   auto-created.
5. Walk-in display name is accepted only for the default walk-in customer.
6. Barcode scanning resolves bakery UOM enrichment correctly.
7. Returns enforce quantity limits and require a reason.
8. Closing handles both synchronous and asynchronous consolidation.
9. Cashier accounts cannot access ERPNext Desk, generic API routes, or
   documents outside their assigned profile scope.
10. The app functions acceptably on minSdk 23 devices with XML Views
    and ViewBinding.
11. No credentials are exposed in the APK, logs, crash reports, or
    API responses.

---

## 11. Operational Assumptions

- ERPNext is deployed and operational with the `bakery_manufacturing` app
  installed. POS Profiles, payment modes, warehouses, item catalogs, and
  price lists are configured before the mobile app is used.
- Each cashier has a dedicated, enabled Frappe User account with only the
  `Mobile POS Cashier` role and explicit POS Profile assignment.
- A public OAuth Client is provisioned on the ERPNext site for the
  mobile app, with Authorization Code grant, PKCE S256, and no client
  secret.
- The Android tablets have reliable local network connectivity to the
  ERPNext server. The MVP does not include an offline mode.
- Managers handle cancellations, failed closings, user provisioning, and
  OAuth token revocation through ERPNext Desk.

---

## 12. Open Product Decisions

The stale-opening behavior is no longer open: `STALE_OPENING` is an
informational warning and does not block sales. A future maximum shift-duration
policy requires separate approval.

| # | Question | Impact |
| --- | --- | --- |
| 1 | Should the app support landscape orientation on tablets, or portrait only? | UI layout and testing scope |
| 2 | What receipt format should the app display after a sale? On-screen summary, printable receipt, or both? | FR-6 and FR-7 detail; potential printer integration |
| 3 | Is there a maximum number of items per sale that the UI should enforce? | UI performance on low-end devices |
| 4 | Should the app display real-time stock availability during item selection? | Catalog UX; stock data is informational pre-submission |
| 5 | What is the expected deployment model for app updates (Play Store, sideloading, MDM)? | Release and distribution process |

---

## 13. Dependencies and Constraints

### System Dependencies

| Dependency | Role |
| --- | --- |
| **ERPNext 16.x** | Source of truth for POS Profiles, invoices, closings, pricing, taxes, stock, batch, serial, payments, and accounting. |
| **Frappe 16.x** | Authentication, OAuth 2.0, permissions, document lifecycle, request handling, and background workers. |
| **`bakery_manufacturing`** | Price Group synchronization, batch barcode UOM enrichment, and walk-in customer display name. |
| **`roti_ropi_pos`** | Backend facade providing the versioned v1 API between the Android app and ERPNext. |

### Repository Constraints

- The backend (`roti_ropi_pos`) and Android (`POSERPNext`) are separate
  repositories with independent implementation plans.
- Backend implementation must not modify files under `apps/erpnext` or
  `apps/frappe`.
- Android implementation must not start until a separate implementation
  plan is written and approved at
  `POSERPNext/docs/mobile-pos/implementation-plan.md`.

### Technology Constraints

- Android: Kotlin, XML Views, ViewBinding, minSdk 23. No Jetpack Compose
  without explicit approval.
- Backend: Python 3.14, Frappe 16, ERPNext 16, MariaDB.
- The app must be lightweight for low-end devices.

---

## Document Cross-References

| Document | Scope |
| --- | --- |
| [architecture.md](architecture.md) | System boundaries, component responsibilities, principal flows, deployment shape, and Phase 0 decisions. |
| [authentication.md](authentication.md) | OAuth 2.0 PKCE details, credential policies, route boundary, authorization model, DocType permission matrix, and security verification plan. |
| [api-contract.md](api-contract.md) | Versioned API endpoint specifications, request/response schemas, error codes, envelope formats, and compatibility rules. |
| [idempotency-and-recovery.md](idempotency-and-recovery.md) | Idempotency key contract, durable record schema, standard and closing-specific transaction algorithms, recovery protocol, and cleanup rules. |
| [integration-boundaries.md](integration-boundaries.md) | Ownership matrix, ERPNext/Frappe/bakery integration rules, forbidden integration patterns, customer boundary, and dependency direction. |
| [implementation-plan.md](implementation-plan.md) | Backend task-by-task implementation plan with phase roadmap, file map, test strategy, and acceptance criteria. |
