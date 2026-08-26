# Android Integration Guide — Mobile POS v1 Gateway

**START HERE.** Read this document before writing or modifying any Android networking, domain,
persistence, or recovery code. It is the single Android-facing entry point for the `roti_ropi_pos`
Mobile POS gateway.

**Status:** audited against runtime source on 2026-08-26. Runtime source and its executable tests are
the authority. The 20 Mobile POS methods are available (17 v1 + 3 Dynamic Promotion facades, POST-only). The Dynamic Promotion sale field and authoritative combined quote are now available; see §7.18 for the closed route and quote contracts.

**Companion documents** (this guide does not repeat them):

| Document | Use it for |
| --- | --- |
| `api-contract.md` | The normative v1 envelope, error, and per-endpoint schema decisions |
| `authentication.md` | OAuth/PKCE decisions and the exact cashier permission policy |
| `idempotency-and-recovery.md` | The durable-request design rationale |
| `backend-readiness-audit.md` | The finding IDs (C-*, I-*, M-*) referenced in §19 |

---

## 1. Purpose

This guide exists so that an Android developer or an Android AI agent never has to guess:

- which endpoints exist,
- what a request and response actually contain,
- which headers are mandatory,
- what an error code means and whether it may be retried,
- what the app must persist to survive a crash mid-mutation,
- who owns each value — the server or the client,
- and in what order the business flow must run.

Anything not stated here, or not stated in `api-contract.md`, is **not** part of v1. Do not infer it.

## 2. Non-negotiable architecture rules

1. **The current gateway surface is exact for dedicated mobile-only cashiers.** Android uses an account
   with only `Mobile POS Cashier`. That account may call the 20 whitelisted methods (17 `roti_ropi_pos.api.v1.*` + 3 `selling_additional.overrides.pos_promo_api.*` POST-only) and OAuth routes. Other routes are rejected. A user with a desk-access role follows normal Frappe authorization and must never be provisioned as an Android cashier. See §7.18 for the Dynamic Promotion facade and quote contracts (now closed).
2. **The server owns all money, stock, tax, and accounting truth.** Android sends intent, renders the
   server's answer. See §16.
3. **Every mutation is idempotent and durable.** Four endpoints require `X-Idempotency-Key`; the key
   and the exact request body must be persisted before the call and retried unchanged. See §10.
4. **POS Invoice mode only.** Any other site invoice mode returns `UNSUPPORTED_POS_MODE`.
5. **Full settlement only.** Partial payment is not supported; `profile.allow_partial_payment` is
   always `false`.
6. **Android never creates a Customer.** It selects an existing one or uses the profile default.
7. **The error enum is frozen from §14.** An unknown code is a protocol violation, not a business
   state — surface it, never silently swallow it.

## 3. Base URL and canonical routing

Every gateway call is a Frappe whitelisted-method call:

```
POST|GET https://<site-host>/api/method/roti_ropi_pos.api.v1.<module>.<method>
```

- `<site-host>` is environment configuration, never hardcoded in a release build.
- The canonical dotted path is the endpoint's identity. Suffix, slash, encoded, `/api/v2/`, and
  `cmd=` variants are rejected by the auth hook even when they resolve to the same Python function.
- Frappe wraps a whitelisted return value in a top-level `message` object. Android must unwrap it:

```json
{ "message": { "ok": true, "data": { }, "meta": { } } }
```

- Successful envelope:

```json
{
  "ok": true,
  "data": { },
  "meta": {
    "api_version": "v1",
    "request_id": "8sk2mfq0d7yn41vbxc9the5paz",
    "server_time": "2026-08-19T09:14:22.418000+07:00",
    "replayed": false
  }
}
```

- Error envelope (HTTP status carries the class; `ok` is `false`):

```json
{
  "ok": false,
  "error": {
    "code": "NO_OPEN_SESSION",
    "message": "This operation requires an open POS session.",
    "details": { "pos_profile": "Outlet Demo POS" },
    "retryable": false
  },
  "meta": {
    "api_version": "v1",
    "request_id": "q4v7zx1m8ct0ns6yhaw3jrbe5d",
    "server_time": "2026-08-19T09:14:22.418000+07:00",
    "replayed": false
  }
}
```

### Failures that arrive without an envelope

Authentication failure, Guest rejection, route-hook rejection, rate limiting, malformed routing, and
unexpected server crashes happen **before** endpoint code runs and return Frappe's native error body.
Android must not require `message.ok` for these. Classify them by HTTP status alone:

| HTTP | Source | Android transport state |
| --- | --- | --- |
| 401 | Invalid or expired bearer token | `authentication_required` |
| 403 | Guest, route auth hook, or disallowed HTTP method | `route_forbidden` / `method_not_allowed` |
| 404 | Unknown or malformed API route | `route_not_found` |
| 429 | Frappe rate limiting | `rate_limited` |
| 500 / 503 | Unexpected server failure (no `error.code`) | `server_unavailable` |

These five names are Android-local states. They are **not** values of `error.code` and must never be
merged into the business error enum in §14.

## 4. Authentication

