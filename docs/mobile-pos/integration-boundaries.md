# Mobile POS Integration Boundaries

## Evidence Legend

- **Verified**: Confirmed in installed code or repository state.
- **Approved**: A Phase 0 integration decision approved for implementation.
- **Proposed**: Required boundary for the target implementation.
- **Inferred**: A reasoned consequence that should be validated in tests.

## Ownership Matrix

| Concern | Owner | Mobile POS rule | Status |
| --- | --- | --- | --- |
| API version and payload shape | `roti_ropi_pos` | Android calls only app-owned v1 endpoints | **Proposed** |
| Authentication identity | Frappe | Use `frappe.session.user`; never accept user identity in payloads | **Verified / Proposed** |
| API authorization | `roti_ropi_pos` | Enforce roles, profile eligibility, and session ownership before core calls | **Proposed** |
| POS Profile | ERPNext | Read and validate existing records; do not copy profile data | **Verified / Proposed** |
| Registered Customer | ERPNext | Search/select existing records; never auto-create from Mobile POS | **Approved** |
| Opening Entry | ERPNext | Create/submit through its controller | **Verified / Proposed** |
| POS Invoice and returns | ERPNext | Build and submit core documents; do not reproduce controller logic | **Verified / Proposed** |
| Closing and consolidation | ERPNext | Submit Closing Entry; never call merge helpers directly | **Verified / Proposed** |
| Price Group | `bakery_manufacturing` | Consume the generated Price List through POS Profile | **Verified / Proposed** |
| Batch default UOM | `bakery_manufacturing` | Use effective `scan_barcode`; do not import `resolve_batch_uom` | **Verified / Proposed** |
| Mobile UI and local retry queue | `POSERPNext` | Persist pending idempotent requests, not ERPNext ledgers | **Proposed** |

## ERPNext Boundary

### Allowed Integration

- **Proposed**: Import documented controller classes or public functions only after checking the installed version during implementation.
- **Proposed**: Use `frappe.get_doc` to create ERPNext documents and normal `insert`, `save`, `submit`, and `cancel` transitions.
- **Proposed**: Use ERPNext item-detail, price-list, barcode, batch quantity, and stock-availability functions as inputs to app-owned response mapping.
- **Proposed**: Let ERPNext recalculate monetary and stock-sensitive values during validation and submission.

### Forbidden Integration

- **Proposed**: No edits under `apps/erpnext`.
- **Proposed**: No direct Android calls to `frappe.client.submit`, `savedocs`, `create_opening_voucher`, `get_invoices`, or arbitrary resource APIs.
- **Approved**: `Mobile POS Cashier` accounts are blocked from those routes by an app `auth_hook`, including `/api/resource` and non-v1 `/api/method` routes.
- **Proposed**: No direct calls to `consolidate_pos_invoices`, `create_merge_logs`, `unconsolidate_pos_invoices`, or `cancel_merge_logs`.
- **Proposed**: The sole closing compatibility exception is an app-owned POS Closing Entry controller override: after the submitted document commits, its callback may invoke core `consolidate_pos_invoices` to enter the normal deterministic queued path. Neither API endpoints nor services call merge-log creation/cancellation helpers.
- **Proposed**: No raw SQL assembled from mobile input.
- **Approved**: `ignore_permissions=True` is forbidden for ERPNext business documents. The sole exception is the app-owned Mobile POS Request control record, guarded by its dedicated service and tests.

### Why the Facade Is Required

- **Verified**: `check_opening_entry(user)` and `get_invoices(start, end, pos_profile, user)` trust a caller-supplied user.
- **Verified**: `get_pos_profile_data` and direct named POS Profile lookup do not enforce assignment themselves.
- **Verified**: Whitelisting controls function invocation but does not automatically apply DocType permissions to raw queries or ordinary `get_doc()` calls.
- **Inferred**: Exposing these helpers directly would permit cross-user or cross-profile data access unless the facade derives and validates scope.
- **Approved**: A dedicated cashier account must never be used for Desk, shared, or elevated to Administrator/Sales Manager. The route-restriction hook prevents general Frappe/ERPNext API use.

### Customer

- **Approved**: ERPNext owns registered Customer records and permissions.
- **Approved**: Customer is a global master and has no ordinary Company ownership field.
- **Approved**: The authorized POS Profile supplies Company and optional Customer Group restrictions.
- **Approved**: Search and selection use normal Customer read permissions and:
  `profile.customer_groups is empty OR customer.customer_group is in the configured groups' closure`.
- **Approved**: The configured closure includes each selected group and all descendants.
- **Approved**: Company/account/internal-party compatibility remains authoritative during ERPNext sale or return submission.
- **Approved**: Mobile POS may default to `POS Profile.customer`, but the resolved default must pass the same existence, enabled, read-permission, and profile Customer Group predicate checks as an explicitly selected Customer.
- **Approved**: A configured default that fails those checks returns `PROFILE_CONFIGURATION_INVALID`; profile origin never bypasses Customer eligibility.
- **Approved**: Mobile POS never creates or modifies a Customer during search, quote, scan, sale, return, or recovery.

## `bakery_manufacturing` Boundary

### Price Group

