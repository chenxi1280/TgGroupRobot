from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import (
    ChatSubscription,
    RenewalAuditLog,
    RenewalCardKey,
    SubscriptionPlan,
    TgChat,
)
from backend.platform.db.schema.models.enums import SubscriptionStatus
from backend.shared.services.base import ServiceBase
from backend.features.subscription.services.subscription_service import get_or_create_chat_subscription, get_plan


@dataclass
class RenewalSnapshot:
    chat_id: int
    group_title: str
    version_name: str
    renew_price_text: str
    end_at_text: str
    subscription: ChatSubscription
    plan: SubscriptionPlan | None


@dataclass(slots=True)
class RenewalRedeemResult:
    success: bool
    message: str
    new_end_at: dt.datetime | None = None


def _format_price(plan: SubscriptionPlan | None) -> str:
    if plan is None:
        return "未配置"
    if plan.price_cents <= 0:
        return "免费"
    amount = plan.price_cents / 100
    if plan.duration_days > 0:
        return f"¥{amount:.2f}/{plan.duration_days}天"
    return f"¥{amount:.2f}"


def _format_end_at(value: dt.datetime | None) -> str:
    if value is None:
        return "永久"
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M")


async def get_renewal_snapshot(session: AsyncSession, chat_id: int) -> RenewalSnapshot:
    sub = await get_or_create_chat_subscription(session, chat_id)
    plan = await get_plan(session, sub.plan_id)
    chat = await ServiceBase._get_by_id(session, TgChat, chat_id)

    return RenewalSnapshot(
        chat_id=chat_id,
        group_title=(chat.title if chat and chat.title else f"群组{chat_id}"),
        version_name=plan.name if plan else "未配置",
        renew_price_text=_format_price(plan),
        end_at_text=_format_end_at(sub.end_at),
        subscription=sub,
        plan=plan,
    )


def normalize_card_code(card_code: str) -> str:
    return (card_code or "").strip().upper()


def hash_card_code(card_code: str) -> str:
    normalized = normalize_card_code(card_code)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def mask_card_code(card_code: str) -> str:
    normalized = normalize_card_code(card_code)
    if not normalized:
        return ""
    return normalized[:4] + "*" * max(len(normalized) - 4, 0)


def calculate_new_expire_at(
    current_end_at: dt.datetime | None,
    *,
    duration_seconds: int,
    now: dt.datetime | None = None,
) -> dt.datetime:
    current_now = now or dt.datetime.now(dt.UTC)
    if current_now.tzinfo is None:
        current_now = current_now.replace(tzinfo=dt.UTC)

    if current_end_at is None:
        base = current_now
    else:
        if current_end_at.tzinfo is None:
            current_end_at = current_end_at.replace(tzinfo=dt.UTC)
        base = current_end_at if current_end_at > current_now else current_now

    return base + dt.timedelta(seconds=max(int(duration_seconds), 0))


async def _create_renewal_audit_log(
    session: AsyncSession,
    *,
    chat_id: int,
    operator_user_id: int | None,
    action: str,
    reason: str | None,
    payload: dict,
) -> None:
    session.add(
        RenewalAuditLog(
            chat_id=chat_id,
            operator_user_id=operator_user_id,
            action=action,
            reason=reason,
            payload=payload,
        )
    )
    await session.flush()


async def redeem_renewal_card(
    session: AsyncSession,
    *,
    chat_id: int,
    operator_user_id: int,
    card_code: str,
    now: dt.datetime | None = None,
) -> RenewalRedeemResult:
    current_now = now or dt.datetime.now(dt.UTC)
    if current_now.tzinfo is None:
        current_now = current_now.replace(tzinfo=dt.UTC)

    normalized_code = normalize_card_code(card_code)
    masked_code = mask_card_code(card_code)
    card_hash = hash_card_code(normalized_code)

    card_result = await session.execute(
        select(RenewalCardKey)
        .where(RenewalCardKey.card_key_hash == card_hash)
        .with_for_update()
    )
    card = card_result.scalar_one_or_none()
    if card is None:
        await _create_renewal_audit_log(
            session,
            chat_id=chat_id,
            operator_user_id=operator_user_id,
            action="failed",
            reason="card_not_found",
            payload={"masked_card": masked_code},
        )
        return RenewalRedeemResult(success=False, message="卡密不存在")

    if card.expires_at is not None:
        expires_at = card.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=dt.UTC)
        if expires_at <= current_now:
            await _create_renewal_audit_log(
                session,
                chat_id=chat_id,
                operator_user_id=operator_user_id,
                action="failed",
                reason="card_expired",
                payload={"card_id": card.id, "masked_card": masked_code},
            )
            return RenewalRedeemResult(success=False, message="卡密已失效")

    if card.used:
        await _create_renewal_audit_log(
            session,
            chat_id=chat_id,
            operator_user_id=operator_user_id,
            action="failed",
            reason="card_used",
            payload={"card_id": card.id, "masked_card": masked_code},
        )
        return RenewalRedeemResult(success=False, message="卡密已使用")

    subscription = await get_or_create_chat_subscription(session, chat_id)
    current_plan = await get_plan(session, subscription.plan_id)
    if current_plan is None or current_plan.code == "free":
        paid_plan = await ServiceBase._get_by_filters(session, SubscriptionPlan, {"code": "pro_monthly"})
        if paid_plan is not None:
            subscription.plan_id = paid_plan.id

    previous_end_at = subscription.end_at
    new_end_at = calculate_new_expire_at(
        previous_end_at,
        duration_seconds=card.duration_seconds,
        now=current_now,
    )

    subscription.status = SubscriptionStatus.active.value
    subscription.end_at = new_end_at
    card.used = True
    card.used_by_chat_id = chat_id
    card.used_by_user_id = operator_user_id
    card.used_at = current_now
    await session.flush()

    await _create_renewal_audit_log(
        session,
        chat_id=chat_id,
        operator_user_id=operator_user_id,
        action="success",
        reason="redeem",
        payload={
            "card_id": card.id,
            "masked_card": masked_code,
            "duration_seconds": int(card.duration_seconds),
            "previous_end_at": previous_end_at.isoformat() if previous_end_at else None,
            "new_end_at": new_end_at.isoformat(),
        },
    )
    return RenewalRedeemResult(
        success=True,
        message=f"续费成功，到期时间已更新为：{_format_end_at(new_end_at)}",
        new_end_at=new_end_at,
    )


def format_renewal_entry_text(snapshot: RenewalSnapshot, contact_username: str | None) -> str:
    contact_line = f"\n购买咨询：@{contact_username.lstrip('@')}" if contact_username else ""
    return (
        "💳 续费订阅\n\n"
        "请点击下方按钮输入服务商提供的续费卡密。\n"
        "核销成功后，卡密会绑定当前群组并自动延长有效期。\n\n"
        f"群组名字：{snapshot.group_title}\n"
        f"当前版本：{snapshot.version_name}\n"
        f"到期时间：{snapshot.end_at_text}"
        f"{contact_line}"
    )
