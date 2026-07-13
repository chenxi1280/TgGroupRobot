from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from backend.platform.db.schema.models.alliance import (
    GarageForwardAuditLog,
    GarageForwardMessageMap,
    GarageForwardRetryQueue,
    GarageForwardSource,
)
from backend.platform.delivery import (
    DeliveryOutcome,
    DeliveryStatus,
    RetryPolicy,
    calculate_next_retry_at,
)


@dataclass(frozen=True, kw_only=True)
class GarageDeliveryRequest:
    chat_id: int
    source_channel_id: int
    source_message_id: int
    message_map_id: int
    reply_markup_snapshot: dict[str, Any] | None


@dataclass(frozen=True, kw_only=True)
class GarageReservationRequest:
    chat_id: int
    source_channel_id: int
    source_message_id: int
    reply_markup_snapshot: dict[str, Any] | None


class GarageForwardDeliveryRepository:
    @staticmethod
    def build_enqueue_statement(request: GarageDeliveryRequest):
        now = dt.datetime.now(dt.UTC)
        values = {
            "chat_id": request.chat_id,
            "source_channel_id": request.source_channel_id,
            "source_message_id": request.source_message_id,
            "message_map_id": request.message_map_id,
            "reply_markup_snapshot": request.reply_markup_snapshot,
            "status": DeliveryStatus.pending.value,
            "retry_count": 0,
            "next_retry_at": now,
            "lease_until": None,
            "send_started_at": None,
            "last_error": None,
            "completed_at": None,
        }
        statement = insert(GarageForwardRetryQueue).values(**values)
        retryable_statuses = (
            DeliveryStatus.retryable_failed.value,
            DeliveryStatus.permanent_failed.value,
        )
        return statement.on_conflict_do_update(
            index_elements=["chat_id", "source_channel_id", "source_message_id"],
            set_={
                "message_map_id": statement.excluded.message_map_id,
                "reply_markup_snapshot": statement.excluded.reply_markup_snapshot,
                "status": DeliveryStatus.pending.value,
                "next_retry_at": now,
                "lease_until": None,
                "send_started_at": None,
                "last_error": None,
                "completed_at": None,
            },
            where=GarageForwardRetryQueue.status.in_(retryable_statuses),
        ).returning(GarageForwardRetryQueue)


