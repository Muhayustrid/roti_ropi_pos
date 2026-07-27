# Mobile POS Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure, versioned, idempotent Mobile POS facade that lets the Android client operate ERPNext POS without exposing broad core methods.

**Architecture:** `roti_ropi_pos.api.v1` contains thin whitelisted endpoints. Focused services derive user/profile/session scope, orchestrate normal ERPNext document transitions, and return app-owned DTOs; ERPNext remains authoritative for all commercial and ledger behavior. A custom `Mobile POS Request` DocType makes mutations replay-safe.

**Tech Stack:** Python 3.14, Frappe 16, ERPNext 16, MariaDB, `IntegrationTestCase`, Ruff, and pre-commit.

## Implementation Methodology

- Superpowers is the primary development methodology.
- Use `superpowers:subagent-driven-development` as the recommended execution mode or `superpowers:executing-plans` as the alternative.
- Use `superpowers:test-driven-development` during implementation.
- Use `superpowers:requesting-code-review` and `superpowers:verification-before-completion` before completion claims.
- Ponytail is a complementary simplicity constraint, not a replacement for Superpowers.
- Use Ponytail at `full` intensity: avoid unnecessary code, reuse verified project patterns, and prefer the standard library, Frappe, ERPNext, and already installed dependencies.
- Add abstractions or dependencies only for a demonstrated requirement and choose the smallest safe implementation satisfying the approved contracts.
- Never simplify away authorization, permissions, validation, idempotency, recovery, auditability, tests, accessibility, or compatibility.
- Do not use Ponytail `ultra` unless explicitly approved.

## Evidence Legend

- **Verified**: Confirmed in the installed source or repository.
- **Approved**: A Phase 0 implementation decision approved by the user.
- **Proposed**: Required by this implementation plan.
- **Inferred**: Must be proved by a test during implementation.

## Global Constraints

- **Verified**: Baseline versions are Frappe `16.27.1`, ERPNext `16.28.0`, `bakery_manufacturing` `0.0.1`, and `roti_ropi_pos` `0.0.1`.
- **Proposed**: Never modify `apps/frappe` or `apps/erpnext`.
- **Proposed**: Never trust client identity, company, warehouse, accounts, rates, taxes, totals, posting status, or document names.
- **Proposed**: Do not use `ignore_permissions=True` for ERPNext business documents. The only exception is the app-owned `Mobile POS Request` control record, whose service validates scope and state transitions before privileged writes.
- **Proposed**: Every mutation is POST-only and requires `X-Idempotency-Key`.
- **Proposed**: Use `frappe.session.user`, preserve installed core mutation permissions, and expose only explicitly scoped read projections.
- **Proposed**: Call POS Closing Entry submission, never merge-log helpers directly.
- **Proposed**: Treat Graphify as navigation only and verify every imported source symbol against the installed files.
- **Approved**: Do not stage, commit, push, or deploy merely because a phase/task was authorized. Every task ends with diff review and requires separate explicit user approval before any commit.
- **Proposed**: V1 requires ERPNext POS Settings invoice mode `POS Invoice` and declares both ERPNext and `bakery_manufacturing` as app dependencies.
- **Approved**: Android uses OAuth 2.0 Authorization Code with mandatory PKCE S256 as a public client. API keys, shared users, Administrator credentials, and embedded secrets are prohibited.
- **Approved**: Cashiers use only `Mobile POS Cashier` plus exact Custom DocPerm fixtures; Sales Manager and broad accounting/administrative roles are not required.
- **Approved**: Registered-customer selection and default walk-in Customer are supported without Customer auto-creation. Submitted sales must be fully settled, and idempotency terminal retention is 90 days.
- **Approved**: V1 has no health endpoint. Adding one requires explicit approval as a new backend contract and task.
- **Approved**: V1 has no return-preview endpoint. Adding one requires explicit approval as a new backend contract and task.
- **Approved**: The MVP has no maximum shift-duration policy.
- **Approved**: This plan contains backend tasks only. Android remains blocked until a separate plan is approved at `/Users/rotiropi/DockerERPNext/POSERPNext/docs/mobile-pos/implementation-plan.md`.
- **Approved**: Completing this plan does not by itself complete Mobile POS delivery.

## Product Scope Authority

- **Approved**: [`product-requirements.md`](product-requirements.md) is the authoritative product-scope document for the Roti Ropi Mobile POS. It defines the product vision, MVP scope, business rules, functional requirements, and acceptance criteria.
- **Approved**: Implementation tasks in this plan and in the future Android implementation plan operate within the product scope defined by the PRD. No implementation task may introduce new product capabilities, user-facing behaviors, endpoints, or business rules beyond what the PRD describes without explicit product-level approval.
- **Approved**: Expanding product scope requires updating the PRD first and obtaining approval before modifying any implementation plan or writing code for the new capability.

Run every `bench` command from `/workspace/development/frappe-bench` inside the development container. Run `pre-commit` and every `git` command from `/workspace/development/frappe-bench/apps/roti_ropi_pos`.

---

## Backend Phase Roadmap

The detailed task instructions remain authoritative. Phases add execution boundaries without duplicating or replacing task steps.

### Backend Phase 1: API Foundation

- **Objective:** Establish stable errors, envelopes, request parsing, and endpoint-boundary behavior.
- **Included:** Task 1.
- **Excluded:** Idempotency, authentication, business endpoints, Android, health, and return preview.
- **Prerequisites:** Approved Phase 0 documents and verified Frappe request behavior.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** Task 1 red/green cycle, `test_api_foundation`, and intended diff review.
- **Acceptance:** Task 1 primitives pass; no business endpoint is claimed ready.
- **Stop:** Any failed check, hidden unknown exception, altered native pre-dispatch response, or out-of-scope diff.
- **Session boundary:** One Task 1 session, then review and explicit approval.

### Backend Phase 2: Durable Idempotency

- **Objective:** Establish versioned mutation identity, durable replay, audit references, and retention cleanup.
- **Included:** Task 2.
- **Excluded:** Endpoint-specific business orchestration and Android local recovery.
- **Prerequisites:** Backend Phase 1.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** Task 2 migration, `test_idempotency`, concurrency, rollback, reference, transaction-ID, and cleanup coverage.
- **Acceptance:** One logical mutation produces one verified reference and stable replay; cleanup preserves unresolved and held records.
- **Stop:** Duplicate creation, missing version in operation ID, reference mismatch, unsafe cleanup, unrelated migration diff, or failed verification.
- **Session boundary:** One Task 2 session, then migration evidence, review, and explicit approval.

### Backend Phase 3: Authentication, Profiles, and Bootstrap

- **Objective:** Establish OAuth/PKCE enforcement, exact cashier authorization, profile scope, route denial, current-opening read support, and bootstrap.
- **Included:** Task 3.
- **Excluded:** Opening mutation and Tasks 4-8 business flows.
- **Prerequisites:** Backend Phase 2 and configured test OAuth Client.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** `test_authentication`, `test_bootstrap`, Frappe OAuth/client regressions, current/stale-opening DTO coverage, and pre-commit.
- **Acceptance:** Auth/profile/bootstrap scaffold passes without broad roles or distributed secrets and exposes prior-day Open entries with `STALE_OPENING`.
- **Stop:** Route bypass, broad role requirement, incomplete bootstrap, hidden stale opening, secret requirement, or failed verification.
- **Session boundary:** One Task 3 session, then security review and explicit approval.

### Backend Phase 4: Opening and Customer Resolution

- **Objective:** Expose current/open session endpoints and scoped existing-Customer resolution.
- **Included:** Task 4 followed by Task 4A.
- **Excluded:** Catalog, sale, Customer creation, Android opening UI, health, return preview, and maximum shift-duration policy.
- **Prerequisites:** Backend Phase 3.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** `test_sessions`, `test_customers`, opening regression, conflict coverage, stale-opening warning, and Customer predicate coverage.
- **Acceptance:** Opening and Customer contracts pass with normal permissions and no Customer creation.
- **Stop:** Duplicate opening, synthetic Customer Company relation, permission leakage, hidden stale warning, Customer mutation, or failed verification.
- **Session boundary:** Separate Task 4 and Task 4A sessions with independent review stops.

