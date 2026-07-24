# Mobile POS Idempotency and Recovery

## Evidence Legend

- **Verified**: Confirmed in installed source.
- **Approved**: A Phase 0 recovery decision approved for implementation.
- **Proposed**: Target behavior for the Mobile POS API.
- **Inferred**: A consequence that must be tested.

## Problem Statement

- **Verified**: POS Invoice submission creates stock, serial/batch, payment, loyalty, and eventual accounting effects. Retrying an unknown-result request without deduplication can create a second sale.
- **Verified**: POS Closing Entry submission can queue consolidation and return before the final state is known.
- **Proposed**: Every mutation is idempotent across network retries, process restarts, and Android restarts.

## Client Contract

- **Proposed**: Every mutation requires `X-Idempotency-Key`.
- **Proposed**: The value is a lowercase UUID string generated once by Android for a logical action and persisted before sending the request.
- **Proposed**: The same key must be reused until Android obtains a terminal response or explicitly abandons an action that never reached the server.
- **Proposed**: A new attempt to perform a new business action always receives a new key, even if its payload matches an older action.
- **Proposed**: Read-only endpoints ignore the header.

## Server Scope and Fingerprint

- **Approved**: Every mutation has a server-owned stable versioned operation ID, such as `v1.sessions.open`, `v1.sales.submit`, `v1.sales.create_return`, or `v1.closing.submit`.
- **Approved**: Android does not send the operation ID as a separate trusted field; the endpoint adapter supplies its constant.
- **Proposed**: Deduplication scope is `(authenticated_user, operation_id, idempotency_key)`.
- **Proposed**: The server validates and normalizes the request first, then computes SHA-256 over canonical JSON containing `operation_id` and the normalized body.
- **Proposed**: Canonical JSON uses sorted keys, UTF-8, no insignificant whitespace, and decimal values normalized so equivalent inputs such as `"1.0"` and `"1.00"` hash identically.
- **Proposed**: Reuse with the same fingerprint returns the original response without rerunning business logic.
- **Proposed**: Reuse with a different fingerprint returns HTTP 409 `IDEMPOTENCY_KEY_REUSED`.

## Durable Record

- **Proposed**: Add a custom DocType named `Mobile POS Request` owned by `roti_ropi_pos` with these fields:

| Field | Type | Rule |
| --- | --- | --- |
| `scope_key` | Data, unique | SHA-256 of user, versioned operation ID, and key |
| `idempotency_key` | Data | Original UUID |
| `endpoint` | Data | Stable versioned operation ID, not a URL; for example `v1.sales.submit` |
| `request_hash` | Data | Canonical request fingerprint |
| `user` | Link User | Authenticated user |
| `status` | Select | `Processing`, `Completed`, `Rejected` |
| `phase` | Select | `Reserved`, `DraftCreated`, `SubmitStarted` for closing recovery |
| `lease_expires_at` | Datetime | Recovery threshold for a durably processing close |
| `reference_doctype` | Link DocType | Created ERPNext type when available |
| `reference_name` | Dynamic Link | Created ERPNext record when available |
| `http_status` | Int | Original successful status |
| `response_json` | Long Text | Original stable API envelope |
| `resolved_at` | Datetime | Time the request became terminal |
| `expires_at` | Datetime | `resolved_at + 90 days`; unset while non-terminal |
| `retention_hold` | Check | Prevent cleanup for recovery, incident, or audit reasons |
| `retention_reason` | Small Text | Required when `retention_hold` is set |
| `audit_reference_written` | Check | Confirms durable transaction ID exists on the business document |

- **Proposed**: The DocType has no Desk create/write/delete permission for normal users. The idempotency service is the only code allowed to use `ignore_permissions=True` for this app-owned control record; its controller validates current user, immutable scope/hash, allowed endpoint, UUID syntax, state transition, and response schema.
- **Proposed**: `response_json` must not contain credentials or unrestricted document data.
- **Approved**: Retain cleanup-eligible completed and rejected records for 90 days after `resolved_at`.
- **Approved**: Add read-only, no-copy `custom_mobile_pos_transaction_id` fields through app fixtures on POS Opening Entry, POS Invoice, and POS Closing Entry. The server writes the client idempotency UUID to each created business document so audit correlation survives deletion of the Mobile POS Request row.

## Safe Scheduled Cleanup

- **Approved**: Run cleanup daily through a `roti_ropi_pos` scheduler event and process bounded batches.
- **Approved**: Delete only records whose status is `Completed` or `Rejected`, `expires_at <= now`, `retention_hold` is false, and no recovery is unresolved. Because `expires_at = resolved_at + 90 days`, this provides exactly 90 days of terminal retention.
- **Approved**: Never delete `Processing`, leased, stale-processing, queued-closing, failed-closing-under-review, incident-held, or audit-held records by age alone.
- **Approved**: Before deleting any completed or rejected record with a business reference, verify that the referenced ERPNext document still stores the same `custom_mobile_pos_transaction_id`. If verification fails, set a retention hold and log an operational error.
- **Approved**: Cleanup removes only Mobile POS Request records. It never deletes, cancels, amends, or edits referenced ERPNext business documents.
- **Approved**: Cleanup uses normal transaction boundaries per batch, records counts without sensitive payloads, and is safe to rerun.

