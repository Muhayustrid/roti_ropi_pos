# Mobile POS Authentication and Authorization

## Evidence Legend

- **Verified**: Confirmed in installed Frappe or ERPNext source.
- **Approved**: A Phase 0 security decision approved for implementation.
- **Proposed**: Required behavior for the Mobile POS API.
- **Inferred**: Security consequence derived from verified behavior.

## Supported Frappe Credentials

| Credential | Wire format | Verified behavior | Mobile policy |
| --- | --- | --- | --- |
| API key and secret | `Authorization: token api_key:api_secret` | Resolves an enabled User after secret validation | **Approved** prohibited for Android |
| OAuth access token | `Authorization: Bearer access_token` | Resolves the token's User through Frappe OAuth | **Approved** only Android API credential |
| Session cookie | `Cookie: sid=session-id` plus CSRF token for unsafe methods | Resumes a Frappe session | **Approved** browser OAuth flow only, not Android API calls |
| HTTP Basic API credentials | Base64 `api_key:api_secret` | Accepted by Frappe | **Approved** prohibited for Android |

- **Verified**: OAuth bearer authentication normally does not require a CSRF token because CSRF validation occurs before header authentication while the request has no authenticated cookie session.
- **Verified**: Cookie-authenticated `POST`, `PUT`, `DELETE`, and `PATCH` requests require a valid Frappe CSRF token unless explicitly exempted.
- **Proposed**: Mobile POS must never set `ignore_csrf` and must never define `allow_guest=True` endpoints.

## Approved OAuth Decision

- **Approved**: Every cashier authenticates as an individual, enabled Frappe User. Shared cashier, Administrator, System Manager, and embedded service credentials are prohibited in Android.
- **Approved**: Android is a public OAuth client using Authorization Code with mandatory PKCE S256. It has a client ID and redirect URI, but no client secret is issued, distributed, embedded, or used by Android.
- **Approved**: Authorization runs in the system browser or a secure Custom Tab, never an embedded credential-capturing WebView.
- **Approved**: Android generates a high-entropy verifier per authorization attempt, sends its S256 challenge, validates OAuth state, exchanges the one-time code, and stores tokens with Android Keystore-backed encryption.
- **Verified**: Installed Frappe advertises Authorization Code, refresh tokens, public-client token authentication method `none`, and PKCE S256.
- **Verified**: Installed Frappe also accepts missing or `plain` PKCE in some paths; the Mobile POS OAuth client provisioning and authorization boundary must therefore reject both and require S256.

## Server Authentication Rules

- **Verified**: Frappe rejects `Guest` from plain whitelisted v1 methods before endpoint code runs.
- **Proposed**: Identity is always read from `frappe.session.user`; payload fields named `user`, `owner`, `cashier`, or `modified_by` are rejected.
- **Verified**: Core bearer validation checks token validity but does not prove the linked User remains enabled.
- **Approved**: The Mobile POS auth boundary explicitly rejects a disabled user even when an existing bearer token is otherwise valid.
- **Proposed**: Responses never include access tokens, refresh tokens, authorization codes, verifiers, cookies, CSRF tokens, or password reset state.
- **Proposed**: Request logging must redact `Authorization`, `Cookie`, and any request fields containing credentials.

## Enforced Route Boundary

- **Approved**: Create the role `Mobile POS Cashier` and assign it to each dedicated cashier account.
- **Proposed**: Register `roti_ropi_pos.mobile_pos.auth_hook.validate_mobile_api_scope` in `auth_hooks`.
- **Approved**: Every v1 request must use the Bearer scheme, and the OAuth Bearer Token must be active, belong to `frappe.session.user`, and reference the configured Mobile POS OAuth Client. Cookie, API-key, Basic, and bearer tokens from other OAuth clients are rejected.
- **Approved**: The hook checks `User.enabled`, `Mobile POS Cashier`, exact shipped v1 paths, and absence of legacy `frappe.form_dict.cmd` dispatch. The only command exception is the exact browser login submission.
- **Approved**: A request carrying the configured Mobile POS client ID is rejected unless its literal decoded path is an approved OAuth endpoint. Generic `/api/method`, `/api/v2/method`, encoded alternate paths, and command substitution cannot invoke Mobile POS OAuth flows.
- **Approved**: Browser login, `authorize`, and consent `approve` are the only authenticated browser-route exceptions for a cashier. Token exchange/refresh runs as a public-client flow without Basic auth or a client secret.
- **Approved**: For the configured Mobile POS client, authorize and approve both require a non-empty challenge and exact `code_challenge_method=S256`, including Guest authorization requests.
- **Proposed**: The hook rejects generic `/api/method`, `/api/resource`, v2, RPC, upload, and Desk API traffic for that role. Static unauthenticated assets are irrelevant to the native client.
- **Proposed**: The hook compares Werkzeug's decoded `request.path` to exact entries. It never uses prefix, substring, query parameter, or client-supplied command matching.
- **Proposed**: Non-mobile users remain governed by normal Frappe behavior; this hook does not attempt to secure all ERPNext whitelisted helpers globally.
- **Inferred**: A stolen mobile bearer token can reach only the facade because `Mobile POS Cashier` does not require broad ERPNext roles and the route gate blocks generic APIs.

