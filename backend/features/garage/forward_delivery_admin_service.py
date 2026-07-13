from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select

from backend.platform.db.schema.models.alliance import (
    GarageForwardAuditLog,
    GarageForwardRetryQueue,
)
from backend.platform.delivery import DeliveryStatus


DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
ACTION_RETRY = "retry"
ACTION_CANCEL = "cancel"
ACTION_REPLAY = "replay_confirm"


@dataclass(frozen=True, slots=True)
class GarageTaskFilter:
    chat_id: int
    statuses: tuple[DeliveryStatus, ...]
    limit: int = DEFAULT_LIST_LIMIT

    def __post_init__(self) -> None:
        if not self.statuses:
            raise ValueError("statuses must not be empty")
        if not 1 <= self.limit <= MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")


@dataclass(frozen=True, slots=True)
class GarageTaskItem:
    id: int
    chat_id: int
    source_channel_id: int
    source_message_id: int
    status: str
    attempts: int
    last_error: str | None
    completed_at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class GarageOperation:
    delivery_id: int
    chat_id: int
    action: str
    now: dt.datetime
    confirmed: bool = False


def build_garage_task_query(filters: GarageTaskFilter):
    return (
        select(GarageForwardRetryQueue)
        .where(
            GarageForwardRetryQueue.chat_id == filters.chat_id,
            GarageForwardRetryQueue.status.in_(tuple(item.value for item in filters.statuses)),
        )
        .order_by(
            GarageForwardRetryQueue.completed_at.desc().nullslast(),
            GarageForwardRetryQueue.updated_at.desc(),
        )
        .limit(filters.limit)
    )


def build_garage_operation_query(*, delivery_id: int, chat_id: int):
    return (
        select(GarageForwardRetryQueue)
        .where(
            GarageForwardRetryQueue.id == delivery_id,
            GarageForwardRetryQueue.chat_id == chat_id,
        )
        .with_for_update()
    )


async def list_garage_tasks(session, filters: GarageTaskFilter) -> tuple[GarageTaskItem, ...]:
    result = await session.execute(build_garage_task_query(filters))
    return tuple(_serialize_task(item) for item in result.scalars().all())


async def apply_garage_operation(session, operation: GarageOperation) -> None:
    result = await session.execute(build_garage_operation_query(
        delivery_id=operation.delivery_id,
        chat_id=operation.chat_id,
    ))
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise ValueError("车库转发任务不存在或不属于当前群")
    _apply_transition(delivery, operation)
    session.add(_operation_audit(delivery, operation.action))


def request_garage_retry(delivery, *, now: dt.datetime) -> None:
    status = DeliveryStatus(delivery.status)
    if status is DeliveryStatus.uncertain:
        raise ValueError("结果不确定任务必须使用确认重放")
    if status not in {DeliveryStatus.retryable_failed, DeliveryStatus.permanent_failed}:
        raise ValueError(f"当前状态不允许重试: {status.value}")
    _reset_to_pending(delivery, now)


def request_garage_replay(delivery, *, now: dt.datetime, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("必须确认可能产生重复消息后才能重放")
    if delivery.status != DeliveryStatus.uncertain.value:
        raise ValueError("只有结果不确定任务可以确认重放")
    _reset_to_pending(delivery, now)


def cancel_garage_delivery(delivery, *, now: dt.datetime) -> None:
    status = DeliveryStatus(delivery.status)
    if status in {DeliveryStatus.processing, DeliveryStatus.succeeded, DeliveryStatus.cancelled}:
        raise ValueError(f"当前状态不允许取消: {status.value}")
    delivery.status = DeliveryStatus.cancelled.value
    delivery.next_retry_at = None
    delivery.lease_until = None
    delivery.completed_at = now


def _apply_transition(delivery, operation: GarageOperation) -> None:
    if operation.action == ACTION_RETRY:
        request_garage_retry(delivery, now=operation.now)
        return
    if operation.action == ACTION_CANCEL:
        cancel_garage_delivery(delivery, now=operation.now)
        return
    if operation.action == ACTION_REPLAY:
        request_garage_replay(delivery, now=operation.now, confirmed=operation.confirmed)
        return
    raise ValueError(f"未知车库转发任务操作: {operation.action}")


def _reset_to_pending(delivery, now: dt.datetime) -> None:
    delivery.status = DeliveryStatus.pending.value
    delivery.retry_count = 0
    delivery.next_retry_at = now
    delivery.lease_until = None
    delivery.send_started_at = None
    delivery.last_error = None
    delivery.completed_at = None


def _serialize_task(delivery) -> GarageTaskItem:
    return GarageTaskItem(
        id=int(delivery.id),
        chat_id=int(delivery.chat_id),
        source_channel_id=int(delivery.source_channel_id),
        source_message_id=int(delivery.source_message_id),
        status=str(delivery.status),
        attempts=int(delivery.retry_count or 0),
        last_error=delivery.last_error,
        completed_at=delivery.completed_at,
    )


def _operation_audit(delivery, action: str):
    return GarageForwardAuditLog(
        chat_id=delivery.chat_id,
        source_channel_id=delivery.source_channel_id,
        source_message_id=delivery.source_message_id,
        action=f"admin_{action}"[:32],
        result="success",
        reason=f"status={delivery.status}",
    )
