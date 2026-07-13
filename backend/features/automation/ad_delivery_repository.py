from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.features.automation.ad_delivery_executor import AdDeliveryPlan
from backend.platform.db.schema.models.automation import AdCampaign, AdRotationHistory, AdRotationRule
from backend.platform.delivery import DeliveryOutcome, DeliveryStatus, RetryPolicy, calculate_next_retry_at
from backend.shared.services.base import ValidationError

DEFAULT_BATCH_LIMIT = 100


@dataclass(frozen=True, slots=True)
class AdPlanningResult:
    created: int
    failed: int


def build_due_history_query(now: dt.datetime, *, limit: int):
    retry_due = and_(
        AdRotationHistory.status == DeliveryStatus.retryable_failed.value,
        AdRotationHistory.next_retry_at <= now,
    )
    return (
        select(AdRotationHistory)
        .where(or_(AdRotationHistory.status == DeliveryStatus.pending.value, retry_due))
        .order_by(AdRotationHistory.next_retry_at, AdRotationHistory.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def recover_expired_history(history: AdRotationHistory, now: dt.datetime) -> None:
    started = history.send_started_at is not None
    history.status = DeliveryStatus.uncertain.value if started else DeliveryStatus.retryable_failed.value
    history.next_retry_at = None if started else now
    history.lease_until = None
    history.error_code = "lease_expired_after_send" if started else "lease_expired_before_send"
    history.error_message = history.error_code
    history.completed_at = now if started else None


def finalize_history(
    history: AdRotationHistory,
    rule: AdRotationRule,
    item: AdCampaign | None,
    *,
    outcome: DeliveryOutcome,
    now: dt.datetime,
    retry_policy: RetryPolicy,
) -> None:
    status, next_retry_at = _resolve_status(history, outcome, now=now, retry_policy=retry_policy)
    history.status = status.value
    history.next_retry_at = next_retry_at
    history.lease_until = None
    history.error_code = outcome.error_code
    history.error_message = outcome.message
    history.completed_at = now if _is_terminal(status) else None
    if status is DeliveryStatus.succeeded:
        _finalize_success(history, rule, item, outcome=outcome, now=now)


def _finalize_success(history, rule, item, *, outcome, now) -> None:
    if outcome.message_id is None:
        raise RuntimeError(f"ad delivery {history.id} has no message id")
    metadata = dict(outcome.metadata)
    pinned_id = metadata.get("pinned_message_id")
    history.message_id = int(outcome.message_id)
    history.pinned_message_id = int(pinned_id) if pinned_id is not None else None
    history.sent_at = now
    rule.last_sent_at = now
    rule.last_sent_item_id = history.campaign_id
    rule.last_sent_message_id = int(outcome.message_id)
    rule.last_pinned_message_id = history.pinned_message_id
    rule.current_order_cursor = int(history.rule_snapshot["next_cursor"])
    if item is None:
        return
    item.last_sent_at = now
    item.last_sent_message_id = int(outcome.message_id)
    item.last_sent_cycle_no = int(item.last_sent_cycle_no or 0) + 1
    item.send_count = int(item.send_count or 0) + 1
    history.cycle_no = item.last_sent_cycle_no


def _resolve_status(history, outcome, *, now, retry_policy):
    if outcome.status is not DeliveryStatus.retryable_failed:
        return outcome.status, None
    next_retry_at = calculate_next_retry_at(
        now,
        attempts=int(history.attempt_count or 0),
        policy=retry_policy,
    )
    if next_retry_at is None:
        return DeliveryStatus.permanent_failed, None
    return DeliveryStatus.retryable_failed, next_retry_at


def _is_terminal(status: DeliveryStatus) -> bool:
    return status in {
        DeliveryStatus.succeeded,
        DeliveryStatus.permanent_failed,
        DeliveryStatus.uncertain,
        DeliveryStatus.cancelled,
    }


class SqlAlchemyAdDeliveryStore:
    def __init__(self, db, *, retry_policy: RetryPolicy | None = None) -> None:
        self._db = db
        self._retry_policy = retry_policy or RetryPolicy()

    async def create_due_dispatches(self, now: dt.datetime) -> AdPlanningResult:
        async with self._db.session_factory() as session:
            rules = await _load_due_rules(session, now)
            created = failed = 0
            for rule in rules:
                was_created, was_failed = await _plan_rule(session, rule, now)
                created += was_created
                failed += was_failed
            await session.commit()
        return AdPlanningResult(created, failed)

    async def recover_expired_leases(self, now: dt.datetime) -> int:
        async with self._db.session_factory() as session:
            result = await session.execute(_expired_query(now))
            histories = tuple(result.scalars().all())
            for history in histories:
                recover_expired_history(history, now)
            await session.commit()
        return len(histories)

    async def claim_due(self, now: dt.datetime, lease_until: dt.datetime, *, limit: int):
        async with self._db.session_factory() as session:
            result = await session.execute(build_due_history_query(now, limit=limit))
            plans = tuple(_claim(history, lease_until) for history in result.scalars().all())
            await session.commit()
        return plans

    async def mark_send_started(self, plan: AdDeliveryPlan, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            history = await _load_processing(session, plan.history_id)
            history.send_started_at = now
            await session.commit()

    async def finalize(self, plan, outcome: DeliveryOutcome, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            history = await _load_processing(session, plan.history_id)
            rule = await _load_rule(session, history.chat_id)
            item = await _load_item(session, history.campaign_id)
            finalize_history(
                history,
                rule,
                item,
                outcome=outcome,
                now=now,
                retry_policy=self._retry_policy,
            )
            await session.commit()

    async def mark_finalize_uncertain(self, plan, error: Exception, *, now: dt.datetime) -> None:
        async with self._db.session_factory() as session:
            history = await _load_processing(session, plan.history_id)
            history.status = DeliveryStatus.uncertain.value
            history.next_retry_at = None
            history.lease_until = None
            history.completed_at = now
            history.error_code = "database_finalize_failed"
            history.error_message = str(error)
            await session.commit()


async def _load_due_rules(session, now: dt.datetime):
    result = await session.execute(
        select(AdRotationRule)
        .where(
            AdRotationRule.enabled.is_(True),
            or_(AdRotationRule.next_run_at.is_(None), AdRotationRule.next_run_at <= now),
        )
        .order_by(AdRotationRule.next_run_at.asc().nullsfirst())
        .limit(DEFAULT_BATCH_LIMIT)
        .with_for_update(skip_locked=True)
    )
    return tuple(result.scalars().all())


async def _plan_rule(session, rule: AdRotationRule, now: dt.datetime) -> tuple[int, int]:
    from backend.features.automation.services.ad_rotation_service import (
        compute_next_run_at,
        list_rotation_items,
        select_next_rotation_item,
    )

    scheduled_for = rule.next_run_at or now
    items = await list_rotation_items(session, rule.chat_id)
    try:
        item, next_cursor = select_next_rotation_item(rule, items, now=now)
        if item is None:
            raise ValidationError("没有可发送的有效轮播广告")
    except ValidationError as exc:
        await _insert_planning_failure(
            session,
            rule,
            scheduled_for=scheduled_for,
            now=now,
            error=exc,
        )
        rule.next_run_at = compute_next_run_at(rule, now=now, sent_at=now)
        return 0, 1
    created = await _insert_pending(
        session,
        rule,
        item,
        scheduled_for=scheduled_for,
        next_cursor=next_cursor,
    )
    rule.next_run_at = compute_next_run_at(rule, now=now, sent_at=now)
    return created, 0


async def _insert_pending(session, rule, item, *, scheduled_for, next_cursor: int) -> int:
    content_snapshot = _content_snapshot(item)
    rule_snapshot = _rule_snapshot(rule, next_cursor)
    statement = (
        insert(AdRotationHistory)
        .values(
            chat_id=rule.chat_id,
            campaign_id=item.id,
            dispatch_key=_dispatch_key(rule.chat_id, scheduled_for),
            scheduled_for=scheduled_for,
            content_snapshot=content_snapshot,
            rule_snapshot=rule_snapshot,
            status=DeliveryStatus.pending.value,
            attempt_count=0,
            sort_order_snapshot=int(item.sort_order or 1),
            title_snapshot=str(item.title or "")[:128],
        )
        .on_conflict_do_nothing(index_elements=["dispatch_key"])
        .returning(AdRotationHistory.id)
    )
    result = await session.execute(statement)
    return 1 if result.scalar_one_or_none() is not None else 0


async def _insert_planning_failure(session, rule, *, scheduled_for, now, error) -> None:
    statement = insert(AdRotationHistory).values(
        chat_id=rule.chat_id,
        campaign_id=None,
        dispatch_key=_dispatch_key(rule.chat_id, scheduled_for),
        scheduled_for=scheduled_for,
        content_snapshot={},
        rule_snapshot=_rule_snapshot(rule, int(rule.current_order_cursor or 1)),
        status=DeliveryStatus.permanent_failed.value,
        attempt_count=0,
        completed_at=now,
        error_code="invalid_rotation_pool",
        error_message=str(error),
        title_snapshot="配置错误",
    ).on_conflict_do_nothing(index_elements=["dispatch_key"])
    await session.execute(statement)


def _dispatch_key(chat_id: int, scheduled_for: dt.datetime) -> str:
    return f"{chat_id}:{int(scheduled_for.timestamp())}"


def _content_snapshot(item) -> dict[str, Any]:
    return {
        "campaign_id": int(item.id),
        "title": str(item.title or ""),
        "content": str(item.content or ""),
        "image_file_id": item.image_file_id,
        "buttons": list(item.buttons or []),
        "last_sent_message_id": item.last_sent_message_id,
        "sort_order": int(item.sort_order or 1),
    }


def _rule_snapshot(rule, next_cursor: int) -> dict[str, Any]:
    return {
        "mode": rule.mode,
        "delete_policy": rule.delete_policy,
        "delete_delay_seconds": int(rule.delete_delay_seconds or 60),
        "unpin_previous": bool(rule.unpin_previous),
        "last_sent_message_id": rule.last_sent_message_id,
        "last_pinned_message_id": rule.last_pinned_message_id,
        "next_cursor": next_cursor,
    }


def _expired_query(now: dt.datetime):
    return (
        select(AdRotationHistory)
        .where(
            AdRotationHistory.status == DeliveryStatus.processing.value,
            AdRotationHistory.lease_until <= now,
        )
        .limit(DEFAULT_BATCH_LIMIT)
        .with_for_update(skip_locked=True)
    )


def _claim(history: AdRotationHistory, lease_until: dt.datetime) -> AdDeliveryPlan:
    history.status = DeliveryStatus.processing.value
    history.attempt_count = int(history.attempt_count or 0) + 1
    history.next_retry_at = None
    history.lease_until = lease_until
    history.send_started_at = None
    history.error_code = None
    history.error_message = None
    history.completed_at = None
    return AdDeliveryPlan(
        history_id=int(history.id),
        chat_id=int(history.chat_id),
        campaign_id=int(history.campaign_id),
        content_snapshot=dict(history.content_snapshot),
        rule_snapshot=dict(history.rule_snapshot),
    )


async def _load_processing(session, history_id: int):
    result = await session.execute(
        select(AdRotationHistory)
        .where(
            AdRotationHistory.id == history_id,
            AdRotationHistory.status == DeliveryStatus.processing.value,
        )
        .with_for_update()
    )
    history = result.scalar_one_or_none()
    if history is None:
        raise RuntimeError(f"ad delivery is not processing: {history_id}")
    return history


async def _load_rule(session, chat_id: int):
    result = await session.execute(select(AdRotationRule).where(AdRotationRule.chat_id == chat_id).with_for_update())
    rule = result.scalar_one_or_none()
    if rule is None:
        raise RuntimeError(f"ad rotation rule is missing: {chat_id}")
    return rule


async def _load_item(session, campaign_id: int | None):
    if campaign_id is None:
        return None
    result = await session.execute(select(AdCampaign).where(AdCampaign.id == campaign_id).with_for_update())
    return result.scalar_one_or_none()