def build_due_query(now: dt.datetime, *, limit: int):
    retry_due = and_(
        GarageForwardRetryQueue.status == DeliveryStatus.retryable_failed.value,
        or_(
            GarageForwardRetryQueue.next_retry_at.is_(None),
            GarageForwardRetryQueue.next_retry_at <= now,
        ),
    )
    return (
        select(GarageForwardRetryQueue)
        .where(or_(
            GarageForwardRetryQueue.status == DeliveryStatus.pending.value,
            retry_due,
        ))
        .order_by(GarageForwardRetryQueue.next_retry_at, GarageForwardRetryQueue.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_expired_lease_query(now: dt.datetime, *, limit: int):
    return (
        select(GarageForwardRetryQueue)
        .where(
            GarageForwardRetryQueue.status == DeliveryStatus.processing.value,
            GarageForwardRetryQueue.lease_until <= now,
        )
        .order_by(GarageForwardRetryQueue.lease_until, GarageForwardRetryQueue.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_processing_delivery_query(delivery_id: int):
    return (
        select(GarageForwardRetryQueue)
        .where(
            GarageForwardRetryQueue.id == delivery_id,
            GarageForwardRetryQueue.status == DeliveryStatus.processing.value,
        )
        .with_for_update()
    )


def recover_expired_delivery(delivery, now: dt.datetime) -> None:
    send_started = delivery.send_started_at is not None
    status = DeliveryStatus.uncertain if send_started else DeliveryStatus.retryable_failed
    delivery.status = status.value
    delivery.next_retry_at = None if send_started else now
    delivery.lease_until = None
    delivery.last_error = "lease_expired_after_send" if send_started else "lease_expired_before_send"
    delivery.completed_at = now if send_started else None


def finalize_delivery(
    session,
    *,
    delivery,
    message_map,
    source,
    outcome: DeliveryOutcome,
    now: dt.datetime,
    retry_policy: RetryPolicy,
) -> None:
    status, next_retry_at = _resolve_status(
        delivery,
        outcome,
        now=now,
        policy=retry_policy,
    )
    delivery.status = status.value
    delivery.next_retry_at = next_retry_at
    delivery.lease_until = None
    delivery.last_error = _format_error(outcome)
    delivery.completed_at = now if _is_terminal(status) else None
    if status is DeliveryStatus.succeeded:
        _finalize_success(
            delivery,
            message_map,
            source,
            outcome=outcome,
            now=now,
        )
    session.add(_build_audit(delivery, status, outcome))


def _resolve_status(
    delivery,
    outcome,
    *,
    now,
    policy,
) -> tuple[DeliveryStatus, dt.datetime | None]:
    if outcome.status is not DeliveryStatus.retryable_failed:
        return outcome.status, None
    attempts = int(delivery.retry_count or 0)
    if attempts >= int(delivery.max_retries or policy.max_attempts):
        return DeliveryStatus.permanent_failed, None
    return DeliveryStatus.retryable_failed, calculate_next_retry_at(
        now,
        attempts=attempts,
        policy=policy,
    )


def _finalize_success(delivery, message_map, source, *, outcome, now) -> None:
    if outcome.message_id is None:
        raise RuntimeError(f"garage delivery {delivery.id if hasattr(delivery, 'id') else '?'} has no message id")
    message_map.target_message_id = int(outcome.message_id)
    message_map.forwarded_at = now
    if source is None:
        return
    current = source.last_seen_message_id
    if current is None or delivery.source_message_id > current:
        source.last_seen_message_id = delivery.source_message_id


def _build_audit(delivery, status: DeliveryStatus, outcome: DeliveryOutcome):
    return GarageForwardAuditLog(
        chat_id=delivery.chat_id,
        source_channel_id=delivery.source_channel_id,
        source_message_id=delivery.source_message_id,
        action="copy" if int(delivery.retry_count or 0) <= 1 else "retry_copy",
        result="success" if status is DeliveryStatus.succeeded else "failed",
        reason=_format_error(outcome) or status.value,
    )


def _format_error(outcome: DeliveryOutcome) -> str | None:
    if not outcome.error_code:
        return outcome.message
    if not outcome.message:
        return outcome.error_code
    return f"{outcome.error_code}: {outcome.message}"


def _is_terminal(status: DeliveryStatus) -> bool:
    return status in {
        DeliveryStatus.succeeded,
        DeliveryStatus.permanent_failed,
        DeliveryStatus.uncertain,
        DeliveryStatus.cancelled,
    }


DEFAULT_BATCH_LIMIT = 50


class SqlAlchemyGarageForwardStore:
    def __init__(self, db, *, retry_policy: RetryPolicy | None = None) -> None:
        self._db = db
        self._retry_policy = retry_policy or RetryPolicy()

    async def reserve_live(
        self,
        request: GarageReservationRequest,
        *,
        now: dt.datetime,
        lease_until: dt.datetime,
    ):
        async with self._db.session_factory() as session:
            message_map = await _create_message_map(session, request)
            if message_map is None:
                return None
            delivery = await _enqueue_delivery(session, request, message_map.id)
            if delivery is None:
                await session.rollback()
                return None
            plan = _claim_delivery(delivery, now=now, lease_until=lease_until)
            await session.commit()
        return plan

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        async with self._db.session_factory() as session:
            result = await session.execute(build_expired_lease_query(now, limit=DEFAULT_BATCH_LIMIT))
            deliveries = tuple(result.scalars().all())
            for delivery in deliveries:
                recover_expired_delivery(delivery, now)
                session.add(_recovery_audit(delivery))
            await session.commit()
        return len(deliveries)

    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int):
        async with self._db.session_factory() as session:
            result = await session.execute(build_due_query(now, limit=limit))
            plans = tuple(
                _claim_delivery(item, now=now, lease_until=lease_until)
                for item in result.scalars().all()
            )
            await session.commit()
        return plans

    async def mark_send_started(self, plan, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            delivery = await _load_processing_delivery(session, plan.delivery_id)
            delivery.send_started_at = now
            await session.commit()

    async def finalize(self, plan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            delivery = await _load_processing_delivery(session, plan.delivery_id)
            message_map = await _load_message_map(session, plan.message_map_id)
            source = await _load_source(session, delivery)
            finalize_delivery(
                session,
                delivery=delivery,
                message_map=message_map,
                source=source,
                outcome=outcome,
                now=now,
                retry_policy=self._retry_policy,
            )
            await session.commit()

    async def mark_finalize_uncertain(self, plan, error: Exception, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            delivery = await _load_processing_delivery(session, plan.delivery_id)
            outcome = DeliveryOutcome.uncertain("database_finalize_failed", str(error))
            delivery.status = DeliveryStatus.uncertain.value
            delivery.next_retry_at = None
            delivery.lease_until = None
            delivery.last_error = _format_error(outcome)
            delivery.completed_at = now
            session.add(_build_audit(delivery, DeliveryStatus.uncertain, outcome))
            await session.commit()


async def _create_message_map(session, request: GarageReservationRequest):
    result = await session.execute(_message_map_event_query(request))
    if result.scalar_one_or_none() is not None:
        return None
    message_map = GarageForwardMessageMap(
        chat_id=request.chat_id,
        source_channel_id=request.source_channel_id,
        source_message_id=request.source_message_id,
        target_message_id=0,
    )
    session.add(message_map)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return None
    return message_map


def _message_map_event_query(request: GarageReservationRequest):
    return select(GarageForwardMessageMap).where(
        GarageForwardMessageMap.chat_id == request.chat_id,
        GarageForwardMessageMap.source_channel_id == request.source_channel_id,
        GarageForwardMessageMap.source_message_id == request.source_message_id,
    )


async def _enqueue_delivery(session, request, message_map_id: int):
    delivery_request = GarageDeliveryRequest(
        chat_id=request.chat_id,
        source_channel_id=request.source_channel_id,
        source_message_id=request.source_message_id,
        message_map_id=message_map_id,
        reply_markup_snapshot=request.reply_markup_snapshot,
    )
    result = await session.execute(
        GarageForwardDeliveryRepository.build_enqueue_statement(delivery_request)
    )
    return result.scalar_one_or_none()


def _claim_delivery(delivery, *, now: dt.datetime, lease_until: dt.datetime):
    from backend.features.garage.forward_delivery_executor import GarageForwardPlan

    delivery.status = DeliveryStatus.processing.value
    delivery.retry_count = int(delivery.retry_count or 0) + 1
    delivery.next_retry_at = None
    delivery.lease_until = lease_until
    delivery.send_started_at = None
    delivery.last_error = None
    delivery.completed_at = None
    return GarageForwardPlan(
        delivery_id=int(delivery.id),
        message_map_id=int(delivery.message_map_id),
        chat_id=int(delivery.chat_id),
        source_channel_id=int(delivery.source_channel_id),
        source_message_id=int(delivery.source_message_id),
        reply_markup_snapshot=delivery.reply_markup_snapshot,
    )


async def _load_processing_delivery(session, delivery_id: int):
    result = await session.execute(build_processing_delivery_query(delivery_id))
    delivery = result.scalar_one_or_none()
    if delivery is None:
        raise RuntimeError(f"garage delivery is not processing: {delivery_id}")
    return delivery


async def _load_message_map(session, message_map_id: int):
    result = await session.execute(
        select(GarageForwardMessageMap)
        .where(GarageForwardMessageMap.id == message_map_id)
        .with_for_update()
    )
    message_map = result.scalar_one_or_none()
    if message_map is None:
        raise RuntimeError(f"garage message map is missing: {message_map_id}")
    return message_map


async def _load_source(session, delivery):
    result = await session.execute(
        select(GarageForwardSource)
        .where(
            GarageForwardSource.chat_id == delivery.chat_id,
            GarageForwardSource.source_channel_id == delivery.source_channel_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


def _recovery_audit(delivery):
    status = DeliveryStatus(delivery.status)
    outcome = DeliveryOutcome(
        status=status,
        error_code=delivery.last_error,
        message=delivery.last_error,
    )
    return _build_audit(delivery, status, outcome)
