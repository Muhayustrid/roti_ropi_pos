# Task 10 Authoritative Return Contract Design

## Scope

This change makes ERPNext the sole authority for Mobile POS returns. Android sends an original POS Invoice name, original row IDs, requested positive quantities, a required reason, and `refund_mode` only when the server reports more than one valid refund mode. Android never sends a refund amount, payment allocation, account, rate, tax, discount, rounding value, or other accounting value.

The existing `sales.list`, `sales.get`, and idempotency infrastructure remain the base. One read-only `sales.quote_return` endpoint is added because selected quantities can change discounts, taxes, rounding, and the refund total; sale detail alone cannot safely preview those values.

## Endpoint Workflow

1. `GET sales.list` returns paginated POS Invoice summaries scoped to the authenticated cashier, authorized POS Profile, and company.
2. `GET sales.get` returns sale detail plus a fresh return projection calculated from submitted ERPNext documents.
3. Android selects original row IDs and quantities. If sale detail exposes one valid refund mode, Android omits `refund_mode`; if it exposes multiple modes, Android selects and sends one exact mode name.
4. `POST sales.quote_return` maps the requested rows through ERPNext without persistence and returns authoritative calculated items, discounts, taxes, totals, rounding, refund amount, and refund allocation. The quote is non-binding and creates no POS Invoice or Mobile POS Request.
5. `POST sales.create_return` repeats all validation and calculation while holding a database lock on the original POS Invoice, submits the normal ERPNext return POS Invoice, and returns receipt-ready detail. The quote is never trusted during submission.
6. Same-key replay requires the identical normalized request, including `refund_mode` when required, and returns the same return POS Invoice reference.

## Sale Detail Return Projection

For each row of a submitted, non-return original POS Invoice, `sale.items[].returnability` contains:

```json
{
  "original_row_id": "row-id-1",
  "item_code": "ITEM-001",
  "original_qty": "2",
  "returned_qty": "1",
  "remaining_qty": "1",
  "uom": "Nos",
  "batch_numbers": [],
  "serial_numbers": [],
  "eligible": true,
  "rejection_reason": null
}
```

`returned_qty` is the exact sum of absolute quantities from submitted POS Invoice returns whose `return_against` is the original invoice and whose child `pos_invoice_item` is the original row ID. Draft and cancelled returns never count. `remaining_qty` is `original_qty - returned_qty`, clamped only to exact zero. A row is ineligible when the source document is not a submitted non-return invoice, nothing remains, its serial/batch references cannot be safely resolved, or current permissions/configuration cannot support a return. Rejection reasons are stable machine values.

The sale-level `return_contract` contains `quantity_policy`, `allowed_refund_modes`, `refund_mode_required`, and the current invoice-level eligibility reason. Reads remain available without an active opening, but quote/create return `NO_OPEN_SESSION` until the cashier has a submitted Open opening for the same profile.

## Refund Mode and Allocation

Valid refund modes are enabled Mode of Payment rows configured on the source POS Profile with `allow_in_returns = 1` and a default Mode of Payment Account for the profile Company, preserving POS Profile order.

- Zero valid modes: `PROFILE_CONFIGURATION_INVALID`, field `refund_modes`, reason `no_valid_refund_mode`; no artifacts.
- One valid mode: the server selects it and rejects client-supplied `refund_mode` as server-owned.
- Multiple valid modes: `refund_mode` is required and must exactly match one `allowed_refund_modes[].mode_of_payment` value.
- Missing required mode: `INVALID_REQUEST`, field `refund_mode`, reason `required_for_multiple_refund_modes`.
- Unknown/disallowed mode: `INVALID_PAYMENT`, reason `refund_mode_not_allowed`, with sanitized `allowed_refund_modes` names.

The server creates exactly one refund payment row for the selected mode. Its amount is the authoritative negative payable: `rounded_total` when ERPNext applies rounding, otherwise `grand_total`. The response exposes positive `refund_amount` for display and negative allocation/payment values matching the persisted POS Invoice. Account selection and ledger allocation remain internal ERPNext behavior.

## Return Quantity Decimal Policy

Policy version: `return-quantity/v1`.

