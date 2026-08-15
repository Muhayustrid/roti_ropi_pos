# Roti Ropi Mobile POS Project Specification

## 1. Purpose

`roti_ropi_pos` is a Frappe application that provides a secure, versioned
Mobile POS backend facade for Roti Ropi bakery cashiers. It exposes a bounded
API for an Android client while ERPNext remains authoritative for POS profiles,
customers, opening entries, invoices, returns, closings, pricing, taxes,
payments, stock, batches, serial numbers, and accounting.

The project exists to:

- replace the heavy ERPNext web POS workflow on low-end Android devices;
- avoid broad ERPNext roles for cashiers;
- prevent duplicate business documents after retries or lost responses;
- preserve batch barcode UOM and walk-in display-name behavior; and
- keep all financial and stock-sensitive decisions on the server.

This repository contains the backend only. The Android client is maintained in
the separate `POSERPNext` repository.

## 2. Authority and Compatibility

This specification describes the current implemented project. Detailed public
payloads and error schemas remain normative in
[`api-contract.md`](api-contract.md).

When sources disagree, use this order:

1. installed Frappe and ERPNext source plus executable tests;
2. current `roti_ropi_pos` source and fixtures;
3. `api-contract.md` and recovery protocol documents;
4. this project summary;
5. historical planning text.

Supported runtime:

- Python `>=3.14`;
- Frappe `>=16,<17`;
- ERPNext `>=16,<17`;
- MariaDB;
- `stock_additional` installed on the same bench.

`roti_ropi_pos/hooks.py:11` declares `erpnext` and `stock_additional` as
required apps.

## 3. Product Roles

### 3.1 Cashier

A cashier is an individual enabled Frappe User with:

- the `Mobile POS Cashier` role;
- an explicit assignment to an enabled POS Profile;
- no Sales Manager, Accounts Manager, System Manager, or Administrator role;
- access only through the approved OAuth and Mobile POS v1 routes.

Cashiers can sign in, open a shift, search and scan items, quote and submit
sales, search existing customers, view scoped sale history, create returns,
close a shift, and poll closing status.

### 3.2 Manager

Managers remain ERPNext Desk users. They own:

- OAuth Client and cashier provisioning;
- POS Profile, Company, Warehouse, Item, Customer, pricing, tax, and payment
  configuration;
- sale cancellation;
- failed-closing review and recovery;
- token revocation and user disablement.

No manager-mobile workflow exists in v1.

### 3.3 System Components

- **Android client** consumes only documented v1 DTOs and error contracts.
- **`roti_ropi_pos`** authenticates, authorizes, validates, deduplicates,
  orchestrates ERPNext documents, and maps stable responses.
- **ERPNext** performs business validation and ledger effects.
- **Frappe** provides OAuth, permissions, request handling, transactions,
  persistence, and workers.
- **`bakery_manufacturing`** currently owns Price Group synchronization and the
  existing walk-in display-name field boundary; `selling_additional` is the
  target owner after the selling cutover.
- **`stock_additional`** owns batch scan UOM enrichment.

## 4. MVP Scope

### 4.1 Included

- OAuth 2.0 Authorization Code with mandatory PKCE S256.
- Explicit cashier-to-POS-Profile assignment.
- Bootstrap and capability projection.
- Opening-session creation and recovery.
- Prior-day opening support with `STALE_OPENING` warning.
- Existing Customer search and selection.
- POS Profile default walk-in Customer.
- Optional walk-in display name for the default Customer only.
- Catalog search, barcode scan, item quote, and full-cart quote.
- Fully settled POS Invoice submission.
- Multiple distinct payment modes with exact settlement.
- Scoped sale history and detail.
- Return quote and idempotent return creation.
- Closing preview, submission, recovery, and async status polling.
- Durable idempotency and 90-day terminal retention.
- POS Invoice mode only.

### 4.2 Excluded

- Sales Invoice mode.
- Partially paid or outstanding invoices.
- Mobile sale cancellation.
- Customer creation or modification.
- Offline ledger or offline accounting.
- Mobile closing retry or cancellation after terminal failure.
- Manager mobile features.
- Health endpoint.
- Maximum shift-duration policy.
- Web/PWA frontend in this repository.
- Production deployment automation.

## 5. Primary Workflows