### Backend Phase 5: Catalog, Scan, Quote, UOM, and Stock

- **Objective:** Expose scoped catalog, effective bakery scan behavior, and authoritative quote inputs.
- **Included:** Task 5.
- **Excluded:** Android cart/cache and authoritative sale submission.
- **Prerequisites:** Backend Phase 4 and verified ERPNext/bakery source contracts.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** `test_catalog`, bakery regressions, effective-override contract, and relevant ERPNext POS/stock regressions.
- **Acceptance:** Catalog/scan/quote contracts pass without private bakery imports or copied ERPNext calculations.
- **Stop:** Source-contract drift, wrong effective override, leaked Item data, duplicated core logic, or failed verification.
- **Session boundary:** One Task 5 session, then boundary review and explicit approval.

### Backend Phase 6: Sale, History, and Returns

- **Objective:** Implement fully settled idempotent sales, scoped history, and ERPNext-mapped returns.
- **Included:** Task 6 followed by Task 7.
- **Excluded:** Partial payment, Sales Invoice mode, cancellation, return preview, Android receipt/UI, and offline accounting.
- **Prerequisites:** Backend Phase 5.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** `test_sales`, concurrency, rollback, return limits, append-only return remarks, replay, and ERPNext POS Invoice regressions.
- **Acceptance:** Sale/history/return contracts pass with zero outstanding amount and durable references.
- **Stop:** Permission bypass, duplicate invoice, non-zero outstanding amount, overwritten remarks, missing return reference, new endpoint, or failed verification.
- **Session boundary:** Separate sequential Task 6 and Task 7 sessions with independent review stops.

### Backend Phase 7: Closing and Recovery

- **Objective:** Implement preview, counted balances, synchronous/queued closing, durable recovery, and status polling.
- **Included:** Task 8.
- **Excluded:** Android closing UI, mobile consolidation retry, and production deployment.
- **Prerequisites:** Backend Phase 6 and verified installed closing source.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** `test_closing`, closing/Merge Log regressions, source-contract checks, and enqueue boundary coverage.
- **Acceptance:** Closing paths pass without duplicate Closing Entry or pre-commit enqueue.
- **Stop:** Competing override, source drift, direct merge-helper call, unsafe retention, or failed verification.
- **Session boundary:** One Task 8 session, then recovery/source review and explicit approval.

### Backend Final: End-to-End Backend Release Evidence

- **Objective:** Verify the complete backend lifecycle and operational setup.
- **Included:** Task 9.
- **Excluded:** Android implementation, Android release claims, production deployment, and final Mobile POS delivery claims.
- **Prerequisites:** Backend Phases 1-7 and approved staging configuration.
- **Ownership:** `roti_ropi_pos`.
- **Verification:** Task 9 backend, dependency, source-contract, security, stale-opening, and staging gates.
- **Acceptance:** All backend checks pass and evidence is recorded without credential leakage or unrelated diffs.
- **Stop:** Any failed command, contract drift, route bypass, credential leak, unrelated diff, or Android/product-level completion claim.
- **Session boundary:** One backend evidence session and a separately approved staging context, then stop for review.

## Planned File Map

| Path | Responsibility |
| --- | --- |
| `roti_ropi_pos/api/v1/*.py` | Thin whitelisted endpoint adapters |
| `roti_ropi_pos/mobile_pos/errors.py` | Stable domain errors |
| `roti_ropi_pos/mobile_pos/responses.py` | Envelopes, request IDs, HTTP status mapping |
| `roti_ropi_pos/mobile_pos/validation.py` | Strict request parsing and decimal normalization |
| `roti_ropi_pos/mobile_pos/authorization.py` | User, role, profile, and document scope |
| `roti_ropi_pos/mobile_pos/auth_hook.py` | Restrict dedicated mobile users to app-owned v1 routes |
| `roti_ropi_pos/mobile_pos/idempotency.py` | Durable mutation execution and replay |
| `roti_ropi_pos/mobile_pos/profiles.py` | Safe POS Profile DTOs and eligibility |
| `roti_ropi_pos/mobile_pos/sessions.py` | Opening Entry orchestration |
| `roti_ropi_pos/mobile_pos/catalog.py` | Search, scan, quote, stock, and UOM mapping |
| `roti_ropi_pos/mobile_pos/customers.py` | Existing-customer search and default/walk-in resolution |
| `roti_ropi_pos/mobile_pos/invoices.py` | POS Invoice sale, history, and return orchestration |
| `roti_ropi_pos/mobile_pos/closing.py` | Preview, submit, status, and locking |
| `roti_ropi_pos/roti_ropi_pos/doctype/mobile_pos_request/*` | Durable idempotency DocType |
| `roti_ropi_pos/tests/test_*.py` | Unit, integration, authorization, and concurrency tests |

### Task 1: API Foundation and Stable Responses

**Status:** **Complete** ✅ (`feat: add mobile POS API foundation` — commit `40813e3`)

**Files:**
- Create: `roti_ropi_pos/api/__init__.py`
- Create: `roti_ropi_pos/api/v1/__init__.py`
- Create: `roti_ropi_pos/mobile_pos/__init__.py`
- Create: `roti_ropi_pos/mobile_pos/errors.py`
- Create: `roti_ropi_pos/mobile_pos/responses.py`
- Create: `roti_ropi_pos/mobile_pos/validation.py`
- Create: `roti_ropi_pos/tests/__init__.py`
- Create: `roti_ropi_pos/tests/test_api_foundation.py`

**Interfaces:**
- Consumes: Frappe request and response globals.
- Produces: `MobilePOSAPIError`, `api_endpoint`, `success`, `require_json_object`, `decimal_string`, and `reject_fields`.

- [ ] **Step 1: Write failing envelope and validation tests**

```python
from decimal import Decimal

from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.responses import success
from roti_ropi_pos.mobile_pos.validation import decimal_string, reject_fields


class TestAPIFoundation(IntegrationTestCase):
    def test_success_envelope_has_stable_metadata(self):
        result = success({"value": "ok"}, request_id="REQ-1", server_time="2026-07-23T14:30:00+07:00")
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"], {"value": "ok"})
        self.assertEqual(result["meta"]["api_version"], "v1")

    def test_decimal_string_rejects_float(self):
        with self.assertRaisesRegex(MobilePOSAPIError, "decimal string"):
            decimal_string(1.5, field="amount")
        self.assertEqual(decimal_string("1.50", field="amount"), Decimal("1.50"))

    def test_reject_fields_blocks_server_owned_values(self):
        with self.assertRaisesRegex(MobilePOSAPIError, "company"):
            reject_fields({"company": "Roti Ropi"}, {"company", "owner"})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_api_foundation
```

Expected: FAIL because `roti_ropi_pos.mobile_pos.errors` does not exist.

- [ ] **Step 3: Implement the error, envelope, and strict parsing interfaces**

```python
class MobilePOSAPIError(Exception):
    def __init__(self, code: str, message: str, *, status: int = 400, details: dict | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}
        self.retryable = retryable
```

```python
def success(data: dict, *, http_status: int = 200, request_id: str | None = None, server_time: str | None = None, replayed: bool = False) -> dict:
    frappe.response["http_status_code"] = http_status
    return {
        "ok": True,
        "data": data,
        "meta": {
            "api_version": "v1",
            "request_id": request_id or frappe.generate_hash(length=26),
            "server_time": server_time or frappe.utils.now_datetime().astimezone().isoformat(),
            "replayed": replayed,
        },
    }
```

