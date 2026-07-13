from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.features.automation.scheduled_delivery_executor import ScheduledDeliveryPlan
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus, RetryPolicy, calculate_next_retry_at
from backend.shared.time_helper import calculate_next_run_time, is_time_in_window

DEFAULT_BATCH_LIMIT = 100


def build_due_occurrence_query(now: dt.datetime, *, limit: int):
    retry_due = and_(
        ScheduledMessageLog.status == DeliveryStatus.retryable_failed.value,
        ScheduledMessageLog.next_retry_at <= now,
    )
    return (
        select(ScheduledMessageLog)
        .where(or_(ScheduledMessageLog.status == DeliveryStatus.pending.value, retry_due))
        .order_by(ScheduledMessageLog.next_retry_at, ScheduledMessageLog.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_expired_occurrence_query(now: dt.datetime, *, limit: int):
    return (
        select(ScheduledMessageLog)
        .where(
            ScheduledMessageLog.status == DeliveryStatus.processing.value,
            ScheduledMessageLog.lease_until <= now,
        )
        .order_by(ScheduledMessageLog.lease_until, ScheduledMessageLog.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def recover_expired_occurrence(occurrence: ScheduledMessageLog, now: dt.datetime) -> None:
    started = occurrence.send_started_at is not None
    occurrence.status = (
        DeliveryStatus.uncertain.value if started else DeliveryStatus.retryable_failed.value
    )
    occurrence.next_retry_at = None if started else now
    occurrence.lease_until = None
    occurrence.error_code = "lease_expired_after_send" if started else "lease_expired_before_send"
    occurrence.error_message = occurrence.error_code
    occurrence.completed_at = now if started else None
    occurrence.success = False if started else None


def snapshot_task(task: ScheduledMessageTask) -> dict[str, Any]:
    return {
        "title": str(task.title or ""),
        "chat_id": int(task.chat_id),
        "delete_previous": bool(task.delete_previous),
        "last_sent_message_id": task.last_sent_message_id,
        "pin_message": bool(task.pin_message),
        "text": task.text,
        "parse_mode": task.parse_mode,
        "media_type": task.media_type,
        "media_file_id": task.media_file_id,
        "buttons": list(task.buttons or []),
    }


def finalize_occurrence(
    occurrence: ScheduledMessageLog,
    task: ScheduledMessageTask,
    outcome: DeliveryOutcome,
    *,
    now: dt.datetime,
    retry_policy: RetryPolicy,
) -> None:
    status, next_retry_at = _resolve_status(occurrence, outcome, now, retry_policy)
    occurrence.status = status.value
    occurrence.next_retry_at = next_retry_at
    occurrence.lease_until = None
    occurrence.error_code = outcome.error_code
    occurrence.error_message = outcome.message
    occurrence.completed_at = now if _is_terminal(status) else None
    occurrence.message_id = outcome.message_id
    occurrence.sent_at = now if status is DeliveryStatus.succeeded else None
    occurrence.success = _legacy_success(status)
    if status is DeliveryStatus.succeeded:
        if outcome.message_id is None:
            raise RuntimeError(f"scheduled occurrence {occurrence.id} has no message id")
        task.last_sent_message_id = int(outcome.message_id)


def _resolve_status(occurrence, outcome, now, retry_policy):
    if outcome.status is not DeliveryStatus.retryable_failed:
        return outcome.status, None
    attempts = int(occurrence.attempt_count or 0)
    next_retry_at = calculate_next_retry_at(now, attempts=attempts, policy=retry_policy)
    if next_retry_at is None:
        return DeliveryStatus.permanent_failed, None
    return DeliveryStatus.retryable_failed, next_retry_at


def _legacy_success(status: DeliveryStatus) -> bool | None:
    if status is DeliveryStatus.succeeded:
        return True
    if _is_terminal(status):
        return False
    return None


def _is_terminal(status: DeliveryStatus) -> bool:
    return status in {
        DeliveryStatus.succeeded,
        DeliveryStatus.permanent_failed,
        DeliveryStatus.uncertain,
        DeliveryStatus.cancelled,
    }


class SqlAlchemyScheduledOccurrenceStore:
    def __init__(self, db, *, retry_policy: RetryPolicy | None = None) -> None:
        self._db = db
        self._retry_policy = retry_policy or RetryPolicy()

    async def create_due_occurrences(self, now: dt.datetime) -> int:
        now_ts = int(now.timestamp())
        async with self._db.session_factory() as session:
            tasks = await _load_due_tasks(session, now_ts)
            created = 0
            for task in tasks:
                created += await _plan_task(session, task, now_ts)
            await session.commit()
        return created

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        async with self._db.session_factory() as session:
            result = await session.execute(build_expired_occurrence_query(now, limit=DEFAULT_BATCH_LIMIT))
            occurrences = tuple(result.scalars().all())
            for occurrence in occurrences:
                recover_expired_occurrence(occurrence, now)
            await session.commit()
        return len(occurrences)

    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int):
        async with self._db.session_factory() as session:
            result = await session.execute(build_due_occurrence_query(now, limit=limit))
            plans = tuple(_claim(item, lease_until) for item in result.scalars().all())
            await session.commit()
        return plans

    async def mark_send_started(self, plan: ScheduledDeliveryPlan, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            occurrence = await _load_processing(session, plan.occurrence_id)
            occurrence.send_started_at = now
            await session.commit()

    async def finalize(self, plan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            occurrence = await _load_processing(session, plan.occurrence_id)
            task = await _load_task_for_update(session, occurrence.task_id)
            finalize_occurrence(occurrence, task, outcome, now=now, retry_policy=self._retry_policy)
            await session.commit()

    async def mark_finalize_uncertain(self, plan, error: Exception, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            occurrence = await _load_processing(session, plan.occurrence_id)
            outcome = DeliveryOutcome.uncertain("database_finalize_failed", str(error))
            task = await _load_task_for_update(session, occurrence.task_id)
            finalize_occurrence(occurrence, task, outcome, now=now, retry_policy=self._retry_policy)
            await session.commit()


async def _load_due_tasks(session, now_ts: int):
    result = await session.execute(
        select(ScheduledMessageTask)
        .where(ScheduledMessageTask.enabled.is_(True), ScheduledMessageTask.next_run_at <= now_ts)
        .order_by(ScheduledMessageTask.next_run_at)
        .limit(DEFAULT_BATCH_LIMIT)
        .with_for_update(skip_locked=True)
    )
    return tuple(result.scalars().all())


async def _plan_task(session, task: ScheduledMessageTask, now_ts: int) -> int:
    if task.start_at and now_ts < task.start_at:
        task.next_run_at = task.start_at
        return 0
    if task.end_at and now_ts > task.end_at:
        task.enabled = False
        return 0
    if not is_time_in_window(now_ts, task.day_start_hour, task.day_end_hour):
        task.next_run_at = calculate_next_run_time(task, now_ts)
        return 0
    snapshot = snapshot_task(task)
    if not _snapshot_has_content(snapshot):
        task.enabled = False
        return 0
    scheduled_for = int(task.next_run_at or now_ts)
    created = await _insert_occurrence(session, task, snapshot, scheduled_for)
    task.next_run_at = calculate_next_run_time(task, now_ts)
    return created


async def _insert_occurrence(session, task, snapshot, scheduled_for: int) -> int:
    statement = (
        insert(ScheduledMessageLog)
        .values(
            task_id=task.task_id,
            chat_id=task.chat_id,
            run_key=f"{task.task_id}:{scheduled_for}",
            scheduled_for=scheduled_for,
            content_snapshot=snapshot,
            status=DeliveryStatus.pending.value,
            attempt_count=0,
        )
        .on_conflict_do_nothing(index_elements=["run_key"])
        .returning(ScheduledMessageLog.id)
    )
    result = await session.execute(statement)
    return 1 if result.scalar_one_or_none() is not None else 0


def _snapshot_has_content(snapshot: dict[str, Any]) -> bool:
    return bool(str(snapshot.get("text") or "").strip() or snapshot.get("media_file_id"))


def _claim(occurrence: ScheduledMessageLog, lease_until: dt.datetime) -> ScheduledDeliveryPlan:
    occurrence.status = DeliveryStatus.processing.value
    occurrence.attempt_count = int(occurrence.attempt_count or 0) + 1
    occurrence.next_retry_at = None
    occurrence.lease_until = lease_until
    occurrence.send_started_at = None
    occurrence.error_code = None
    occurrence.error_message = None
    occurrence.completed_at = None
    return ScheduledDeliveryPlan(
        occurrence_id=int(occurrence.id),
        task_id=str(occurrence.task_id),
        chat_id=int(occurrence.chat_id),
        snapshot=dict(occurrence.content_snapshot),
    )


async def _load_processing(session, occurrence_id: int) -> ScheduledMessageLog:
    result = await session.execute(
        select(ScheduledMessageLog)
        .where(
            ScheduledMessageLog.id == occurrence_id,
            ScheduledMessageLog.status == DeliveryStatus.processing.value,
        )
        .with_for_update()
    )
    occurrence = result.scalar_one_or_none()
    if occurrence is None:
        raise RuntimeError(f"scheduled occurrence is not processing: {occurrence_id}")
    return occurrence


async def _load_task_for_update(session, task_id) -> ScheduledMessageTask:
    result = await session.execute(
        select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise RuntimeError(f"scheduled task is missing: {task_id}")
    return task
