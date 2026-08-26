# Mobile POS Dynamic Promotion Backend Status

## Purpose

This document records the backend state for Android Dynamic Promotion integration. Runtime source and executable tests are authoritative.

The Mobile POS sale extension is complete. Both backend contracts for Android checkout are now closed with executable evidence.

## Implemented Backend Work

`roti_ropi_pos` commit `859e0b7` adds one optional request-only `sales.submit.promotions` object. It:

- accepts a JSON object or `null`;
- permits promotion-only `items: []` when the object is non-null;
- keeps plain empty-item sales invalid;
- serializes the object as compact deterministic UTF-8 JSON;
- rejects serialized payloads above 64 KiB;
- includes the normalized value in the idempotency request hash;
- passes the value opaquely through `custom_selling_additional_pending_promotions`;
- returns the unchanged standard `SaleDetail` and existing error enum.

`selling_additional` commit `81346f0` grants `Mobile POS Cashier` read-only Promotion permission. It grants no create, write, delete, report, export, share, or submit permission.

The `selling_additional` lifecycle materializes Model C rows before the Mobile POS total check:

- one non-stock parent carries full package revenue;
- stock components carry zero revenue;
- submit writes promotion selection facts;
- replay creates no second invoice, selection, or fact.

## Verified Evidence

- `roti_ropi_pos.tests.test_sale_task9`: 71 tests passed twice (including promotion sale) on the qualifying site.
- `selling_additional.tests.test_pos_promo_api`: 8 tests passed twice (including assigned/enabled profile and POST-only checks).
- `roti_ropi_pos.tests.test_promo_bearer_route`: 17 tests passed twice — valid cashier reaches all three exact POST paths, negatives remain denied.
- `roti_ropi_pos.tests.test_quote_cart_promotions`: 12 tests passed twice — parser, promotion-only, mixed, oversized, and artifact checks.
- `roti_ropi_pos.tests.test_promo_quote_submit_integration`: 4 tests passed twice — promotion-only, mixed, replay, and price-change parity.
- `selling_additional.tests.test_promotion_contracts`: 5 tests passed.
- `roti_ropi_pos.tests.test_source_contracts`: 43 tests passed.
- `roti_ropi_pos.tests.test_authentication`: 39 tests passed twice (allowlist now 20 with promo facades).
- Independent review for the sale extension found Critical 0 and Important 0; promo bearer and quote integration also verified.

## Blocker 1: Direct HTTP Route — CLOSED

Three facade methods exist (now allowlisted and POST-only):

```text
/api/method/selling_additional.overrides.pos_promo_api.get_available_promotions
/api/method/selling_additional.overrides.pos_promo_api.get_promotion_detail
/api/method/selling_additional.overrides.pos_promo_api.quote_promotion
```

All three decorators are now `@frappe.whitelist(methods=["POST"])`, preserving the Desk POS `frappe.xcall()` (POST) consumer. They return native Frappe `{ "message": ... }` responses.

`roti_ropi_pos/mobile_pos/auth_hook.py` now allowlists exactly 20 methods: the original 17 plus the three promo facades. `MOBILE_POS_PATHS` derives from that set. A valid dedicated cashier bearer reaches all three exact POST paths; all negatives remain denied.

Facade scope is now fail-closed: `_check_access` requires an explicit `pos_profile`, verifies the POS Profile exists, is enabled, is readable, and is assigned to `frappe.session.user` via `applicable_for_users` (Administrator bypasses assignment for existing Desk tests). `get_promotion_detail` now requires `pos_profile`; an ineligible promotion for the assigned outlet returns `eligibility.is_eligible == false` with a reason, and quote/materialization rejects it — this preserves Desk behavior while keeping profile scope fail-closed.

Verified exit evidence (17-test bearer module, twice):

