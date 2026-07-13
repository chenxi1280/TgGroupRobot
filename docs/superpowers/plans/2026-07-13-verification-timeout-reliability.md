# Verification Timeout Reliability Implementation Plan

> **Execution:** Implement inline with test-driven development. Keep unrelated worktree changes unstaged.

**Goal:** Replace loss-prone verification timeout claims with a durable, operator-visible state machine that distinguishes retryable, permanent, uncertain, successful, and cancelled outcomes.

**Architecture:** Keep the generic state/outcome/backoff primitives in the platform delivery layer. Keep verification-specific claim/finalize queries in a repository and inject a Telegram action executor into the worker. Persist the action snapshot before any Telegram call. `timeout_handled` remains a compatibility field and becomes true only after successful completion or an explicit no-action terminal outcome.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, python-telegram-bot 21.6, PostgreSQL, pytest

---

### Task 1: Align product and data contracts

**Files:**
- Modify: `docs/product/TgGroupRobot_PRD.md`
- Modify: `.planning/full_closure_20260713/findings.md`

- [x] Document all timeout states and the compatibility meaning of `timeout_handled`.
- [x] Document retry, uncertain, cancel, and explicit replay operations.
- [x] Document that an expired admin-review challenge is not automatically punished and reaches a successful no-action terminal state.
- [x] Verify the new wording with `rg`.

### Task 2: Add shared delivery primitives with RED/GREEN

**Files:**
- Create: `backend/platform/delivery/__init__.py`
- Create: `backend/platform/delivery/models.py`
- Create: `backend/platform/delivery/retry.py`
- Create: `tests/test_delivery_models.py`

- [x] Add failing tests for the seven persisted statuses and four immutable outcome kinds.
- [x] Add failing tests for bounded exponential retry scheduling.
- [x] Run the focused tests and verify failures are caused by missing production interfaces.
- [x] Implement immutable enums/outcomes and pure retry calculation under the 50-line limit.
- [x] Run focused tests and verify GREEN.

### Task 3: Extend the verification persistence contract with RED/GREEN

**Files:**
- Modify: `backend/platform/db/schema/models/moderation.py`
- Modify: `backend/platform/db/schema/models/__init__.py`
- Modify: `backend/platform/db/schema/models/core.py`
- Modify: `backend/platform/db/runtime/startup_migrations.py`
- Modify: `backend/platform/db/runtime/schema_gate.py`
- Modify: `tests/test_startup_schema_migrations.py`
- Create: `tests/test_verification_timeout_model.py`

- [x] Add failing model tests for status, action, attempts, retry time, lease, send-start, last error, completion, and replay lineage fields.
- [x] Add failing compatibility migration and required-index tests.
- [x] Verify RED.
- [x] Add ORM fields and a claim index without redundant single-column indexes.
- [x] Add idempotent compatibility SQL that maps legacy handled rows to `succeeded` and others to `pending`.
- [x] Run focused schema/model tests and verify GREEN.

### Task 4: Build the injected executor and repository with RED/GREEN

**Files:**
- Create: `backend/features/verification/timeout_executor.py`
- Create: `backend/features/verification/timeout_repository.py`
- Create: `backend/features/verification/timeout_worker.py`
- Create: `tests/test_verification_timeout_executor.py`
- Create: `tests/test_verification_timeout_repository.py`

- [x] Add executor tests for success, rate-limit retryable failure, permission permanent failure, and network uncertain result.
- [x] Add repository tests for `FOR UPDATE SKIP LOCKED`, action snapshot, lease, attempt increment, and due-status filtering.
- [x] Verify RED.
- [x] Implement typed protocols, immutable plans, Telegram exception classification, and repository transitions.
- [x] Run focused tests and verify GREEN.

### Task 5: Replace the scheduler worker state machine with RED/GREEN

**Files:**
- Modify: `backend/platform/scheduler/tasks/verification_timeout_task.py`
- Modify: `tests/test_verification_runtime_flow.py`
- Create: `tests/test_verification_timeout_worker.py`

- [x] Replace tests that assert failed actions are permanently hidden.
- [x] Add failing worker tests for retryable failure, uncertain result, success ordering, scheduler health propagation, and per-item isolation.
- [x] Add failing concrete-store and scheduler-delegation tests.
- [x] Implement the concrete SQLAlchemy store and replace the legacy scheduler body with worker delegation.
- [x] Verify RED against the missing injected worker.
- [x] Implement short orchestration functions using repository and executor injection.
- [x] Ensure `timeout_handled=True` only for successful/no-action completion.
- [x] Run verification-focused tests and verify GREEN.

### Task 6: Add operator list/retry/cancel/replay operations with RED/GREEN

**Files:**
- Inspect and modify the existing verification admin menu modules under `backend/features/admin/moderation/`.
- Inspect and modify the existing web-admin routing modules under `backend/features/web_admin/`.
- Add focused menu/API tests under `tests/`.

- [x] Add tests for filtered failed/uncertain lists.
- [x] Add authorization and transition tests for retry, cancel, and confirmed uncertain replay.
- [x] Add failing service tests for filtered failed/uncertain lists and retry/cancel/confirmed-replay transitions.
- [x] Add failing Web-admin route and explicit replay-confirmation tests.
- [x] Verify RED for the new service, Telegram page, Web routes, and static UI contracts.
- [x] Implement Telegram admin-menu and Web-admin operations using the same service layer.
- [x] Run focused tests and verify GREEN.

### Task 7: Verify and commit the batch

- [x] Run all verification, delivery, schema, menu, and web-admin tests with a 60-second hard timeout.
- [x] Run the full test suite with a 60-second hard timeout.
- [x] Run `compileall`, JavaScript syntax checks, and `git diff --check`.
- [x] Review function lengths and file lengths for every new/modified file.
- [x] Update the durable acceptance matrix with exact evidence.
- [x] Stage only reviewed verification-reliability files and commit the closed batch.