### 5.1 Authenticate and Bootstrap

1. Android opens Frappe authorization in the system browser or Custom Tab.
2. Android uses Authorization Code with a high-entropy PKCE S256 verifier.
3. Android exchanges the code without a client secret.
4. Android calls `bootstrap.get` with the resulting Bearer token.
5. Backend derives identity from `frappe.session.user`.
6. Backend returns assigned profiles, selected profile, current opening,
   unresolved closing, supported POS mode, and server-derived capabilities.

### 5.2 Open a Shift

1. Cashier selects an assigned POS Profile.
2. Android sends opening balances and one `X-Idempotency-Key`.
3. Backend validates payment modes and exact decimal-string amounts.
4. Backend serializes conflicting opening decisions with profile/user locks.
5. ERPNext creates and submits one POS Opening Entry.
6. Retry with the same key and body returns the same opening.

A valid prior-day opening remains active. The API returns `STALE_OPENING`; it
does not block sales. Current implementation allows at most one Open entry per
POS Profile globally and at most one Open entry per cashier globally
(`roti_ropi_pos/mobile_pos/sessions.py:73-106`).

### 5.3 Build and Submit a Sale

1. Cashier searches or scans items.
2. Backend resolves the effective ERPNext scan override so batch UOM
   enrichment applies.
3. Android requests item or cart quotes for display.
4. Android sends item identities, quantities, UOM/batch/serial selections,
   accepted grand total, payment intent, and an idempotency key.
5. Backend locks the active opening and relevant stock rows.
6. Backend resolves the Customer without creating one.
7. Backend rebuilds a POS Invoice and asks ERPNext to calculate current values.
8. Backend rejects changed price, invalid stock identifiers, invalid payments,
   non-zero outstanding, or non-zero change.
9. ERPNext inserts and submits the invoice.
10. Backend returns authoritative receipt data.

Quotes are snapshots. They do not reserve stock or bind submission.

### 5.4 Return Items

1. Cashier opens a scoped POS Invoice detail.
2. Backend returns current cumulative return and remaining-quantity data.
3. Android may request `sales.quote_return` without creating a document.
4. Android submits source row IDs, positive quantities, required reason,
   conditional refund mode, and an idempotency key.
5. Backend locks the source invoice and recalculates remaining quantities.
6. ERPNext maps and submits one negative POS Invoice return.
7. Backend appends the reason without replacing existing remarks.

A return cannot exceed remaining quantity. Partial return of serialized rows is
not supported because Android does not select physical serials.

### 5.5 Close a Shift

1. Backend derives the opening, invoice set, payment snapshot, and totals.
2. `closing.preview` returns a server-owned `preview_id` and counted-amount
   policy.
3. Android submits the exact payment-mode set, counted amounts, preview ID,
   and one idempotency key.
4. Backend revalidates the snapshot while holding the Opening lock.
5. Backend creates and submits one POS Closing Entry through the closing
   recovery executor.
6. Fewer than 10 invoices follow synchronous ERPNext submission.
7. At least 10 invoices enter the queued path after the Closing commits.
8. Android polls `closing.status` until `submitted` or `failed`.

A linked Draft, Queued, or Failed closing blocks new sale, return, opening, and
closing mutations. An unlinked `Reserved` Processing request appears in
session/bootstrap recovery state but does not currently block sale or return
services until the Closing Entry is linked to the Opening. Failed closing
requires manager review in Desk.

## 6. Backend Architecture

```text
POSERPNext Android
        |
        | HTTPS + OAuth Bearer + v1 DTOs
        v
roti_ropi_pos.api.v1
        |
        +-- auth_hook / authorization
        +-- validation / responses
        +-- sessions / customers / catalog / invoices / closing
        +-- idempotency / Mobile POS Request
        |
        +-- ERPNext controllers and documents
        +-- effective stock_additional scan override
```

### 6.1 Modules

