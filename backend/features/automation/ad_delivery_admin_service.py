from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from backend.platform.db.schema.models.automation import AdCampaign, AdRotationHistory, AdRotationRule
from backend.platform.delivery import DeliveryStatus
from backend.shared.services.base import NotFoundError, ValidationError

RETRYABLE_STATUSES = {
    DeliveryStatus.retryable_failed.value,
    DeliveryStatus.permanent_failed.value,
}
CANCELLABLE_STATUSES = RETRYABLE_STATUSES | {
    DeliveryStatus.pending.value,
    DeliveryStatus.uncertain.value,
}


async def list_delivery_history(session, chat_id: int, *, status: str | None = None, limit: int = 20):
    statement = select(AdRotationHistory).where(AdRotationHistory.chat_id == chat_id)
    if status:
        statement = statement.where(AdRotationHistory.status == status)
    result = await session.execute(statement.order_by(AdRotationHistory.id.desc()).limit(limit))
    return tuple(result.scalars().all())


async def retry_delivery(session, history_id: int, chat_id: int) -> None:
    history = await _load_history(session, history_id, chat_id)
    if history.status not in RETRYABLE_STATUSES:
        raise ValidationError("只有明确失败的广告派发可以直接重试")
    _reset_pending(history)


async def cancel_delivery(session, history_id: int, chat_id: int) -> None:
    history = await _load_history(session, history_id, chat_id)
    if history.status not in CANCELLABLE_STATUSES:
        raise ValidationError("当前广告派发状态不允许取消")
    history.status = DeliveryStatus.cancelled.value
    history.next_retry_at = None
    history.lease_until = None
    history.completed_at = dt.datetime.now(dt.UTC)


async def replay_uncertain_delivery(
    session,
    history_id: int,
    chat_id: int,
    *,
    admin_id: int,
    reason: str,
) -> int:
    source = await _load_history(session, history_id, chat_id)
    if source.status != DeliveryStatus.uncertain.value:
        raise ValidationError("只有不确定状态需要确认重放")
    if source.campaign_id is None or not source.content_snapshot:
        raise ValidationError("该记录没有可重放的广告快照")
    replay = AdRotationHistory(
        chat_id=source.chat_id,
        campaign_id=source.campaign_id,
        dispatch_key=f"replay:{source.id}:{uuid.uuid4().hex}",
        scheduled_for=dt.datetime.now(dt.UTC),
        content_snapshot=dict(source.content_snapshot),
        rule_snapshot=dict(source.rule_snapshot),
        status=DeliveryStatus.pending.value,
        attempt_count=0,
        sort_order_snapshot=source.sort_order_snapshot,
        title_snapshot=source.title_snapshot,
        replay_of_history_id=source.id,
        replay_admin_id=admin_id,
        replay_reason=reason,
    )
    session.add(replay)
    await session.flush()
    return int(replay.id)


async def toggle_pool_membership(session, chat_id: int, campaign_id: int, *, pool: str) -> bool:
    rule = await _load_rule(session, chat_id)
    campaign = await session.get(AdCampaign, campaign_id)
    if campaign is None or campaign.chat_id != chat_id:
        raise ValidationError("轮播广告不属于当前群")
    if pool not in {"top", "exclude"}:
        raise ValidationError("未知轮播池")
    attribute = "top_campaign_ids" if pool == "top" else "exclude_campaign_ids"
    values = {int(value) for value in getattr(rule, attribute, []) or []}
    is_added = campaign_id not in values
    values.add(campaign_id) if is_added else values.remove(campaign_id)
    setattr(rule, attribute, sorted(values))
    await session.flush()
    return is_added


async def _load_history(session, history_id: int, chat_id: int):
    result = await session.execute(
        select(AdRotationHistory)
        .where(AdRotationHistory.id == history_id, AdRotationHistory.chat_id == chat_id)
        .with_for_update()
    )
    history = result.scalar_one_or_none()
    if history is None:
        raise NotFoundError("广告派发记录不存在")
    return history


async def _load_rule(session, chat_id: int):
    result = await session.execute(
        select(AdRotationRule).where(AdRotationRule.chat_id == chat_id).with_for_update()
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise NotFoundError("轮播规则不存在")
    return rule


def _reset_pending(history: AdRotationHistory) -> None:
    history.status = DeliveryStatus.pending.value
    history.attempt_count = 0
    history.next_retry_at = None
    history.lease_until = None
    history.send_started_at = None
    history.completed_at = None
    history.error_code = None
    history.error_message = None
