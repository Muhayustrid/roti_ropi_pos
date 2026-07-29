# Mobile POS Backend Gateway: Android Handoff

This document gives a new Android implementation session enough backend context to consume the shipped Mobile POS API. Runtime code and [`api-contract.md`](api-contract.md) remain authoritative.

## Status and Scope

`roti_ropi_pos` is the completed Frappe/ERPNext v16 backend gateway for a separately implemented Android POS client. It owns:

- OAuth/client/cashier boundary enforcement;
- versioned Mobile POS endpoints and stable DTO/error envelopes;
- profile, session, customer, catalog, sale, return, and closing orchestration;
- durable idempotency and closing recovery.

ERPNext remains authoritative for POS Profile, Customer, Item, pricing, taxes, stock, batches, serials, POS Opening Entry, POS Invoice, returns, closing, consolidation, and accounting. Android must not duplicate those rules.

Android is outside this repository and should be built separately in:

```text
/Users/rotiropi/DockerERPNext/POSERPNext
```

## Runtime Requirements

- Frappe and ERPNext v16.
- Required apps: `erpnext`, `bakery_manufacturing`, and `roti_ropi_pos`.
- **POS Settings > Invoice Type** must be `POS Invoice`.
- HTTPS base URL.
- Redis workers must run for queued closing consolidation.
- Each cashier uses an individual enabled Frappe User with only `Mobile POS Cashier` plus exported minimum DocPerm fixtures.
- Each cashier must be assigned to an enabled POS Profile.

## Authentication

Use OAuth 2.0 Authorization Code with mandatory PKCE S256 through a system browser or Custom Tab.

Android is a public client:

- never embed or send a client secret;
- never use API keys, Basic auth, shared cashier users, Administrator credentials, or a credential WebView;
- generate a high-entropy verifier and S256 challenge for each authorization attempt;
- validate `state` before exchanging the authorization code;
- store access and refresh tokens using Keystore-backed encryption;
- send `Authorization: Bearer <access_token>` on every v1 API call.

Allowed OAuth routes for the configured client are:

```text
/api/method/login
/api/method/frappe.integrations.oauth2.authorize
/api/method/frappe.integrations.oauth2.approve
/api/method/frappe.integrations.oauth2.get_token
```

Configure one public OAuth Client per site, then store its ID in site config:

```bash
bench --site <site> set-config mobile_pos_oauth_client_id <client-id>
```

OAuth Client settings:

- grant type: Authorization Code;
- response type: Code;
- token endpoint authentication: None;
- scope: `all`;
- `skip_authorization = 0`;
- allowed role: `Mobile POS Cashier`;
- exact approved Android redirect URI;
- no distributed client secret.

## Transport Contract

Base endpoint path:

```text
https://<site>/api/method/roti_ropi_pos.api.v1.<module>.<method>
```

Common headers:

```http
Authorization: Bearer <access_token>
Accept: application/json
Content-Type: application/json
```

Add a client-generated lowercase UUID header only for business mutations:

```http
X-Idempotency-Key: <lowercase-uuid>
```

Required on:

- `POST sessions.open`;
- `POST sales.submit`;
- `POST sales.create_return`;
- `POST closing.submit`.

Do not add it to GET requests, `catalog.scan`, or `catalog.quote_item`.

Send monetary values and quantities as JSON decimal strings, never floating-point numbers. Frappe wraps method return values in top-level `message`:

```json
{
  "message": {
    "ok": true,
    "data": {},
    "meta": {
      "api_version": "v1",
      "request_id": "...",
      "server_time": "2026-07-29T12:00:00+00:00",
      "replayed": false
    }
  }
}
```

Expected domain errors use:

```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "INVALID_REQUEST",
      "message": "...",
      "details": {},
      "retryable": false
    },
    "meta": {
      "api_version": "v1",
      "request_id": "...",
      "server_time": "...",
      "replayed": false
    }
  }
}
```

Authentication, route-hook, malformed-route, rate-limit, and some server failures occur before endpoint code and use native Frappe bodies. Android must classify HTTP 401, 403, 404, 429, and 5xx without assuming `message.ok` exists.

## Endpoint Inventory

| HTTP | Endpoint | Android responsibility |
| --- | --- | --- |
| GET | `bootstrap.get` | Load cashier, profiles, selected profile, opening, capabilities, and POS mode. Optional `pos_profile`. |
| GET | `sessions.current` | Read current opening for required `pos_profile`. |
| POST | `sessions.open` | Send `pos_profile` and `opening_balances[{mode_of_payment, amount}]`. |
| GET | `customers.search` | Search existing Customers using `pos_profile`, `q`, `start`, and `limit`. |
| GET | `catalog.search` | Search scoped items using `pos_profile`, `q`, optional `item_group`, `start`, and `limit`. |
| POST | `catalog.scan` | Send `pos_profile` and scanned `value`. |
| POST | `catalog.quote_item` | Send profile, item, quantity, UOM, optional customer and batch. Treat quote as UI snapshot. |
| POST | `sales.submit` | Send accepted total, item identities/selections, and payments. Server rebuilds authoritative invoice. |
| GET | `sales.get` | Read scoped POS Invoice detail by `name`. |
| GET | `sales.list` | Read scoped history by profile/status/query/pagination. |
| POST | `sales.create_return` | Send source POS Invoice, reason, source row IDs, quantities, and negative refund payments. |
| GET | `closing.preview` | Load server-derived opening, invoice count, total, and expected payments. |
| POST | `closing.submit` | Send profile and counted closing balances. |
| GET | `closing.status` | Poll scoped closing by `name` while status is `queued`. |