| Module | Responsibility |
| --- | --- |
| `roti_ropi_pos.api.v1` | Whitelisted HTTP adapters, request parsing, method restrictions, and unknown-field rejection |
| `mobile_pos.auth_hook` | Exact route allowlist, OAuth client validation, Bearer enforcement, and PKCE policy |
| `mobile_pos.authorization` | Current user, role, POS mode, profile assignment, capability, and DocType permission checks |
| `mobile_pos.responses` | Stable envelopes, request IDs, savepoints, rollback, and expected-error mapping |
| `mobile_pos.validation` | Exact decimal-string and quantity policies |
| `mobile_pos.sessions` | Current/opening lifecycle and stale-opening projection |
| `mobile_pos.customers` | Permission-aware existing Customer search and resolution |
| `mobile_pos.catalog` | Catalog search, effective scan override, item details, and stock snapshots |
| `mobile_pos.invoices` | Cart quote, sale submission, history, detail, return quote, and return creation |
| `mobile_pos.closing` | Preview identity, closing creation, recovery, receipt, and status |
| `mobile_pos.idempotency` | Durable mutation reservation, replay, audit correlation, and cleanup |
| `overrides.pos_invoice` | Mobile invoice-to-opening binding |
| `overrides.pos_closing_entry` | Safe after-commit queued consolidation boundary |

### 6.2 Dependency Rules

Allowed:

- normal ERPNext document APIs and verified public controller boundaries;
- effective whitelisted-method resolution for stock barcode behavior;
- persisted ERPNext data and registered hooks.

Forbidden:

- editing Frappe or ERPNext source;
- direct Android access to generic Frappe resources or ERPNext helpers;
- copying ERPNext ledger, pricing, tax, or stock algorithms;
- importing private `stock_additional` helpers or exception types (or private
  `bakery_manufacturing` helpers);
- raw SQL assembled from mobile input;
- `ignore_permissions=True` for ERPNext business documents;
- direct API-service calls to merge-log creation or cancellation helpers.

Current implementation discrepancy: closing submission and queued consolidation
temporarily switch server context to `Administrator` after cashier permission
checks (`roti_ropi_pos/mobile_pos/closing.py:216-222,606-620`). This conflicts
with the repository rule requiring normal permissions for ERPNext business
documents and remains security debt until removed.

## 7. Public API v1

Base path:

```text
/api/method/roti_ropi_pos.api.v1.<module>.<method>
```

Every endpoint requires:

- HTTPS enforced by the deployment reverse proxy; the application endpoint
  layer does not reject plain HTTP itself;
- configured-client Bearer authentication;
- enabled current user;
- `Mobile POS Cashier` role;
- supported `POS Invoice` mode;
- exact route allowlisting;
- operation-specific profile and document permissions.

### 7.1 Endpoint Inventory

| Method | Endpoint | Mutation | Purpose |
| --- | --- | ---: | --- |
| GET | `bootstrap.get` | No | User, profiles, opening, closing, capabilities |
| GET | `sessions.current` | No | Current opening and closing projection |
| POST | `sessions.open` | Yes | Create and submit Opening Entry |
| GET | `customers.search` | No | Search existing eligible Customers |
| GET | `catalog.search` | No | Search profile-scoped saleable items |
| POST | `catalog.scan` | No | Resolve barcode, batch, or serial |
| POST | `catalog.quote_item` | No | Calculate one item snapshot |
| POST | `sales.quote_cart` | No | Calculate authoritative cart snapshot at response time |
| POST | `sales.submit` | Yes | Create and submit fully settled POS Invoice |
| GET | `sales.list` | No | List cashier-owned profile/company invoices |
| GET | `sales.get` | No | Read scoped sale detail and returnability |
| POST | `sales.quote_return` | No | Calculate return accounting without persistence |
| POST | `sales.create_return` | Yes | Create and submit POS Invoice return |
| GET | `closing.preview` | No | Calculate bound closing snapshot |
| POST | `closing.submit` | Yes | Create and submit/recover Closing Entry |
| GET | `closing.status` | No | Read refreshed closing receipt and status |

Detailed payloads, DTOs, HTTP statuses, and stable error schemas are defined in
[`api-contract.md`](api-contract.md).

### 7.2 Response Rules

Successful in-endpoint responses contain:

- `ok: true`;
- `data`;
- `meta.api_version`;
- `meta.request_id`;
- `meta.server_time`;
- `meta.replayed`.

Expected in-endpoint errors contain:

- `ok: false`;
- stable `error.code`;
- human-readable `error.message`;
- object-valued `error.details`;
- `error.retryable`;
- the same metadata fields.

Authentication, route rejection, rate limiting, malformed routing, and some
server failures occur before the endpoint wrapper and retain Frappe-native
error bodies.

