# Mobile POS API Contract v1

## Evidence Legend

- **Verified**: Confirmed in installed Frappe, ERPNext, or bakery source.
- **Approved**: A Phase 0 API decision approved for implementation.
- **Proposed**: The v1 contract to implement.
- **Inferred**: Derived behavior requiring validation.

## Transport

- **Proposed**: Base path: `/api/method/roti_ropi_pos.api.v1.<module>.<method>`.
- **Verified**: Frappe wraps a whitelisted method's return value in the top-level `message` property.
- **Proposed**: HTTPS is mandatory. JSON request bodies use `Content-Type: application/json`.
- **Approved**: Android sends `Authorization: Bearer <access_token>` using an active token issued to the configured public Mobile POS OAuth Client through Authorization Code with mandatory PKCE S256. The token user must be enabled and have `Mobile POS Cashier`. Cookie, API-key, Basic, shared, wrong-client bearer, and embedded-secret access are prohibited.
- **Proposed**: Mutations require `X-Idempotency-Key` and accept `POST` only.
- **Proposed**: Monetary amounts and quantities are decimal strings. Dates are `YYYY-MM-DD`; timestamps are ISO 8601 with an offset.
- **Approved**: Every v1 endpoint requires ERPNext POS Settings invoice mode `POS Invoice` and returns the same `UNSUPPORTED_POS_MODE` error when the site is configured for direct Sales Invoice mode.

## Envelopes

### Success

```json
{
  "message": {
    "ok": true,
    "data": {},
    "meta": {
      "api_version": "v1",
      "request_id": "01K0Y8Q9B2M6FG7J6JM2H4R8HX",
      "server_time": "2026-07-23T14:30:00+07:00",
      "replayed": false
    }
  }
}
```

### Expected Error

```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "NO_OPEN_SESSION",
      "message": "No open POS session is available for this profile.",
      "details": {
        "pos_profile": "OUTLET-01"
      },
      "retryable": false
    },
    "meta": {
      "api_version": "v1",
      "request_id": "01K0Y8Q9B2M6FG7J6JM2H4R8HX",
      "server_time": "2026-07-23T14:30:00+07:00",
      "replayed": false
    }
  }
}
```

- **Proposed**: Known errors raised after a v1 endpoint starts are mapped to this envelope and an appropriate HTTP status after rollback to the endpoint savepoint.
- **Verified**: Authentication failure, Guest rejection, mobile route-hook rejection, rate limiting, malformed routing, and some server failures happen before endpoint code and use Frappe's native error body.
- **Proposed**: Android normalizes native pre-dispatch responses into its transport error model; it must not require a `message.ok` envelope for those failures.
- **Proposed**: Unknown endpoint exceptions use Frappe's HTTP 500 response and expose only server-side diagnostic identifiers.
- **Approved**: Read-only endpoint adapters own their successful `success(...)` envelope.
- **Approved**: The common endpoint decorator owns stable expected-error envelopes.
- **Approved**: For standard mutations, `execute_idempotent` is the sole owner of successful envelope creation, HTTP status persistence, replay metadata, and stored response serialization.
- **Approved**: Standard business-operation callbacks return domain data and a durable business reference; they do not call `success(...)`.
- **Approved**: Expected errors from standard mutations are rolled back and mapped by the endpoint decorator; they are not stored by `execute_idempotent`.
- **Approved**: Closing remains the documented exception: its closing-specific recovery executor may durably store and replay a stable `Rejected` envelope.

## Native Pre-Dispatch Errors

| HTTP | Source | Android classification |
| --- | --- | --- |
| 401 | Invalid/expired credentials or expired session | `authentication_required` |
| 403 | Guest rejection, Mobile route auth hook, or disallowed HTTP method | `route_forbidden` or `method_not_allowed` |
| 404 | Unknown or malformed API route | `route_not_found` |
| 429 | Frappe rate limiting | `rate_limited` |
| 500/503 | Unexpected server failure or server availability | `server_unavailable` |

- **Proposed**: These classifications are Android-local transport states, not values in a v1 `message.error.code` envelope.

## Stable In-Endpoint Error Codes

