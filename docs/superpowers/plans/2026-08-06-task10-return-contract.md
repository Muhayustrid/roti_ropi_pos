# Task 10 Authoritative Return Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide an Android-ready v1 Mobile POS return workflow whose quantities, totals, refund allocation, concurrency, and replay behavior are authoritative in ERPNext.

**Architecture:** Keep the v1 adapters thin, extend the existing invoice service and decimal validator, and reuse ERPNext's POS Invoice return mapper. A read-only return quote previews calculated accounting; create-return recalculates under a source-invoice row lock and persists through the existing idempotency executor.

**Tech Stack:** Python 3.14, Frappe/ERPNext v16, MariaDB, `IntegrationTestCase`, Ruff.

## Global Constraints

- Do not modify ERPNext, Frappe, or the Android repository.
- Android submits no refund amount, payment allocation, account, rate, tax, discount, rounding, or accounting value.
- Use `return-quantity/v1` exact decimal rules and never round or truncate request values.
- `v1.sales.create_return` remains idempotent through `Mobile POS Request`.
- Rejections and rollback leave no POS Invoice or Mobile POS Request artifacts.
- All repository code, tests, documentation, branch, commit, and PR text are English.

---

### Task 1: Return projection and quantity policy

**Files:**
- Modify: `roti_ropi_pos/mobile_pos/validation.py`
- Modify: `roti_ropi_pos/mobile_pos/invoices.py`
- Test: `roti_ropi_pos/tests/test_return_task10.py`

**Interfaces:**
- Produces: `return_quantity_policy() -> dict`, `return_quantity_string(value) -> Decimal`, and additive `sale.return_contract` / `item.returnability` fields.
- Consumes: submitted POS Invoice returns linked by `return_against` and `pos_invoice_item`.

- [ ] Write failing integration tests for no prior return, one prior partial return, multiple prior returns, full return, ignored draft/cancelled returns, and exact serial/batch references.
- [ ] Run `bench --site development.localhost run-tests --module roti_ropi_pos.tests.test_return_task10` and confirm failures are missing contract fields.
- [ ] Add strict quantity parsing using effective POS Invoice Item precision and the installed decimal storage capacity.
- [ ] Aggregate submitted returned quantities once per original invoice and project exact `Decimal` strings, eligibility, rejection reasons, refund modes, and policy.
- [ ] Re-run the focused module and confirm green before continuing.

### Task 2: Authoritative return quote and refund selection

**Files:**
- Modify: `roti_ropi_pos/api/v1/sales.py`
- Modify: `roti_ropi_pos/mobile_pos/invoices.py`
- Modify: `roti_ropi_pos/mobile_pos/auth_hook.py`
- Test: `roti_ropi_pos/tests/test_return_task10.py`

**Interfaces:**
- Produces: `POST roti_ropi_pos.api.v1.sales.quote_return` and `build_return_quote(payload) -> dict`.
- Consumes payload: `source_name`, unique `source_item_row`/`qty` rows, and conditional `refund_mode` only.

- [ ] Write failing tests proving quote requires cashier/profile/opening scope, creates no artifacts, rejects malformed/excess-scale/duplicate rows, and calculates rates, discounts, taxes, rounding, positive refund amount, and one negative allocation.
- [ ] Add tests for zero modes, one auto-selected mode, multiple modes requiring selection, and disallowed selection.
- [ ] Run the new tests and confirm the expected missing-endpoint/old-contract failures.
- [ ] Add the exact auth-hook route, shared return selection parser, valid-mode resolver, ERPNext mapped calculation, and stable errors.
- [ ] Re-run the focused module and confirm all quote tests pass.

### Task 3: Locked idempotent return creation

**Files:**
- Modify: `roti_ropi_pos/api/v1/sales.py`
- Modify: `roti_ropi_pos/mobile_pos/invoices.py`
- Test: `roti_ropi_pos/tests/test_return_task10.py`

**Interfaces:**
- Produces: final `v1.sales.create_return` request without payments and a receipt-ready `return_sale` response.
- Consumes: the same row selection/refund-mode rules as quote plus required trimmed `reason`.

- [ ] Write failing tests for full/partial/exact-boundary returns, stable `RETURN_LIMIT_EXCEEDED` details, required reason, authoritative refund override prevention, and receipt fields.
- [ ] Write a different-key concurrent test whose total requested quantity exceeds the remaining quantity and assert one success, one `RETURN_LIMIT_EXCEEDED`, and one submitted return.
- [ ] Write replay, exactly-one POS Invoice/Mobile POS Request, rejection-no-artifacts, and forced-submit rollback tests.
- [ ] Run tests and confirm failures expose the old client-payment contract and missing source lock.
- [ ] Lock the original invoice with `FOR UPDATE`, recalculate after the lock, assign the server-owned refund row, submit normally, and map known limit errors without hiding unknown ERPNext failures.
- [ ] Re-run the focused module and confirm green.

### Task 4: Serial/batch permission boundary

**Files:**
- Modify: `roti_ropi_pos/fixtures/custom_docperm.json`
- Modify: `docs/mobile-pos/authentication.md`
- Test: `roti_ropi_pos/tests/test_authentication.py`
- Test: `roti_ropi_pos/tests/test_return_task10.py`

**Interfaces:**
- Produces: exact cashier permission needed for ERPNext Serial and Batch Bundle handling.
- Consumes: existing exact-route OAuth/cashier boundary; no generic bundle endpoint is exposed.

- [ ] Write failing fixture and integration tests for permitted full serialized/batch returns and rejected partial serialized return.
- [ ] Add only the proven Serial and Batch Bundle Custom DocPerm fields.
- [ ] Run authentication and return modules and confirm green.

### Task 5: Versioned contract and response-drop protocol

**Files:**
- Modify: `docs/mobile-pos/api-contract.md`
- Modify: `docs/mobile-pos/android-backend-handoff.md`
- Modify: `docs/mobile-pos/architecture.md`
- Create: `docs/mobile-pos/response-drop-return-v1.md`
- Test: `roti_ropi_pos/tests/test_source_contracts.py`

**Interfaces:**
- Produces: exact request/response/error/decimal/replay contract and staging-only `mobile-pos-response-drop/v1` return procedure.

- [ ] Update contract examples to remove client refund amounts/allocations and document `sales.quote_return`, return projections, policies, errors, and receipt fields.
- [ ] Replace the obsolete no-preview decision with the approved authoritative quote boundary.
- [ ] Document identical UUID/body hash, commit-before-drop, immediate disarm, exactly-one records, sanitized evidence, and ERPNext-safe cleanup.
- [ ] Add source-contract assertions only for executable route/operation registration boundaries, not prose text.
- [ ] Run source-contract tests and Ruff.

### Task 6: Verification, independent review, and delivery

**Files:**
- Verify all changed files; no new implementation files unless a failing test requires one.

- [ ] Run focused modules: return, sales, authentication, idempotency, mobile flow, and source contracts.
- [ ] Run full `bench --site development.localhost run-tests --app roti_ropi_pos` and `ruff check roti_ropi_pos`.
- [ ] Dispatch an independent Sol read-only review for accounting authority, cumulative limits, concurrency, idempotency, decimals, authorization, rollback, and documentation alignment.
- [ ] Fix every concrete Critical/Important finding with a failing test first and rerun verification.
- [ ] Stage only confirmed Task 10 paths, commit in English, push the requested branch, create one non-draft backend PR, address concrete CI/review findings, and merge.
- [ ] Sync backend main, record final SHA/fixture provenance, then remove only the requested Task 10 worktree and safely delete its merged local branch.
