# Phase 2 Idempotency Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Backend Phase 2 gaps with real concurrent database evidence, bounded duplicate-contender resolution, and cleanup guards for every unresolved recovery state.

**Architecture:** Keep standard mutations atomic inside Frappe's request transaction. A unique `scope_key` serializes first use; a loser performs a bounded latest-state locking read and either replays, reports a hash conflict, or returns retryable in-progress. Cleanup remains a bounded app-owned control-record deletion that excludes all leased or recovery-phased rows.

**Tech Stack:** Python 3.14, Frappe 16.27.1, ERPNext 16.28.0, MariaDB, `IntegrationTestCase`, `threading`, Ruff, pre-commit.

## Global Constraints

- Never edit `apps/frappe` or `apps/erpnext`.
- Do not add dependencies; use Python standard library, Frappe, and MariaDB.
- Do not call `frappe.db.commit()` inside `execute_idempotent`.
- `ignore_permissions=True` remains limited to `Mobile POS Request`; ERPNext business documents use normal permissions.
- Preserve operation IDs, response envelopes, HTTP 201/200 behavior, canonical hashing, and 90-day retention.
- Do not implement the Backend Phase 7 closing recovery executor.
- Local per-task commits are authorized only on branch `worktree-phase6-prerequisite-closure`; do not push, merge, migrate, or begin a later phase without separate explicit user approval.
- Run every `bench` command inside `frappe_docker_devcontainer-frappe-1` from `/workspace/development/frappe-bench`.

## File Map

| Path | Responsibility |
| --- | --- |
| `roti_ropi_pos/mobile_pos/idempotency.py` | Bounded conflict resolution and cleanup eligibility |
| `roti_ropi_pos/tests/test_idempotency.py` | Unit, transactional, cleanup, and true-concurrency evidence |
| `roti_ropi_pos/tests/helpers.py` | Existing test data only; modify only if the concurrency test proves a reusable connection helper is required |

---

### Task 1: Bounded Duplicate-Contender Resolution

**Files:**
- Modify: `roti_ropi_pos/mobile_pos/idempotency.py:18-245`
- Test: `roti_ropi_pos/tests/test_idempotency.py:184-192`

**Interfaces:**
- Consumes: `scope_key: str`, `request_hash: str`, `operation_id: str`.
- Produces: `_resolve_committed_request(scope_key: str, request_hash: str, operation_id: str) -> dict`; returns a replay response or raises a stable Mobile POS error.
- Preserves: `execute_idempotent(operation_id: str, validated_payload: dict, operation: Callable[[str], MutationResult]) -> dict`.

- [ ] Add failing tests for a missing-then-completed locking read, bounded Processing result, hash mismatch, and missing-row exhaustion. Mock `time.sleep`; assert all `_get_existing_request` calls use `for_update=True`.
- [ ] Run focused tests; expect RED because resolver/constants do not exist.
- [ ] Add `time`, `CONFLICT_RESOLUTION_ATTEMPTS = 5`, `CONFLICT_RESOLUTION_DELAY_SECONDS = 0.05`; extend `_get_existing_request(scope_key, *, for_update=False)`; implement bounded resolver exactly as approved design.
- [ ] Replace duplicate insert branch with rollback-to-savepoint plus `_resolve_committed_request`; no commit inside executor.
- [ ] Run full `roti_ropi_pos.tests.test_idempotency`; expect GREEN.
- [ ] Commit locally with `fix: resolve concurrent mobile POS requests` plus required co-author trailer.

### Task 2: True Concurrent Business-Reference Evidence

**Files:**
- Modify: `roti_ropi_pos/tests/test_idempotency.py`
- Modify only if proved necessary: `roti_ropi_pos/tests/helpers.py`

**Interfaces:**
- Consumes: `execute_idempotent`, `open_session`, authorized POS Profile, independent Frappe thread-local connections.
- Produces: one test proving twenty simultaneous identical logical mutations create one submitted POS Opening Entry and one completed Mobile POS Request.

- [ ] Add private worker using `ThreadPoolExecutor`, `Barrier(20)`, `frappe.init(site=...)`, `frappe.connect()`, per-thread `frappe.set_user`, commit on success, rollback on error, and `frappe.destroy()`.
- [ ] Add concurrent test using one cashier/profile/key. Assert one business document, one request, one first success; bounded contenders may return only replay or `REQUEST_IN_PROGRESS`, and every in-progress result must replay same reference on a later retry.
- [ ] Run focused test; capture RED or validate sensitivity by temporarily forcing immediate in-progress, then restore.
- [ ] Make only evidence-driven changes: locking reads, <=1 second bounded wait, known duplicate exceptions. No global lock, no executor commit, no sequential substitute.
- [ ] Run concurrent test three times and full idempotency module; expect stable GREEN.
- [ ] Commit locally with `test: verify concurrent mobile POS idempotency` plus required co-author trailer.

### Task 3: Cleanup Lease and Recovery Guards

**Files:**
- Modify: `roti_ropi_pos/mobile_pos/idempotency.py:248-296`
- Test: `roti_ropi_pos/tests/test_idempotency.py:194-281`

**Interfaces:**
- Produces: `_is_cleanup_candidate(request, now) -> bool` and safe `delete_expired_requests(batch_size=100) -> int`.

- [ ] Add failing tests preserving expired terminal row with active lease and expired terminal row with nonblank recovery phase; keep eligible blank-phase/blank-lease deletion proof.
- [ ] Run focused tests; expect RED.
- [ ] Implement predicate requiring terminal due unheld row with blank lease and blank phase. Lock/reload each candidate before predicate. Expired lease remains unresolved and preserved.
- [ ] Run full idempotency module; expect GREEN.
- [ ] Commit locally with `fix: preserve unresolved mobile POS requests` plus required co-author trailer.

### Task 4: Phase 2 Verification Gate

**Files:** Review only.

- [ ] Run idempotency module and full app gate in container.
- [ ] Run `pre-commit run --all-files` and `git diff --check`.
- [ ] Audit no executor commit, no core edits, true 20-worker evidence, one reference/request, safe cleanup, and no business document deletion.
- [ ] Write evidence report. No code commit unless verification itself requires an approved test-only correction.