1. Valid mobile-only cashier reaches all three exact POST paths through HTTP (including `validate_mobile_api_scope`).
2. All three calls require an enabled POS Profile assigned to that cashier.
3. All three are POST-only; GET/PUT/DELETE/PATCH are rejected via `allowed_http_methods_for_whitelisted_func`.
4. Wrong-client and expired bearer tokens are rejected with `AuthenticationError`.
5. Disabled users and users without `Mobile POS Cashier` are rejected.
6. Missing, unassigned, disabled profiles are rejected with `PermissionError`/`ValidationError`.
7. Generic RPC, `/api/resource`, `/api/v2`, `cmd=`, alias, encoded, and trailing-path variants remain blocked.
8. Promotion permission remains read-only (verified by `test_promotion_contracts`).
9. Detail for an ineligible promotion returns `is_eligible false` (not a generic success) — documented above.

## Blocker 2: Authoritative Combined Quote — CLOSED

`sales.quote_cart` now accepts the same optional `promotions` object/null as `sales.submit` (compact deterministic UTF-8, 64 KiB limit, opaque in `roti_ropi_pos`, validated/materialized in `selling_additional`). `quote_promotion.total_price` remains package pricing only; the authoritative quote is `sales.quote_cart`.

The quote lifecycle reuses the same `before_validate` providers as submit: for non-null promotions the in-memory `POS Invoice` sets `custom_selling_additional_pending_promotions` and runs `before_validate` before `set_missing_values` and `calculate_taxes_and_totals`, so Model C parent (full revenue) and components (zero) are materialized before tax/rounding. A shared helper avoids duplicated lifecycle logic. The invoice is never saved.

Verified exit evidence (12-test quote module + 4-test integration, each twice):

1. Regular-only quote unchanged; `promotions: null` equals omission.
2. Promotion-only (`items: []` allowed only with non-null promotions) returns Model C parent and components with authoritative `grand_total`, `payable`, `taxes`, `payment_modes`, and `payment_amount_policy`.
3. Mixed regular+promotion quote returns combined authoritative totals; `sales.submit` accepts the quoted `grand_total`/`payable` unchanged and creates exactly one Model C instance.
4. Stale quote triggers existing `PRICE_CHANGED` and creates no invoice.
5. Quote creates no `POS Invoice`, `Mobile POS Request`, selection, fact, Item Price, or stock/accounting artifact (proven by counts before/after).
6. `promotions` accepts object or `null`, rejects non-objects and oversized payloads with `INVALID_REQUEST`, and uses the existing error contract for semantic invalidity.

## Deployment Prerequisites

Before any target site serves the completed sale extension:

1. Take and record a backup.
2. Migrate `selling_additional` on that site.
3. Set `Stock Settings.auto_insert_price_list_rate_if_missing` to `0`.
4. Verify all Promotion parent items have zero selling Item Price rows.
5. Verify POS Settings uses POS Invoice mode.

The authorized backup `20260826_114814` and one migrate on `selling-cutover.localhost` succeeded during prior backend implementation (verified recovery boundary). No new migrate was performed in this task; that historical authorization does not authorize another migrate or deployment.

## Canonical Documents

- `PROJECT_STATE.md` — cross-app checkpoint and resume point.
- `docs/mobile-pos/api-contract.md` — normative Mobile POS wire contract.
- `docs/mobile-pos/authentication.md` — bearer and exact-route boundary.
- `docs/mobile-pos/android-integration-guide.md` — complete Android gateway guide.
- `/Users/rotiropi/POS_Android/docs/dynamic-promotion-integration-handoff.md` — actual React Native file map, gates, and future sequence.

## Resume Point — Both Blockers Closed

The exact bearer-route contract and the authoritative promotion-aware quote are now closed with executable evidence. Android transport and UI implementation may start from `/Users/rotiropi/POS_Android/docs/dynamic-promotion-integration-handoff.md`. The Desk POS `frappe.xcall()` POST consumer remains supported.

Deploy is not authorized by this document.