## Standard Mutation Operation Contract

```python
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MutationResult:
    data: dict
    reference_doctype: str
    reference_name: str
    http_status: int = 201


def execute_idempotent(
    operation_id: str,
    validated_payload: dict,
    operation: Callable[[str], MutationResult],
) -> dict:
    ...
```

- **Approved**: `execute_idempotent` passes the validated lowercase UUID idempotency key to the operation as `transaction_id`.
- **Approved**: Before `insert()` or `submit()`, the operation writes `transaction_id` to the business document's `custom_mobile_pos_transaction_id`.
- **Approved**: The operation returns `MutationResult` and never creates the public success envelope.
- **Approved**: Before terminal completion, `execute_idempotent` loads the returned reference, verifies the expected DocType for the operation, and verifies the persisted transaction ID matches the request key.
- **Approved**: Only after verification does `execute_idempotent` create the stable success envelope, persist its status/body/reference, set `audit_reference_written`, and return it.
- **Approved**: A missing reference, unexpected DocType, or mismatched transaction ID is an internal invariant failure that rolls back the standard transaction.
- **Approved**: The closing-specific executor follows the same transaction-ID and reference invariants but retains its documented ability to persist and replay a stable `Rejected` envelope.

## Standard Transaction Algorithm

1. **Proposed**: Validate authentication, endpoint payload shape, versioned operation ID, and idempotency-key syntax.
2. **Proposed**: Compute `scope_key` and `request_hash` from the server-owned operation ID.
3. **Proposed**: Insert `Mobile POS Request` with `Processing` in the same database transaction as the business mutation.
4. **Proposed**: If the unique insert conflicts, lock/read the existing row after the competing transaction resolves.
5. **Proposed**: If its hash differs, return `IDEMPOTENCY_KEY_REUSED`.
6. **Proposed**: If it is `Completed`, deserialize and return the stored response.
7. **Proposed**: Execute the callback once with the idempotency UUID as `transaction_id`.
8. **Proposed**: The callback writes the transaction ID before inserting/submitting the ERPNext document and returns `MutationResult`.
9. **Proposed**: Verify the durable reference, expected DocType, and matching transaction ID.
10. **Proposed**: Create and store the successful envelope, then mark the request `Completed`.
11. **Proposed**: Let the request transaction commit business data and idempotency data together.
12. **Proposed**: On any raised exception, let Frappe roll back both records. A retry can then execute safely.

- **Proposed**: API code must not catch an exception and return success without first rolling back to a request savepoint.
- **Proposed**: Expected errors from standard mutations are owned by the common endpoint decorator and are not persisted by `execute_idempotent`.
- **Proposed**: Unexpected errors are re-raised after request-ID logging.
- **Inferred**: MariaDB's unique constraint serializes concurrent first-use attempts for the same scope. A concurrency test is mandatory.

### HTTP Status Replay

- **Proposed**: The persisted record stores the first successful HTTP status and envelope.
- **Proposed**: First creation endpoints set `frappe.response.http_status_code = 201`.
- **Proposed**: A replay changes only `meta.replayed` to `true`, sets HTTP 200, and preserves the original business data and request ID.

## Closing Exception Protocol

- **Verified**: ERPNext's synchronous merge path calls `frappe.db.commit()` in `create_merge_logs`, and its queued path can enqueue before the outer API request commits.
- **Inferred**: Generic request-transaction idempotency cannot guarantee atomicity around Closing Entry submission.
- **Proposed**: Register an app-owned POS Closing Entry controller override. For fewer than ten POS Invoice child rows it delegates to core unchanged. For ten or more, it sets Queued and registers an `after_commit` callback; only after the submitted Closing Entry is committed does that callback load it from the database and invoke core `consolidate_pos_invoices`, which then enqueues the standard worker. The API service never calls merge-log creation helpers.
- **Proposed**: `closing.submit` uses a dedicated recovery protocol:
  1. Create and commit the `Processing` Mobile POS Request before any closing mutation, with a short recovery lease.
  2. Lock the current Opening Entry, derive the invoice set, insert a Draft POS Closing Entry normally, link its name to the request record, and commit both.
  3. Set request phase `SubmitStarted`, commit it, and submit that exact Draft Closing Entry. Synchronous core consolidation may commit internally; queued consolidation is deferred by the controller override until the submitted document commits.
  4. Read the Closing Entry's persisted state, store the stable initial response, mark the request `Completed`, and commit.
  5. On replay of `Processing` with an unexpired lease, return HTTP 409 `REQUEST_IN_PROGRESS` and do not submit concurrently.
  6. On replay after lease expiry, lock the request. If it references Draft after an interrupted `SubmitStarted` phase, resume submit once; if it references Queued, Submitted, or Failed, synthesize the original submit response from persisted core state and complete the request.
  7. If a processing request has no reference after lease expiry, repeat Draft creation under the Opening Entry lock.
  8. If submit raises a known validation, permission, or state error, call `frappe.db.rollback()` before any durable recovery write. Reload and lock the request and Closing Entry from the database. If the persisted reference remains Draft, store the stable error envelope/status, mark the request `Rejected`, commit only that rejection, and never auto-resubmit it. If persisted state is Queued, Submitted, or Failed, reconcile that state instead of rejecting it. A corrected user action requires a new key.
  9. If a queued document has no deterministic ERPNext job after commit, replay calls the app's `ensure_committed_closing_job(name)` once; this function verifies `docstatus == 1` before invoking the core consolidation orchestrator.