Response compatibility rules:

- additive fields may appear within v1;
- clients must ignore unknown response fields;
- existing type, meaning, and requiredness cannot break within v1;
- breaking changes require parallel `api.v2` modules;
- unlisted ERPNext fields are not public contract.

## 8. Security Model

### 8.1 OAuth

Android is a public OAuth client:

- Authorization Code only;
- PKCE challenge required and method exactly `S256`;
- no client secret issued or embedded;
- system browser or secure Custom Tab only;
- Bearer scheme required for v1 API calls;
- active token must belong to the configured Mobile POS OAuth Client and
  `frappe.session.user`;
- disabled users and wrong-client tokens are rejected.

Prohibited credentials include API keys, Basic credentials, session-cookie API
calls, shared cashier credentials, service-user credentials, and Administrator
credentials.

### 8.2 Route Boundary

`roti_ropi_pos/mobile_pos/auth_hook.py:10-37` defines exact mobile and OAuth
paths. Cashier access to generic `/api/method`, `/api/resource`, uploads, Desk,
legacy `cmd`, encoded alternate paths, and `/api/v2/method` is rejected.

### 8.3 Cashier DocType Permissions

| DocType | Allowed permissions |
| --- | --- |
| Account | select |
| POS Profile | read |
| POS Opening Entry | read, create, write, submit |
| POS Invoice | read, create, write, submit |
| POS Closing Entry | read, create, write, submit |
| Customer | read |
| Item | read |
| Sales Invoice | none |
| Mobile POS Request | none for cashier; service-controlled |

No cashier cancel, delete, amend, report, export, import, or share permission is
allowed. Current fixtures also grant Serial and Batch Bundle read, create,
write, and submit permission, but `AGENTS.md` does not approve that DocType in
the exact cashier permission set. Treat this as implementation drift requiring
fixture removal or explicit policy approval, not part of the approved model.

### 8.4 Trust Boundary

The backend derives or recalculates:

- user and owner;
- Company, POS Profile, Warehouse, and price list;
- document names and status;
- rates, discounts, taxes, accounts, and totals;
- payment accounts and payable amount;
- opening and closing invoice sets;
- stock, batch, serial, and return limits.

Client attempts to control restricted fields are rejected.

## 9. Data Model and Hooks

### 9.1 `Mobile POS Request`

The app-owned DocType stores durable mutation state:

- unique scope key;
- idempotency UUID;
- stable operation ID;
- canonical request hash;
- authenticated user;
- `Processing`, `Completed`, or `Rejected` status;
- closing recovery phase and lease;
- ERPNext business reference;
- original HTTP status and stable response JSON;
- resolution and expiry timestamps;
- audit-correlation flag;
- retention hold and reason.

Normal users cannot create, write, or delete these rows through Desk.

### 9.2 Custom Fields

- `POS Payment Method.custom_mobile_pos_suggested_opening_amount` stores the
  server-projected opening suggestion.
- `custom_mobile_pos_transaction_id` is persisted read-only on POS Opening
  Entry, POS Invoice, and POS Closing Entry.
- `custom_walk_in_customer_name` is owned by `bakery_manufacturing`, not this
  app; `selling_additional` is the target owner after the selling cutover.

### 9.3 Active Hooks

`roti_ropi_pos/hooks.py` registers:

- required apps;
- daily expired-request cleanup;
- POS Invoice controller override;
- POS Closing Entry controller override;
- Custom Field, Role, and Custom DocPerm fixtures;
- Mobile POS authentication hook.

## 10. Idempotency and Recovery

Every mutation requires a lowercase UUID `X-Idempotency-Key`:

- `v1.sessions.open`;
- `v1.sales.submit`;
- `v1.sales.create_return`;
- `v1.closing.submit`.

Deduplication scope is authenticated user, server-owned operation ID, and key.
The server hashes canonical validated request data.

Rules:

- same key and same hash returns the original business result;
- replay returns HTTP 200 and sets `meta.replayed = true`;
- same key with a different hash returns `IDEMPOTENCY_KEY_REUSED`;
- an active same-key operation returns `REQUEST_IN_PROGRESS`;
- business logic runs once;
- the business document must persist the same transaction UUID before the
  request can become `Completed`.