## Authorization Model

### Exact DocType Permissions

- **Verified**: POS Invoice grants Accounts User create/write/submit and Accounts Manager create/write/submit/cancel.
- **Verified**: POS Opening Entry and POS Closing Entry grant create/submit/cancel only to System Manager, Sales Manager, and Administrator.
- **Approved**: Cashiers do not receive Sales Manager, Accounts Manager, System Manager, Administrator, or shared service credentials.
- **Proposed**: Backend Phase 3 proves the role, Custom DocPerm fixtures, route boundary, profile authorization, current-opening read scaffold, and bootstrap without relying on Tasks 4-8.
- **Proposed**: Task-specific tests in Backend Phases 4-7 prove each operation's exact permissions when that operation exists. Backend Final Task 9 proves the complete lifecycle.

| DocType | Read | Create | Write | Submit | Cancel | Other rights |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| POS Profile | Yes | No | No | N/A | N/A | None |
| POS Opening Entry | Yes | Yes | Yes | Yes | No | No delete, amend, report, export, import, or share |
| POS Invoice | Yes | Yes | Yes | Yes | No | No delete, amend, report, export, import, or share |
| POS Closing Entry | Yes | Yes | Yes | Yes | No | No delete, amend, report, export, import, or share |
| Customer | Yes | No | No | N/A | N/A | None |
| Item | Yes | No | No | N/A | N/A | None |
| Sales Invoice | No | No | No | No | No | None |
| Mobile POS Request | No | No | No | N/A | No | Service-controlled only |

- **Approved**: No additional DocType permission is granted unless an integration test proves a specific core requirement. Support configuration is read internally only for safe projections.
- **Approved**: The sole `ignore_permissions=True` exception is the app-owned Mobile POS Request lifecycle; ERPNext business documents always use normal permissions.

### Operation Matrix

| Operation | Authentication | App checks | Core permission |
| --- | --- | --- | --- |
| Bootstrap/profile list | Required | Eligible assigned profile only | POS Profile read |
| Current session | Required | Current user and assigned profile only | POS Opening Entry read |
| Open session | Required | Eligible profile, no conflicting session | POS Opening Entry create + submit |
| Search customers | Required | Existing enabled visible Customers; bounded query; no creation | Customer read |
| Catalog/search/scan | Required | Eligible profile, allowed company/warehouse | Item/POS Profile read as applicable |
| Submit sale | Required | Own active session, matching profile | POS Invoice create + submit |
| View sale | Required | Own assigned profile/opening scope | POS Invoice read |
| Create return | Required | Source visible, return limits valid | POS Invoice read + create + submit |
| Closing preview | Required | Own opening and assigned profile | POS Opening Entry/POS Invoice read |
| Submit closing | Required | Own opening and assigned profile | POS Closing Entry create + submit |
| Closing status | Required | Closing linked to visible opening/profile | POS Closing Entry read |

- **Approved**: There is no cashier cancellation endpoint in the MVP. Manager cancellation remains in ERPNext Desk.

### POS Scope Checks

- **Proposed**: A named profile is accepted only when enabled, assigned to the current user, and compatible with its company and warehouse.
- **Approved**: Unassigned-profile fallback is not used. Every mobile POS Profile must explicitly list the cashier.
- **Approved**: The authoritative active-opening predicate is:
  `docstatus = 1`,
  `status = "Open"`,
  empty `pos_closing_entry`,
  `user = frappe.session.user`,
  `pos_profile = the selected enabled and authorized profile`,
  and `company = the authorized profile company`.
- **Approved**: The predicate has no hard current-calendar-day filter because a valid shift may cross midnight.
- **Approved**: The opening DTO returns `posting_date` and `period_start_date`, where `period_start_date` is the opening timestamp.
- **Approved**: When the opening timestamp is on an earlier calendar date in the site timezone, the DTO includes the stable `STALE_OPENING` warning. The condition must not be hidden from Android.
- **Approved**: A future manager policy may introduce a maximum shift duration, but no such limit is part of the MVP.
- **Verified**: ERPNext rejects a new opening when either the POS Profile already has an Open entry or the cashier is assigned to another Open entry.
- **Approved**: Mobile endpoints expose only documents belonging to the authenticated cashier's assigned profile and opening scope.
- **Proposed**: Company, warehouse, and POS Profile are derived from the authorized profile. Conflicting client values return `PROFILE_SCOPE_MISMATCH`.

