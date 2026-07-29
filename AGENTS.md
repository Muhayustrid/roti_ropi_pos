# Roti Ropi Mobile POS Backend Rules

Read this file before changing this repository. These rules apply to the entire `roti_ropi_pos` app.

## Communication and Change Control

- Communicate with the user in Indonesian.
- Write repository Markdown, code comments, technical documentation, test names, and commit messages in English.
- Do not commit, push, deploy, migrate production, or begin a later implementation phase without explicit user approval.
- Verify the installed Frappe and ERPNext source before relying on a core method, field, hook, permission, or side effect.
- After a task or phase is confirmed complete (all tests pass, committed, pushed), update its **Status** line in `docs/mobile-pos/implementation-plan.md` to `**Complete** ✅ (<commit message> — commit <hash>)`. Do this in the same session before closing, no separate approval needed.

## Ownership and Boundaries

- `roti_ropi_pos` owns the versioned Mobile POS backend API, authorization boundary, stable DTOs/errors, idempotency, and ERPNext POS orchestration.
- `bakery_manufacturing` owns manufacturing behavior, Price Group synchronization, batch default-UOM behavior, and the existing walk-in display-name customization.
- Integrate with `bakery_manufacturing` only through registered hooks, persisted ERPNext data, or an explicitly public contract. Do not import private bakery helpers.
- ERPNext remains the source of truth for POS Profile, Customer, opening, POS Invoice, returns, closing, pricing, taxes, payments, stock, serials, batches, and accounting.
- Never edit files under `apps/erpnext` or `apps/frappe`. Use supported app hooks, Custom DocPerm, fixtures, controller overrides, or whitelisted app methods.
- The Android client is a separate repository at `/Users/rotiropi/DockerERPNext/POSERPNext` and must consume only documented Mobile POS API contracts.

## MVP Scope

- Support ERPNext `POS Invoice` mode only. Return stable `UNSUPPORTED_POS_MODE` when the site uses another POS invoice mode.
- Do not add Sales Invoice mode to the MVP.
- Every submitted MVP invoice must be fully settled. Multiple distinct payment modes are allowed only when the authoritative invoice has zero outstanding amount.
- Partially paid invoices are post-MVP.
- Search and select existing enabled registered Customers through a permission-aware endpoint.
- Omitted customer selection resolves to the assigned POS Profile default walk-in Customer.
- Accept an optional walk-in display name only for that default walk-in Customer and map it to bakery's existing `custom_walk_in_customer_name` boundary.
- Never create a Customer from search, quote, scan, sale, return, or recovery requests.
- Cashier corrections use POS Invoice returns. Mobile cancellation is outside the cashier MVP; manager cancellation remains an ERPNext Desk workflow.

## Authentication and Authorization

- Android authentication is OAuth 2.0 Authorization Code with mandatory PKCE S256.
- Treat Android as a public OAuth client. Never embed or distribute a client secret.
- Never use API keys, Basic credentials, shared cashier accounts, Administrator credentials, or service-user credentials in Android.
- Every cashier authenticates as an individual enabled Frappe User with the `Mobile POS Cashier` role and an explicitly assigned enabled POS Profile.
- Do not require or grant Sales Manager, Accounts Manager, System Manager, or Administrator to a cashier.
- OAuth Client, POS Profile, Company, Warehouse, Mode of Payment, pricing, tax, Item, and Customer master setup remains an ERPNext Desk responsibility for appropriate manager roles; do not expose administrative setup through cashier endpoints.
- Enforce an exact route allowlist for `Mobile POS Cashier`; block generic Frappe methods, resources, uploads, RPC, and Desk APIs.
- Reject legacy `cmd`, generic method, encoded alternate path, and `/api/v2/method` dispatch for Mobile POS API/OAuth flows. The only command exception is the exact browser login submission.
- Require the Bearer scheme on every v1 request and verify the active token belongs to the configured Mobile POS OAuth Client, current enabled user, and `Mobile POS Cashier` role. Cookie, API-key, Basic, and wrong-client bearer authentication are forbidden.
- Enforce a non-empty PKCE challenge with `code_challenge_method=S256` on both authorize and approve for the configured Mobile POS public client; do not rely on Frappe defaults.
- Derive user identity from `frappe.session.user`. Reject client-controlled user, owner, company, warehouse, account, rate, tax, total, status, and document identity fields.

### Exact Cashier DocType Permissions

| DocType | Allowed permissions |
| --- | --- |
| Account | select |
| POS Profile | read |
| POS Opening Entry | read, create, write, submit |
| POS Invoice | read, create, write, submit |
| POS Closing Entry | read, create, write, submit |
| Customer | read |
| Item | read |
| Sales Invoice | none |
| Mobile POS Request | none for the user; service-controlled only |