| HTTP | Code | Meaning | Retryable |
| --- | --- | --- | --- |
| 400 | `INVALID_REQUEST` | Syntax, type, or unsupported field error | No |
| 403 | `PERMISSION_DENIED` | Missing role or core permission | No |
| 403 | `PROFILE_SCOPE_MISMATCH` | Profile/document is outside user scope | No |
| 404 | `RESOURCE_NOT_FOUND` | Visible resource does not exist | No |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Same key has a different request hash | No |
| 409 | `SESSION_ALREADY_OPEN` | User/profile has a conflicting opening | No |
| 409 | `SESSION_ALREADY_CLOSED` | Opening is no longer open | No |
| 409 | `DOCUMENT_STATE_CONFLICT` | Operation conflicts with current ERPNext state | Usually no |
| 409 | `REQUEST_IN_PROGRESS` | A durably started closing request is still being processed | Yes |
| 422 | `NO_OPEN_SESSION` | Sale requires an active opening | No |
| 422 | `UNSUPPORTED_POS_MODE` | Site is not configured for POS Invoice mode | No |
| 422 | `PRICE_CHANGED` | Authoritative price differs from accepted client quote | No |
| 422 | `INSUFFICIENT_STOCK` | ERPNext rejects available stock | No |
| 422 | `INVALID_BATCH` | Batch is absent, expired, incompatible, or insufficient | No |
| 422 | `INVALID_SERIAL_NUMBER` | Serial selection is invalid | No |
| 422 | `INVALID_PAYMENT` | Payment rows violate profile/invoice rules | No |
| 422 | `RETURN_LIMIT_EXCEEDED` | Requested return exceeds source sale | No |
| 422 | `PROFILE_CONFIGURATION_INVALID` | Assigned POS Profile configuration cannot satisfy the requested operation | No |
| 503 | `TEMPORARILY_UNAVAILABLE` | Dependency or worker unavailable | Yes |

### Error Detail Schemas

| Code | Required `details` fields |
| --- | --- |
| `INVALID_REQUEST` | `field: string`, `reason: string` |
| `PERMISSION_DENIED` | Empty object |
| `PROFILE_SCOPE_MISMATCH` | `pos_profile: string` |
| `RESOURCE_NOT_FOUND` | `resource_type: string`; optional `name: string` |
| `IDEMPOTENCY_KEY_REUSED` | `endpoint: string` |
| `SESSION_ALREADY_OPEN` | `opening_entry: string`, `pos_profile: string` |
| `SESSION_ALREADY_CLOSED` | `opening_entry: string` |
| `DOCUMENT_STATE_CONFLICT` | `doctype: string`, `name: string`, `state: string` |
| `REQUEST_IN_PROGRESS` | `endpoint: string`, `retry_after_seconds: integer` |
| `NO_OPEN_SESSION` | `pos_profile: string` |
| `UNSUPPORTED_POS_MODE` | `configured_mode: string`, `required_mode: "POS Invoice"` |
| `PRICE_CHANGED` | `accepted_grand_total: decimal string`, `authoritative_grand_total: decimal string`, `currency: string`, `items: SaleItem[]`, `taxes: SaleTax[]` |
| `INSUFFICIENT_STOCK` | `item_code: string`, `warehouse: string`, `requested_qty: decimal string`, `available_qty: decimal string` |
| `INVALID_BATCH` | `item_code: string`, `batch_no: string`, `reason: string` |
| `INVALID_SERIAL_NUMBER` | `item_code: string`, `serial_no: string`, `reason: string` |
| `INVALID_PAYMENT` | `mode_of_payment: string or null`, `reason: string` |
| `RETURN_LIMIT_EXCEEDED` | `source_item_row: string`, `requested_qty: decimal string`, `remaining_qty: decimal string` |
| `PROFILE_CONFIGURATION_INVALID` | `pos_profile: string`, `field: string`, `reason: string` |
| `TEMPORARILY_UNAVAILABLE` | `retry_after_seconds: integer` |

- **Proposed**: `details` is always an object. Clients ignore additive unknown fields but may rely on the required fields above.

## Shared Objects

### POS Profile Summary

```json
{
  "name": "OUTLET-01",
  "company": "Roti Ropi",
  "warehouse": "Outlet 01 - RR",
  "currency": "IDR",
  "selling_price_list": "PG-Outlet 01",
  "customer": "Walk In Customer",
  "allow_partial_payment": false,
  "invoice_mode": "POS Invoice"
}
```

### Opening Session