## Android Credential Lifecycle

- **Proposed**: Accept only HTTPS base URLs; cleartext traffic is disabled in the Android manifest.
- **Proposed**: Store credentials using Android Keystore-backed encryption and exclude them from backup, screenshots, analytics, crash reports, and logs.
- **Proposed**: Keep tokens, authorization codes, verifiers, and secrets out of Gradle files, source control, QR codes, deep links, logs, analytics, and backups.
- **Proposed**: On HTTP 401, stop automatic mutation retries, preserve pending idempotency records locally, and require re-authentication or reprovisioning.
- **Proposed**: On logout or device reassignment, delete local credentials and pending sensitive response bodies. Idempotency keys may remain only if required to recover a known pending mutation after the same user signs in.
- **Proposed**: Logout removes local tokens. Managers can revoke OAuth Bearer Token records or disable the user in ERPNext Desk. Android does not hold a secret for Frappe's advertised `client_secret_basic` revocation method; direct public-client revocation is not assumed until verified.

## HTTP and Error Behavior

- **Verified**: Frappe authentication, Guest rejection, route-hook rejection, rate limiting, and some HTTP failures occur before app endpoint code executes.
- **Proposed**: Pre-dispatch failures use Frappe's native error body and HTTP status. Android maps native 401, 403, 429, and 5xx responses to transport-level errors and reads Frappe's server request identifier when available.
- **Proposed**: Stable Mobile POS envelopes apply only after a v1 endpoint begins execution.
- **Approved**: Known `frappe.PermissionError` failures raised by `profile.check_permission()`, document permission checks, or equivalent Mobile POS service checks are converted at the service/endpoint boundary into the approved stable HTTP 403 Mobile POS envelope.
- **Proposed**: An authenticated user lacking an operation permission inside a v1 endpoint returns `PERMISSION_DENIED`.
- **Proposed**: A profile read failure is mapped to `PROFILE_SCOPE_MISMATCH` when existence must not be disclosed.
- **Approved**: Permission mapping catches only known permission failures. Unknown exceptions are logged with the request ID and re-raised; they are never silently converted into authorization errors.
- **Proposed**: A valid user outside a profile/document scope also receives HTTP 403; responses must not reveal whether an inaccessible document exists.
- **Proposed**: Authentication errors are never cached and include a request ID for server-side diagnosis.

## Security Verification

- **Proposed**: Test every endpoint as Guest, wrong-profile cashier, correctly assigned cashier, user without `Mobile POS Cashier`, disabled user, and a second-company cashier.
- **Proposed**: Test mandatory S256 on Guest/authenticated authorize and approve, missing challenge rejection, `plain` rejection, wrong verifier, state mismatch, redirect mismatch, authorization-code replay, refresh, manager revocation, disabled user, and bearer access.
- **Proposed**: Reject cookie, API-key, Basic, wrong-client bearer, and legacy `cmd` attempts against every v1 route.
- **Proposed**: Prove the public client exchanges a code without a client secret and the APK/configuration contains no secret or shared credential.
- **Proposed**: Prove browser authorization and consent work while generic core methods/resources remain blocked for the cashier role.
- **Proposed**: Inspect logs and crash output to prove credentials are redacted.

## Source Evidence

- **Verified**: `frappe/auth.py:28-118,384-424,629-739`
- **Verified**: `frappe/sessions.py:210-236,317-350`
- **Verified**: `frappe/__init__.py:439-495`
- **Verified**: `erpnext/accounts/doctype/pos_profile/pos_profile.py:274-316`
- **Verified**: `erpnext/accounts/doctype/pos_opening_entry/pos_opening_entry.json:139-180`
- **Verified**: `erpnext/accounts/doctype/pos_invoice/pos_invoice.json:1645-1682`
- **Verified**: `erpnext/accounts/doctype/pos_closing_entry/pos_closing_entry.json:270-311`
- **Verified**: `frappe/integrations/oauth2.py:66-175,314-341,397-419`
- **Verified**: `frappe/oauth.py:76-92,130-167`
- **Verified**: `frappe/integrations/doctype/oauth_client/oauth_client.json:194-199`
- **Verified**: `frappe/tests/test_oauth20.py:153-196`
