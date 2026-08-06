# Mobile POS Response-Drop Protocol — Return Creation Extension

## Scope

This approved staging-only extension of `mobile-pos-response-drop/v1` covers
`v1.sales.create_return`. It reuses the proven Task 9 external one-shot reverse
proxy between the test client and normal staging ingress. It adds no production
hook, application fault switch, or Android-controlled ingress behavior.

`sales.quote_return` is out of scope because it is read-only and creates no
`Mobile POS Request` or POS Invoice.

## Preconditions

- Use a dedicated staging cashier, authorized POS Profile, submitted Open POS
  Opening Entry, and a submitted original POS Invoice owned by that cashier.
- Refresh `sales.get`, select an eligible original row, and request no more than
  its current `remaining_qty` using `return-quantity/v1` syntax.
- Obtain a successful `sales.quote_return`. If multiple modes are exposed,
  include the selected allowed `refund_mode` in both original and replay bodies;
  if one mode is exposed, omit it from both.
- Arm the external proxy for exactly one matching
  `POST .../roti_ropi_pos.api.v1.sales.create_return` response.

## One-Shot Drop and Replay

1. Generate a fresh lowercase UUID for `X-Idempotency-Key`. Record only its
   SHA-256 and `original_uuid_valid: true` in sanitized evidence.
2. Serialize the final request body once. Record its exact byte SHA-256, never
   the body. Send those exact bytes with the UUID.
3. The proxy forwards the request normally and waits for the complete upstream
   response. It must not drop or reset the upstream request.
4. After upstream completion, query by the UUID through a restricted operator
   command and prove that `Mobile POS Request.status == "Completed"`, its
   `reference_name` is a submitted return POS Invoice, and the transaction is
   visible from a fresh database connection. Record
   `backend_commit_observed_at` and the sanitized return reference.
5. Only after that proof, the proxy drops the downstream response and records
   `response_dropped_at`, where
   `backend_commit_observed_at <= response_dropped_at`.
6. Immediately disarm the one-shot rule before any retry. Record
   `proxy_disarmed: true` and `proxy_disarmed_at`.
7. Replay the exact stored request bytes with the same UUID. Record the replay
   UUID SHA-256, `replay_uuid_matches: true`, the replay body SHA-256, and
   `replay_body_hash_matches: true`.
8. Require HTTP 200, `meta.replayed == true`, and the same sanitized return POS
   Invoice reference as the committed original.

## Exactly-Once Proof

From a fresh database connection, record only sanitized counts and references:

- exactly one submitted `POS Invoice` with `is_return = 1`, the expected
  `return_against`, and `custom_mobile_pos_transaction_id` equal to the UUID;
- exactly one `Mobile POS Request` for the scoped `v1.sales.create_return`
  operation and UUID, with `status = "Completed"` and `reference_name` equal to
  that return POS Invoice;
- `original_return_reference == replay_return_reference`;
- no second stock or payment/accounting effect appears after replay.

The evidence schema is limited to: generated `evidence_id`, protocol/version,
timestamps, endpoint identifier, UUID/body SHA-256 values, equality booleans,
HTTP statuses, replay boolean, sanitized POS Invoice references, document/count
assertions, proxy armed/disarmed booleans, and PASS/FAIL checks.

## Redaction

Evidence and proxy logs must not contain credentials, OAuth tokens, cookies,
Authorization headers, raw `X-Idempotency-Key` values, request bodies, free-text
return reasons, cashier/customer identifiers, customer contact data, item
descriptions, serial numbers, batch numbers, payment accounts, or other PII.
Disable request/header/body logging before arming the proxy. Hashes are computed
in memory and only the digests are persisted.

## Cleanup

1. Confirm the proxy is disarmed. If disarm cannot be proven, stop; do not run
   cleanup or another request.
2. Retain the sanitized evidence and its exact document references.
3. Correct the staging return only through ERPNext-safe business workflow. A
   manager may cancel the submitted return when core permits it; otherwise post
   the appropriate compensating ERPNext transaction. Never delete, amend by
   database update, or directly reverse stock/accounting rows of a submitted POS
   Invoice.
4. Do not delete the original sale, opening, cashier, POS Profile, capability,
   or fixture records. `Mobile POS Request` remains until the existing terminal
   retention/correlation cleanup procedure declares it eligible; never delete
   it merely to reset this test.
5. Verify final stock/accounting state through normal ERPNext reports and record
   only PASS/FAIL plus sanitized references.

## PASS Criteria

PASS requires all of the following: valid original UUID hash; identical replay
UUID hash; identical exact-body hash; committed backend state before downstream
drop; immediate proxy disarm; identical original/replay return references;
exactly one submitted return POS Invoice; exactly one completed Mobile POS
Request; no duplicate stock/accounting effect; redaction compliance; and
ERPNext-safe cleanup. Any missing proof is FAIL and ends the run.