**Flow:** OAuth 2.0 Authorization Code with mandatory PKCE `S256`, public client, no client secret.

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/method/login` | POST | Login form inside the system browser or secure Custom Tab authorization session (`cmd=login`), never an app-controlled WebView |
| `/api/method/frappe.integrations.oauth2.authorize` | GET | Authorization request; `code_challenge` and `code_challenge_method=S256` are mandatory |
| `/api/method/frappe.integrations.oauth2.approve` | GET/POST | Consent; same PKCE requirement |
| `/api/method/frappe.integrations.oauth2.get_token` | POST | Code→token and refresh-token exchange |

Hard rules enforced by the runtime auth hook:

1. `code_challenge` must be non-empty and `code_challenge_method` must be exactly `S256`. `plain` and
   a missing challenge are rejected — including for a Guest authorization request.
2. The token endpoint rejects `client_secret`, HTTP Basic authentication, and any `grant_type` other
   than `authorization_code` or `refresh_token`. Android holds no secret.
3. Every gateway call sends `Authorization: Bearer <access_token>`. Cookie, API key/secret, Basic, and
   a bearer token issued to a different OAuth client are all rejected.
4. The bearer token must belong to the configured Mobile POS client, its user must match the session
   user, the token must be `Active` and unexpired, the user must be enabled, and the user must hold the
   `Mobile POS Cashier` role. Any failure is a pre-dispatch 401/403 with no envelope.
5. Legacy `cmd=` dispatch is rejected for the mobile client and for mobile-only accounts.

Use the system browser or an AppAuth-style custom tab, never an embedded WebView you control, and store
tokens in the Android keystore-backed store. Never log a token, code, or verifier.

**On HTTP 401:** stop all automatic mutation retries immediately, keep every pending idempotency record
on disk, refresh the token, and only then resume the pending mutation with its **original** key and
body. Discarding pending records on 401 can duplicate a sale.

## 5. Android startup sequence

Run this exact order on every cold start and after every token refresh:

1. **Token check.** No valid token → authenticate (§4). Never call a gateway endpoint without a bearer.
2. **`bootstrap.get`.** Read `profiles[]`, `selected_profile`, `opening_session`, `closing`,
   `capabilities`, `pos_mode`. If `pos_mode` is not `"POS Invoice"` or the call returns
   `UNSUPPORTED_POS_MODE`, block the app with a configuration screen — do not degrade to a local mode.
3. **Profile selection.** Exactly one profile → select it. Several → let the cashier pick. Zero →
   configuration error screen; the cashier is not assigned to any POS Profile.
4. **Branch on session state:**
   - `opening_session == null` → Open Session screen.
   - `opening_session.lifecycle_state == "active"` → Cashier Home.
   - `lifecycle_state == "closing_in_progress"` → Closing recovery flow (§13), not Cashier Home.
   - `lifecycle_state == "closing_failed"` → blocking manager-escalation screen (§13).
5. **Pending-mutation recovery.** Before enabling any input, drain the local pending-mutation queue
   (§10). A pending sale, return, or closing must be resolved before the cashier can start new work.
6. **Capabilities gate.** Enable UI actions strictly from `capabilities`. `cancel_sale` is always
   `false` in v1 — never render a cancel action.

`bootstrap.get` is a superset of `sessions.current`; do not call both at startup. Use
`sessions.current` afterwards for cheap refresh and for polling.

## 6. Screen-to-endpoint matrix

| Android screen / user action | Endpoint | Idempotency key | Notes |
| --- | --- | --- | --- |
| Login / token refresh | OAuth routes (§4) | — | Not part of the v1 envelope |
| App start, profile list | `bootstrap.get` | No | Superset of `sessions.current` |
| Session state refresh, polling | `sessions.current` | No | Cheap; safe to poll |
| Open Session → confirm | `sessions.open` | **Yes** | 201 create / 200 replay |
| Cashier Home | *(no call)* | — | Rendered from bootstrap + local cart |
| Catalog browse / paging | `catalog.search` | No | `start` ≤ 1000, `limit` ≤ 100 |
| Search box | `catalog.search` (`q`) | No | Debounce locally; server-side filter |
| Barcode scan | `catalog.scan` | No | **POST**, not GET |
| Customer picker | `customers.search` | No | Never creates a Customer |
| Add item to cart / change qty or UOM | `catalog.quote_item` | No | **POST**; authoritative per-line price |
| Cart totals | `sales.quote_cart` | No | **POST**; authoritative grand total and payable |
| Payment screen | *(no call)* | — | Rendered from the cart quote |
| Payment → submit sale | `sales.submit` | **Yes** | 201 create / 200 replay |
| Receipt | *(no call)* | — | Rendered from the submit/replay response |
| History list | `sales.list` | No | `limit` ≤ 100 |
| Sale detail | `sales.get` | No | Carries the returnability projection |
| Return builder preview | `sales.quote_return` | No | **POST**, read-only |
| Return → submit | `sales.create_return` | **Yes** | 201 create / 200 replay |
| Closing preview | `closing.preview` | No | Returns `preview_id` |
| Closing → submit counted cash | `closing.submit` | **Yes** | 201 create / 200 replay |
| Closing recovery after key loss | `closing.recover` | **No — forbidden** | Takes only `pos_profile` |
| Queued-consolidation polling | `closing.status` | No | Poll with backoff |
| Logout | **NOT PROVIDED BY BACKEND** | — | Local token deletion only; see §19 |

## 7. Complete endpoint reference

Twenty endpoints are currently allowed (17 `roti_ropi_pos.api.v1.*` + 3 `selling_additional.overrides.pos_promo_api.*` POST-only). This section is the complete v1 gateway surface. The three promotion facades are now allowlisted as POST-only (see §7.18) and are part of the allowed surface.

All decimal money and quantity values are **JSON strings** in `ascii_decimal_dot` syntax
(`"12500.00"`), never JSON numbers. Send them as strings and parse them into a decimal type — never a
float. Sending a JSON number where a decimal string is expected is rejected or silently reinterpreted
by the language runtime, and either way loses cents.

Unknown request fields are rejected with `INVALID_REQUEST` on every POST endpoint. Do not send fields
this document does not list.

### 7.1 `bootstrap.get`

- **Route:** `GET /api/method/roti_ropi_pos.api.v1.bootstrap.get`
- **Purpose:** one-shot startup state: user, assigned profiles, current session, closing projection,
  capabilities.
- **Auth:** bearer + `Mobile POS Cashier`. **Idempotency key:** no.
- **Params:** `pos_profile` (optional string). Omitted → the server picks when exactly one profile is
  assigned.
- **Response `data`:**

```json
{
  "user": { "name": "cashier.demo@example.test", "full_name": "Cashier Demo" },
  "profiles": [
    {
      "name": "Outlet Demo POS",
      "company": "Demo Company",
      "warehouse": "Outlet Demo - DC",
      "currency": "IDR",
      "selling_price_list": "Outlet Demo Retail",
      "customer": "Walk-In Demo",
      "allow_partial_payment": false,
      "invoice_mode": "POS Invoice",
      "opening_payment_modes": [
        { "mode_of_payment": "Cash", "suggested_opening_amount": "0.00", "amount_editable": true },
        { "mode_of_payment": "QRIS Demo", "suggested_opening_amount": "0.00", "amount_editable": true }
      ],
      "opening_amount_policy": {
        "currency": "IDR",
        "decimal_places": 2,
        "minimum": "0.00",
        "api_syntax": "ascii_decimal_dot",
        "rounding": "reject",
        "policy_version": "opening-amount/v1"
      }
    }
  ],
  "selected_profile": { "name": "Outlet Demo POS" },
  "opening_session": null,
  "closing": null,
  "capabilities": {
    "open_session": true,
    "submit_sale": false,
    "create_return": false,
    "cancel_sale": false,
    "close_session": false
  },
  "pos_mode": "POS Invoice"
}
```

`selected_profile` is a full profile object with the same keys as a `profiles[]` entry (abbreviated
above). `cancel_sale` is always `false`. Every other capability is `false` when no profile is selected,
and every one is `false` while an unresolved closing holds the session. A capability is also `false`
when the cashier lacks the underlying DocType permission, so treat the object as the single source of
truth for enabling UI actions rather than deriving it from session state.

- **Errors:** `PERMISSION_DENIED` 403, `PROFILE_SCOPE_MISMATCH` 403, `UNSUPPORTED_POS_MODE` 422,
  `INVALID_REQUEST` 400.
- **Retry:** safe to repeat (read-only). **Server authority:** everything. **Android:** stores
  `selected_profile.name` and renders capabilities.

### 7.2 `sessions.current`

- **Route:** `GET .../roti_ropi_pos.api.v1.sessions.current`
- **Params:** `pos_profile` (**required** string).
- **Response `data`:** `{ "opening_session": <OpeningSession|null>, "closing": <ClosingProjection|null> }`

```json
{
  "opening_session": {
    "name": "POS-OPE-2026-00042",
    "pos_profile": "Outlet Demo POS",
    "company": "Demo Company",
    "user": "cashier.demo@example.test",
    "status": "open",
    "lifecycle_state": "active",
    "closing": null,
    "posting_date": "2026-08-19",
    "period_start_date": "2026-08-19T08:03:11+07:00",
    "opening_balances": [
      { "mode_of_payment": "Cash", "opening_amount": "250000.00" }
    ],
    "warnings": []
  },
  "closing": null
}
```

- `lifecycle_state` ∈ `"active"`, `"closing_in_progress"`, `"closing_failed"`. This is the single field
  Android branches on.
- `warnings[]` may carry `{"code": "STALE_OPENING", "message": ..., "details": {"opening_date",
  "server_date"}}` when the shift started on an earlier calendar day. Informational only — a prior-day
  opening is still valid and must not be auto-closed by the client.
- `ClosingProjection` (also embedded as `opening_session.closing`):
  `{ "name": string|null, "status": "processing"|"draft"|"queued"|"submitted"|"failed"|"cancelled",
  "phase": "Reserved"|"DraftCreated"|"SubmitStarted"|null, "status_endpoint": "v1.closing.status"|null,
  "failure": {"code": "CLOSING_FAILED", "message": string}|null }`
- **Errors:** `INVALID_REQUEST` 400, `PROFILE_SCOPE_MISMATCH` 403, `PERMISSION_DENIED` 403,
  `UNSUPPORTED_POS_MODE` 422. **Retry:** safe.

### 7.3 `sessions.open`

- **Route:** `POST .../roti_ropi_pos.api.v1.sessions.open`
- **Headers:** `Authorization: Bearer …`, `Content-Type: application/json`,
  **`X-Idempotency-Key: <lowercase UUID>`**.
- **Request:**

```json
{
  "pos_profile": "Outlet Demo POS",
  "opening_balances": [
    { "mode_of_payment": "Cash", "amount": "250000.00" },
    { "mode_of_payment": "QRIS Demo", "amount": "0.00" }
  ]
}
```

The row field is **`amount`** on the wire. (`opening_amount` is the internal name after the adapter
renames it — do not send `opening_amount`.) Every mode must be one of
`profile.opening_payment_modes`; duplicates and an empty list are rejected. Amounts follow
`opening-amount/v1`: `ascii_decimal_dot`, no sign, no exponent, scale ≤ `decimal_places`,
`rounding: "reject"` — the server never rounds for you.

- **Response `data`:** `{ "opening_session": <OpeningSession> }` — same shape as §7.2.
- **HTTP:** `201` on create, `200` on replay (`meta.replayed: true`).
- **Errors:** `INVALID_REQUEST` 400 (bad key, unknown or duplicate mode, malformed amount),
  `PROFILE_SCOPE_MISMATCH` 403, `PERMISSION_DENIED` 403, `SESSION_ALREADY_OPEN` 409,
  `IDEMPOTENCY_KEY_REUSED` 409, `REQUEST_IN_PROGRESS` 409, `UNSUPPORTED_POS_MODE` 422,
  `PROFILE_CONFIGURATION_INVALID` 422, `TEMPORARILY_UNAVAILABLE` 503.
- **`SESSION_ALREADY_OPEN`** carries `opening_entry` and `pos_profile`. One open session per profile
  **and** one per cashier — a conflict on either raises it. Recovery: call `sessions.current` and adopt
  the existing session; never generate a new key and retry.

### 7.4 `customers.search`

- **Route:** `GET .../roti_ropi_pos.api.v1.customers.search`
- **Params:** `pos_profile` (**required**), `q` (optional, default `""`), `start` (optional, ≥ 0,
  default 0), `limit` (optional, default 20, capped at 100).
- **Response `data`:**

```json
{
  "customers": [
    { "name": "CUST-2026-00017", "customer_name": "Andi Demo", "mobile_no": "+620000000000",
      "is_default_walk_in": false },
    { "name": "Walk-In Demo", "customer_name": "Walk-In Demo", "mobile_no": null,
      "is_default_walk_in": true }
  ],
  "page": { "start": 0, "limit": 20, "has_more": false }
}
```

Only enabled Customers inside the profile's Customer Group closure are returned.
**Android must never create a Customer.** There is no create endpoint and none will be added in v1.

### 7.5 `catalog.search`

- **Route:** `GET .../roti_ropi_pos.api.v1.catalog.search`
- **Params:** `pos_profile` (**required**), `q` (optional), `item_group` (optional), `start`
  (optional, 0 ≤ `start` ≤ **1000** — beyond that is `INVALID_REQUEST`), `limit` (optional, default 20,
  capped at 100).
- **Response `data`:**

```json
{
  "items": [
    {
      "item_code": "DEMO-BREAD-001",
      "item_name": "Demo Sweet Bread",
      "description": "Demo bakery item",
      "image": "/files/demo-bread.png",
      "uom": "Pcs",
      "price_list_rate": "12000.00",
      "currency": "IDR",
      "available_qty": "48.0"
    }
  ],
  "page": { "start": 0, "limit": 20, "has_more": true }
}
```

Only items in the profile's item groups, sellable, enabled, non-variant, non-fixed-asset are listed.
`price_list_rate` here is a **catalog display price**, not a binding line price — the binding line
price comes from `catalog.quote_item` (§7.7). `available_qty` drifts as other terminals sell; treat it
as a hint, never as a reservation.

### 7.6 `catalog.scan`

- **Route:** `POST .../roti_ropi_pos.api.v1.catalog.scan` — **POST, not GET.**
- **Request:** `{ "pos_profile": "Outlet Demo POS", "value": "8991234567890" }` — exactly these two
  fields; anything else is `INVALID_REQUEST`.
- **Response `data`:**

```json
{
  "scan": {
    "item_code": "DEMO-BREAD-001",
    "barcode": "8991234567890",
    "batch_no": null,
    "serial_no": null,
    "uom": "Pcs",
    "conversion_factor": "1.0",
    "warehouse": "Outlet Demo - DC"
  },
  "warnings": []
}
```

- A scan may resolve a batch or serial directly from the barcode; carry `batch_no` / `serial_no`
  straight into the cart line rather than re-deriving them.
- `warnings[]` may carry `{"code": "MISSING_UOM_CONVERSION", "message": "The selected UOM has no
  conversion factor."}`; in that case `conversion_factor` is `null`. Show the cashier a warning; do not
  invent a factor of 1.
- **Unknown barcode:** `RESOURCE_NOT_FOUND` 404, `details: {"resource_type": "scan_value", "name":
  "<scanned value>"}`. A resolvable barcode pointing at an item outside the profile's scope returns
  `RESOURCE_NOT_FOUND` with `resource_type: "item"`.

### 7.7 `catalog.quote_item`

- **Route:** `POST .../roti_ropi_pos.api.v1.catalog.quote_item` — **POST, not GET.**
- **Purpose:** the authoritative single-line price. Call it whenever a line is added or its qty, UOM,
  batch, or customer changes.
- **Request:**

```json
{
  "pos_profile": "Outlet Demo POS",
  "customer": "CUST-2026-00017",
  "item_code": "DEMO-BREAD-001",
  "qty": "2",
  "uom": "Pcs",
  "batch_no": null
}
```

`pos_profile`, `item_code`, `qty`, `uom` required; `customer` and `batch_no` optional (may be `null`).
`qty` must be a decimal string strictly greater than zero.

- **Response `data`:**

```json
{
  "item": {
    "item_code": "DEMO-BREAD-001",
    "qty": "2.0",
    "uom": "Pcs",
    "conversion_factor": "1.0",
    "warehouse": "Outlet Demo - DC",
    "available_qty": "48.0",
    "price_list_rate": "12000.00",
    "discount_percentage": "0.0",
    "rate": "12000.00",
    "item_tax_template": null
  },
  "warnings": []
}
```

`rate` is the price after price list, price rules, and discount — the only value Android may display as
the line price. Never recompute `rate` from `price_list_rate` and `discount_percentage`.

- **Errors:** `INVALID_REQUEST` 400, `RESOURCE_NOT_FOUND` 404 (item unknown or out of profile scope),
  `INVALID_BATCH` 422 with `reason` ∈ `not_found`, `wrong_item`, `expired`, `wrong_warehouse`,
  `insufficient`; `PROFILE_CONFIGURATION_INVALID` 422.
- **Warnings:** `MISSING_UOM_CONVERSION` as in §7.6.

### 7.8 `sales.quote_cart`

- **Route:** `POST .../roti_ropi_pos.api.v1.sales.quote_cart`
- **Purpose:** the authoritative whole-cart total. **No idempotency key, no durable request, no stock
  reservation** — it is a pure read that changes nothing.
- **Request:**

```json
{
  "pos_profile": "Outlet Demo POS",
  "customer": "CUST-2026-00017",
  "walk_in_customer_name": null,
  "items": [
    { "item_code": "DEMO-BREAD-001", "qty": "2", "uom": "Pcs", "batch_no": null, "serial_numbers": [] }
  ]
}
```

`pos_profile` and a non-empty `items` are required. `customer`, `walk_in_customer_name` optional;
per row, `batch_no` and `serial_numbers` optional (`serial_numbers` defaults to `[]`, duplicates are
rejected). This endpoint now accepts an optional `promotions` object/null (same shape as `sales.submit`, 64 KiB, opaque). A promotion-only quote may send `items: []` when `promotions` is non-null; plain quotes still require non-empty `items`. It returns authoritative `grand_total`, `payable`, taxes, and payment policy for regular, promotion, and mixed carts.

- **Response `data`:**

```json
{
  "grand_total": "26400.00",
  "payable": "26400.00",
  "currency": "IDR",
  "items": [
    { "row_id": "a1b2c3d4e5", "item_code": "DEMO-BREAD-001", "item_name": "Demo Sweet Bread",
      "qty": "2.0", "uom": "Pcs", "conversion_factor": "1.0", "rate": "12000.00",
      "amount": "24000.00", "batch_no": null, "serial_numbers": [] }
  ],
  "taxes": [
    { "description": "PPN Demo 10%", "rate": "10.0", "tax_amount": "2400.00", "total": "26400.00" }
  ],
  "payment_modes": [
    { "mode_of_payment": "Cash", "default": true, "allow_in_returns": true, "currency": "IDR" },
    { "mode_of_payment": "QRIS Demo", "default": false, "allow_in_returns": false, "currency": "IDR" }
  ],
  "payment_amount_policy": {
    "currency": "IDR",
    "decimal_places": 2,
    "minimum": "0.01",
    "api_syntax": "ascii_decimal_dot",
    "rounding": "reject",
    "policy_version": "sale-payment-amount/v1"
  }
}
```

**`payable` is the amount the cashier must collect** (it is `rounded_total` when that is greater than
zero, otherwise `grand_total`). Settle against `payable`, never against `grand_total`.

`grand_total` from the latest quote is what you send back as `client_accepted_grand_total` in
`sales.submit`.

### 7.9 `sales.submit`

- **Route:** `POST .../roti_ropi_pos.api.v1.sales.submit`
- **Headers:** bearer, JSON, **`X-Idempotency-Key`**.
- **Request:**

```json
{
  "pos_profile": "Outlet Demo POS",
  "customer": "CUST-2026-00017",
  "walk_in_customer_name": null,
  "client_accepted_grand_total": "26400.00",
  "items": [
    { "item_code": "DEMO-BREAD-001", "qty": "2", "uom": "Pcs", "batch_no": null, "serial_numbers": [] }
  ],
  "payments": [
    { "mode_of_payment": "Cash", "amount": "26400.00", "reference_no": null }
  ],
  "promotions": null
}
```

Required: `pos_profile`, `client_accepted_grand_total`, and non-empty `payments`.
Optional: `customer`, `walk_in_customer_name`, `promotions`; per payment row, `reference_no`.
`promotions` accepts a JSON object or `null` and is limited to 64 KiB after compact deterministic UTF-8
serialization. Omission or `null` preserves plain-sale behavior. A plain sale requires non-empty `items`.
A promotion-only sale may send `items: []` only when `promotions` is non-null.

Canonical promotion value:

```json
{
  "instances": [
    {
      "promotion": "PROMO-00001",
      "selections": [
        {
          "choice_group_key": "grp_example",
          "options": [{ "option_id": "option-row-name", "qty": 1 }]
        }
      ]
    }
  ]
}
```

`roti_ropi_pos` passes this object opaquely to the POS Invoice lifecycle. `selling_additional` validates
and materializes Model C rows. The response remains the standard `SaleDetail`; no new response field or
error code exists. The normalized value participates in the idempotency hash.
`walk_in_customer_name` is accepted **only** when the resolved customer is the profile default —
otherwise `INVALID_REQUEST` with `reason: "This field is accepted only for profile default Customer."`

- **Response `data`:** `{ "sale": <SaleDetail> }`

```json
{
  "sale": {
    "summary": {
      "doctype": "POS Invoice",
      "name": "ACC-PSINV-2026-00311",
      "status": "paid",
      "customer": "CUST-2026-00017",
      "walk_in_customer_name": null,
      "currency": "IDR",
      "grand_total": "26400.00",
      "paid_amount": "26400.00",
      "change_amount": "0.00",
      "rounded_total": "26400.00",
      "outstanding_amount": "0.00",
      "discount_amount": "0.00",
      "total_taxes_and_charges": "2400.00",
      "posting_date": "2026-08-19",
      "posting_time": "09:41:07"
    },
    "items": [
      { "row_id": "f6a7b8c9d0", "item_code": "DEMO-BREAD-001", "item_name": "Demo Sweet Bread",
        "qty": "2.0", "uom": "Pcs", "conversion_factor": "1.0", "rate": "12000.00",
        "amount": "24000.00", "batch_no": null, "serial_numbers": [] }
    ],
    "taxes": [
      { "description": "PPN Demo 10%", "rate": "10.0", "tax_amount": "2400.00", "total": "26400.00" }
    ],
    "payments": [
      { "mode_of_payment": "Cash", "amount": "26400.00", "reference_no": null }
    ]
  }
}
```

- **HTTP:** `201` create, `200` replay (`meta.replayed: true`). This is the receipt payload — persist it
  before clearing the pending mutation.
- **Errors:** `INVALID_REQUEST` 400, `RESOURCE_NOT_FOUND` 404 (customer),
  `IDEMPOTENCY_KEY_REUSED` 409, `REQUEST_IN_PROGRESS` 409, `NO_OPEN_SESSION` 422, `PRICE_CHANGED` 422,
  `INSUFFICIENT_STOCK` 422, `INVALID_BATCH` 422, `INVALID_SERIAL_NUMBER` 422, `INVALID_PAYMENT` 422,
  `PROFILE_CONFIGURATION_INVALID` 422, `DOCUMENT_VALIDATION_FAILED` 422, `PERMISSION_DENIED` 403,
  `PROFILE_SCOPE_MISMATCH` 403, `IDEMPOTENCY_INVARIANT` 500, `TEMPORARILY_UNAVAILABLE` 503.

**Server-side money enforcement on submit** — the server re-quotes every line under a stock lock,
so a stale client total cannot post:

1. **`PRICE_CHANGED`** when the authoritative grand total differs from `client_accepted_grand_total`.
   `details` carry `accepted_grand_total`, `authoritative_grand_total`, `currency`, and the full
   recalculated `items` and `taxes`. Android **must** replace its cart totals with the returned values,
   show the cashier the new amount, and require explicit re-confirmation. Never auto-resubmit with the
   new total and never reuse the old key after the amount changes — a changed amount is a new intent and
   needs a **new** key.
2. **Exact settlement.** The sum of `payments[].amount` must equal `payable`. Underpayment and
   overpayment both raise `INVALID_PAYMENT` with `payable` and `received`; overpayment adds
   `change_amount`. Change is not supported in v1 — collect the exact amount.
3. **`INSUFFICIENT_STOCK`** carries `item_code`, `warehouse`, `requested_qty`, `available_qty`.

### 7.10 `sales.list`

- **Route:** `GET .../roti_ropi_pos.api.v1.sales.list`
- **Params:** `pos_profile` (**required**), `status` (**required**, exactly one of `all`, `paid`,
  `return`, `consolidated`, `cancelled`), `q` (optional), `start` (optional, ≥ 0), `limit` (optional,
  default 20, capped at 100).
- **Response `data`:**

```json
{
  "sales": [ { "doctype": "POS Invoice", "name": "ACC-PSINV-2026-00311", "status": "paid",
               "customer": "CUST-2026-00017", "walk_in_customer_name": null, "currency": "IDR",
               "grand_total": "26400.00", "paid_amount": "26400.00", "change_amount": "0.00",
               "rounded_total": "26400.00", "outstanding_amount": "0.00", "discount_amount": "0.00",
               "total_taxes_and_charges": "2400.00", "posting_date": "2026-08-19",
               "posting_time": "09:41:07" } ],
  "page": { "start": 0, "limit": 20, "has_more": false }
}
```

`status` has no default — Android must always send it explicitly. Scope is the authorized profile only.
**Note:** this endpoint is *not* limited to the current opening session (see §19, I-7); if the screen
must show "this shift only", Android has to filter client-side by comparing `posting_date`/`posting_time`
against `opening_session.period_start_date`, and that filter is approximate.

### 7.11 `sales.get`

- **Route:** `GET .../roti_ropi_pos.api.v1.sales.get`
- **Params:** `name` (**required**, POS Invoice name).
- **Response `data`:** `{ "sale": <SaleDetail> }` — `summary`, `taxes`, `payments` as in §7.9, plus a
  `returnability` object on every item row and a `return_contract` object at the sale level:

```json
{
  "sale": {
    "summary": { },
    "items": [
      {
        "row_id": "f6a7b8c9d0",
        "item_code": "DEMO-BREAD-001",
        "item_name": "Demo Sweet Bread",
        "qty": "2.0", "uom": "Pcs", "conversion_factor": "1.0",
        "rate": "12000.00", "amount": "24000.00",
        "batch_no": null, "serial_numbers": [],
        "returnability": {
          "original_row_id": "f6a7b8c9d0",
          "item_code": "DEMO-BREAD-001",
          "original_qty": "2.0",
          "returned_qty": "0.0",
          "remaining_qty": "2.0",
          "uom": "Pcs",
          "batch_numbers": [],
          "serial_numbers": [],
          "eligible": true,
          "rejection_reason": null
        }
      }
    ],
    "taxes": [ ],
    "payments": [ ],
    "return_contract": {
      "quantity_policy": {
        "decimal_places": 3,
        "minimum": "0.001",
        "maximum": "999999999999.999",
        "api_syntax": "ascii_decimal_dot",
        "rounding": "reject",
        "policy_version": "return-quantity/v1"
      },
      "allowed_refund_modes": [ { "mode_of_payment": "Cash" } ],
      "refund_mode_required": false
    }
  }
}
```

- `returnability.remaining_qty` is the **only** returnable quantity Android may offer. Never compute it
  as `original_qty − returned_qty` yourself.
- `rejection_reason` is `null` when `eligible` is `true`, otherwise exactly one of
  `SOURCE_NOT_RETURNABLE`, `RETURN_LIMIT_REACHED`, `NO_VALID_REFUND_MODE`,
  `SERIAL_BATCH_REFERENCE_UNAVAILABLE`. A row that is not eligible must not be sent to
  `sales.quote_return` or `sales.create_return`.
- `refund_mode_required` is `true` only when more than one refund mode is allowed. When it is `false`
  the server picks the mode and Android must send `refund_mode: null` (sending one is
  `INVALID_REQUEST`).
- When the fetched invoice is itself a return, the detail also carries `return_against`,
  `return_reason`, `refund_amount`, and `refund_allocations[]`.
- **Errors:** `INVALID_REQUEST` 400, `RESOURCE_NOT_FOUND` 404 with an **empty** `details` object (an
  invoice outside the cashier's scope is not confirmed to exist), `PERMISSION_DENIED` 403.

### 7.12 `sales.quote_return`

- **Route:** `POST .../roti_ropi_pos.api.v1.sales.quote_return` — read-only, **no idempotency key**.
- **Request:**

```json
{
  "source_name": "ACC-PSINV-2026-00311",
  "items": [ { "source_item_row": "f6a7b8c9d0", "qty": "1" } ],
  "refund_mode": null
}
```

`source_name` and a non-empty `items` are required; `refund_mode` is optional/`null`. `source_item_row`
is the `row_id` from `sales.get`. A duplicate `source_item_row` is `INVALID_REQUEST`. `qty` follows
`return-quantity/v1` and is a **positive** decimal string (the sign is the server's job).

- **Response `data`:** `{ "return_quote": { … } }`

```json
{
  "return_quote": {
    "source_name": "ACC-PSINV-2026-00311",
    "currency": "IDR",
    "items": [
      { "row_id": null, "item_code": "DEMO-BREAD-001", "item_name": "Demo Sweet Bread",
        "qty": "-1.0", "uom": "Pcs", "conversion_factor": "1.0", "rate": "12000.00",
        "amount": "-12000.00", "batch_no": null, "serial_numbers": [], "batch_numbers": [] }
    ],
    "taxes": [ { "description": "PPN Demo 10%", "rate": "10.0", "tax_amount": "-1200.00",
                 "total": "-13200.00" } ],
    "discount_amount": "0.00",
    "total_taxes_and_charges": "-1200.00",
    "grand_total": "-13200.00",
    "rounded_total": "-13200.00",
    "refund_amount": "13200.00",
    "allowed_refund_modes": [ { "mode_of_payment": "Cash" } ],
    "refund_mode_required": false,
    "selected_refund_mode": "Cash",
    "refund_allocations": [ { "mode_of_payment": "Cash", "amount": "-13200.00", "reference_no": null } ]
  }
}
```

`refund_amount` is positive for display. `items[].qty`, item amounts, totals, and
`refund_allocations[].amount` are negative. Never derive the refund from the line rates.

### 7.13 `sales.create_return`

- **Route:** `POST .../roti_ropi_pos.api.v1.sales.create_return`
- **Headers:** bearer, JSON, **`X-Idempotency-Key`**.
- **Request:**

```json
{
  "source_name": "ACC-PSINV-2026-00311",
  "reason": "Item damaged on handover",
  "items": [ { "source_item_row": "f6a7b8c9d0", "qty": "1" } ],
  "refund_mode": null
}
```

`source_name`, `reason` (non-empty), and non-empty `items` are required. `reason` is **not** optional
here even though `sales.quote_return` has no such field.

- **Response `data`:** `{ "return_sale": <SaleDetail with is_return> }` — `summary`, `items` (return
  rows, which additionally carry `batch_numbers`), `taxes`, `payments`, plus `return_against`,
  `return_reason`, `refund_amount`, `refund_allocations[]`.
- **HTTP:** `201` create, `200` replay.
- **Errors:** `INVALID_REQUEST` 400, `RESOURCE_NOT_FOUND` 404 (empty details),
  `IDEMPOTENCY_KEY_REUSED` 409, `REQUEST_IN_PROGRESS` 409, `NO_OPEN_SESSION` 422,
  `RETURN_LIMIT_EXCEEDED` 422, `INVALID_SERIAL_NUMBER` 422, `INVALID_PAYMENT` 422,
  `PROFILE_CONFIGURATION_INVALID` 422, `DOCUMENT_VALIDATION_FAILED` 422, `PERMISSION_DENIED` 403,
  `IDEMPOTENCY_INVARIANT` 500, `TEMPORARILY_UNAVAILABLE` 503.

**Refund-mode rules** (identical for quote and create):

| Eligible refund modes on the profile | Android must send | Violation |
| --- | --- | --- |
| 0 | — | `PROFILE_CONFIGURATION_INVALID` 422, `reason: "no_valid_refund_mode"` |
| 1 | `refund_mode: null` | Sending one → `INVALID_REQUEST` 400, `reason: "server_selected_for_single_refund_mode"` |
| > 1 | the chosen `mode_of_payment` | Sending `null` → `INVALID_REQUEST` 400, `reason: "required_for_multiple_refund_modes"`; a mode not in the list → `INVALID_PAYMENT` 422, `reason: "refund_mode_not_allowed"` with `allowed_refund_modes` |

A mode is eligible only if it is on the profile, has `allow_in_returns`, is an enabled Mode of Payment,
and has a default account for the company. Read the list from
`sales.get → return_contract.allowed_refund_modes`; never hardcode "Cash".

**`RETURN_LIMIT_EXCEEDED`** carries `source_name`, `source_item_row`, `requested_qty`, `remaining_qty`,
and `refresh_endpoint: "v1.sales.get"`. Re-fetch `sales.get`, refresh the returnability projection, and
let the cashier re-enter — do not clamp the quantity silently.

**Serialized rows** must return the full remaining serial set. A partial serialized return is
`INVALID_SERIAL_NUMBER` 422 with `reason: "partial_serial_return_not_supported"` and
`source_item_row`.

### 7.14 `closing.preview`

- **Route:** `GET .../roti_ropi_pos.api.v1.closing.preview`
- **Params:** `pos_profile` (**required**). No idempotency key.
- **Response `data`:**

```json
{
  "opening_session": { },
  "preview_id": "3f7c1a9e64b2d508aa71c3e9b04d6f82c5178ab390de24f6b7c081a5d93e42bc",
  "preview_version": "closing-preview/v1",
  "preview_binding": {
    "opening_entry": "POS-OPE-2026-00042",
    "pos_profile": "Outlet Demo POS",
    "cashier": "cashier.demo@example.test",
    "invoice_count": 5,
    "payment_modes": ["Cash", "QRIS Demo"]
  },
  "invoice_count": 5,
  "grand_total": "250000.00",
  "net_total": "227272.73",
  "total_quantity": "10.0",
  "total_taxes_and_charges": "22727.27",
  "expected_payments": [
    { "mode_of_payment": "Cash", "opening_amount": "250000.00", "expected_amount": "400000.00" },
    { "mode_of_payment": "QRIS Demo", "opening_amount": "0.00", "expected_amount": "100000.00" }
  ],
  "counted_amount_policy": {
    "currency": "IDR",
    "decimal_places": 2,
    "max_scale": 2,
    "api_syntax": "ascii_decimal_dot",
    "minimum": "0.00",
    "maximum": "999999999999.99",
    "rounding": "reject",
    "policy_version": "closing-counted-amount/v1"
  }
}
```

- `preview_id` is a SHA-256 binding over the whole snapshot (opening, profile, cashier, company,
  currency, every eligible invoice row, expected payments, policy). It has **no expiry timer**, but any
  new sale, return, or configuration change invalidates it.
- `expected_amount` = `opening_amount` + sales − change, per mode. It is the server's expectation; the
  cashier's physical count goes in `closing.submit`.
- **Errors:** `INVALID_REQUEST` 400, `PROFILE_SCOPE_MISMATCH` 403, `PERMISSION_DENIED` 403,
  `NO_OPEN_SESSION` 422, `PROFILE_CONFIGURATION_INVALID` 422.

### 7.15 `closing.submit`

- **Route:** `POST .../roti_ropi_pos.api.v1.closing.submit`
- **Headers:** bearer, JSON, **`X-Idempotency-Key`**.
- **Request:**

```json
{
  "pos_profile": "Outlet Demo POS",
  "preview_id": "3f7c1a9e64b2d508aa71c3e9b04d6f82c5178ab390de24f6b7c081a5d93e42bc",
  "closing_balances": [
    { "mode_of_payment": "Cash", "closing_amount": "400000.00" },
    { "mode_of_payment": "QRIS Demo", "closing_amount": "100000.00" }
  ]
}
```

All three fields required. `closing_balances` must contain **exactly** the modes from
`preview.expected_payments` — no missing mode, no unknown mode, no duplicate. The row field is
`closing_amount` (not `amount`, not `counted_amount`). Amounts follow `closing-counted-amount/v1`.

- **Response `data`:** `{ "closing": <Closing> }`

```json
{
  "closing": {
    "name": "POS-CLO-2026-00019",
    "opening_entry": "POS-OPE-2026-00042",
    "pos_profile": "Outlet Demo POS",
    "status": "submitted",
    "invoice_count": 5,
    "grand_total": "250000.00",
    "net_total": "227272.73",
    "total_quantity": "10.0",
    "total_taxes_and_charges": "22727.27",
    "payments": [
      { "mode_of_payment": "Cash", "opening_amount": "250000.00", "expected_amount": "400000.00",
        "counted_amount": "400000.00", "difference": "0.00" },
      { "mode_of_payment": "QRIS Demo", "opening_amount": "0.00", "expected_amount": "100000.00",
        "counted_amount": "100000.00", "difference": "0.00" }
    ],
    "reconciliation": {
      "expected_total": "500000.00",
      "counted_total": "500000.00",
      "difference_total": "0.00"
    },
    "failure": null
  }
}
```

- `status` ∈ `"draft"`, `"queued"`, `"submitted"`, `"failed"`, `"cancelled"`.
- **HTTP:** `201` create, `200` replay.
- A shortage or surplus does **not** block the close: `difference` is recorded, not rejected.
- **Errors:** `INVALID_REQUEST` 400 (and one 422 variant carrying only `reason`, for an ERPNext
  document rejection during closing), `PROFILE_SCOPE_MISMATCH` 403, `PERMISSION_DENIED` 403,
  `CLOSING_ALREADY_CLOSED` 409, `CLOSING_IN_PROGRESS` 409, `CLOSING_PREVIEW_STALE` 409,
  `IDEMPOTENCY_KEY_REUSED` 409, `REQUEST_IN_PROGRESS` 409, `NO_OPEN_SESSION` 422,
  `CLOSING_PAYMENT_MODE_UNKNOWN` / `_DUPLICATE` / `_MISSING` 422, `CLOSING_DECIMAL_MALFORMED` 422,
  `CLOSING_DECIMAL_SCALE_EXCEEDED` 422, `CLOSING_AMOUNT_OUT_OF_BOUNDS` 422,
  `IDEMPOTENCY_INVARIANT` 500, `TEMPORARILY_UNAVAILABLE` 503.
- **`CLOSING_PREVIEW_STALE`** carries `current_preview_id` and `refresh_endpoint:
  "v1.closing.preview"`. Re-run the preview, re-show the new expected amounts, have the cashier
  re-confirm the count, then submit with a **new** key — the payload changed, so the old key would be
  rejected as reused.

### 7.16 `closing.recover`

- **Route:** `POST .../roti_ropi_pos.api.v1.closing.recover`
- **Headers:** bearer, JSON. **No `X-Idempotency-Key`** — sending one is not required and the endpoint
  accepts no other field.
- **Request:** `{ "pos_profile": "Outlet Demo POS" }` — any additional field is `INVALID_REQUEST`.
- **Purpose:** resolve a closing whose idempotency key Android has lost (reinstall, storage wipe, key
  never persisted). It **adopts** the closing that already exists on the server; it never creates a
  second one.
- **Response `data`:** `{ "closing": <Closing> }`, identical shape to §7.15.
- **Outcomes:**

| Server state | Result |
| --- | --- |
| Draft closing exists for this opening | Resumed and submitted; `201` with `status` `submitted` or `queued` |
| Closing already submitted / queued / failed | Returns the durable state; `201`/`200` |
| A prior recover already completed under a stored request | `200` with `meta.replayed: true` |
| A live lease is still running | `REQUEST_IN_PROGRESS` 409, retryable, `retry_after_seconds` |
| Nothing to recover | `CLOSING_RECOVERY_NOT_AVAILABLE` 409 |
| Cannot be adopted safely | `CLOSING_RECOVERY_REQUIRES_MANAGER` 409 with `reason` |
| No open session | `NO_OPEN_SESSION` 422 |

- `CLOSING_RECOVERY_REQUIRES_MANAGER` `reason` values: `cashier_mismatch`, `profile_mismatch`,
  `opening_mismatch`, `closing_state_unrecoverable`, `closing_not_mobile_owned`. All five mean **stop**;
  see §13.
- Requires only `submit` permission on POS Closing Entry (not `create`), because it creates nothing.

### 7.17 `closing.status`

- **Route:** `GET .../roti_ropi_pos.api.v1.closing.status`
- **Params:** `name` (**required**, POS Closing Entry name).
- **Response `data`:** `{ "closing": <Closing> }`, identical shape to §7.15.
- **Purpose:** poll a `queued` consolidation until it becomes `submitted` or `failed`.
- **Errors:** `INVALID_REQUEST` 400, `PERMISSION_DENIED` 403 (a closing owned by another cashier or
  another company — the scope check is deliberately reported as a permission failure),
  `PROFILE_SCOPE_MISMATCH` 403. A name that does not exist at all raises Frappe's native
  document-not-found response **without** a v1 envelope; handle it as a transport-level 404, not as
  `RESOURCE_NOT_FOUND`.

### 7.18 Dynamic Promotion status — CLOSED (2026-08-27)

| Operation | Backend status | Android status |
| --- | --- | --- |
| Optional `sales.submit.promotions` field | Implemented and tested | **Available:** use with `sales.quote_cart` authoritative totals |
| Three `selling_additional.overrides.pos_promo_api` facades | Implemented POST-only, 20 allowlist, enabled+assigned via `_check_access` | **Available:** POST-only with valid bearer and assigned POS Profile |
| Promotion-only or mixed-cart authoritative quote | Implemented via `sales.quote_cart` with `promotions` | **Available:** use authoritative `sales.quote_cart` for `grand_total`/`payable` |

Implemented facade paths:

```text
/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions
/api/method/selling_additional.overrides.pos_promo_api.get_promotion_detail
/api/method/selling_additional.overrides.pos_promo_api.quote_promotion
```

All three facades are now `@frappe.whitelist(methods=["POST"])`, preserving the Desk POS `frappe.xcall()` (POST) consumer.

These facades return native Frappe `{ "message": ... }` responses, not the v1 envelope. `Mobile POS
Cashier` has read-only Promotion permission. Facade checks now enforce Promotion read + POS Profile enabled/assigned via `applicable_for_users` (Administrator bypass for Desk), and require `pos_profile` for all three (including detail). `MOBILE_POS_METHODS` now contains 20 exact methods (17 v1 + 3 promo POST-only) and `MOBILE_POS_PATHS` derives from them; real HTTP tests prove the full dispatch pipeline.

`quote_promotion.total_price` is package pricing only and must not become `client_accepted_grand_total`. `sales.quote_cart` now accepts the same optional `promotions` object/null as `sales.submit` and returns authoritative tax, rounding, `grand_total`, `payable`, and payment policy for regular, promotion-only, and mixed carts.

**Note:** The Dynamic Promotion route and combined-quote blockers are now closed. The hard stop below is retired; payment and `sales.submit` for a Dynamic Promotion cart are now allowed via the authoritative quote. Bearer tests prove the three exact facade routes and a backend quote returns authoritative promotion-only
and mixed-cart totals plus payment policy.

Deployment also requires `selling_additional`, a recorded backup before migrate,
`auto_insert_price_list_rate_if_missing = 0`, and zero selling Item Price rows for every Promotion parent
item. See `/Users/rotiropi/POS_Android/docs/dynamic-promotion-integration-handoff.md`.

## 8. Catalog, customer, and quote flow

Order matters. Each step's output feeds the next; skipping a step means the cashier sees a price the
server never agreed to.

```
select profile
   └─> catalog.search / catalog.scan          (find the item)
         └─> catalog.quote_item                (authoritative LINE price)
               └─> local cart line             (store the server's rate, not your own)
                     └─> sales.quote_cart      (authoritative CART total + payable)
                           └─> payment screen  (settle exactly `payable`)
```

Rules:

1. **Re-quote the line** on every change to qty, UOM, batch, or customer. A cached `rate` from a
   different qty or a different customer is invalid — pricing rules are qty- and customer-dependent.
2. **Re-quote the cart** whenever any line changes, the customer changes, or a line is removed. Then
   discard the previous cart quote entirely; a superseded quote is not a fallback.
3. **Customer selection.** No selection → the profile default (walk-in) is used. `walk_in_customer_name`
   is a free-text display label accepted **only** with the profile default customer. Selecting a
   customer changes pricing, so it must precede the cart quote.
4. **Batch and serial.** If `catalog.scan` resolved a `batch_no` or `serial_no`, carry it into the line.
   For a serialized item, `serial_numbers` must list exactly as many entries as `qty`, with no
   duplicates.
5. **`MISSING_UOM_CONVERSION`** means the custom UOM has no conversion factor. Warn the cashier and
   block the line; do not assume 1.
6. Availability shown by `catalog.search` / `catalog.quote_item` is a snapshot. Only `sales.submit`
   takes a stock lock, so `INSUFFICIENT_STOCK` at submit time is a normal outcome, not a bug.

## 9. Sale and payment

### Ordering

```
1. sales.quote_cart              -> grand_total, payable, payment_modes, payment_amount_policy
2. cashier enters tender          -> sum(payments[].amount) MUST equal payable exactly
3. persist pending mutation       -> key + exact serialized body, on disk, BEFORE the call
4. sales.submit                   -> 201 + sale detail (the receipt)
5. persist the terminal response  -> then, and only then, clear the pending mutation
6. render receipt from the response, never from local computation
```

Step 3 is not optional. If the process dies between step 4 and step 5, the only way to recover the
receipt without risking a duplicate invoice is the persisted key and body.

### Payment rules

- Send `amount` per row as a decimal string honouring `payment_amount_policy`
  (`sale-payment-amount/v1`): `ascii_decimal_dot`, `rounding: "reject"`, minimum from the policy, scale
  ≤ `decimal_places`. The server never rounds a submitted amount for you.
- `mode_of_payment` must come from `payment_modes[]` of the cart quote. An unconfigured or duplicated
  mode is `INVALID_PAYMENT`.
- Total must equal **`payable`** exactly. There is no change and no partial payment in v1.
- `reference_no` is optional free text for non-cash tenders.

### The server recalculates everything

`sales.submit` re-quotes every line, re-derives taxes, re-checks stock under a `FOR UPDATE` lock on Bin,
expands Product Bundles, and compares its own grand total to `client_accepted_grand_total`. A mismatch
is `PRICE_CHANGED` and the transaction is rolled back — nothing is posted. This is why an Android-side
total is never authoritative: it is only an assertion the server may reject.

### Receipt

The receipt is `data.sale` from the create response, or the identical `data.sale` from a `200` replay.
Reprint from persisted local storage or from `sales.get`; both are the server's own numbers.

## 10. Idempotency and recovery

### Which endpoints need a key

| Endpoint | `X-Idempotency-Key` |
| --- | --- |
| `sessions.open` | **Required** |
| `sales.submit` | **Required** |
| `sales.create_return` | **Required** |
| `closing.submit` | **Required** |
| `closing.recover` | **Not used** — recovers from server state |
| every read endpoint, `sales.quote_cart`, `sales.quote_return` | Not used |

### Key format

Exactly a **lowercase UUID v4**, 36 characters:
`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`.
Uppercase hex, a missing header, or any other shape is `INVALID_REQUEST` 400 with
`details: {"field": "X-Idempotency-Key", "reason": "Expected a lowercase UUID."}`.

### One key = one logical intent

The server hashes a canonical normalization of the request body and binds it to the key. Same key +
same body = replay. Same key + **different** body = `IDEMPOTENCY_KEY_REUSED` 409, and the original
result is **not** returned.

Therefore:

- **Generate the key once**, at the moment the cashier confirms the intent — never per HTTP attempt.
- **Persist the key together with the exact serialized request body** before the first attempt. Retry
  with those bytes, not with a re-serialization of live UI state; a re-serialized body can differ by a
  field order or a decimal spelling and trip the hash check.
- **The cashier changing the amount is a new intent** → new key, new body, new pending record.

### Retry decision

Read `error.retryable`. It is `true` for exactly two codes:

| Code | HTTP | Meaning | Action |
| --- | --- | --- | --- |
| `REQUEST_IN_PROGRESS` | 409 | A request under this key really is running; the outcome is unknown | Wait `details.retry_after_seconds`, then retry the **same** key and body |
| `TEMPORARILY_UNAVAILABLE` | 503 | The request that held this key committed nothing; replay is safe | Wait `details.retry_after_seconds`, then retry the **same** key and body |

Every other code is `retryable: false` and final for that body. Android may send a new request only
after the cashier changes the input, and then only with a new key.

### Replay semantics

- **Completed key, same body** → the stored response verbatim, HTTP **200**, `meta.replayed: true`. Note
  the create response was `201`; a `200` with `replayed: true` is a success, not a conflict.
- **Rejected key (closing only), same body** → the stored *error* envelope with its original status and
  `meta.replayed: true`. The business logic does not re-run.
- **A failed standard mutation** (`sessions.open`, `sales.submit`, `sales.create_return`) leaves **no
  durable request row** — the whole transaction rolls back. Retrying the same key re-runs the business
  logic from scratch. This is safe and intended: nothing was committed.
- **`closing.submit` is the exception** and durably stores its phases. See §13.

### `IDEMPOTENCY_INVARIANT` (500)

A server-side consistency defect, not a business branch, and never retryable. Android must:

1. Stop the mutation. Do **not** retry, and do **not** generate a new key.
2. Reconcile read-only: `sessions.current`, `sales.get` / `sales.list`, `closing.status`.
3. Show an internal-error state and route the cashier to manager escalation. Never map it to a
   business message.

### Recovery pseudoflow

```
CONFIRM INTENT
  key   = uuid4().lowercase()
  body  = serialize(intent)
  store PENDING { key, endpoint, body, state = "unsent" }   # durable, survives process death

ATTEMPT
  store PENDING.state = "in_flight"
  response = POST endpoint, header X-Idempotency-Key = key, body = body

  on HTTP 201 or 200:
      store TERMINAL { key, response }        # durable
      clear PENDING                            # only after TERMINAL is durable
      render from response

  on error envelope with retryable = true:
      wait details.retry_after_seconds
      goto ATTEMPT                             # SAME key, SAME body

  on error envelope with retryable = false:
      store TERMINAL { key, error }            # keep the outcome for audit
      clear PENDING
      show the mapped user action from §14

  on HTTP 401:
      keep PENDING intact
      refresh token
      goto ATTEMPT                             # SAME key, SAME body

  on timeout / socket error / no response at all:
      keep PENDING (state stays "in_flight")   # OUTCOME UNKNOWN — may have committed
      goto ATTEMPT after backoff               # SAME key, SAME body

RELAUNCH / PROCESS DEATH
  for each PENDING record:
      if endpoint == "closing.submit" and key was lost entirely:
          POST closing.recover { pos_profile }       # see §13
      else:
          goto ATTEMPT                                # SAME key, SAME body
  block cashier input until every PENDING record is resolved
```

### The four dangerous situations, stated plainly

| Situation | What the server did | What Android must do |
| --- | --- | --- |
| Request timed out | Unknown — possibly committed | Retry same key; the replay tells you the truth |
| Response dropped after commit | Committed | Retry same key → `200`, `replayed: true`, real receipt |
| Process died mid-flight | Unknown | On relaunch, retry same key before anything else |
| Storage wiped, key lost | Unknown | Sale/return: reconcile via `sales.list` (read-only) and let the cashier decide. Closing: `closing.recover` |

Never generate a fresh key to "just try again". That is how one physical sale becomes two POS Invoices,
and the gateway cannot undo it for you.

## 11. History

- **List:** `sales.list` with a mandatory `status` filter, `limit` ≤ 100, and `start` paging. Use
  `page.has_more` for infinite scroll, not a count.
- **Detail:** `sales.get` by `name`. Always re-fetch the detail before opening the return builder — the
  returnability projection is live and another terminal may have consumed the remaining quantity.
- **Reprint:** render from the persisted terminal response or from a fresh `sales.get`.
- **Scope:** the authorized profile only. An invoice outside scope returns `RESOURCE_NOT_FOUND` with an
  empty `details` object, deliberately not confirming whether it exists.
- **Current-shift filter:** NOT PROVIDED BY BACKEND as a server-side filter. See §7.10 and §19 (I-7).
- **Status mapping:** the runtime lowercases the ERPNext status and maps `Credit Note Issued` to
  `paid`. Treat any status string you do not recognize as informational text — do not branch business
  logic on an unrecognized value (§19, M-6).

## 12. Return and refund

### Ordering

```
sales.list  ->  sales.get (returnability + return_contract)
                  └─> cashier picks rows and quantities   (qty <= returnability.remaining_qty)
                        └─> reason (free text, required by create)
                              └─> refund mode (only when refund_mode_required == true)
                                    └─> sales.quote_return          (authoritative refund_amount)
                                          └─> persist pending {key, body}
                                                └─> sales.create_return  (201 + return receipt)
                                                      └─> persist terminal, then clear pending
```

### Rules

1. **Eligibility is server-declared.** Offer a row only when `returnability.eligible` is `true`. An
   ineligible row carries a `rejection_reason`; show it and disable the row.
2. **Quantity ceiling is `remaining_qty`.** Never `original_qty`, never a locally tracked remainder.
   Exceeding it is `RETURN_LIMIT_EXCEEDED` with a `refresh_endpoint` telling you to re-read `sales.get`.
3. **Quantities are positive on the wire.** The server produces the negative lines and totals.
4. **`reason` is required by `create_return`** and not accepted by `quote_return`.
5. **Refund mode** follows the table in §7.13. Read the allowed list from the server every time.
6. **`refund_amount` is the server's number.** Android displays it and never computes a refund from line
   rates, taxes, or the original payment split.
7. **Serialized rows return in full**; a partial serialized return is rejected.
8. **Replay and recovery** are identical to a sale: same key, same body, `200` + `replayed: true` on
   replay. A dropped response after a committed return is recovered by replaying the key, or — if the
   key is gone — by reading `sales.list` / `sales.get` and letting the cashier confirm before any new
   attempt.
9. **The return receipt** is `data.return_sale`, including `return_against`, `return_reason`,
   `refund_amount`, and `refund_allocations[]`.

## 13. Closing

Closing is the highest-risk flow in the app. A duplicated closing corrupts the accounting period, and
unlike a duplicated sale it cannot be reversed by a return. Read this whole section before writing any
closing code.

### 13.1 Session identity

There is no "closing id" that Android invents. Closing identity is server-side:

- the **opening session** (`POS-OPE-…`) is the subject being closed;
- the **`X-Idempotency-Key`** identifies one closing *attempt*;
- the **POS Closing Entry name** (`POS-CLO-…`) is the durable result.

One open session per cashier and per profile, so `pos_profile` plus the authenticated cashier uniquely
identifies what is being closed. That is why `closing.recover` needs nothing but `pos_profile`.

### 13.2 Normal flow

```
1. GET  closing.preview  { pos_profile }
        -> preview_id, expected_payments, counted_amount_policy
2. cashier physically counts each mode
3. persist PENDING { key = uuid4, body = {pos_profile, preview_id, closing_balances} }
4. POST closing.submit  (X-Idempotency-Key)
        -> 201, closing.status = "submitted" | "queued"
5. persist TERMINAL, then clear PENDING
6. if status == "queued": poll closing.status until "submitted" or "failed"
```

`closing_balances` must mirror `expected_payments` exactly — one row per mode, same modes, no
duplicates. Counted amounts are the cashier's physical count, sent as decimal strings; a difference from
`expected_amount` is recorded in `payments[].difference` and does not block the close.

### 13.3 Durable phases on the server

`closing.submit` commits at each phase boundary, so a crash never loses work and never duplicates it:

| Phase | Durably committed | What a replay or recovery does |
| --- | --- | --- |
| `Reserved` | Request row, 30 s lease, no document yet | Re-creates the draft under the opening lock |
| `DraftCreated` | Draft POS Closing Entry + the opening's link to it | Resumes submitting **that** draft — never creates a second |
| `SubmitStarted` | Phase marker + renewed lease | Completes from persisted state, or detects that consolidation already committed |
| completed | `Completed` request with the stored response | Returns the stored response, `200`, `replayed: true` |

The lease is **30 seconds**. While it is live, a competing attempt gets `REQUEST_IN_PROGRESS`. Once it
expires, the next attempt with the same key reclaims it and continues from the phase reached.

Android does not manage phases. It only needs to know: **a committed draft already exists on the server
after `DraftCreated`, so a second submit attempt with a new key would be a second closing.**

### 13.4 Queued consolidation

When the session holds **10 or more** unconsolidated invoices, consolidation is deferred to a background
worker and the response carries `status: "queued"`. Poll `closing.status` with backoff (1 s, 2 s, 4 s, …)
until it becomes `submitted` (done) or `failed` (§13.6). Fewer than 10 invoices consolidates
synchronously and returns `submitted` immediately.

`queued` is a success. Do not retry `closing.submit` while polling.

### 13.5 Recovery paths

| What Android still holds | Endpoint | Why |
| --- | --- | --- |
| Key **and** exact body | `closing.submit` with that key and body | Replay; resumes or returns the stored result |
| Neither (wiped, reinstalled, key never persisted) | `closing.recover` with `pos_profile` | Adopts the server's existing closing |
| Only the closing name | `closing.status` with `name` | Read-only observation |
| Nothing, and a session exists that was never closed | `closing.preview` then a fresh submit | Only after `recover` says `CLOSING_RECOVERY_NOT_AVAILABLE` |

### 13.6 Manager escalation and the incident hold

A closing whose consolidation fails is marked `failed`. From that moment:

- `closing.submit` / `closing.status` / `closing.recover` report
  `failure: {"code": "CLOSING_FAILED", "message": "Closing failed. A manager must review it in ERPNext."}`
- `sessions.current` reports `opening_session.lifecycle_state = "closing_failed"`
- `bootstrap.get` returns **all** capabilities `false` — `open_session`, `submit_sale`,
  `create_return`, `cancel_sale`, `close_session`

Android in this state **may**: poll `closing.status` or `sessions.current`, and show previously stored
receipts read-only. Android **must not**: submit a sale, create a return, open a session, or retry
closing.

Resolution is a manager action in ERPNext Desk. When the manager cancels the failed Closing Entry, the
opening's link is cleared, `lifecycle_state` returns to `active`, `close_session` becomes `true` again,
and the cashier can take a fresh preview and close normally. Android detects this only by polling; there
is no push channel.

### 13.7 Ambiguous recovery — hard stop

`CLOSING_RECOVERY_REQUIRES_MANAGER` 409 means the server refuses to let this cashier adopt the closing.
`details.reason` is one of:

| `reason` | Meaning |
| --- | --- |
| `cashier_mismatch` | The closing belongs to a different cashier |
| `profile_mismatch` | Different POS Profile or different company |
| `opening_mismatch` | The closing is bound to a different opening |
| `closing_state_unrecoverable` | Cancelled, or in a draft state that cannot be resumed |
| `closing_not_mobile_owned` | The closing carries no valid Mobile POS transaction id — it was not created by this gateway |

In every one of these cases Android is **FORBIDDEN** to call `closing.submit`, `closing.recover` again,
`sessions.open`, or any sale/return mutation. Show a blocking dialog ("Closing held for manager review"),
keep the pending record, and poll `sessions.current` until the state changes.

### 13.8 Closing decision table

The authoritative Android decision table. "New closing request allowed?" means: may Android generate a
**new** `X-Idempotency-Key` and call `closing.submit`?

| # | Observed situation | Call | Request | Expected result | New closing request allowed? | Next step |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Fresh normal close, session `active` | `closing.submit` | new key; `{pos_profile, preview_id, closing_balances}` | `201`, `status` `submitted` or `queued` | **Yes** | `submitted` → receipt. `queued` → row 9 |
| 2 | Timeout or dropped response, key **and** body retained | `closing.submit` | **original** key, **identical** body | `200` `replayed: true`, or `409 REQUEST_IN_PROGRESS` | **No — reuse the key** | On `REQUEST_IN_PROGRESS`, wait `retry_after_seconds` and replay |
| 3 | Process death, key and body on disk | `closing.submit` | saved key and body | `200` `replayed: true`, or `201` | **No — reuse the key** | Store receipt, clear pending |
| 4 | Reinstall or storage wipe, key lost | `closing.recover` | `{pos_profile}` | `201`/`200` with `closing` | **No — never submit** | Adopt the returned closing as the result |
| 5 | `recover` → `CLOSING_RECOVERY_NOT_AVAILABLE` | `closing.preview`, then `closing.submit` | fresh preview, new key | `200` preview, then `201` | **Yes** — nothing was pending | Normal close |
| 6 | `recover` → `CLOSING_RECOVERY_REQUIRES_MANAGER` | poll `sessions.current` only | `{pos_profile}` | `409` with `reason` | **FORBIDDEN** | Blocking manager-review dialog; keep pending |
| 7 | `403 PROFILE_SCOPE_MISMATCH`, or `reason: cashier_mismatch` | none | — | `403` / `409` | **FORBIDDEN** | Wrong cashier or profile: re-select profile or log out |
| 8 | `409 CLOSING_ALREADY_CLOSED` | `sessions.current` | `{pos_profile}` | opening reported closed | **FORBIDDEN** | Treat as closed; go to Open Session |
| 9 | `status == "queued"` | poll `closing.status` | `{name}` | `queued` → `submitted` \| `failed` | **FORBIDDEN** | Backoff poll. `submitted` → receipt. `failed` → row 10 |
| 10 | `status == "failed"` / `lifecycle_state == "closing_failed"` | poll `sessions.current` or `closing.status` | — | `failure.code = CLOSING_FAILED` | **FORBIDDEN** | Incident hold (§13.6). All capabilities `false` |
| 11 | `409 CLOSING_IN_PROGRESS` (a draft is held under another key) | `closing.recover` | `{pos_profile}` | adopts the draft | **FORBIDDEN** | Never submit a second closing |
| 12 | `409 CLOSING_PREVIEW_STALE` | `closing.preview`, re-confirm the count, submit | fresh `preview_id`, **new** key | `200` preview, then `201` | **Yes** — the body changed | The old key would be `IDEMPOTENCY_KEY_REUSED` |
| 13 | `422 NO_OPEN_SESSION` | `bootstrap.get` | — | no opening | **FORBIDDEN** | Nothing to close; go to Open Session |
| 14 | `500 IDEMPOTENCY_INVARIANT` | `closing.status` / `sessions.current` | — | read-only reconcile | **FORBIDDEN** | Internal error screen, manager escalation |

**The single rule behind the table:** a second closing may only be created when the server has told
Android, in this order, that (a) no unresolved closing exists (`CLOSING_RECOVERY_NOT_AVAILABLE`) or the
session is `active` with `closing == null`, **and** (b) a fresh `preview_id` was obtained. Row 12 is the
only case where a new key is correct while a closing intent is already in flight, and it is correct
precisely because the payload changed.

## 14. Error handling

Freeze the Android error enum from this table plus the non-error codes below. **30 stable codes exist.**
A code outside this table is a protocol violation: log it, show a generic internal-error message, and
never silently ignore it.

`SESSION_ALREADY_CLOSED` and `DOCUMENT_STATE_CONFLICT` appeared in older drafts, have **no runtime
producer**, and must not be defined by Android.

### Business validation (cashier can fix the input)

| Code | HTTP | Retryable | User action | Android action | Show server message? | Auto-retry? |
| --- | --- | --- | --- | --- | --- | --- |
| `INVALID_REQUEST` | 400 | No | None — this is a client bug | Log with `details.field`; generic error to the cashier | No | No |
| `PRICE_CHANGED` | 422 | No | Review and re-confirm the new total | Replace cart totals from `details.items`/`taxes`; require re-confirm; **new key** | No — show the new amount | No |
| `INSUFFICIENT_STOCK` | 422 | No | Reduce qty or drop the line | Show `available_qty`; re-quote the cart | No | No |
| `INVALID_BATCH` | 422 | No | Pick another batch | Clear the batch on that line; branch on `details.reason` | No | No |
| `INVALID_SERIAL_NUMBER` | 422 | No | Fix the serial selection | Re-scan; for returns, require the full remaining set | No | No |
| `INVALID_PAYMENT` | 422 | No | Correct the tender | Show `payable` vs `received`; for returns use `allowed_refund_modes` | No | No |
| `RETURN_LIMIT_EXCEEDED` | 422 | No | Lower the return qty | Re-fetch `sales.get`, refresh returnability | No | No |
| `NO_OPEN_SESSION` | 422 | No | Open a session | Navigate to Open Session | No | No |
| `SESSION_ALREADY_OPEN` | 409 | No | None | Adopt the existing session via `sessions.current` | No | No |
| `DOCUMENT_VALIDATION_FAILED` | 422 | No | Depends on the ERPNext rule | **Show `details.display_message`** — it is the operator-facing text | **Yes** | No |
| `CLOSING_PAYMENT_MODE_UNKNOWN` | 422 | No | None — client bug | Rebuild `closing_balances` from `expected_payments` | No | No |
| `CLOSING_PAYMENT_MODE_DUPLICATE` | 422 | No | None — client bug | Deduplicate rows | No | No |
| `CLOSING_PAYMENT_MODE_MISSING` | 422 | No | Count the missing mode | Add the missing mode's row | No | No |
| `CLOSING_DECIMAL_MALFORMED` | 422 | No | Re-enter the amount | Validate against `counted_amount_policy` before sending | No | No |
| `CLOSING_DECIMAL_SCALE_EXCEEDED` | 422 | No | Re-enter with fewer decimals | Enforce `max_scale` in the input field | No | No |
| `CLOSING_AMOUNT_OUT_OF_BOUNDS` | 422 | No | Re-enter within range | Enforce `minimum`/`maximum` in the input field | No | No |
| `CLOSING_PREVIEW_STALE` | 409 | No | Re-confirm the count | Re-run `closing.preview`; **new key** | No | No |

### Configuration

| Code | HTTP | Retryable | User action | Android action | Show server message? | Auto-retry? |
| --- | --- | --- | --- | --- | --- | --- |
| `UNSUPPORTED_POS_MODE` | 422 | No | Contact a manager | Block the app; configuration screen | No | No |
| `PROFILE_CONFIGURATION_INVALID` | 422 | No | Contact a manager | Disable the affected flow; log `details.field`/`reason` | No | No |
| `RESOURCE_NOT_FOUND` | 404 | No | Pick something else | Refresh the list; for sale lookups `details` is empty by design | No | No |

### Auth and permission

| Code | HTTP | Retryable | User action | Android action | Show server message? | Auto-retry? |
| --- | --- | --- | --- | --- | --- | --- |
| `PERMISSION_DENIED` | 403 | No | Contact a manager | Disable the action; do not retry. `details` is empty | No | No |
| `PROFILE_SCOPE_MISMATCH` | 403 | No | Re-select a profile | Return to profile selection; re-run `bootstrap.get` | No | No |

### Retryable contention

| Code | HTTP | Retryable | User action | Android action | Show server message? | Auto-retry? |
| --- | --- | --- | --- | --- | --- | --- |
| `REQUEST_IN_PROGRESS` | 409 | **Yes** | Wait | Wait `retry_after_seconds`, replay same key and body | No | **Yes** |
| `TEMPORARILY_UNAVAILABLE` | 503 | **Yes** | Wait | Wait `retry_after_seconds`, replay same key and body | No | **Yes** |

### Idempotency and recovery/escalation

| Code | HTTP | Retryable | User action | Android action | Show server message? | Auto-retry? |
| --- | --- | --- | --- | --- | --- | --- |
| `IDEMPOTENCY_KEY_REUSED` | 409 | No | None — client bug | The body changed under a used key; do **not** retry; reconcile read-only | No | No |
| `CLOSING_IN_PROGRESS` | 409 | No | Wait / recover | Call `closing.recover`; never a second submit | No | No |
| `CLOSING_ALREADY_CLOSED` | 409 | No | None | Treat as closed; refresh session | No | No |
| `CLOSING_RECOVERY_NOT_AVAILABLE` | 409 | No | Proceed normally | Nothing pending; take a fresh preview | No | No |
| `CLOSING_RECOVERY_REQUIRES_MANAGER` | 409 | No | Contact a manager | Hard stop; blocking dialog; poll only | No | No |

### Internal invariant and unknown failures

| Code / class | HTTP | Retryable | Android action |
| --- | --- | --- | --- |
| `IDEMPOTENCY_INVARIANT` | 500 | No | Server defect. Stop, reconcile read-only, escalate. Never auto-retry, never a new key, never a business message |
| Any 500/503 with **no** `error.code` | 500/503 | — | Native failure. Keep pending records, classify as `server_unavailable`, retry only idempotent mutations with the same key |
| Any unrecognized `error.code` | any | Treat as No | Protocol violation: log the raw code, show a generic error, keep pending state, do not invent behaviour |

### Non-error stable codes (inside successful responses)

| Code | Location | Meaning |
| --- | --- | --- |
| `STALE_OPENING` | `opening_session.warnings[].code` | The shift began on an earlier calendar day; informational |
| `MISSING_UOM_CONVERSION` | `warnings[].code` on `catalog.scan`, `catalog.quote_item` | The selected UOM has no conversion factor |
| `CLOSING_FAILED` | `closing.failure.code` on `closing.submit`, `closing.status`, `closing.recover`, `sessions.current`, `bootstrap.get` | Consolidation failed; manager must review |
| `SOURCE_NOT_RETURNABLE` | `items[].returnability.rejection_reason` | Source is draft, cancelled, or itself a return |
| `RETURN_LIMIT_REACHED` | same | No remaining returnable quantity |
| `NO_VALID_REFUND_MODE` | same | The source profile has no valid refund mode |
| `SERIAL_BATCH_REFERENCE_UNAVAILABLE` | same | The tracked row has no readable batch or serial reference |

## 15. Persistence requirements

This section says **what** must be durable, not which library to use. If the Android repository already
has a working persistence and DTO pattern, keep it — do not introduce a new database, DI framework, or
architecture on account of this document.

### Must be durable (survive process death, app kill, and reboot)

| Data | Why |
| --- | --- |
| Access token, refresh token, expiry | Avoids a re-login on every cold start; keystore-backed |
| Selected profile name | Every endpoint needs `pos_profile` |
| Authoritative opening session identity (`opening_session.name`, `pos_profile`, `lifecycle_state`) | Recovery decisions depend on it |
| **Every pending idempotent mutation**: endpoint, `X-Idempotency-Key`, the **exact serialized request body**, and a state flag (`unsent` / `in_flight`) | The only safe way to retry without duplicating a document |
| Pending closing metadata: `preview_id`, the submitted `closing_balances`, and the closing name once known | Enables replay and identifies what to poll |
| Terminal responses for sales, returns, and closings (the receipt payloads) | Reprint, audit, and safe clearing of pending state |
| Recovery flags: "a closing is unresolved", "manager review required" | Must survive a restart or the cashier can bypass the hold |

**Ordering invariant:** write the terminal response durably **before** deleting the pending record.
Deleting first and crashing loses the receipt and leaves an unknown server state.

### Must be ephemeral (never persisted as truth)

- Search text, selected tab, scroll position, expanded rows.
- Transient loading and error banners.
- **Superseded quotes.** A cart quote replaced by a newer one, and any line quote whose qty/UOM/
  customer changed, must be discarded — not kept as a fallback.
- Any Android-computed total, tax, discount, or refund. These are display-time derivations of a server
  response, and they are never inputs to a decision.
- Cached availability (`available_qty`). It drifts between terminals.

### DTO guidance

- Model money and quantities as decimal strings on the wire and a decimal type in memory. **Never a
  `float`/`Double`.** JSON floats lose cents.
- Model `rejection_reason`, `lifecycle_state`, `closing.status`, and `error.code` as TypeScript string
  unions or discriminated unions with an explicit unknown value that retains the raw string. A new server
  value must not crash the parser or map silently onto an existing case.
- Keep the response envelope (`ok`, `data`, `error`, `meta`) as one generic wrapper type. Read
  `meta.replayed` — it distinguishes "just created" from "recovered", which changes the UI copy.
- Never model a field this document does not list. An unknown extra field in a response should be
  ignored; an unknown field you *send* is `INVALID_REQUEST`.

## 16. Server-vs-Android authority matrix

| Concern | Authority | Android's role |
| --- | --- | --- |
| Cashier identity, profile assignment, company | **Server** (`bootstrap.get`) | Sends the selected `pos_profile`; never overrides company or warehouse |
| Warehouse / outlet | **Server** (derived from the profile) | Displays it; never sends one |
| Price list and selling price | **Server** | Sends item, qty, UOM, customer; displays the returned `rate` |
| Item and UOM validity | **Server** | Sends what the cashier picked; surfaces rejections |
| Custom UOM conversion factor | **Server** (`stock_additional` behaviour, surfaced by the gateway) | Uses `conversion_factor`; blocks the line on `MISSING_UOM_CONVERSION` |
| Stock availability, batch, serial | **Server** | Sends selections; `available_qty` is a hint, never a reservation |
| Tax computation | **Server** | Renders `taxes[]` |
| Discount and pricing rules | **Server** | Never applies a local discount |
| `grand_total` | **Server** | Echoes the latest quote as `client_accepted_grand_total`; accepts `PRICE_CHANGED` |
| `payable` (amount to collect) | **Server** | Settles exactly this value |
| Payment validity and exact settlement | **Server** | Pre-validates against `payment_amount_policy` to save a round trip; the server's answer is final |
| POS Invoice creation and document state | **Server** | Sends intent with an idempotency key |
| Return eligibility | **Server** (`returnability.eligible`) | Offers only eligible rows |
| Remaining returnable qty and value | **Server** (`remaining_qty`) | Caps the input; never recomputes |
| Refund amount and refund mode allowance | **Server** | Displays `refund_amount`; picks a mode only when `refund_mode_required` |
| Closing expected amounts | **Server** (`expected_payments`) | Collects the physical count only |
| Closing reconciliation and differences | **Server** | Displays `reconciliation` |
| Accounting entries and stock postings | **Server / ERPNext** | Never simulated, never predicted |
| Cart contents, selected qty, chosen UOM, chosen customer, entered tender, counted cash, return reason | **Android** (intent) | These are the *only* values Android originates |
| Idempotency key generation and pending-state durability | **Android** | The server validates the key but cannot invent it for you |

**One sentence:** Android owns *intent* and *presentation*; the server owns every *number* and every
*document state*. Any value Android computes for a preview is non-authoritative and must be replaced by
the server quote before the cashier acts on it.

## 17. Offline and network-failure behavior

**v1 has no offline sale mode.** Every price, stock check, tax, and document write requires the server.
Android must not queue sales for later submission against locally computed totals — the totals would be
stale and the stock unchecked.

What Android may do without a network:

- Show the last known catalog page and the last cart quote, clearly marked stale.
- Show persisted receipts and history detail already stored locally.
- Keep the pending-mutation queue on disk, ready to resume.

What Android must not do without a network:

- Create, price, or settle a sale or return from local data.
- Decide that a pending mutation failed. **No response is not a failure** — it is an unknown outcome.
- Delete a pending record because the request "obviously did not go through".

### Failure classification

| Symptom | Meaning | Action |
| --- | --- | --- |
| DNS/socket failure before the request left the device | Almost certainly not committed | Retry with the same key when connectivity returns |
| Timeout after the request was sent | **Unknown** | Retry with the same key; the replay reveals the truth |
| HTTP 401 | Token expired | Keep pending records, refresh the token, resume with the same key |
| HTTP 429 | Rate limited | Backoff; retry reads freely, mutations with the same key |
| HTTP 500/503 without an envelope | Server-side failure, commit status unknown | Same-key retry for mutations; surface `server_unavailable` |
| `TEMPORARILY_UNAVAILABLE` envelope | The holder of this key committed nothing | Same-key retry after `retry_after_seconds` |

Backoff for reads: exponential with jitter. Backoff for mutations: honour
`details.retry_after_seconds` when present, otherwise exponential with jitter — and always the same key.

## 18. Integration checklist

Auth and transport

- [ ] Authorization Code + PKCE `S256`; `code_challenge` always sent; no client secret anywhere
- [ ] `Authorization: Bearer` on every gateway call; no cookies, no API key
- [x] Only currently allowed exact routes are called; now 20 methods (17 v1 + 3 promo POST-only) and OAuth routes
- [x] Dynamic Promotion facades are now allowlisted and POST-only; real HTTP bearer tests pass
- [ ] No `/api/resource`, `/api/v2`, generic RPC, alternate path, or `cmd=` dispatch is used
- [ ] `message` unwrapped; `ok` / `data` / `error` / `meta` handled generically
- [ ] Native pre-dispatch failures (401/403/404/429/500/503 without an envelope) classified separately
      from `error.code`

Money and correctness

- [ ] Every decimal is a string on the wire and a decimal type in memory; no floats
- [ ] Regular line prices come only from `catalog.quote_item`; regular cart totals only from `sales.quote_cart`
- [x] Dynamic Promotion payment now uses the authoritative combined quote (`sales.quote_cart` with `promotions`)
- [ ] Settlement is against `payable`, exactly, with no change and no partial payment
- [ ] `client_accepted_grand_total` is the latest quote's `grand_total`
- [ ] `PRICE_CHANGED` replaces local totals and forces cashier re-confirmation with a new key

Idempotency

- [ ] Lowercase UUID v4 keys, one per logical intent, generated at confirmation time
- [ ] Key **and exact serialized body** persisted before the first attempt
- [ ] Retries reuse the stored key and bytes; a changed amount gets a new key
- [ ] `retryable` is the only field consulted for retry; `retry_after_seconds` honoured
- [ ] Terminal response persisted before the pending record is cleared
- [ ] Relaunch drains the pending queue before enabling cashier input

Returns

- [ ] Rows offered only when `returnability.eligible`; `rejection_reason` displayed otherwise
- [ ] Quantity capped by `remaining_qty`, read fresh from `sales.get`
- [ ] `reason` sent on `create_return`; refund mode sent only when `refund_mode_required`
- [ ] `refund_amount` displayed from the server; never computed locally

Closing

- [ ] `preview_id` sent unchanged from `closing.preview`
- [ ] `closing_balances` mirrors `expected_payments` exactly (`closing_amount` field name)
- [ ] Counted amounts validated against `counted_amount_policy` before sending
- [ ] `queued` triggers `closing.status` polling with backoff, not a resubmit
- [ ] Lost key → `closing.recover`, never a second `closing.submit`
- [ ] `CLOSING_RECOVERY_REQUIRES_MANAGER` and `closing_failed` are hard stops honouring all-false
      capabilities
- [ ] Decision table §13.8 implemented row by row

Errors and state

- [ ] Error enum frozen from §14; `SESSION_ALREADY_CLOSED` and `DOCUMENT_STATE_CONFLICT` absent
- [ ] Unknown codes logged and surfaced, never swallowed
- [ ] `DOCUMENT_VALIDATION_FAILED` shows `details.display_message`; other codes use local copy
- [ ] Capabilities from `bootstrap.get` gate the UI; `cancel_sale` never rendered
- [ ] `lifecycle_state` drives the startup branch

## 19. Known backend gaps Android must design around

All P0 blockers from `backend-readiness-audit.md` are closed (P0-1 … P0-7, verified on the four-app
test site). Everything below is P1/P2 and **not scheduled in the current workstream**. Android must plan
around the current runtime, not around a promised fix.

### Capabilities that do not exist

| Missing capability | Runtime reality | What Android must do | Finding |
| --- | --- | --- | --- |
| **Logout / token revocation** | **NOT PROVIDED BY BACKEND.** No revoke or logout endpoint. Android holds no secret for Frappe's `client_secret_basic` revocation, so public-client revocation is not assumed to work | Logout = delete local tokens and wipe cached state. A manager revokes the OAuth Bearer Token record or disables the user in ERPNext Desk. Do not claim server-side sign-out in the UI | M-11 (P2) |
| **Current-session sale history** | `sales.list` is profile-scoped, not opening-scoped | Filter client-side against `opening_session.period_start_date` if a "this shift" view is required, and treat it as approximate | I-7 (P1) |
| **Backend / minimum-client compatibility signal** | `bootstrap.get` carries no deployment revision, contract revision, or minimum Android version | Pin the contract version in the Android build and verify the target site manually before release. There is no server handshake to detect a mismatch | I-12 (P1) |
| **Configuration diagnosis** | A missing OAuth client setting fails closed as a plain pre-dispatch rejection with no targeted error | Distinguish "wrong credentials" from "server not configured" only by an operator-facing generic message; do not attempt to auto-diagnose | I-13 (P1) |

### Behaviours to code defensively against

| Issue | Impact on Android | Finding |
| --- | --- | --- |
| A reloaded return can lose its reason and change its item contract | Do not assume a re-fetched return detail is byte-identical to the create response; persist your own terminal receipt | I-11 (P1) |
| Catalog `has_more` can be a false positive at page boundaries | Tolerate an empty next page; do not treat it as an error | M-5 (P2) |
| Sale read `status` values are not exhaustively defined | Handle unknown status strings as informational text, not as a business branch | M-6 (P2) |
| Some `PROFILE_CONFIGURATION_INVALID` details deviate from the documented schema | Read `details` defensively; never crash on a missing `field` or `pos_profile` | M-7 (P2) |
| `sales.quote_cart` can surface item-level errors not enumerated per endpoint | Handle every §14 code on the quote path, not just the ones listed under quote-cart | M-9 (P2) |
| `meta.request_id` format and log-correlation semantics are informal | Log it verbatim for support; do not parse it | M-10 (P2) |
| Catalog and customer text search have unbounded high-offset cost | Keep `limit` modest and honour the `start` ≤ 1000 catalog cap; do not deep-paginate | I-9, I-10 (P1) |

### Not in v1 at all

- Sale cancellation (`capabilities.cancel_sale` is permanently `false`).
- Partial payment and change.
- Customer creation.
- Direct Sales Invoice mode (only `POS Invoice`).
- Any push channel: every state change is discovered by polling.

## 20. DO NOT GUESS

If this document and `api-contract.md` do not state it, it does not exist. When something is missing,
stop and ask a backend owner — do not fill the gap with an assumption.

1. **Do not guess endpoint names.** The 20 in §7 are the currently allowed gateway surface (17 v1 + 3 promo POST-only). The promotion facades are now allowlisted per §7.18.
2. **Do not guess HTTP methods.** `catalog.scan` and `catalog.quote_item` are **POST**. `closing.recover`
   is **POST**. Everything read-only in §7 is GET except `sales.quote_cart` and `sales.quote_return`,
   which are POST.
3. **Do not guess field names.** `amount` in `sessions.open`, `closing_amount` in `closing.submit`,
   `client_accepted_grand_total` in `sales.submit`, `source_item_row` in returns. An unknown field is
   rejected.
4. **Do not guess error codes.** 30 exist. Two removed ones must not be defined.
5. **Do not guess a retry policy.** `error.retryable` decides; only two codes are `true`.
6. **Do not guess whether a key may be reused.** Same intent → same key. Changed amount → new key.
7. **Do not guess a decimal format.** `ascii_decimal_dot`, string, no exponent, no sign, scale from the
   policy object, `rounding: "reject"`.
8. **Do not guess a total.** Any number the cashier sees before payment must come from a server quote.
9. **Do not guess closing state.** Use the §13.8 table; when in doubt, `closing.recover` or poll.
10. **Do not guess that a timeout means failure.** It means unknown. Replay the key.
11. **Do not derive a promotion checkout total.** `quote_promotion.total_price` is not POS Invoice tax,
    rounding, `grand_total`, `payable`, or payment authority. Stop at §7.18.

## Rules for Android AI Agents

These twelve rules are binding on any AI agent modifying the Android client.

1. **Do not call raw Frappe DocType APIs** (`/api/resource/*`, `frappe.client.*`, `/api/v2/*`) when the
   gateway already covers the capability. The auth hook rejects them for a Mobile POS token, and a route
   that happens to work today is a security regression, not a feature.
2. **Do not recreate ERPNext business logic locally.** No local pricing, tax, discount, stock,
   returnability, refund, or reconciliation engine. Call the quote endpoints.
3. **Do not invent API fields.** Send only the fields listed in §7. Unknown fields are rejected with
   `INVALID_REQUEST`, and a field that is silently accepted today may be rejected tomorrow.
4. **Do not invent error codes.** The enum is frozen from §14. Do not resurrect `SESSION_ALREADY_CLOSED`
   or `DOCUMENT_STATE_CONFLICT`.
5. **Do not silently ignore an unknown error code.** Log the raw value, surface a generic error, keep
   pending state intact. Swallowing an unknown code hides a contract break until it costs money.
6. **Do not generate a new idempotency key when retrying the same logical mutation.** Same intent means
   the same key and the same stored bytes. A new key on a retry is how one sale becomes two.
7. **Do not delete pending mutation state before the terminal authoritative response is durably
   stored.** Write the terminal record first, then clear the pending record — never the reverse.
8. **Do not create a second closing while a recovery is unresolved.** If `closing.recover` returns
   `CLOSING_RECOVERY_REQUIRES_MANAGER`, or the session reports `closing_in_progress` /
   `closing_failed`, submitting again is forbidden. Poll and escalate.
9. **Do not treat Android-computed totals as authoritative.** A local sum is a preview. The server's
   `payable`, `grand_total`, `refund_amount`, and `expected_amount` are the only real numbers.
10. **Do not bypass the gateway using ERPNext endpoints.** A dedicated mobile-only cashier may call the
    20 exact routes (17 v1 + 3 promo POST-only) and the four OAuth routes. Never add a desk-access role to an Android cashier.
    The promotion facades are now allowlisted per §7.18.
11. **Do not implement promotion payment from separate local sums.** Wait for one authoritative backend
    quote covering regular-only, promotion-only, and mixed carts.
12. **Read this document before modifying Android networking, domain, or recovery code.** If a change
    seems to require a behaviour this document does not describe, the change is wrong or the backend
    needs a contract update first — raise it, do not improvise.