```json
{
  "name": "POS-OPE-2026-00001",
  "pos_profile": "OUTLET-01",
  "company": "Roti Ropi",
  "user": "cashier@example.com",
  "status": "open",
  "posting_date": "2026-07-23",
  "period_start_date": "2026-07-23T08:00:00+07:00",
  "opening_balances": [
    {"mode_of_payment": "Cash", "opening_amount": "500000"}
  ],
  "warnings": []
}
```

- **Approved**: `posting_date` is the ERPNext opening posting date and `period_start_date` is the opening timestamp.
- **Approved**: `warnings` is always an array.
- **Approved**: When `period_start_date` is on an earlier calendar date in the configured site timezone, `warnings` contains:

```json
{
  "code": "STALE_OPENING",
  "message": "The current POS opening started on an earlier calendar day.",
  "details": {
    "opening_date": "2026-07-22",
    "server_date": "2026-07-23"
  }
}
```

- **Approved**: The warning is informational and does not invalidate the opening. No maximum shift-duration policy exists in the MVP.

### Sale Summary

```json
{
  "doctype": "POS Invoice",
  "name": "ACC-PSINV-2026-00001",
  "status": "paid",
  "customer": "Walk In Customer",
  "walk_in_customer_name": "Ayu",
  "currency": "IDR",
  "grand_total": "55000",
  "paid_amount": "55000",
  "change_amount": "0",
  "posting_date": "2026-07-23",
  "posting_time": "14:25:00"
}
```

### Sale Detail

```json
{
  "summary": {
    "doctype": "POS Invoice",
    "name": "ACC-PSINV-2026-00001",
    "status": "paid",
    "customer": "Walk In Customer",
    "walk_in_customer_name": "Ayu",
    "currency": "IDR",
    "grand_total": "55000",
    "paid_amount": "55000",
    "change_amount": "0",
    "posting_date": "2026-07-23",
    "posting_time": "14:25:00"
  },
  "items": [
    {
      "row_id": "8f1a2b3c4d",
      "item_code": "CROISSANT-PACK",
      "item_name": "Croissant Pack",
      "qty": "2",
      "uom": "Pack",
      "conversion_factor": "6",
      "rate": "25000",
      "amount": "50000",
      "batch_no": "BATCH-QR-0001",
      "serial_numbers": []
    }
  ],
  "taxes": [
    {"description": "VAT", "rate": "10", "tax_amount": "5000", "total": "55000"}
  ],
  "payments": [
    {"mode_of_payment": "Cash", "amount": "55000", "reference_no": null}
  ]
}
```

- **Proposed**: Opening status values are `open`, `closed`, and `cancelled`.
- **Approved**: A sale created by the MVP can end only in a fully settled submitted status such as `paid`; it never creates `partly_paid` or `unpaid`. Read responses may also contain `return`, `consolidated`, or `cancelled` for later lifecycle states.

## Endpoints

- **Approved**: The endpoint inventory below is the complete approved v1 surface.
- **Approved**: V1 has no health endpoint and no return-preview endpoint. Either addition requires explicit approval as a new backend contract and task.

### `GET bootstrap.get`

- **Proposed**: Returns user identity, eligible profiles, current opening, capabilities, and server configuration needed to start the app.
- **Proposed**: Optional query: `pos_profile` to select one eligible profile.

```json
{
  "user": {"name": "cashier@example.com", "full_name": "Cashier One"},
  "profiles": [],
  "selected_profile": null,
  "opening_session": null,
  "capabilities": {
    "open_session": false,
    "submit_sale": false,
    "create_return": false,
    "cancel_sale": false,
    "close_session": false
  },
  "pos_mode": "POS Invoice"
}
```

- **Approved**: Every capability is derived from the authenticated user, selected authorized profile, current opening, supported POS mode, and exact DocType permissions; it is never accepted from the client.
- **Approved**: `open_session` is true only when an authorized selected profile exists, no active opening exists for that cashier/profile decision, and the user has POS Opening Entry create and submit permission.
- **Approved**: `submit_sale` is true only when an authorized selected profile and active submitted/unclosed opening exist and the user has POS Invoice create and submit permission.
- **Approved**: `create_return` is true only when an authorized selected profile and active submitted/unclosed opening exist and the user has POS Invoice read, create, and submit permission. Source-sale visibility and remaining quantity are still checked by the return endpoint.
- **Approved**: `cancel_sale` is always false in v1.
- **Approved**: `close_session` is true only when an authorized selected profile and active submitted/unclosed opening exist and the user has POS Closing Entry create and submit permission.
- **Approved**: When no profile is selected, every mutation capability is false. The API must not advertise a mutation that would immediately fail a server-known prerequisite.
- **Approved**: `allow_partial_payment` is always `false` in the v1 contract even if a POS Profile is configured otherwise; the API enforces the MVP invariant.

