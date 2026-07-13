from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask
from backend.platform.delivery import DeliveryStatus
from backend.shared.services.base import NotFoundError, ValidationError

RETRYABLE_ADMIN_STATUSES = {
    DeliveryStatus.retryable_failed.value,
    DeliveryStatus.permanent_failed.value,
}
CANCELLABLE_STATUSES = {
    DeliveryStatus.pending.value,
    DeliveryStatus.retryable_failed.value,
    DeliveryStatus.permanent_failed.value,
    DeliveryStatus.uncertain.value,
}


async def list_task_occurrences(session, task_id, *, limit: int = 10):
    result = await session.execute(
        select(ScheduledMessageLog)
        .where(ScheduledMessageLog.task_id == task_id)
        .order_by(ScheduledMessageLog.id.desc())
        .limit(limit)
    )
    return tuple(result.scalars().all())


async def retry_occurrence(session, occurrence_id: int, chat_id: int) -> None:
    occurrence = await _load_for_update(session, occurrence_id, chat_id)
    if occurrence.status not in RETRYABLE_ADMIN_STATUSES:
        raise ValidationError("只有明确失败的执行记录可以直接重试")
    _reset_for_replay(occurrence)


async def cancel_occurrence(session, occurrence_id: int, chat_id: int) -> None:
    occurrence = await _load_for_update(session, occurrence_id, chat_id)
    if occurrence.status not in CANCELLABLE_STATUSES:
        raise ValidationError("当前状态不允许取消")
    occurrence.status = DeliveryStatus.cancelled.value
    occurrence.next_retry_at = None
    occurrence.lease_until = None
    occurrence.completed_at = dt.datetime.now(dt.UTC)
    occurrence.success = False


async def replay_uncertain_occurrence(session, occurrence_id: int, chat_id: int) -> int:
    source = await _load_for_update(session, occurrence_id, chat_id)
    if source.status != DeliveryStatus.uncertain.value:
        raise ValidationError("只有不确定状态需要确认重放")
    replay = ScheduledMessageLog(
        task_id=source.task_id,
        chat_id=source.chat_id,
        run_key=f"replay:{source.id}:{uuid.uuid4().hex}",
        scheduled_for=source.scheduled_for,
        content_snapshot=dict(source.content_snapshot),
        status=DeliveryStatus.pending.value,
        attempt_count=0,
    )
    session.add(replay)
    await session.flush()
    return int(replay.id)


async def load_task_for_history(session, chat_id: int, task_key: str):
    statement = select(ScheduledMessageTask).where(
        ScheduledMessageTask.chat_id == chat_id,
        ScheduledMessageTask.short_id == task_key,
    )
    result = await session.execute(statement)
    task = result.scalar_one_or_none()
    if task is None:
        raise NotFoundError("定时消息任务不存在")
    return task


async def _load_for_update(session, occurrence_id: int, chat_id: int):
    result = await session.execute(
        select(ScheduledMessageLog)
        .where(ScheduledMessageLog.id == occurrence_id, ScheduledMessageLog.chat_id == chat_id)
        .with_for_update()
    )
    occurrence = result.scalar_one_or_none()
    if occurrence is None:
        raise NotFoundError("执行记录不存在")
    return occurrence


def _reset_for_replay(occurrence: ScheduledMessageLog) -> None:
    occurrence.status = DeliveryStatus.pending.value
    occurrence.next_retry_at = None
    occurrence.lease_until = None
    occurrence.send_started_at = None
    occurrence.completed_at = None
    occurrence.error_code = None
    occurrence.error_message = None
    occurrence.success = None
    occurrence.attempt_count = 0
