# Garage Forward Reliability Implementation Plan

> Scope: close garage-forward idempotency, snapshot, cursor, retry, uncertainty, and operator-recovery gaps without absorbing unrelated advertising changes.

## Task 1: Lock the product and schema contract

- [x] Add durable status, snapshot, success cursor, uncertainty, and operator replay rules to the PRD.
- [x] Add RED model/schema tests for the unique event key and required execution fields.
- [x] Update ORM, fresh SQL, startup compatibility SQL, and schema gate.

## Task 2: Make reservation and enqueue idempotent

- [x] Add RED tests proving a failed live delivery keeps its message-map placeholder.
- [x] Add RED tests proving duplicate enqueue updates one queue record with a PostgreSQL upsert.
- [x] Persist message-map id and immutable reply-markup snapshot before Telegram execution.
- [x] Remove stale-slot deletion and orphan-purge behavior.

## Task 3: Implement explicit delivery transitions

- [x] Add RED repository tests for `FOR UPDATE SKIP LOCKED`, lease recovery, send-start marking, and locked finalization.
- [x] Classify Telegram outcomes as succeeded, retryable, permanent, or uncertain.
- [x] Finalize success atomically across queue, message map, source cursor, and audit.
- [x] Keep send-started lease expirations and post-send finalization failures in `uncertain`.

## Task 4: Replace the retry task with an isolated worker

- [x] Add RED tests for button snapshot replay, per-item isolation, batch health propagation, and no automatic uncertain replay.
- [x] Introduce injected executor/repository/worker responsibilities under the hard code metrics.
- [x] Register the task without silent missing-database success.

## Task 5: Add operator recovery

- [x] Add RED service/menu tests for filtered lists, retry, cancel, and confirmed uncertain replay.
- [x] Add Telegram admin operations backed by the same state service.
- [x] Record every operator transition in the audit log.

## Task 6: Verify and commit this batch

- [x] Run focused garage, schema, scheduler, and admin tests under 60 seconds.
- [x] Run the full suite under 60 seconds.
- [x] Run compile, diff, and new-file hard-metric checks.
- [x] Update the durable acceptance matrix with exact evidence.
- [x] Stage only reviewed garage-reliability hunks and commit the closed batch.