No v1 health, cancellation, Customer mutation, return-preview, closing-retry, upload, generic resource, Desk, or generic RPC endpoint exists.

## Critical Request Shapes

### Sale

```json
{
  "pos_profile": "OUTLET-01",
  "customer": null,
  "walk_in_customer_name": "Ayu",
  "client_accepted_grand_total": "55000",
  "items": [
    {
      "item_code": "CROISSANT-PACK",
      "qty": "2",
      "uom": "Pack",
      "batch_no": "BATCH-QR-0001",
      "serial_numbers": []
    }
  ],
  "payments": [
    {"mode_of_payment": "Cash", "amount": "55000", "reference_no": null}
  ]
}
```

Response data contains `sale: SaleDetail`. Client total is only an acceptance check. Server derives profile, cashier, company, warehouse, accounts, prices, discounts, taxes, stock, and document state. Every submitted MVP sale must be fully settled.

### Return

Get `source_item_row` from `sales.get` response at `sale.items[].row_id`:

```json
{
  "source_name": "ACC-PSINV-2026-00001",
  "reason": "Customer returned one pack",
  "items": [
    {"source_item_row": "row-id-1", "qty": "1"}
  ],
  "payments": [
    {"mode_of_payment": "Cash", "amount": "-30000", "reference_no": null}
  ]
}
```

Response data contains `return_sale: SaleDetail`. Returns use ERPNext mapping and enforce remaining return quantity. V1 does not cancel sales.

### Closing

```json
{
  "pos_profile": "OUTLET-01",
  "closing_balances": [
    {"mode_of_payment": "Cash", "closing_amount": "975000"}
  ]
}
```

Closing status is one of `draft`, `queued`, `submitted`, `failed`, or `cancelled`. Poll `closing.status` after a `queued` response. A failed closing exposes only `CLOSING_FAILED`; manager review happens in ERPNext Desk.

## Lifecycle

1. Authenticate through browser-based OAuth Authorization Code + PKCE S256.
2. Call `bootstrap.get`; select an authorized profile.
3. Call `sessions.current`. Open a session only when none exists and capability allows it.
4. Search Customers and catalog; use scan and quote for cart UI.
5. Submit fully settled sale with one persistent idempotency key.
6. On lost response, retry the same normalized body with the same key.
7. Use `sales.get`/`sales.list` for reconciliation and history.
8. Use `sales.create_return` for cashier corrections.
9. Call `closing.preview`, collect counted balances, then call `closing.submit`.
10. Poll `closing.status` until terminal.

A prior-day submitted/Open/unclosed opening remains valid and includes `STALE_OPENING`; no maximum shift-duration policy exists.

## Idempotency and Retry

Persist each pending mutation's normalized body, idempotency UUID, operation, and state locally until terminal.

- Timeout or connection loss: retry same body and same key.
- HTTP 429/503: honor `Retry-After`; retry same key.
- HTTP 500: limited same-key retries, then reconcile through read/status endpoint.
- HTTP 401: stop mutation retries, preserve pending body/key, re-authenticate.
- `REQUEST_IN_PROGRESS`: wait using server details, then retry or poll.
- `IDEMPOTENCY_KEY_REUSED`: stop; key was reused with different data.
- User-correctable 4xx/422: corrected logical action gets a new key.
- Replay success returns HTTP 200 and `meta.replayed = true`.

Server scopes idempotency by cashier, operation, and key. Terminal records are retained for 90 days.

## Android Boundaries

Do not implement:

- offline accounting or a parallel ledger;
- client-side authoritative pricing, tax, stock, batch, serial, or account rules;
- Customer creation/update;
- sale cancellation;
- partial/unpaid sales;
- direct Sales Invoice mode;
- generic Frappe API access;
- embedded secrets or shared credentials.

Recommended Android responsibilities: encrypted token storage, typed DTOs, pending-action persistence, same-key retry, WorkManager network retry, status reconciliation, XML Views/ViewBinding UI, accessibility, and secure log redaction.

## Source References

Read these before Android implementation:

- [`api-contract.md`](api-contract.md) — exact v1 request, response, DTO, and error contract.
- [`authentication.md`](authentication.md) — OAuth/PKCE and credential lifecycle.
- [`idempotency-and-recovery.md`](idempotency-and-recovery.md) — retry and recovery rules.
- [`integration-boundaries.md`](integration-boundaries.md) — ownership and ERPNext/bakery boundaries.
- [`product-requirements.md`](product-requirements.md) — authoritative MVP product scope.
- [`../../README.md`](../../README.md) — site setup and runtime requirements.

Backend executable evidence lives in `roti_ropi_pos/tests/`, especially `test_mobile_pos_flow.py`, `test_authentication.py`, `test_sales.py`, `test_closing.py`, and `test_source_contracts.py`.