```python
def decimal_string(value: object, *, field: str) -> Decimal:
    if not isinstance(value, str):
        raise MobilePOSAPIError(
            "INVALID_REQUEST",
            f"{field} must be a decimal string.",
            details={"field": field, "reason": "Expected a decimal string."},
        )
    try:
        return Decimal(value)
    except InvalidOperation:
        raise MobilePOSAPIError(
            "INVALID_REQUEST",
            f"{field} must be a decimal string.",
            details={"field": field, "reason": "Invalid decimal syntax."},
        )


def reject_fields(payload: dict, blocked: set[str]) -> None:
    present = sorted(blocked.intersection(payload))
    if present:
        raise MobilePOSAPIError(
            "INVALID_REQUEST",
            f"Server-owned fields are not accepted: {', '.join(present)}.",
            details={"field": present[0], "reason": "This field is server-owned."},
        )
```

Implement `api_endpoint` to establish a savepoint, map `MobilePOSAPIError` into the documented error envelope/status, roll back to the savepoint before returning errors, and re-raise unknown exceptions after request-ID logging. Known permission failures are converted to `MobilePOSAPIError` by the service or common Mobile POS endpoint boundary before this mapper handles them; unknown exceptions are never converted into permission errors. Document in its test that authentication, mobile-route-hook, rate-limit, and routing failures happen before this decorator and retain Frappe's native response shape.

- [ ] **Step 4: Run foundation tests**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Prepare the foundation for user review**

Review `git diff`, report the proposed English commit message `feat: add mobile POS API foundation`, and wait for explicit commit approval. Phase authorization is not commit approval.

### Task 2: Durable Idempotency

**Status:** **Complete** ✅ (`feat: add idempotent mobile POS mutations` — commit `23dc6c1`)

**Files:**
- Create: `roti_ropi_pos/roti_ropi_pos/doctype/mobile_pos_request/__init__.py`
- Create: `roti_ropi_pos/roti_ropi_pos/doctype/mobile_pos_request/mobile_pos_request.py`
- Create: `roti_ropi_pos/roti_ropi_pos/doctype/mobile_pos_request/mobile_pos_request.json`
- Create: `roti_ropi_pos/mobile_pos/idempotency.py`
- Create: `roti_ropi_pos/tests/test_idempotency.py`
- Create: `roti_ropi_pos/fixtures/custom_field.json`
- Modify: `roti_ropi_pos/hooks.py`

**Interfaces:**
- Consumes: authenticated user, server-owned versioned operation ID, parsed payload, and an operation callable accepting the transaction UUID.
- Produces:
  `MutationResult`,
  `execute_idempotent(operation_id: str, validated_payload: dict, operation: Callable[[str], MutationResult]) -> dict`,
  `verify_business_reference`,
  and `delete_expired_requests()`.

- [ ] **Step 1: Write failing first-run, replay, conflict, rollback, and concurrency tests**

```python
from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from roti_ropi_pos.mobile_pos.errors import MobilePOSAPIError
from roti_ropi_pos.mobile_pos.idempotency import MutationResult, execute_idempotent


class TestIdempotency(IntegrationTestCase):
    def test_same_key_and_payload_replays_one_operation(self):
        calls = []
        result = lambda name: MutationResult(
            data={"name": name},
            reference_doctype="POS Invoice",
            reference_name=name,
        )
        with (
            patch("frappe.get_request_header", return_value="6ba7b810-9dad-41d1-80b4-00c04fd430c8"),
            patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
        ):
            first = execute_idempotent(
                "v1.sales.submit",
                {"qty": "1"},
                lambda transaction_id: calls.append(1) or result("INV-1"),
            )
            second = execute_idempotent(
                "v1.sales.submit",
                {"qty": "1"},
                lambda transaction_id: calls.append(2) or result("INV-2"),
            )
        self.assertEqual(calls, [1])
        self.assertEqual(first["data"], second["data"])
        self.assertEqual(second["meta"]["replayed"], True)

    def test_same_key_and_changed_payload_is_conflict(self):
        result = MutationResult(data={"name": "INV-1"}, reference_doctype="POS Invoice", reference_name="INV-1")
        with (
            patch("frappe.get_request_header", return_value="6ba7b810-9dad-41d1-80b4-00c04fd430c8"),
            patch("roti_ropi_pos.mobile_pos.idempotency.verify_business_reference"),
        ):
            execute_idempotent("v1.sales.submit", {"qty": "1"}, lambda transaction_id: result)
            with self.assertRaises(MobilePOSAPIError) as error:
                execute_idempotent("v1.sales.submit", {"qty": "2"}, lambda transaction_id: result)
        self.assertEqual(error.exception.code, "IDEMPOTENCY_KEY_REUSED")
```

Add database-level tests that assert one `Mobile POS Request` and one business reference after twenty concurrent attempts, and no request row after an operation raises.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_idempotency
```

Expected: FAIL because the DocType and service do not exist.

- [ ] **Step 3: Create the DocType with an enforced unique scope key**

Before the first migration, activate `required_apps = ["erpnext", "bakery_manufacturing"]` in `hooks.py` and verify both apps are installed on the test site.

Define the exact fields from `idempotency-and-recovery.md`, including phase, lease, terminal timestamps, 90-day expiry, retention hold/reason, and audit-reference state. Make `scope_key` unique, allow only `Processing`, `Completed`, and `Rejected`, and grant no normal-user Desk permissions. Add read-only `custom_mobile_pos_transaction_id` fixtures to POS Opening Entry, POS Invoice, and POS Closing Entry. Only the idempotency service writes the control record with `ignore_permissions=True`; ERPNext business documents use normal permission.

- [ ] **Step 4: Implement canonical hashing and transactional execution**

```python
@dataclass(frozen=True)
class MutationResult:
    data: dict
    reference_doctype: str
    reference_name: str
    http_status: int = 201