- **Proposed**: This is the only business flow in v1 allowed to call `frappe.db.commit()` explicitly, because installed ERPNext already breaks outer request atomicity during closing.
- **Proposed**: The submit replay returns the stored initial state. Android calls `closing.status` to obtain current consolidation state.
- **Proposed**: A rejected replay returns its stored stable error with HTTP status and `meta.replayed = true`.

## Endpoint-Specific Recovery

### Open Session

- **Proposed**: Replay returns the same POS Opening Entry.
- **Proposed**: If Android loses the response and the idempotency record is unavailable after rollback, `sessions.current` recovers the current user's actual open entry.

### Submit Sale

- **Proposed**: Replay returns the same POS Invoice and authoritative totals.
- **Proposed**: Android must not generate a fresh key merely because the first request timed out.
- **Proposed**: `sales.get` accepts the returned ERPNext name for later recovery but never substitutes for idempotency on initial submission.

### Return

- **Proposed**: Return replay resolves to the same return document.
- **Proposed**: A return with a new key is still constrained by ERPNext's remaining returnable quantity.

### Close Session

- **Proposed**: The idempotency record references the POS Closing Entry immediately after creation.
- **Proposed**: Replay returns the same closing entry and original submit response; it does not silently replace a stored `queued` response with a later state.
- **Proposed**: `closing.status` reads the referenced Closing Entry and merge outcome; it never starts consolidation.
- **Proposed**: A failed ERPNext closing is reviewed and retried in ERPNext Desk, not by creating a second Closing Entry or invoking a mobile retry endpoint.

## Android Retry Policy

| Failure | Client action | Key behavior |
| --- | --- | --- |
| Connection loss or timeout | Exponential retry with jitter | Reuse key |
| HTTP 429 or 503 | Honor `Retry-After`, then retry | Reuse key |
| HTTP 401 | Stop and re-authenticate | Preserve key and payload |
| HTTP 409 `IDEMPOTENCY_KEY_REUSED` | Stop; flag local corruption/user conflict | Do not retry |
| HTTP 422 business error | Show correction; create a new logical action after edit | New key |
| HTTP 500 | Retry a limited number of times, then reconcile | Reuse key |
| Success or replayed success | Mark local action complete | Retire key |

- **Proposed**: Retry delays are 1, 2, 4, 8, and 16 seconds plus 0-500 ms jitter for foreground attempts.
- **Proposed**: Background retries use Android WorkManager with network constraints and retain the original request body and key.
- **Proposed**: Android displays `request_id` and business reference in support details.

## Locking Beyond Idempotency

- **Proposed**: Opening and closing services lock the relevant Opening Entry while deciding whether to create or close a session.
- **Proposed**: Sale submission relies on ERPNext stock and serial/batch validation at submit time; preflight stock is informational.
- **Proposed**: Closing submission re-derives invoice references while holding the session-level lock.
- **Inferred**: Two different idempotency keys can still race on the same opening session, so business locks and core uniqueness/validation remain necessary.

## Observability

- **Proposed**: Log request ID, endpoint, user, idempotency-key hash prefix, replay state, duration, and resulting document reference.
- **Proposed**: Never log full authorization headers, full idempotency keys, payment secrets, or unrestricted request bodies.
- **Proposed**: Metrics count first execution, replay, hash conflict, rollback, and stale processing detection.

## Acceptance Criteria

- **Proposed**: Twenty concurrent identical sale requests produce one submitted POS Invoice and nineteen equivalent replays.
- **Proposed**: Same key plus changed quantity returns HTTP 409 and creates no second document.
- **Proposed**: A failure after document insertion but before request completion rolls back both document and idempotency record.
- **Proposed**: Retrying after a simulated lost response returns the original sale or closing reference.
- **Proposed**: Cleanup deletes eligible completed/rejected records only after 90 days and preserves Processing, unresolved recovery, held records, and every ERPNext business document.
- **Proposed**: Cleanup refuses deletion when the referenced document lacks the matching `custom_mobile_pos_transaction_id`.