- Grant no cashier cancel, delete, amend, report, export, import, or share rights.
- Add a permission only after an integration test proves that an exact DocType permission is required. Never substitute a broad ERPNext role.
- Use normal permissions for ERPNext business documents. The app-owned Mobile POS Request service is the sole permitted `ignore_permissions=True` exception.

### Endpoint Checks

- Every endpoint requires OAuth bearer identity, `Mobile POS Cashier`, supported POS Invoice mode, an explicitly assigned enabled profile, and company/profile scope.
- Opening endpoints derive the cashier, validate profile payment modes, enforce no conflicting opening, and use normal create/submit permission.
- Customer search returns existing enabled visible Customers only, uses bounded pagination, and never creates records.
- Catalog and scan endpoints derive price list and warehouse from the profile and return safe projections only.
- Quote and sale endpoints resolve Customer through the shared customer boundary and recalculate prices, taxes, stock, UOM, batch, serial, and totals server-side.
- Sale submission requires an opening owned by the current cashier/profile and authoritative zero outstanding amount.
- History and return endpoints support POS Invoice only and enforce source/profile visibility and remaining return quantity.
- Closing endpoints derive opening, period, invoices, and user server-side and use the documented closing recovery protocol.

## API and Recovery Rules

- Keep public methods under versioned modules such as `roti_ropi_pos.api.v1`.
- Preserve the envelopes, DTO types, HTTP behavior, and stable error codes in `docs/mobile-pos/api-contract.md`.
- Breaking contract changes require a new API version. Additive response fields are allowed only where the contract permits them.
- Every mutation requires a client-generated `X-Idempotency-Key` and durable Mobile POS Request processing.
- Retain terminal cleanup-eligible idempotency records for 90 days.
- Never delete Processing, unresolved recovery, leased, failed-closing-under-review, incident-held, or audit-held request records by age alone.
- Cleanup must verify durable `custom_mobile_pos_transaction_id` correlation before deleting a request row and must never delete ERPNext business documents.
- Do not call POS merge-log creation/cancellation helpers from API services. Preserve the reviewed after-commit closing boundary.

## Testing and Verification

- Use test-driven development for feature and bug-fix work.
- Run targeted tests with `bench --site development.localhost run-tests --module <module>` inside `/workspace/development/frappe-bench`.
- Run the full app gate with `bench --site development.localhost run-tests --app roti_ropi_pos`.
- Run `pre-commit run --all-files` from `apps/roti_ropi_pos`.
- Test OAuth PKCE S256, exact role permissions, route denial, cross-user/company isolation, customer behavior, full settlement, stock/batch/serial validation, idempotent concurrency, returns, synchronous closing, queued closing, and safe 90-day cleanup.
- Run relevant bakery and ERPNext regression modules when their boundaries are exercised.
- Do not claim completion without fresh command output and a clean review of the intended diff.

## Skills and Navigation

- Use `brainstorming` before new behavior, `writing-plans` for approved multi-step work, `test-driven-development` during implementation, `systematic-debugging` for failures, `requesting-code-review` before completion, and `verification-before-completion` before success claims.
- Primary Frappe development skill: `/Users/rotiropi/DockerERPNext/ai-skills/frappe/skills/skills/frappe-app-dev/SKILL.md`.
- This is an existing app; read `/Users/rotiropi/DockerERPNext/ai-skills/frappe/skills/skills/frappe-app-dev/references/existing-app.md`, then load only task-relevant references.
- Before implementing APIs, hooks, DocTypes, permissions, controllers, caching, tests, or bench operations, read the corresponding reference in `/Users/rotiropi/DockerERPNext/ai-skills/frappe/skills/skills/frappe-app-dev/references/`. For fixtures, read `hooks.md` and `bench-operations.md`, plus `permissions.md` for role/permission fixtures and `testing.md` for test data.
- Frappe skills and references are guidance only. They do not override this file or the versioned Mobile POS contracts, and they do not replace verification against installed Frappe/ERPNext source and executable tests.
- Use the `graphify` skill for codebase navigation only; installed source and executable tests remain authoritative.
- Graphify skill: `/Users/rotiropi/.config/opencode/skills/graphify/SKILL.md`.
- ERPNext graph: `/Users/rotiropi/DockerERPNext/graphify-output/erpnext/graphify-out/graph.json`.
- Frappe graph: `/Users/rotiropi/DockerERPNext/graphify-output/frappe/graphify-out/graph.json`.
- Bakery graph: `/Users/rotiropi/DockerERPNext/graphify-output/bakery_manufacturing/graphify-out/graph.json`.
- Do not infer correctness from Graphify edges. Re-open every cited source location before implementation.