def normalize_for_hash(value):
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized, "f")
    if isinstance(value, dict):
        return {key: normalize_for_hash(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_for_hash(item) for item in value]
    return value


def canonical_hash(operation_id: str, validated_payload: dict) -> str:
    normalized = normalize_for_hash(validated_payload)
    body = json.dumps(
        {"operation_id": operation_id, "payload": normalized},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def execute_idempotent(
    operation_id: str,
    validated_payload: dict,
    operation: Callable[[str], MutationResult],
) -> dict:
    user = frappe.session.user
    key = require_idempotency_key()
    request_hash = canonical_hash(operation_id, validated_payload)
    scope_key = hashlib.sha256(f"{user}\n{operation_id}\n{key}".encode()).hexdigest()
    request = create_or_get_locked_request(scope_key, key, operation_id, request_hash, user)
    if request.request_hash != request_hash:
        raise MobilePOSAPIError(
            "IDEMPOTENCY_KEY_REUSED",
            "The idempotency key was already used with different data.",
            status=409,
            details={"endpoint": operation_id},
        )
    if request.status == "Completed":
        return replay_response(request)
    result = operation(key)
    verify_business_reference(operation_id, result, key)
    response = success(result.data, http_status=result.http_status)
    complete_request(
        request,
        response,
        reference_doctype=result.reference_doctype,
        reference_name=result.reference_name,
        audit_reference_written=True,
    )
    return response
```

Implement unique-conflict handling so the loser waits for and locks the committed row. Do not commit inside this standard function. `verify_business_reference` loads the reference, verifies the DocType allowed for the operation, and verifies the persisted `custom_mobile_pos_transaction_id` equals the request key. `replay_response` preserves data/request ID, changes only `meta.replayed` to true, and sets HTTP 200. Expected standard-mutation errors are rolled back and mapped by the common endpoint decorator; only the closing-specific recovery executor may durably store a `Rejected` response.

- [ ] **Step 5: Add cleanup scheduling**

Add `scheduler_events = {"daily": ["roti_ropi_pos.mobile_pos.idempotency.delete_expired_requests"]}`. Delete in bounded batches only when status is Completed/Rejected, `expires_at <= now`, no lease/recovery is unresolved, no retention hold exists, and every referenced ERPNext document contains the matching `custom_mobile_pos_transaction_id`. A mismatch creates a hold. Never delete business documents.

- [ ] **Step 6: Migrate and run tests**

```bash
bench --site development.localhost migrate
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_idempotency
```

Expected: migration succeeds and tests PASS.

- [ ] **Step 7: Prepare idempotency for user review**

Review the intended diff, report the proposed English commit message `feat: add idempotent mobile POS mutations`, and wait for explicit commit approval.

### Task 3: Authorization, Profiles, and Bootstrap

**Status:** **Complete** ✅ (`feat: add mobile POS authz, sessions, customers, and catalog` — commit `3c5194b`)

**Files:**
- Create: `roti_ropi_pos/mobile_pos/authorization.py`
- Create: `roti_ropi_pos/mobile_pos/auth_hook.py`
- Create: `roti_ropi_pos/mobile_pos/profiles.py`
- Create: `roti_ropi_pos/mobile_pos/sessions.py`
- Create: `roti_ropi_pos/api/v1/bootstrap.py`
- Create: `roti_ropi_pos/fixtures/role.json`
- Create: `roti_ropi_pos/fixtures/custom_docperm.json`
- Create: `roti_ropi_pos/tests/test_authentication.py`
- Create: `roti_ropi_pos/tests/test_bootstrap.py`
- Modify: `roti_ropi_pos/hooks.py`

**Interfaces:**
- Consumes: `frappe.session.user`, POS Profile, User roles, and core permissions.
- Produces: `validate_mobile_api_scope()`, `mobile_pos_endpoint`, `require_authenticated_user()`, `require_pos_invoice_mode()`, `get_authorized_profile(name)`, `require_doc_permission(doctype, permission_type, doc=None)`, `profile_dto(doc)`, `get_current_opening(profile)`, `opening_dto(doc)`, and `bootstrap.get(pos_profile=None)`.

- [ ] **Step 1: Write failing cross-user, cross-company, Guest, role, and bootstrap tests**

Create two companies and two cashiers with explicitly assigned profiles. Verify unassigned profiles are never returned. Assign only `Mobile POS Cashier` and the exact Custom DocPerm fixtures. Prove the role, fixture matrix, profile authorization, bootstrap, current-opening projection, and route boundary work without broad roles, API keys, or shared users. Include known profile and document permission failures and prove they use the stable envelope; inject an unrelated exception and prove it is re-raised. Include a prior-day submitted Open entry and prove bootstrap returns its posting date, opening timestamp, and `STALE_OPENING` warning only after POS Opening Entry read permission succeeds. Do not claim Tasks 4-8 business operations work in this task; Task-specific tests and Task 9 provide that evidence.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_authentication
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_bootstrap
```

Expected: FAIL because authorization and bootstrap modules do not exist.

- [ ] **Step 3: Implement profile eligibility and core permission checks**

```python
def require_authenticated_user() -> str:
    if frappe.session.user == "Guest":
        raise frappe.PermissionError("Authentication is required.")
    return frappe.session.user


def get_authorized_profile(name: str):
    user = require_authenticated_user()
    try:
        profile = frappe.get_doc("POS Profile", name)
    except frappe.DoesNotExistError:
        raise MobilePOSAPIError(
            "PROFILE_SCOPE_MISMATCH",
            "The POS Profile is not available.",
            status=403,
            details={"pos_profile": name},
        )
    try:
        profile.check_permission("read")
    except frappe.PermissionError as error:
        raise MobilePOSAPIError(
            "PROFILE_SCOPE_MISMATCH",
            "The POS Profile is not available.",
            status=403,
            details={"pos_profile": name},
        ) from error
    if profile.disabled:
        raise MobilePOSAPIError(
            "PROFILE_SCOPE_MISMATCH",
            "The POS Profile is not available.",
            status=403,
            details={"pos_profile": name},
        )
    assigned = {row.user for row in profile.applicable_for_users}
    if user not in assigned:
        raise MobilePOSAPIError(
            "PROFILE_SCOPE_MISMATCH",
            "The POS Profile is not available.",
            status=403,
            details={"pos_profile": name},
        )
    return profile


def require_doc_permission(doctype: str, permission_type: str, doc=None) -> None:
    try:
        if not frappe.has_permission(doctype, ptype=permission_type, doc=doc):
            raise frappe.PermissionError
    except frappe.PermissionError as error:
        raise MobilePOSAPIError(
            "PERMISSION_DENIED",
            "The operation is not permitted.",
            status=403,
        ) from error
```

Catch only known `frappe.PermissionError` failures when mapping authorization errors. Unknown exceptions must propagate to the request-ID logger and native HTTP 500 handling.

Implement capabilities by checking the exact `Mobile POS Cashier` role, endpoint scope, selected authorized profile, shared current opening, and `require_doc_permission` for each DocType/action. Return no unrestricted POS Profile fields. Read POS Settings and return `UNSUPPORTED_POS_MODE` unless `invoice_type` is `POS Invoice`.

- `open_session` requires a selected authorized profile, no active opening, and POS Opening Entry create/submit permission.
- `submit_sale` requires a selected authorized profile, an active submitted/unclosed opening, and POS Invoice create/submit permission.
- `create_return` requires a selected authorized profile, an active submitted/unclosed opening, and POS Invoice read/create/submit permission; source visibility remains endpoint-specific.
- `cancel_sale` is always false.
- `close_session` requires a selected authorized profile, an active submitted/unclosed opening, and POS Closing Entry create/submit permission.
- With no selected profile, every mutation capability is false.

Do not advertise a mutation capability that would immediately fail a server-known prerequisite.

Implement `mobile_pos_endpoint` as the common inner decorator for every v1 endpoint. Before endpoint logic it verifies the enabled user, `Mobile POS Cashier`, Bearer/client boundary, and `require_pos_invoice_mode()`. This guarantees sessions, customers, catalog, sales, returns, and closing all return the same stable `UNSUPPORTED_POS_MODE` error rather than checking only bootstrap or sale.

Implement the read-only current-opening service in `mobile_pos/sessions.py`:

```python
def get_current_opening(profile):
    name = frappe.db.get_value(
        "POS Opening Entry",
        {
            "user": frappe.session.user,
            "pos_profile": profile.name,
            "company": profile.company,
            "docstatus": 1,
            "status": "Open",
            "pos_closing_entry": ["is", "not set"],
        },
        "name",
        order_by="period_start_date desc",
    )
    if not name:
        return None
    opening = frappe.get_doc("POS Opening Entry", name)
    require_doc_permission("POS Opening Entry", "read", doc=opening)
    return opening
```

Do not add a calendar-date filter. `bootstrap.get` and later session endpoints must use this shared service.

`opening_dto(doc)` returns `posting_date`, `period_start_date`, and `warnings`. Compare the site-timezone calendar date of `period_start_date` with the current site date. When the opening date is earlier, include exactly:

```python
{
    "code": "STALE_OPENING",
    "message": "The current POS opening started on an earlier calendar day.",
    "details": {
        "opening_date": opening_date,
        "server_date": server_date,
    },
}
```

The warning is informational. Do not introduce a maximum shift-duration policy.

- [ ] **Step 4: Add the dedicated mobile role and enforce its route boundary**

```python
MOBILE_POS_PATHS = {
    "/api/method/roti_ropi_pos.api.v1.bootstrap.get",
    "/api/method/roti_ropi_pos.api.v1.sessions.current",
    "/api/method/roti_ropi_pos.api.v1.sessions.open",
    "/api/method/roti_ropi_pos.api.v1.customers.search",
    "/api/method/roti_ropi_pos.api.v1.catalog.search",
    "/api/method/roti_ropi_pos.api.v1.catalog.scan",
    "/api/method/roti_ropi_pos.api.v1.catalog.quote_item",
    "/api/method/roti_ropi_pos.api.v1.sales.submit",
    "/api/method/roti_ropi_pos.api.v1.sales.get",
    "/api/method/roti_ropi_pos.api.v1.sales.list",
    "/api/method/roti_ropi_pos.api.v1.sales.create_return",
    "/api/method/roti_ropi_pos.api.v1.closing.preview",
    "/api/method/roti_ropi_pos.api.v1.closing.submit",
    "/api/method/roti_ropi_pos.api.v1.closing.status",
}

MOBILE_POS_BROWSER_PATHS = {
    "/api/method/login",
    "/api/method/frappe.integrations.oauth2.authorize",
    "/api/method/frappe.integrations.oauth2.approve",
}

MOBILE_POS_TOKEN_PATHS = {
    "/api/method/frappe.integrations.oauth2.get_token",
}


def validate_mobile_oauth_request(path: str, user: str) -> None:
    mobile_client_id = frappe.conf.get("mobile_pos_oauth_client_id")
    client_id = frappe.form_dict.get("client_id")
    is_mobile_client = bool(mobile_client_id and client_id == mobile_client_id)
    is_mobile_cashier = user != "Guest" and "Mobile POS Cashier" in frappe.get_roles(user)
    command = frappe.form_dict.get("cmd")
    is_login_submit = path == "/api/method/login" and command == "login"
    if command and (is_mobile_client or is_mobile_cashier) and not is_login_submit:
        raise frappe.PermissionError("Legacy command dispatch is not allowed.")
    if not is_mobile_client:
        return
    if path not in MOBILE_POS_BROWSER_PATHS | MOBILE_POS_TOKEN_PATHS:
        raise frappe.PermissionError("Alternate OAuth dispatch is not allowed.")
    if path in {
        "/api/method/frappe.integrations.oauth2.authorize",
        "/api/method/frappe.integrations.oauth2.approve",
    }:
        if not frappe.form_dict.get("code_challenge") or frappe.form_dict.get("code_challenge_method") != "S256":
            raise frappe.AuthenticationError("Mobile POS requires PKCE S256.")
    if path in MOBILE_POS_TOKEN_PATHS:
        authorization = frappe.get_request_header("Authorization", "")
        if frappe.form_dict.get("client_secret") or authorization.lower().startswith("basic "):
            raise frappe.AuthenticationError("Mobile POS is a public OAuth client.")


def validate_mobile_api_scope() -> None:
    path = frappe.request.path.rstrip("/")
    user = frappe.session.user
    validate_mobile_oauth_request(path, user)
    if path in MOBILE_POS_PATHS:
        auth_type, separator, access_token = frappe.get_request_header("Authorization", "").partition(" ")
        if auth_type.lower() != "bearer" or not separator or not access_token:
            raise frappe.AuthenticationError("OAuth bearer authentication is required.")
        token = frappe.db.get_value(
            "OAuth Bearer Token",
            access_token,
            ["client", "user", "status"],
            as_dict=True,
        )
        if (
            not token
            or token.client != frappe.conf.get("mobile_pos_oauth_client_id")
            or token.user != user
            or token.status != "Active"
            or not frappe.db.get_value("User", user, "enabled")
            or "Mobile POS Cashier" not in frappe.get_roles(user)
            or path not in MOBILE_POS_PATHS
        ):
            raise frappe.AuthenticationError("The Mobile POS bearer token is not authorized.")
        return
    if user != "Guest" and "Mobile POS Cashier" in frappe.get_roles(user) and path not in MOBILE_POS_BROWSER_PATHS:
        frappe.throw("This account may access only the Mobile POS API.", frappe.PermissionError)
```

Register the auth hook and exported `Mobile POS Cashier` Role/Custom DocPerm fixtures. Set `Mobile POS Cashier.desk_access = 0` explicitly; dedicated cashier Users are `Website User` accounts and must not inherit `Desk User`. Required apps were already activated and verified before Task 2's migration. Provision a public OAuth Client per site with Authorization Code, response Code, token auth method None, scope `all`, `skip_authorization = 0`, `allowed_roles = Mobile POS Cashier`, approved redirect URI, and no secret issued or distributed to Android. Store its client ID in site config `mobile_pos_oauth_client_id`. Enforce `code_challenge_method=S256` and a non-empty challenge on both authorize and approve because installed Frappe accepts weaker paths. Any request carrying that client ID is rejected unless its literal decoded path is an approved OAuth endpoint; `/api/v2/method`, generic `/api/method`, and legacy `cmd` dispatch cannot substitute for it. Token exchange and refresh reject Basic auth and `client_secret`. Test login/authorize/approve/token/refresh, state/redirect/verifier failures, disabled users, wrong OAuth client, cookie/API-key/Basic attempts, legacy `cmd`, v2/encoded/generic route bypasses, and absence of distributed secrets. Android logout clears local tokens; server revocation is an authenticated manager Desk operation until a no-secret public-client revocation flow is separately verified.

The Custom DocPerm fixture grants exactly: Account select; POS Profile read; POS Opening Entry read/create/write/submit; POS Invoice read/create/write/submit; POS Closing Entry read/create/write/submit; Customer read; and Item read. Account select is required by installed ERPNext `get_party_account()` while building authoritative POS Invoice defaults; generic Account routes remain blocked by the exact Mobile POS route allowlist. It grants no cancel, delete, amend, report, export, import, or share rights, no Sales Invoice access, and no direct Mobile POS Request access. Any additional permission requires a failing integration test that identifies the exact DocType; never substitute a broad ERPNext role.

Frappe's automatic `All` role and its exact standard POS Invoice permlevel-1 read row are preserved. This field-level read does not authorize generic API or resource access; exact route denial and safe, server-owned DTOs remain mandatory.

The committed Custom DocPerm rows are a reviewed snapshot of the standard permission matrix from Frappe 16.27.1 and ERPNext 16.28.0. Every ERPNext upgrade must review these six DocTypes before migration. If the permission-matrix drift test fails, regenerate the snapshot intentionally from a clean site containing only the exact new Frappe and ERPNext versions, review the complete diff, and rerun the full permission and POS regression gates. Tests, migrations, installation, and deployment must never regenerate or accept upstream permission changes automatically.

Matching standard identities retain deterministic fixture names derived from `(parent, role, permlevel, if_owner)` across regeneration. If upstream removes an identity, fixture import and migration do not detect or clean the stale deterministic `Custom DocPerm` row, so `bench migrate` can succeed. After migration, the mandatory permission snapshot/idempotency gate must fail because the database state differs from the committed fixture. Acceptance remains blocked until explicit reviewed cleanup of that exact stale deterministic row is approved and performed. No cleanup patch is needed now because the committed baseline contained only the six cashier rows and no standard snapshot rows.

- [ ] **Step 5: Run tests and static checks**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_authentication
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_bootstrap
pre-commit run --all-files
```

Expected: all commands PASS.

- [ ] **Step 6: Prepare authorization and bootstrap for user review**

Review the intended diff, report the proposed English commit message `feat: add scoped mobile POS bootstrap`, and wait for explicit commit approval.

### Task 4: Opening Session API

**Status:** **Complete** ✅ (`feat: add mobile POS authz, sessions, customers, and catalog` — commit `3c5194b`)

**Files:**
- Modify: `roti_ropi_pos/mobile_pos/sessions.py`
- Create: `roti_ropi_pos/api/v1/sessions.py`
- Create: `roti_ropi_pos/tests/test_sessions.py`

**Interfaces:**
- Consumes: `get_authorized_profile`, shared `get_current_opening`/`opening_dto`, `execute_idempotent`, and POS Opening Entry controller.
- Produces: `open_session(profile, balances, transaction_id)`, `sessions.current`, and `sessions.open`.

- [ ] **Step 1: Write failing current/open/conflict/permission/replay tests**

Assert current session reuses the shared bootstrap lookup, derives the user and Company, and returns a prior-day Open entry with posting date, opening timestamp, and `STALE_OPENING`. Assert opening balance modes belong to the profile, core create/submit permission is enforced, replay returns one submitted Opening Entry, same-profile/different-user conflict is rejected, and same-user/different-profile conflict is rejected.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sessions
```

Expected: FAIL because the session endpoints and opening operation do not exist yet.

- [ ] **Step 3: Expose the shared current-session lookup**

Implement `sessions.current` by authorizing the selected enabled profile and calling Task 3's `get_current_opening(profile)`. Do not duplicate, hide warnings from, or weaken the shared predicate.

- [ ] **Step 4: Implement idempotent opening creation**

Build a POS Opening Entry with session user, profile Company, normalized balance rows, and normal `insert().submit()`. Accept `transaction_id`, set `custom_mobile_pos_transaction_id` before insert, and return `MutationResult` with the Opening Entry reference. Lock both profile-open and user-open conflict decisions before creation and map known core failures without suppressing unknown exceptions.

- [ ] **Step 5: Run tests**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 6: Prepare sessions for user review**

Review the intended diff, report the proposed English commit message `feat: add mobile POS opening sessions`, and wait for explicit commit approval.

### Task 4A: Customer Search and Resolution

**Status:** **Complete** ✅ (`feat: add mobile POS authz, sessions, customers, and catalog` — commit `3c5194b`)

**Files:**
- Create: `roti_ropi_pos/mobile_pos/customers.py`
- Create: `roti_ropi_pos/api/v1/customers.py`
- Create: `roti_ropi_pos/tests/test_customers.py`

**Interfaces:**
- Consumes: authorized POS Profile, Customer read permission, query text, optional selected Customer, and optional walk-in display name.
- Produces: `search_customers`, `resolve_customer`, `customer_dto`, and `customers.search`.

- [ ] **Step 1: Write failing customer search and resolution tests**

Cover name/mobile search, bounded pagination, disabled/inaccessible exclusion, empty profile Customer Groups, configured Customer Group closure, omitted-customer defaulting, explicit profile default eligibility, registered selection, bakery walk-in display name, display-name rejection for non-walk-in Customer, and zero Customer creation. Prove that missing, disabled, permission-inaccessible, and predicate-ineligible configured defaults return `PROFILE_CONFIGURATION_INVALID`. Do not create a synthetic wrong-company Customer test.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_customers
```

Expected: FAIL because customer modules do not exist.

- [ ] **Step 3: Implement permission-aware search**

Query existing enabled Customer rows through a permission-aware API, constrain fields to the contract, cap `limit` at 100, and apply deterministic ordering. Include a Customer when:
`profile.customer_groups is empty OR customer.customer_group is in the configured groups' closure`.
The closure includes each configured group and every descendant. Mark only `profile.customer` as `is_default_walk_in`. Never add a Customer Company ownership relation or call `frappe.new_doc`, `insert`, or Customer mutation methods.

- [ ] **Step 4: Implement the shared customer resolver**

First resolve `customer_name = selected_customer or profile.customer`, then apply the same checks regardless of where the name came from: the Customer exists, is enabled, passes normal read permission, and satisfies the approved profile Customer Group predicate. Do not branch around eligibility for the profile default. If the configured default is absent or fails any check, raise `PROFILE_CONFIGURATION_INVALID` with `pos_profile`, `field = "customer"`, and a stable reason. Map an invalid explicit selection to the existing non-disclosing resource/scope error contract. Accept `walk_in_customer_name` only when the eligible resolved name equals `profile.customer`, then return it for mapping to `custom_walk_in_customer_name`. Reject the field for every registered non-walk-in Customer. Quote supplies profile Company and Customer context; sale/return submission remains authoritative for Company/account/internal-party compatibility.

- [ ] **Step 5: Run tests and prepare customer work for review**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_customers
```

After the test passes, review the intended diff, report the proposed English commit message `feat: add scoped mobile customer search`, and wait for explicit commit approval.

### Task 5: Catalog, Scan, Quote, UOM, and Stock

**Status:** **Complete** ✅ (`feat: add scoped mobile POS catalog` — commit `8e0bbab`, fixes up to `1d30e11`)

**Files:**
- Create: `roti_ropi_pos/mobile_pos/catalog.py`
- Create: `roti_ropi_pos/api/v1/catalog.py`
- Create: `roti_ropi_pos/tests/test_catalog.py`

**Interfaces:**
- Consumes: authorized profile, shared customer resolver, effective ERPNext `scan_barcode`, POS catalog, item details, batch quantity, and stock availability.
- Produces: `search_items`, `scan_value`, `quote_item`, item DTOs, and the three catalog endpoints.

- [ ] **Step 1: Write failing catalog, exact-scan, bakery-UOM, batch, expiry, pagination, and scope tests**

Include an Item with `custom_default_uom_warehouse`, a matching UOM conversion, warehouse stock, active and expired batches, an unauthorized item group, and a Price Group-generated selling price list.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_catalog
```

Expected: FAIL because catalog modules do not exist.

- [ ] **Step 3: Implement strict search and DTO mapping**

Call the installed POS item search only with server-derived profile settings, cap `limit` at 100, and map its result to the contract without leaking unrestricted Item fields. Treat quantity and price as snapshots.

- [ ] **Step 4: Implement scan through the registered ERPNext method path**

```python
def scan_value(profile, value: str) -> dict:
    method_path = frappe.override_whitelisted_method("erpnext.stock.utils.scan_barcode")
    scanner = frappe.get_attr(method_path)
    result = scanner(value, {"doctype": "POS Invoice", "warehouse": profile.warehouse})
    if not result:
        raise MobilePOSAPIError(
            "RESOURCE_NOT_FOUND",
            "No item, serial number, batch, or barcode matched.",
            status=404,
            details={"resource_type": "scan_value", "name": value},
        )
    return map_scan_result(result, profile)
```

Verify in a source-contract test that `frappe.override_whitelisted_method()` returns `bakery_manufacturing.overrides.barcode_scanner.custom_scan_barcode` when both apps are installed. Never import bakery internals directly from the catalog service.

If the effective scan result contains a non-stock UOM without `conversion_factor`, add the app warning `{ "code": "MISSING_UOM_CONVERSION", "message": "The selected UOM has no conversion factor." }`. Do not depend on or parse `frappe.msgprint` text emitted by the bakery override.

- [ ] **Step 5: Implement authoritative quote calculation**

Resolve customer through `mobile_pos.customers`, then use ERPNext item details/conversion/stock/batch functions with profile company, warehouse, resolved customer, price list, currency, quantity, UOM, and selected batch. Return structured warnings and reject expired/wrong-item/wrong-warehouse batches.

- [ ] **Step 6: Run app and bakery regressions**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_catalog
bench --site development.localhost run-tests --module bakery_manufacturing.tests.test_barcode_scanner
bench --site development.localhost run-tests --module bakery_manufacturing.bakery_manufacturing.doctype.price_group.test_price_group
```

Expected: all modules PASS.

- [ ] **Step 7: Prepare catalog for user review**

Review the intended diff, report the proposed English commit message `feat: add scoped mobile POS catalog`, and wait for explicit commit approval.

### Task 6: Idempotent Sale Submission

**Status:** **Proposed**

**Files:**
- Create: `roti_ropi_pos/mobile_pos/invoices.py`
- Create: `roti_ropi_pos/api/v1/sales.py`
- Create: `roti_ropi_pos/tests/test_sales.py`

**Interfaces:**
- Consumes: authorized profile/current opening, idempotency, ERPNext POS Invoice controller, catalog quote inputs, and profile payment modes.
- Produces: `submit_sale(payload, transaction_id) -> MutationResult`, `sale_summary(doc)`, `sale_detail(doc)`, and `sales.submit`.

- [ ] **Step 1: Write failing normal sale, price-change, payment, stock, serial, batch, permissions, rollback, and concurrency tests**

Assert client financial/account fields are rejected, server values win, customer resolution follows the approved contract, underpayment creates no invoice, multiple distinct modes can fully settle, a changed accepted total creates no invoice, and twenty identical concurrent requests create one invoice.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sales
```

Expected: FAIL because invoice service and endpoint do not exist.

- [ ] **Step 3: Implement strict request parsing**

Allow only `pos_profile`, optional `customer`, optional `walk_in_customer_name`, `client_accepted_grand_total`, `items`, and `payments`. Item rows allow only identity, quantity, UOM, batch, and serial selections. Payment rows allow only distinct profile modes, amount, and reference number.

- [ ] **Step 4: Build and submit one authoritative POS Invoice**

```python
def submit_sale(payload: dict, transaction_id: str) -> MutationResult:
    profile = get_authorized_profile(payload["pos_profile"])
    require_pos_invoice_mode()
    require_current_opening(profile)
    require_doc_permission("POS Invoice", "create")
    invoice = frappe.new_doc("POS Invoice")
    invoice.pos_profile = profile.name
    invoice.company = profile.company
    customer = resolve_customer(profile, payload.get("customer"), payload.get("walk_in_customer_name"))
    invoice.customer = customer.name
    invoice.custom_walk_in_customer_name = customer.walk_in_customer_name
    invoice.custom_mobile_pos_transaction_id = transaction_id
    append_validated_items(invoice, profile, payload["items"])
    invoice.set_missing_values()
    append_validated_payments(invoice, profile, payload["payments"])
    invoice.calculate_taxes_and_totals()
    verify_fully_settled(invoice)
    verify_accepted_total(invoice, payload["client_accepted_grand_total"])
    invoice.insert()
    invoice.submit()
    return MutationResult(
        data={"sale": sale_detail(invoice)},
        reference_doctype=invoice.doctype,
        reference_name=invoice.name,
    )
```

Re-read the installed `set_missing_values` and tax-calculation sequence during implementation and adjust ordering to match core tests. `verify_fully_settled` requires authoritative `outstanding_amount == 0`; partial payment is rejected with `INVALID_PAYMENT`. Do not copy core calculations into the app.

- [ ] **Step 5: Wrap submission with idempotency**

The endpoint validates/normalizes JSON once, then supplies the server-owned operation ID and transaction UUID to the business operation. Decorator order is mandatory so Frappe registers the wrapped callable:

```python
@frappe.whitelist(methods=["POST"])
@mobile_pos_endpoint
def submit(**payload):
    validated_payload = parse_sale_request(payload)
    return execute_idempotent(
        "v1.sales.submit",
        validated_payload,
        lambda transaction_id: submit_sale(validated_payload, transaction_id),
    )
```

`mobile_pos_endpoint` composes stable error mapping with Bearer/client/user/role checks and `require_pos_invoice_mode()`. No v1 endpoint may use `api_endpoint` directly.

- [ ] **Step 6: Run app and ERPNext invoice tests**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sales
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice.test_pos_invoice
```

Expected: all tests PASS.

- [ ] **Step 7: Prepare sale submission for user review**

Review the intended diff, report the proposed English commit message `feat: submit idempotent mobile POS sales`, and wait for explicit commit approval.

### Task 7: Sale History and Returns

**Status:** **Proposed**

**Files:**
- Modify: `roti_ropi_pos/mobile_pos/invoices.py`
- Modify: `roti_ropi_pos/api/v1/sales.py`
- Modify: `roti_ropi_pos/tests/test_sales.py`

**Interfaces:**
- Consumes: scoped POS Invoice queries, ERPNext POS Invoice return mapper, and idempotency.
- Produces: `list_sales`, `get_sale`, `create_return(payload, transaction_id) -> MutationResult`, and corresponding endpoints.

- [ ] **Step 1: Write failing scope, walk-in search, partial return, return-limit, permission, consolidation, and replay tests**

Test POS Invoice-only history while proving a cashier cannot read another profile's records. Verify no Sales Invoice result or cancellation endpoint is exposed.

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sales
```

Expected: FAIL on missing history/return interfaces.

- [ ] **Step 3: Implement scoped history and detail mapping**

Use permission-aware queries plus explicit owner/profile constraints. Map `custom_walk_in_customer_name` to `walk_in_customer_name`; cap page size at 100 and use deterministic posting date/time/name ordering.

- [ ] **Step 4: Implement return through ERPNext mapping**

Call `erpnext.accounts.doctype.pos_invoice.pos_invoice.make_sales_return`, verify POS Invoice source visibility, and select source rows by the `row_id` exposed in Sale Detail. Trim and validate the required non-empty `reason`, then append it without overwriting existing remarks:

```python
return_reason = f"Mobile POS Return Reason: {reason.strip()}"
return_invoice.remarks = "\n".join(
    value for value in (return_invoice.remarks, return_reason) if value
)
```

Set requested negative quantities and payment amounts, set `custom_mobile_pos_transaction_id` before insert, recalculate, insert, and submit normally. Return `MutationResult` with the return POS Invoice reference and use `v1.sales.create_return` as the operation ID. Reject quantities beyond the remaining core-mapped quantity; do not accept a source DocType parameter and do not add a return-preview endpoint.

- [ ] **Step 5: Run tests**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 6: Prepare history and returns for user review**

Review the intended diff, report the proposed English commit message `feat: add mobile POS history and returns`, and wait for explicit commit approval.

### Task 8: Closing Preview, Submit, and Status

**Status:** **Proposed**

**Files:**
- Create: `roti_ropi_pos/mobile_pos/closing.py`
- Create: `roti_ropi_pos/overrides/__init__.py`
- Create: `roti_ropi_pos/overrides/pos_closing_entry.py`
- Create: `roti_ropi_pos/api/v1/closing.py`
- Create: `roti_ropi_pos/tests/test_closing.py`
- Modify: `roti_ropi_pos/hooks.py`

**Interfaces:**
- Consumes: authorized profile/opening, permission-aware invoice set, Opening Entry balances, Closing Entry controller, and idempotency.
- Produces: `MobilePOSClosingEntry`, `ensure_committed_closing_job`, `preview_closing`, `submit_closing`, `closing_status`, and three closing endpoints.

- [ ] **Step 1: Write failing preview, balance, stale invoice, sync, queued, failed, scope, permission, and replay tests**

Cover fewer than ten and at least ten POS Invoice child rows, because installed ERPNext chooses synchronous versus queued consolidation at that threshold. Patch enqueue in the automated boundary test because `frappe.in_test` executes the job immediately; reserve real worker polling for staging.

- [ ] **Step 2: Run tests and verify failure**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_closing
```

Expected: FAIL because closing modules do not exist.

- [ ] **Step 3: Implement server-derived preview**

Lock/read the current user's opening, derive its period/profile, retrieve submitted eligible invoices, aggregate taxes and payments, and combine sales amounts with actual Opening Entry balance rows. Never accept invoice names, user, start, or end from Android.

- [ ] **Step 4: Implement recoverable Closing Entry submission**

Implement the closing exception protocol from `idempotency-and-recovery.md` using operation ID `v1.closing.submit`: commit a leased `Processing` request first; lock the Opening Entry; set `custom_mobile_pos_transaction_id` on one Draft Closing Entry before insert; insert and commit the Draft plus its request reference; set/commit phase `SubmitStarted`; submit that exact draft; verify the reference and transaction ID; then reconcile persisted core state and complete the request. An unexpired lease returns `REQUEST_IN_PROGRESS`; an expired lease resumes an interrupted Draft once or completes from Queued/Submitted/Failed state. On a known submit error, call `frappe.db.rollback()`, reload/lock request and closing, verify the persisted document is still Draft, then store/commit the stable `Rejected` response. If reload finds Queued, Submitted, or Failed, reconcile it instead. This prevents submit-side writes from leaking into a rejection commit and prevents replay loops. This explicit commit protocol is limited to closing because installed ERPNext itself commits or enqueues during submit.

- [ ] **Step 5: Defer queued consolidation until after commit**

```python
class MobilePOSClosingEntry(POSClosingEntry):
    def on_submit(self):
        if len(self.pos_invoices) < 10:
            return super().on_submit()
        self.set_status(update=True, status="Queued")
        self.update_sales_invoices_closing_entry()
        closing_name = self.name
        frappe.db.after_commit.add(lambda: ensure_committed_closing_job(closing_name))
        frappe.publish_realtime(
            f"poe_{self.pos_opening_entry}",
            message={"operation": "Closed", "doc": self},
            docname=f"POS Opening Entry/{self.pos_opening_entry}",
        )


def ensure_committed_closing_job(closing_name: str) -> None:
    closing = frappe.get_doc("POS Closing Entry", closing_name)
    if closing.docstatus != 1 or closing.status != "Queued":
        return
    consolidate_pos_invoices(closing_entry=closing)
```

Register `override_doctype_class = {"POS Closing Entry": "roti_ropi_pos.overrides.pos_closing_entry.MobilePOSClosingEntry"}` after verifying no installed app already overrides that controller. The callback invokes only core's consolidation orchestrator on a database-confirmed submitted document; it never calls `create_merge_logs` directly. Use core's deterministic job ID to suppress duplicate enqueue. Add an app test that commits a submitted Closing Entry before the enqueue spy is called, plus a source-contract test covering core `on_submit` changes.

- [ ] **Step 6: Implement scoped polling**

Map core Closing Entry and merge state to `draft`, `queued`, `submitted`, `failed`, or `cancelled`. Failed state returns only `{ "code": "CLOSING_FAILED", "message": "Closing failed. A manager must review it in ERPNext." }`; it never exposes raw `error_message`. V1 has no mobile retry endpoint, and polling never mutates data.

- [ ] **Step 7: Run app and ERPNext closing tests**

```bash
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_closing
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_closing_entry.test_pos_closing_entry
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice_merge_log.test_pos_invoice_merge_log
```

Expected: all modules PASS.

- [ ] **Step 8: Prepare closing for user review**

Review the intended diff, report the proposed English commit message `feat: add mobile POS closing workflow`, and wait for explicit commit approval.

### Task 9: Backend End-to-End Security, Upgrade, and Release Gate

**Status:** **Proposed**

**Files:**
- Create: `roti_ropi_pos/tests/test_mobile_pos_flow.py`
- Create: `roti_ropi_pos/tests/test_source_contracts.py`
- Modify: `README.md`
- Modify: `docs/mobile-pos/*.md` whenever executable evidence justifies a status/source update or verified behavior differs from the proposal.

**Interfaces:**
- Consumes: all v1 endpoints and installed hooks.
- Produces: executable evidence for one complete POS lifecycle and documented operational setup.

- [ ] **Step 1: Write the end-to-end lifecycle test**

Exercise OAuth bearer bootstrap and prior-day stale-opening warning using an existing Open fixture. Continue the lifecycle with that opening, or close it before testing creation of a new opening; never attempt to open a second session while the stale opening remains Open. Then exercise customer search/default walk-in selection, catalog search, bakery batch-UOM scan, quote, fully settled multi-mode sale, lost-response replay, history, partial return with preserved and appended remarks, closing preview, closing submit, and final status using one cashier with only `Mobile POS Cashier`.

- [ ] **Step 2: Write source-contract tests**

Assert installed callable signatures, effective barcode override behavior, required POS document fields, POS Invoice mode, core synchronous/queued closing threshold assumptions, internal closing commit behavior, and Frappe auth-hook/override dispatch behavior. Fail with a message naming the source boundary that must be re-audited.

- [ ] **Step 3: Run the complete backend gate**

```bash
bench --site development.localhost migrate
bench --site development.localhost run-tests --app roti_ropi_pos
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_authentication
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_idempotency
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sessions
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_customers
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_catalog
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_sales
bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_closing
bench --site development.localhost run-tests --module bakery_manufacturing.tests.test_barcode_scanner
bench --site development.localhost run-tests --module bakery_manufacturing.bakery_manufacturing.doctype.price_group.test_price_group
bench --site development.localhost run-tests --module erpnext.tests.test_point_of_sale
bench --site development.localhost run-tests --module erpnext.stock.tests.test_utils
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_opening_entry.test_pos_opening_entry
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice.test_pos_invoice
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_closing_entry.test_pos_closing_entry
bench --site development.localhost run-tests --module erpnext.accounts.doctype.pos_invoice_merge_log.test_pos_invoice_merge_log
bench --site development.localhost run-tests --module frappe.tests.test_frappe_client
bench --site development.localhost run-tests --module frappe.tests.test_oauth20
pre-commit run --all-files
```

Before Task 9 execution, verify every exact module path against the installed source. A missing or renamed suite is a hard stop requiring source-contract review; do not guess a replacement path. Expected: every verified command exits 0 with no failed tests or hooks.

- [ ] **Step 4: Perform staging API smoke tests**

Use a dedicated staging cashier and OAuth Authorization Code with PKCE S256. Record request IDs and ERPNext document names for bootstrap, customer search, open, scan, submit, replay, return, close, and status. Verify that a prior-day submitted/unclosed opening remains visible with `posting_date`, `period_start_date`, and `STALE_OPENING`. With developer mode disabled and active workers, close at least ten POS Invoice rows and record the real `queued` to `submitted` transition. Confirm the bearer token is denied from core method/resource routes and that no tokens, verifiers, authorization codes, or stack traces appear in logs.

- [ ] **Step 5: Update implementation status in the documents**

Update evidence status whenever new executable or installed-source evidence justifies it and add exact source references. When verified behavior differs from the proposal, record the deviation and fail the release gate pending an explicit contract decision. Preserve approved Phase 0 decisions; never rewrite an Approved invariant merely to match an accidental implementation, and version approved breaking changes as v2.

- [ ] **Step 6: Prepare release evidence and documentation for user review**

Review the intended diff, report the proposed English commit message `test: verify mobile POS lifecycle`, and wait for explicit commit approval.

## Backend Implementation Acceptance Criteria

- **Proposed**: App-owned v1 methods expose the contracted opening, catalog/scan, sale, history, return, closing, and recovery lifecycle for a separately implemented client.
- **Proposed**: OAuth Authorization Code with PKCE S256 works without a client secret, API key, shared user, or administrator credential.
- **Proposed**: The lifecycle passes with only `Mobile POS Cashier` and exact Custom DocPerm fixtures; no Sales Manager role is assigned.
- **Proposed**: Customer search selects existing records, omitted selection uses the default walk-in Customer, bakery display name is scoped correctly, and no Customer is auto-created.
- **Proposed**: Every submitted MVP invoice has zero outstanding amount; multiple payment modes are accepted only for full settlement.
- **Proposed**: All identity/profile/company/warehouse scope is derived and verified server-side.
- **Proposed**: ERPNext performs normal insert/submit validation and all business side effects; cashier correction uses the normal return mapper.
- **Proposed**: Duplicate mutation attempts cannot create duplicate ERPNext documents.
- **Proposed**: Stable envelopes and error codes match `api-contract.md`.
- **Proposed**: No core files, Price Group sidebar implementation, Android code, production deployment, or unrelated app files are changed by backend execution.
- **Approved**: Android credential storage, networking, DTOs, local recovery, WorkManager, XML Views, ViewBinding, accessibility, compatibility, performance, and UI work require a separate approved plan at `/Users/rotiropi/DockerERPNext/POSERPNext/docs/mobile-pos/implementation-plan.md`.
- **Verified**: That Android plan does not currently exist.
- **Approved**: Backend completion alone does not establish final Mobile POS delivery. Final delivery requires both the completed backend plan and the separately approved and completed Android plan.

## Execution Handoff

- **Proposed**: Recommended execution is subagent-driven development with one fresh implementer and two-stage review per task.
- **Proposed**: Inline execution is also valid when performed with the executing-plans workflow and review checkpoints after each task.
- **Approved**: Phase 0 decisions are complete. Do not start Backend Phase 1 without a new explicit user instruction.
- **Approved**: Backend authorization never authorizes Android implementation, commit, push, deployment, or production migration.
