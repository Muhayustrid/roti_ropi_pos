# OAuth Backend Phase 3–4 Design

## Context

Mobile POS Phase 3–4 currently has partial profile, bootstrap, and opening-session code but lacks request-level OAuth enforcement, exact role permissions, customer resolution, and required regression coverage. This change completes Backend Phase 3 and Phase 4 while preserving Frappe/ERPNext permission checks, OAuth public-client behavior, and existing v1 response contracts.

## Scope

Included:

- OAuth Authorization Code public-client boundary with mandatory PKCE S256.
- Exact Mobile POS route allowlist for endpoints currently shipped.
- Dedicated `Mobile POS Cashier` Role and exact Custom DocPerm fixtures.
- Permission-aware profile/bootstrap/current-opening behavior.
- Idempotent opening creation and conflict handling.
- Existing-Customer search and shared customer resolution.
- Phase 3–4 tests and relevant Frappe/ERPNext regressions.

Excluded:

- Automatic or fixture-based OAuth Client provisioning.
- Catalog, sale, return, closing, Android, deployment, or production migration work.
- Customer creation or synthetic Customer-to-Company ownership.
- Future endpoint paths not yet implemented.

## OAuth and Route Boundary

Register `roti_ropi_pos.mobile_pos.auth_hook.validate_mobile_api_scope` in `auth_hooks`.

The hook compares Werkzeug's decoded request path against exact paths. Mobile API allowlist contains only:

- `/api/method/roti_ropi_pos.api.v1.bootstrap.get`
- `/api/method/roti_ropi_pos.api.v1.sessions.current`
- `/api/method/roti_ropi_pos.api.v1.sessions.open`
- `/api/method/roti_ropi_pos.api.v1.customers.search`

OAuth browser exceptions are exact login, authorize, and approve paths. Public-client token exchange/refresh uses the exact Frappe token path. Generic `/api/method`, `/api/resource`, `/api/v2/method`, encoded alternate paths, upload/RPC/Desk routes, and legacy `cmd` substitution are rejected. Exact browser login submission remains the sole `cmd` exception.

Requests carrying configured `mobile_pos_oauth_client_id` may access only approved OAuth paths. Authorize and approve require a non-empty `code_challenge` and exact `code_challenge_method=S256`, including Guest requests. Token exchange and refresh reject Basic authorization and `client_secret`.

Every shipped v1 endpoint requires a non-empty Bearer token whose active `OAuth Bearer Token` row belongs to configured client and current session user. User must remain enabled and hold `Mobile POS Cashier`. Cookie, API-key, Basic, wrong-client, wrong-user, inactive-token, and Guest access fail before endpoint logic.

OAuth Client provisioning remains manual per site. Manager configures Authorization Code, response Code, token auth method None, scope `all`, `skip_authorization=0`, approved redirect URI, allowed role `Mobile POS Cashier`, no Android secret, and site config `mobile_pos_oauth_client_id`.

## Role and Permissions

Export Role fixture `Mobile POS Cashier` and exact Custom DocPerm fixtures:

| DocType | Permissions |
| --- | --- |
| POS Profile | read |
| POS Opening Entry | read, create, write, submit |
| POS Invoice | read, create, write, submit |
| POS Closing Entry | read, create, write, submit |
| Customer | read |
| Item | read |

No fixture grants cancel, delete, amend, report, export, import, share, Sales Invoice access, or Mobile POS Request access. Cashiers need no Sales Manager, Accounts Manager, System Manager, or Administrator role.

## Authorization, Profiles, and Bootstrap

Keep `mobile_pos_endpoint` as endpoint-level defense after auth hook. It verifies authenticated enabled user, cashier role, and POS Invoice mode, then maps known permission failures to stable API errors.

`get_authorized_profile()` accepts only an enabled POS Profile explicitly assigned to current user and readable through normal core permission. `list_assigned_profiles()` applies the same read-permission rule and excludes disabled/unassigned profiles. Safe profile DTO remains limited to contract fields.

Bootstrap returns current user, eligible profiles, optional selected profile, shared current opening, capabilities, and POS mode. Capabilities reflect exact core permissions and current-opening prerequisites; unavailable mutations remain false.

## Opening Sessions

Reuse `get_current_opening()` and `opening_dto()` for bootstrap and `sessions.current`. Current predicate requires current user, authorized profile/company, submitted document, status Open, and no closing entry. No calendar-day filter applies. Prior-day openings expose `posting_date`, timezone-aware `period_start_date`, and stable `STALE_OPENING` warning.

Opening creation derives user and company server-side, checks create/submit permissions, locks profile and user decisions, rejects same-profile or same-user conflicts, validates distinct profile payment modes, sets durable transaction ID, and calls normal `insert().submit()`. Existing idempotency executor provides one document and stable replay.

## Customer Search and Resolution

Add focused customer service and v1 adapter.

`customers.search` requires authorized profile and Customer read permission. Parameters are `pos_profile`, optional `q`, `start` default 0, and `limit` default 20 capped at 100. Query returns enabled Customers only, uses permission-aware Frappe APIs, deterministic ordering, and `limit + 1` pagination evidence. Search matches Customer identity/name/mobile fields and returns only contract DTO fields.

Eligibility predicate is shared by search and resolution:

- If profile has no configured Customer Groups, any enabled readable Customer is eligible.
- Otherwise eligible groups are each configured Customer Group plus all descendants, resolved through Customer Group nested-set boundaries.

Configured default and explicit Customer selection pass identical existence, enabled, read-permission, and group-scope validation. Invalid configured default raises `PROFILE_CONFIGURATION_INVALID` with profile and field details. Invalid explicit selection uses non-disclosing resource/scope error. Omitted selection resolves to profile default. `walk_in_customer_name` is accepted only when resolved Customer equals profile default. No path creates or mutates Customer.

## Error Handling

Input validation rejects unknown fields, invalid types, negative pagination, oversized limits, malformed balances, duplicate modes, and client-owned identity/scope fields. Known authentication, permission, profile configuration, scope, conflict, and resource errors use stable envelopes. Unknown exceptions propagate to existing request-ID logging and HTTP 500 handling; broad exception swallowing is prohibited.

## Testing

Add:

- `test_authentication.py`: PKCE S256, public-client token rules, bearer/client/user/status checks, disabled users, exact routes, legacy/generic/v2/encoded bypass denial, role and fixture matrix.
- `test_bootstrap.py`: Guest/role/profile checks, cross-user/profile isolation, safe DTO, permission failures, capabilities, current/stale opening, unknown exception propagation.
- `test_customers.py`: search fields, pagination bounds, disabled/inaccessible exclusion, group closure, default and explicit resolution, walk-in name scope, and zero creation.

Extend `test_sessions.py` where needed for company/profile isolation and opening regressions.

Fresh verification commands:

```bash
bench --site development.localhost migrate
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_authentication
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_bootstrap
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sessions
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_customers
bench --site development.localhost run-tests --module frappe.tests.test_oauth20
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_opening_entry.test_pos_opening_entry
bench --site development.localhost run-tests --app roti_ropi_pos
pre-commit run --all-files
```

Completion requires every verified command to exit zero, intended diff review, and no unrelated changes.