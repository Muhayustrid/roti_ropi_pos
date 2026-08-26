# Handoff Prompt — Mobile POS × Dynamic Promotion Integration

Copy everything below this line into a fresh AI session opened in
`apps/roti_ropi_pos`. Do not paste anything above the line.

---

## Task

Integrate the Dynamic Promotion engine (owned by `selling_additional`) into
the Mobile POS v1 API so a cashier on Android can sell a promotion package.
The change is small: the engine already owns the full POS Invoice lifecycle.
Mobile only needs to (a) let the client discover/quote promotions and
(b) carry a pending-promotion payload on sale submission.

Read `PROJECT_STATE.md` first — it is the canonical cross-repo checkpoint.
Read `selling_additional/AGENTS.md` (sibling app) for the promotion domain
rules before touching anything.

## What already exists (do NOT rebuild)

`selling_additional` (merged to its `main` at `d5653de…`/`d565e3e`) owns:

- The Promotion DocTypes, the pure domain module
  (`selling_additional/promotions/` — eligibility, pricing, engine), and the
  POS Invoice lifecycle hooks (`before_validate` materializes a pending
  payload into rows; `validate`/`before_submit` re-assert invariants;
  `on_submit`/`on_cancel` write facts).
- Three whitelisted HTTP endpoints, permission-gated, in
  `selling_additional/overrides/pos_promo_api.py`:
  - `get_available_promotions(pos_profile)`
  - `get_promotion_detail(promotion, pos_profile)`
  - `quote_promotion(promotion, choices, pos_profile)`
- The invoice-level Custom Field that carries the pending payload:
  `custom_selling_additional_pending_promotions` (JSON string:
  `{"instances": [{"promotion": ..., "selections": [...]}]}`).
- The Desk POS reference client: `selling_additional/.../pos_promotions.js`
  (how a client drives the picker: list → detail → quote → set pending
  payload → save).

The engine materializes rows on invoice save. A mobile invoice **without**
the payload field is a plain invoice — the engine no-ops. That path is
already safe and tested.

## Hard constraints

1. **Mobile POS v1 contract is closed.** No new error codes, no changed
   response fields, no changed transport. The only permitted change is ONE
   new OPTIONAL request field on the sale payload (below). Record this as an
   explicit contract-extension decision in `PROJECT_STATE.md` and update
   `docs/mobile-pos/api-contract.md` in the same commit.
2. **No private imports.** `roti_ropi_pos` must never import
   `selling_additional.*` modules. The source-contract test
   `roti_ropi_pos/tests/test_source_contracts.py` (AST scan) enforces this.
   The pending payload is an opaque JSON string passed through a Custom
   Field — roti validates nothing, the engine's hooks do.
3. **Deploy order.** A site running the integrated mobile API must have
   `selling_additional` migrated (backup → migrate) and
   `auto_insert_price_list_rate_if_missing = 0` (D12 rule: promotion parent
   items must never gain Item Prices).
4. `required_apps` already lists `selling_additional` — keep it that way.

## Implementation steps

1. **Sale payload extension** — `roti_ropi_pos/api/v1/sales.py`:
   - `_parse_sale_payload` allowlist: add one optional field, e.g.
     `promotions` (JSON object `{"instances": [...]}` or null).
   - Parse it as an opaque JSON string (size-cap it, e.g. 64 KB) and thread
     it to the invoice builder in `roti_ropi_pos/mobile_pos/invoices.py`,
     which sets `custom_selling_additional_pending_promotions`.
   - Do NOT add it to `_parse_quote_payload` unless you also wire cart-quote
     promo pricing (see step 3 — optional, decide explicitly).
   - `_unknown()` must keep rejecting everything else. All existing error
     codes stay byte-identical.
2. **Idempotency** — the payload is part of the invoice doc, so replays of
   the same `transaction_id` materialize identically (engine materializes
   once, I8). Add a test proving replay with the same payload does not
   duplicate instances.
3. **Discovery/quote for Android** — no new roti endpoints. The Android
   client calls the three `selling_additional.overrides.pos_promo_api`
   methods directly over HTTP with the cashier's bearer token.
   - **Decision point:** the gate requires Promotion `read`. Design §18
     grants read to Sales User; the `Mobile POS Cashier` role may lack it.
     If so, extend the Promotion DocPerm in `selling_additional` to grant
     read to `Mobile POS Cashier` (that is a selling_additional change —
     coordinate it there, one permission row + fixture + test), or have the
     site assign Sales User to cashiers. Record which path was taken.
4. **Response DTOs unchanged** — materialized promotion rows flow back
   through `sale_item_dto` with standard fields only. Do not add promo
   fields to v1 responses.
5. **Tests** (all in roti_ropi_pos, no selling_additional imports):
   - Sale with `promotions` payload → invoice submitted, Model C rows
     correct (parent full revenue + zero-rate components), facts written.
   - Sale without the field → byte-identical v1 behaviour (regression).
   - Invalid/oversized/unknown-shape payload → existing INVALID-style error
     envelope, no new error codes.
   - Replay idempotency (see step 2).
   - Source-contract test still green (no private imports).
6. **Docs**: update `docs/mobile-pos/api-contract.md` (the one new optional
   request field) and this file's status line.

## Verification

```bash
cd /workspace/development/frappe-bench
bench --site mobile-pos-regression.localhost run-tests --module roti_ropi_pos.tests.test_source_contracts
bench --site mobile-pos-regression.localhost run-tests --module roti_ropi_pos.tests.test_authentication
# plus the new test module(s) you add; run mutating modules twice
```

Ruff from the app root: `uvx ruff check .` and `uvx ruff format --check .`.
Never run two suites concurrently against one site.

## Boundaries

- Do not modify `selling_additional` from this session except the single
  Promotion permission row if step 3's decision requires it — and record it.
- Do not touch `bakery_manufacturing`, stock/scanner ownership, or the Desk
  POS asset.
- Commit messages in English; communicate with the operator in Indonesian.
- Update `PROJECT_STATE.md` (resume point + the v1-extension decision) at
  the end; commit it.