- **Verified**: `PriceGroup.on_update` creates or updates a selling Price List, synchronizes Item Price rows, and assigns that list to POS Profiles matching configured company/warehouse outlets.
- **Proposed**: Mobile POS reads the resulting `POS Profile.selling_price_list`; it does not query Price Group to calculate prices.
- **Proposed**: Price Group creation, maintenance, and sidebar exposure remain outside `roti_ropi_pos`.
- **Verified**: The current sidebar injection is implemented in `bakery_manufacturing.after_migrate`.
- **Approved**: The future `extend_bootinfo` sidebar replacement is a separate bakery task and is not a Mobile POS Phase 1 blocker.

### Batch UOM

- **Verified**: `bakery_manufacturing` overrides `erpnext.stock.utils.scan_barcode` with `custom_scan_barcode(search_value, ctx)`.
- **Verified**: For batch scans, the override reads Item `custom_default_uom_warehouse` and may add `uom`, `conversion_factor`, and a warning.
- **Proposed**: Mobile POS passes the ERPNext method path through `frappe.override_whitelisted_method()` and then resolves the returned path, matching Frappe's request dispatcher and selecting the bakery implementation.
- **Proposed**: Mobile POS maps a server warning into its own warning array rather than depending on Desk `frappe.msgprint` behavior.
- **Proposed**: Mobile POS must still verify batch quantity, expiry, warehouse, and item detail before submission.

### Recent Orders

- **Verified**: `bakery_manufacturing` overrides `get_past_order_list` to include `custom_walk_in_customer_name`.
- **Approved**: Mobile POS preserves `custom_walk_in_customer_name` for POS Invoice responses and accepts it only when the selected Customer is the POS Profile default walk-in Customer. It does not import the override's private helpers or add Sales Invoice support.

## Frappe Boundary

- **Verified**: `/api/method/<path>` authenticates requests, applies method overrides, checks whitelisting and allowed HTTP methods, then invokes the function with request parameters.
- **Proposed**: Every app-owned mutation is decorated with `@frappe.whitelist(methods=["POST"])`.
- **Proposed**: App-owned read endpoints use `GET` only where payloads contain no secrets and are naturally cache-safe; scan/item quote requests use `POST`.
- **Proposed**: The facade uses Frappe's transaction lifecycle and request logging, not a second web framework.
- **Approved**: Android is a public OAuth client using Authorization Code with mandatory PKCE S256 and no secret issued or distributed to Android. The boundary enforces S256 on authorize/approve and verifies every v1 Bearer token belongs to the configured client and enabled cashier.
- **Approved**: Exact-route enforcement rejects legacy `cmd`, cookie, API-key, Basic, wrong-client bearer, generic resource/method, upload, and Desk access. OAuth tests cover login, authorization, consent approval, token exchange, refresh, and manager revocation.

## Android Boundary

- **Verified**: No approved Android implementation plan currently exists at `/Users/rotiropi/DockerERPNext/POSERPNext/docs/mobile-pos/implementation-plan.md`.
- **Approved**: Android implementation is outside this backend plan and must not start until a separate plan exists at that path and is explicitly approved.
- **Proposed**: Android models contain API DTOs, not Frappe `Document` JSON.
- **Approved**: Android uses Kotlin, XML Views, ViewBinding, and minSdk 23. The generated Compose starter is not approved application architecture; Compose requires explicit future approval.
- **Approved**: Authorization uses the system browser or Custom Tab with PKCE S256. Tokens are stored using Android Keystore-backed encryption; shared/API-key/Administrator credentials are prohibited.
- **Proposed**: Android sends an `X-Idempotency-Key` on every mutation and persists that key with its pending action until a terminal response is received.
- **Proposed**: Android never generates ERPNext document names, posting statuses, totals, tax rows, account names, or server timestamps.
- **Proposed**: Android may cache catalog display data, but sale submission must tolerate the server returning updated price, stock, tax, or UOM validation errors.
- **Proposed**: Android treats a close response of `queued` as pending and polls the status endpoint.

## Dependency Direction

```text
POSERPNext -> roti_ropi_pos -> ERPNext/Frappe
                         -> effective ERPNext overrides registered by bakery_manufacturing

bakery_manufacturing -X-> roti_ropi_pos
ERPNext/Frappe       -X-> roti_ropi_pos
```

- **Proposed**: Declare both ERPNext and `bakery_manufacturing` as required apps before the first Mobile POS schema/fixture migration because POS transactions and bakery batch-UOM/Price Group behavior are business-critical v1 dependencies.
- **Proposed**: Activating this declaration belongs to Backend Phase 2 before Task 2's first migration, not to the later authentication task.

## Upgrade Discipline

- **Proposed**: Pin compatibility to Frappe `>=16,<17` and ERPNext `>=16,<17` in documentation and CI policy, while bench continues to manage installation.
- **Proposed**: Before each dependency upgrade, rerun source-contract and integration tests for all imported functions.
- **Proposed**: Treat Graphify output as a navigation index only. Source files and tests are the evidence for implementation decisions.

## Source Evidence

- **Verified**: `bakery_manufacturing/hooks.py:10-23`
- **Verified**: `bakery_manufacturing/overrides/barcode_scanner.py:6-57`
- **Verified**: `bakery_manufacturing/overrides/pos_overrides.py:9-50`
- **Verified**: `bakery_manufacturing/bakery_manufacturing/doctype/price_group/price_group.py:5-231`
- **Verified**: `frappe/handler.py:65-86`
- **Verified**: `frappe/model/document.py:431-587,1112-1150`
