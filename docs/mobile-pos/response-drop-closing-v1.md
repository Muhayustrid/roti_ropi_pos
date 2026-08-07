# Mobile POS Response-Drop Protocol — Closing Submission

## Scope

This approved staging-only protocol covers `v1.closing.submit`. It uses the
existing external one-shot response-drop proxy and normal OAuth + PKCE ingress.
It adds no production fault switch and does not execute the Android staging
gate.

## Preconditions

- Use one dedicated cashier, authorized POS Profile, submitted Open POS Opening
  Entry, and at least ten submitted unconsolidated POS Invoices so real workers
  exercise `queued` to terminal processing.
- Fetch a fresh `closing.preview`; preserve its server-owned `preview_id`, exact
  payment-mode set, and counted-amount policy.
- Generate one lowercase UUID and serialize the final submit body once. Record
  only SHA-256 digests of the UUID and exact body bytes.
- Arm the proxy for exactly one matching Closing submit response. Disable raw
  header/body logging before arming it.

## Commit, Drop, and Replay

1. Send the exact body with the original UUID.
2. Let the proxy forward the complete request and wait for upstream completion.
3. From a fresh database connection, prove that exactly one `Mobile POS Request`
   exists for the UUID and `v1.closing.submit`, that it is `Completed`, and that
   it references exactly one persisted `POS Closing Entry` carrying the same
   `custom_mobile_pos_transaction_id`.
4. Record the sanitized Closing reference, original HTTP status, initial
   Closing status, and `backend_commit_observed_at`. Only then drop the
   downstream response and record `response_dropped_at`.
5. Immediately disarm the one-shot rule and record proof and timestamp.
6. Replay the same UUID and byte-identical body. Require matching UUID/body
   digests, HTTP 200, `meta.replayed == true`, and the same Closing reference.
7. Confirm there is still exactly one request row and one Closing Entry. A
   stored initial `queued` response remains `queued` on replay; this is accepted
   but nonterminal.
8. Poll `closing.status` without mutating state until it reports `submitted` or
   `failed`. Capture a real `queued` to terminal transition and the complete
   authoritative receipt.

## Required Final Proof

- Original execution was accepted and committed before the downstream drop.
- Original and replay UUID/body hashes match exactly.
- Exactly one `Mobile POS Request` and one `POS Closing Entry` exist, with the
  same Closing reference and transaction correlation.
- The terminal receipt matches persisted Opening, profile, invoice count,
  grand/net/tax/quantity totals, and every opening/expected/counted/difference
  payment value.
- After `submitted`, `sessions.current` has no active Opening and bootstrap may
  advertise `open_session` without creating an Opening. After `failed`, the
  original Opening remains visible but blocked with `closing_failed`; manager
  cancellation must project the actual restored Opening state.

## Redaction and Cleanup

Evidence may contain timestamps, protocol version, hashes, booleans, statuses,
counts, and sanitized document references only. It must not contain OAuth
tokens, cookies, Authorization headers, raw UUIDs, bodies, cashier/customer
identifiers, payment accounts, or unrestricted amounts.

Do not delete or directly edit the submitted Closing, Opening, invoices,
accounting rows, or request record. Keep the request under normal retention.
Any business correction uses ERPNext manager workflow. Failure to prove proxy
disarm, commit-before-drop, exact replay, exactly-once documents, a real queued
transition, or safe final session/capability state is a protocol FAIL.
