# Review Findings Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the confirmed runtime ownership, scheduler durability, verification transaction, and regression failures.

**Architecture:** Model startup as explicit state, treat leader ownership and persisted pause state as mandatory safety dependencies, and commit verification identity before Telegram side effects. Preserve request-scope caching through injected loaders/checkers.

**Tech Stack:** Python 3.12, asyncio, python-telegram-bot, SQLAlchemy async, PostgreSQL advisory locks, pytest, Ruff.

---

### Task 1: Runtime lifecycle and leader ownership

**Files:**
- Modify: `backend/app/runtime.py`
- Modify: `backend/platform/runtime/leader_lock.py`
- Test: `tests/test_runtime_reliability.py`

- [ ] Add tests for partial-start cleanup, lock-before-schema ordering, transaction completion, and lock-loss signaling.
- [ ] Run the focused tests and confirm they fail for the reviewed defects.
- [ ] Add explicit runtime state and leader monitoring with minimal public surface.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Scheduler durable pause

**Files:**
- Modify: `backend/platform/scheduler/core/core.py`
- Test: `tests/test_scheduler_resume_and_status.py`

- [ ] Add tests proving restore errors abort startup and auto-pause persistence errors surface.
- [ ] Run the focused tests and confirm RED.
- [ ] Make safety-critical persistence fail closed.
- [ ] Run the focused tests and confirm GREEN.

### Task 3: Verification transaction boundary

**Files:**
- Modify: `backend/features/verification/verification_handler.py`
- Test: `tests/test_verification_prompt_delivery.py`

- [ ] Add a test proving challenge commit precedes restriction and prompt send.
- [ ] Run it and confirm RED.
- [ ] Commit the challenge and prompt outcomes at their durability boundaries.
- [ ] Run the verification domain tests and confirm GREEN.

### Task 4: Regression contracts and visible failures

**Files:**
- Modify: moderation/group handler modules and affected tests
- Modify: `backend/features/web_admin/static/admin.js`

- [ ] Restore injected loader/checker seams and update only intentionally changed assertions.
- [ ] Remove the silent operations-center catch.
- [ ] Run the 29 previously failing tests until GREEN.

### Task 5: Full verification

**Files:**
- Verify all changed files and planning evidence.

- [ ] Run full pytest with a 60-second hard timeout.
- [ ] Run Ruff and repository quality checks.
- [ ] Inspect final diff and update planning status with exact evidence.