Standard mutations keep business and request records in one request
transaction. Exceptions roll both back.

Closing uses a documented exception because ERPNext closing may commit or
enqueue during submission. It durably progresses through reservation, Draft
creation, submit start, and reconciliation. A lease prevents concurrent
recovery. Replays resume or reconcile the same Closing Entry; they never create
a replacement close.

Terminal cleanup runs daily:

- completed/rejected, unheld rows expire after 90 days;
- Processing, leased, unresolved, failed-under-review, incident-held, and
  audit-held rows are preserved;
- referenced document transaction ID must match before deletion;
- cleanup never deletes or edits ERPNext business documents.

## 11. Business Invariants

### 11.1 POS Mode

`POS Settings.invoice_type` must equal `POS Invoice`. Every v1 endpoint returns
`UNSUPPORTED_POS_MODE` for another mode.

### 11.2 Customer

- Customer must already exist, be enabled, permission-visible, and satisfy the
  profile Customer Group closure when configured.
- Omitted Customer resolves to `POS Profile.customer`.
- Default Customer is validated like explicit selection.
- Walk-in display name is allowed only for that default Customer.
- Search, quote, sale, return, and recovery never create a Customer.

### 11.3 Quantities and Money

Client quantities and monetary values use exact JSON decimal strings:

- ASCII digits with an optional decimal point;
- no JSON float, whitespace, grouping, exponent, or implicit locale parsing;
- no rounding or truncation;
- server-projected precision and bounds apply;
- sale payments must be positive;
- opening and closing counted values may be zero where their policy permits.

### 11.4 Sale

- Active submitted opening is mandatory.
- Prices, taxes, stock, UOM, batch, serial, and totals are recalculated.
- Accepted grand total must match current authoritative grand total.
- Payment modes must be distinct and profile-enabled.
- Payment sum must equal authoritative payable exactly.
- Underpayment and overpayment are rejected.
- Submitted invoice must have zero outstanding and zero change.

### 11.5 Return

- Source must be a visible submitted non-return POS Invoice.
- Return rows reference unique source item rows.
- Requested quantity cannot exceed current remaining quantity.
- Return reason is required and appended to remarks.
- Refund modes and allocations are server-controlled.
- Mobile cancellation does not exist.

### 11.6 Closing

- Opening, profile, cashier, invoice, payment, and total data are server-derived.
- Submitted `preview_id` must match the locked current snapshot.
- Counted balances must contain the exact preview payment-mode set once each.
- Queued is accepted but nonterminal.
- Failed closing requires manager review.

## 12. Non-Functional Requirements

### 12.1 Security

- No embedded client secrets, API keys, or shared credentials.
- No internal stack traces or unrestricted documents in stable responses.
- Credentials and authorization headers must not enter logs or stored response
  bodies.
- Scope checks occur before business-document access.

### 12.2 Reliability

- Retries, timeouts, process restarts, and response loss must not duplicate
  business documents.
- Different keys racing on the same business resource remain serialized through
  business locks and ERPNext validation.
- Closing recovery must preserve one request and one Closing Entry.

### 12.3 Precision

- Monetary and quantity values cross the API as strings.
- Android must use server-projected decimal policies.
- Server comparisons use exact decimal arithmetic.

### 12.4 Performance

- Common local-network operations target sub-second response time.
- Pagination is bounded to 100 returned records.
- Android UI must remain suitable for low-end devices.
- Catalog stock and quote results are informational snapshots.

### 12.5 Maintainability

- Android depends only on versioned DTOs, not Frappe document shapes.
- Backend reuses ERPNext controllers instead of duplicating business logic.
- Imported core boundaries require source-contract tests before dependency
  upgrades.

### 12.6 Auditability

- Every created mobile business document stores its transaction UUID.
- Request IDs identify server diagnostics.
- Terminal request records remain available for 90 days unless longer holds
  apply.

## 13. Configuration and Deployment

Required site setup:

1. Install ERPNext, `stock_additional`, and `roti_ropi_pos` on one bench.
2. Set **POS Settings > Invoice Type** to **POS Invoice**.
3. Configure Companies, Warehouses, Items, Customers, prices, taxes, POS
   Profiles, and payment modes in ERPNext Desk.