### `GET sessions.current`

- **Proposed**: Query: `pos_profile` (required).
- **Approved**: Returns the submitted, Open, unclosed Opening Entry owned by the authenticated cashier, assigned to the selected enabled profile, and matching the authorized profile Company, or `null`.
- **Approved**: No hard current-calendar-day filter applies.
- **Approved**: A prior-day opening remains current and contains `STALE_OPENING` in its DTO warnings.
- **Approved**: The response always exposes the opening `posting_date`, `period_start_date`, and warning array when an opening exists.
- **Verified**: Core `check_opening_entry` trusts a user argument, so the facade supplies only `frappe.session.user`.

```json
{
  "opening_session": null
}
```

### `POST sessions.open`

```json
{
  "pos_profile": "OUTLET-01",
  "opening_balances": [
    {"mode_of_payment": "Cash", "amount": "500000"},
    {"mode_of_payment": "Card", "amount": "0"}
  ]
}
```

- **Proposed**: Reject unknown or duplicate payment modes and derive company/user from the profile and session.
- **Proposed**: Returns `{ "opening_session": OpeningSession }`. The endpoint sets `frappe.response.http_status_code` to 201 on first execution and 200 on replay.

### `GET customers.search`

- **Approved**: Query: `pos_profile` (required), `q` (default empty), `start` (default `0`), and `limit` (default `20`, maximum `100`).
- **Approved**: Results include only existing enabled Customers visible through normal Customer read permissions.
- **Approved**: The authorized profile fixes Company and Customer Group scope. A Customer is eligible when:
  `profile.customer_groups is empty OR customer.customer_group is in the configured groups' closure`.
- **Approved**: The closure includes each configured Customer Group and all descendants.
- **Approved**: Customer is a global master without an ordinary Company ownership field. The endpoint must not invent a Company field or relation.
- **Approved**: This endpoint never creates or modifies a Customer.

```json
{
  "customers": [
    {
      "name": "CUST-2026-00001",
      "customer_name": "Ayu Bakery",
      "mobile_no": "081234567890",
      "is_default_walk_in": false
    }
  ],
  "page": {"start": 0, "limit": 20, "has_more": false}
}
```

- **Approved**: An empty search may include the POS Profile's default walk-in Customer with `is_default_walk_in: true`.

### `GET catalog.search`

- **Proposed**: Query: `pos_profile` (required), `q` (default empty), `item_group` (optional), `start` (default `0`), `limit` (default `20`, maximum `100`).
- **Proposed**: Returns display items and pagination metadata. Results are scoped to the profile's item groups, price list, warehouse, and Item Group user permissions.

```json
{
  "items": [
    {
      "item_code": "CROISSANT",
      "item_name": "Croissant",
      "description": "Butter croissant",
      "image": null,
      "uom": "Nos",
      "price_list_rate": "15000",
      "currency": "IDR",
      "available_qty": "18"
    }
  ],
  "page": {"start": 0, "limit": 20, "has_more": false}
}
```

- **Proposed**: Catalog price and stock are snapshots, not guarantees.

### `POST catalog.scan`

```json
{
  "pos_profile": "OUTLET-01",
  "value": "BATCH-QR-0001"
}
```

```json
{
  "scan": {
    "item_code": "CROISSANT-PACK",
    "barcode": null,
    "batch_no": "BATCH-QR-0001",
    "serial_no": null,
    "uom": "Pack",
    "conversion_factor": "6",
    "warehouse": "Outlet 01 - RR"
  },
  "warnings": []
}
```

- **Proposed**: Calls the effective ERPNext method so the bakery override applies.
- **Proposed**: Returns `RESOURCE_NOT_FOUND` if no item/serial/batch/barcode resolves.

### `POST catalog.quote_item`

```json
{
  "pos_profile": "OUTLET-01",
  "customer": null,
  "item_code": "CROISSANT-PACK",
  "qty": "2",
  "uom": "Pack",
  "batch_no": "BATCH-QR-0001"
}
```