- Input type: JSON string only.
- Syntax: ASCII digits with one optional decimal dot and at least one digit on each used side, matching `[0-9]+(?:\.[0-9]+)?`.
- Whitespace, grouping separators, exponent notation, leading `+`, leading `-`, empty fractions, NaN, and infinity are rejected.
- Sign: request quantities are positive; the server creates negative ERPNext return quantities.
- Zero: rejected.
- Scale: at most the effective ERPNext `POS Invoice Item.qty` precision, capped by the installed `decimal(21,9)` storage scale. The current development fixture resolves to two decimal places. Excess scale is rejected; no rounding or truncation occurs.
- Minimum: one unit at the allowed scale (`1` at scale zero, otherwise `0.00...1`).
- Maximum: the row's current `remaining_qty`, additionally bounded by the installed decimal storage capacity.
- Comparison: parsed `Decimal` values are compared exactly against submitted-document aggregates before any ERPNext document assignment.

There is no refund-amount input policy because Android never submits a refund amount.

## Concurrency, Idempotency, and Rollback

`sales.create_return` takes a `FOR UPDATE` lock on the original POS Invoice, then uses a locking current read for submitted prior return rows before mapping and submitting. The current read deliberately bypasses any older MariaDB `REPEATABLE-READ` snapshot established by idempotency lookup. Different idempotency keys therefore serialize on one source invoice; the loser sees the winner, refreshes remaining quantities, and receives `RETURN_LIMIT_EXCEEDED` rather than creating an excess return.

Duplicate logical row IDs are rejected before mutation. `RETURN_LIMIT_EXCEEDED` is HTTP 422 and contains `source_name`, `source_item_row`, `requested_qty`, `remaining_qty`, and `refresh_endpoint: "v1.sales.get"`. Ineligible source documents/rows, malformed decimals, and invalid refund modes are stable validation errors.

The existing `execute_idempotent("v1.sales.create_return", ...)` owns canonical hashing, exactly-one Mobile POS Request, same-result replay, and savepoint rollback. Any rejected or failed mutation leaves no return POS Invoice and no Mobile POS Request. Unknown ERPNext exceptions remain unknown errors after rollback rather than being mislabeled.

## Serial and Batch Returns

Sale detail resolves direct fields and Serial and Batch Bundle entries into sanitized serial/batch reference arrays. Batch rows may be partially returned against their original batch. Because the approved Android request contains only row ID and quantity, serialized rows are returnable only when the request returns all currently remaining serials; partial serial selection is rejected with `INVALID_SERIAL_NUMBER`, reason `partial_serial_return_not_supported`. This prevents the server from guessing which physical serial was returned.

The cashier fixture grants only the additional Serial and Batch Bundle permissions proven necessary by ERPNext's normal submit path. No ERPNext/Frappe core code or generic Android route is added.

## Receipt Response

`sales.create_return` returns `return_sale: SaleDetail`. Additive receipt fields include `return_against`, sanitized return reason, `grand_total`, `rounded_total`, `refund_amount`, `outstanding_amount`, discounts, taxes, item rates/amounts, currency, and persisted refund allocations/payment rows. The durable POS Invoice name remains the receipt and reconciliation reference.

## Response-Drop Protocol

`mobile-pos-response-drop/v1` is extended for `v1.sales.create_return` using the proven Task 9 external one-shot proxy topology. Evidence records only a generated evidence ID, hashes, booleans, statuses, counts, sanitized references, and timestamps. It proves identical original/replay UUID, identical exact request-body SHA-256, backend commit before drop, immediate proxy disarm, one return POS Invoice, one Mobile POS Request, and identical return references.

Evidence excludes credentials, tokens, cookies, Authorization headers, request bodies, customer/cashier PII, item descriptions, and free-text reason. Cleanup first disarms the proxy, then corrects the exact staging return through ERPNext-safe cancellation/reversal policy. It never directly deletes a submitted business document. Mobile POS Request cleanup uses the existing retention/correlation procedure only.

## Test Boundaries

Focused integration tests cover cashier authorization/profile scope, pagination/walk-in summaries, no/partial/multiple/full prior returns, exact boundary and over-limit errors, different-key concurrency, reason and decimal validation, authoritative quote/refund allocation, zero/one/multiple mode rules, replay/exactly-one artifacts, rejection/rollback, receipt fields, and serial/batch permissions. Full relevant backend modules run before review and delivery.