4. Create dedicated enabled cashier Users.
5. Assign only `Mobile POS Cashier` and explicit enabled POS Profiles.
6. Configure a public OAuth Client for Authorization Code, response type Code,
   token endpoint authentication method `None`, scope `all`, allowed role
   `Mobile POS Cashier`, consent enabled, and approved redirect URI.
7. Store the client ID per site:

```bash
bench --site <site> set-config mobile_pos_oauth_client_id <client-id>
```

No separate API gateway or database is required. Existing Frappe workers handle
queued closing consolidation.

## 14. Verification

Run from `/workspace/development/frappe-bench`:

```bash
bench --site development.localhost run-tests --app roti_ropi_pos
```

Target individual modules with:

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.<module>
```

Run static checks from `apps/roti_ropi_pos`:

```bash
pre-commit run --all-files
```

Required coverage includes:

- OAuth PKCE S256 and exact route denial;
- role and DocType permission fixtures;
- cross-user, profile, and Company isolation;
- customer eligibility and no creation;
- opening conflict and stale warning;
- catalog, scan override, UOM, stock, batch, and serial behavior;
- exact sale settlement and price-change rejection;
- same-key and distinct-key concurrency;
- return limits, refund modes, and reason handling;
- synchronous and queued closing boundaries;
- closing response-drop recovery and serialization;
- safe 90-day cleanup;
- Frappe, ERPNext, `stock_additional`, and bakery source contracts.

Production-like queued closing requires a staging test with developer mode off,
active workers, and at least 10 invoice rows. Frappe test mode may execute
queued jobs immediately and does not alone prove worker polling.

## 15. Acceptance Criteria

Backend MVP is accepted when fresh verification proves:

1. A dedicated cashier can bootstrap, open, quote, sell, view, return, preview
   closing, submit closing, and read terminal closing status.
2. Cashier needs no broad ERPNext manager role.
3. Cashier cannot access generic Frappe, Desk, resource, upload, or unapproved
   method routes.
4. Every submitted sale has zero outstanding and zero change.
5. Same-key concurrent retries create exactly one business document.
6. Different-key business races respect stock, return, opening, and closing
   limits.
7. Customer search and transactions create no Customer records.
8. Walk-in display name works only for the profile default Customer.
9. Batch barcode UOM enrichment resolves through the registered override.
10. Return quantities and refund modes remain server-authoritative.
11. Closing supports synchronous and queued paths without duplicate closing.
12. Request cleanup preserves recovery/audit records and all business documents.
13. Full app tests, static checks, dependency regressions, and security review
    pass on the deploy image.

Backend acceptance does not establish complete product delivery. Android build,
contract, device, credential-storage, UX, and release tests belong to the
separate Android repository.

## 16. Known Documentation Drift

Current source resolves these older document statements:

- `sales.quote_return` is implemented and part of v1, despite an old PRD row
  calling return preview out of scope.
- `sales.list` currently scopes history by owner, authorized profile, and
  Company; it does not limit results to the current opening period.
- Opening conflict rules are global per profile and global per cashier, not
  only per cashier/profile pair.
- Early `architecture.md` text describing this app as an unimplemented minimal
  app is historical; current source contains the complete v1 backend facade.
- Current closing internals switch server context to `Administrator`, contrary
  to the normal-permission rule for ERPNext business documents.
- Current fixtures grant Serial and Batch Bundle permissions absent from the
  exact cashier permission policy in `AGENTS.md`.

## 17. Companion Documents

| Document | Detail |
| --- | --- |
| [`product-requirements.md`](product-requirements.md) | Product vision, journeys, scope, and open product decisions |
| [`architecture.md`](architecture.md) | Design history, component boundaries, and deployment shape |
| [`authentication.md`](authentication.md) | OAuth, route gate, credentials, and permission model |
| [`api-contract.md`](api-contract.md) | Exact endpoint payloads, DTOs, HTTP behavior, and stable errors |
| [`idempotency-and-recovery.md`](idempotency-and-recovery.md) | Standard mutation and closing recovery algorithms |
| [`integration-boundaries.md`](integration-boundaries.md) | ERPNext, Frappe, extracted-app, and Android ownership boundaries |
| [`testing-strategy.md`](testing-strategy.md) | Required scenarios, commands, regressions, and release evidence |
| [`implementation-plan.md`](implementation-plan.md) | Backend task and phase history |