- **Proposed**: Returns server-calculated item rate, discount, UOM conversion, warehouse, available quantity, item tax template, and warnings.
- **Proposed**: This is a quote for UI feedback; sale submission recalculates it.
- **Approved**: Omitted or null `customer` resolves to the profile's default walk-in Customer. A supplied value must be an existing enabled Customer visible to `Mobile POS Cashier`; no Customer is created.

```json
{
  "item": {
    "item_code": "CROISSANT-PACK",
    "qty": "2",
    "uom": "Pack",
    "conversion_factor": "6",
    "warehouse": "Outlet 01 - RR",
    "available_qty": "18",
    "price_list_rate": "25000",
    "discount_percentage": "0",
    "rate": "25000",
    "item_tax_template": "VAT 10% - RR"
  },
  "warnings": []
}
```

- **Proposed**: When `uom` is present but `conversion_factor` is absent, `warnings` contains `{ "code": "MISSING_UOM_CONVERSION", "message": "The selected UOM has no conversion factor." }`.

### `POST sales.submit`

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
    },
    {
      "item_code": "COFFEE",
      "qty": "1",
      "uom": "Cup",
      "batch_no": null,
      "serial_numbers": []
    }
  ],
  "payments": [
    {"mode_of_payment": "Cash", "amount": "60000", "reference_no": null}
  ]
}
```

- **Proposed**: Reject client-supplied accounts, rates, discounts, tax rows, company, warehouse, owner, posting status, paid totals, and document names.
- **Proposed**: Rebuild rows against current profile/customer context and submit one POS Invoice.
- **Proposed**: If `client_accepted_grand_total` differs from the authoritative total, return `PRICE_CHANGED` with the new summary and create no invoice.
- **Approved**: Null or omitted `customer` resolves to `POS Profile.customer`.
- **Approved**: A supplied Customer must already exist, be enabled, pass normal read permissions, and satisfy the same authorized-profile Customer predicate used by `customers.search`.
- **Approved**: The configured default Customer passes those same checks after its name is resolved from the POS Profile. A missing, disabled, permission-inaccessible, or predicate-ineligible default returns `PROFILE_CONFIGURATION_INVALID`; it is never trusted merely because it came from the profile.
- **Approved**: Quote supplies the profile Company and Customer context but is non-authoritative. POS Invoice submission is the authoritative Company/account/internal-party compatibility gate.
- **Approved**: `walk_in_customer_name` is optional only when the resolved Customer equals the profile's default walk-in Customer. It maps to bakery's existing `custom_walk_in_customer_name`; the field is rejected for a registered non-walk-in Customer.
- **Approved**: The endpoint never creates a Customer.
- **Approved**: Payment modes must be distinct, enabled for the profile, and use server-derived accounts. Multiple modes are allowed only when core calculation finishes with `outstanding_amount == 0`; underpayment returns `INVALID_PAYMENT` and creates no invoice. Overpayment/change remains subject to ERPNext's core POS rules.
- **Proposed**: Returns `{ "sale": SaleDetail }`; first execution sets HTTP 201 and replay sets HTTP 200.

### `GET sales.get`

- **Approved**: Query: `name` (required). V1 reads POS Invoice only.
- **Proposed**: Returns `{ "sale": SaleDetail }` for a sale visible within the user's profile scope.

### `GET sales.list`

- **Proposed**: Query: `pos_profile` (required), `status` (required), `q` (optional), `start` (default `0`), `limit` (default `20`, maximum `100`).
- **Proposed**: Accepted list filters are `all`, `paid`, `return`, `consolidated`, and `cancelled`; the facade maps them to explicit core filters.
- **Approved**: Includes POS Invoice summaries only and preserves bakery's `custom_walk_in_customer_name` as `walk_in_customer_name`.

```json
{
  "sales": [
    {
      "doctype": "POS Invoice",
      "name": "ACC-PSINV-2026-00001",
      "status": "paid",
      "customer": "Walk In Customer",
      "walk_in_customer_name": "Ayu",
      "currency": "IDR",
      "grand_total": "55000",
      "paid_amount": "55000",
      "change_amount": "0",
      "posting_date": "2026-07-23",
      "posting_time": "14:25:00"
    }
  ],
  "page": {"start": 0, "limit": 20, "has_more": false}
}
```

### `POST sales.create_return`

```json
{
  "source_name": "ACC-PSINV-2026-00001",
  "items": [
    {"source_item_row": "row-id-1", "qty": "1"}
  ],
  "payments": [
    {"mode_of_payment": "Cash", "amount": "-30000"}
  ],
  "reason": "Customer returned one pack"
}
```

- **Approved**: The source is always POS Invoice in v1. Direct Sales Invoice mode and Sales Invoice returns are outside MVP scope.
- **Proposed**: Build from ERPNext's POS Invoice return mapper, apply requested negative quantities, recalculate, and submit.
- **Approved**: Trim and validate a non-empty `reason`.
- **Approved**: Append `Mobile POS Return Reason: <reason>` to standard `POS Invoice.remarks`.
- **Approved**: Preserve existing remarks and insert exactly one newline before the appended content when existing remarks are non-empty.
- **Proposed**: Return `{ "return_sale": SaleDetail }`; first execution sets HTTP 201 and replay sets HTTP 200.
- **Approved**: V1 does not expose a separate return-preview endpoint.

- **Approved**: V1 exposes no `sales.cancel` endpoint to Android. Cashier corrections use `sales.create_return`; manager cancellation remains an ERPNext Desk operation and may be designed separately after MVP.

### `GET closing.preview`

- **Proposed**: Query: `pos_profile` (required).
- **Proposed**: Derives the current user's Opening Entry, period, and invoice set.

```json
{
  "opening_session": {
    "name": "POS-OPE-2026-00001",
    "pos_profile": "OUTLET-01",
    "company": "Roti Ropi",
    "user": "cashier@example.com",
    "status": "open",
    "posting_date": "2026-07-22",
    "period_start_date": "2026-07-22T20:00:00+07:00",
    "opening_balances": [
      {"mode_of_payment": "Cash", "opening_amount": "500000"}
    ],
    "warnings": [
      {
        "code": "STALE_OPENING",
        "message": "The current POS opening started on an earlier calendar day.",
        "details": {
          "opening_date": "2026-07-22",
          "server_date": "2026-07-23"
        }
      }
    ]
  },
  "invoice_count": 12,
  "grand_total": "820000",
  "expected_payments": [
    {
      "mode_of_payment": "Cash",
      "opening_amount": "500000",
      "expected_amount": "980000"
    }
  ]
}
```

### `POST closing.submit`

```json
{
  "pos_profile": "OUTLET-01",
  "closing_balances": [
    {"mode_of_payment": "Cash", "closing_amount": "975000"}
  ]
}
```

- **Proposed**: Re-derives invoices and expected amounts, creates POS Closing Entry, and submits it.
- **Proposed**: Returns the object below. The endpoint does not call consolidation helpers directly.

```json
{
  "closing": {
    "name": "POS-CLO-2026-00001",
    "opening_entry": "POS-OPE-2026-00001",
    "pos_profile": "OUTLET-01",
    "status": "queued",
    "invoice_count": 12,
    "failure": null
  }
}
```

### `GET closing.status`

- **Proposed**: Query: `name` (required).
- **Proposed**: Returns the same `closing` object with refreshed status. Allowed API statuses are `draft`, `queued`, `submitted`, `failed`, and `cancelled`.
- **Proposed**: Failed status returns `failure: {"code": "CLOSING_FAILED", "message": "Closing failed. A manager must review it in ERPNext."}` and never returns the raw core traceback/error message.
- **Proposed**: V1 has no mobile closing-retry endpoint. A manager reviews and retries failed consolidation in ERPNext Desk.

## Compatibility Rules

- **Proposed**: Additive fields may appear in v1 responses; Android must ignore unknown fields.
- **Proposed**: Existing field meaning, type, requiredness, and error-code meaning do not change within v1.
- **Proposed**: Breaking changes require `api.v2` modules and parallel support during client migration.
- **Proposed**: Internal ERPNext document names and fields not listed here are not part of the mobile contract.

## Approved MVP Invariants

- **Approved**: OAuth bearer tokens come only from Authorization Code with PKCE S256 for an individual cashier and a public Android client.
- **Approved**: Registered-customer selection and the POS Profile default walk-in Customer are supported; Customer auto-creation is forbidden.
- **Approved**: Every submitted sale is fully settled. Partial payment is post-MVP.
- **Approved**: POS Invoice is the only v1 invoice mode. Other configuration returns `UNSUPPORTED_POS_MODE` with `configured_mode` and `required_mode` details.
- **Approved**: Android cancellation is outside MVP scope.
