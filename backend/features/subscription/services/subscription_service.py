from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSubscription, SubscriptionPlan
from backend.platform.db.schema.models.enums import SubscriptionStatus
from backend.shared.services.base import ServiceBase
from backend.shared.services.chat_service import ensure_chat


DEFAULT_PLANS: list[tuple[str, str, int, int, dict]] = [
    ("free", "免费版", 0, 0, {"ads": False, "keywords": False}),
    ("pro_monthly", "Pro（月付）", 990, 30, {"ads": True, "keywords": True}),
    ("pro_yearly", "Pro（年付）", 9990, 365, {"ads": True, "keywords": True}),
]


@dataclass(frozen=True)
class SubscriptionOverview:
    chat_id: int
    chat_title: str
    version_name: str
    renewal_price_text: str
    expires_at_text: str
    status: str


def _format_money(price_cents: int) -> str:
    return f"{price_cents / 100:.2f}"


def _format_expire_at(end_at: dt.datetime | None) -> str:
    if end_at is None:
        return "永久"
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=dt.UTC)
    return end_at.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M")


def _build_renewal_price_text(current_plan: SubscriptionPlan | None, plans: list[SubscriptionPlan]) -> str:
    if current_plan is not None and current_plan.duration_days > 0:
        price = _format_money(current_plan.price_cents)
        return f"{price} / {current_plan.duration_days}天"

    paid_plans = [plan for plan in plans if plan.price_cents > 0 and plan.duration_days > 0]
    if not paid_plans:
        return "未配置"

    paid_plans.sort(key=lambda plan: (plan.duration_days, plan.price_cents))
    base = paid_plans[0]
    return f"{_format_money(base.price_cents)} / {base.duration_days}天"


async def ensure_default_plans(session: AsyncSession) -> None:
    """
    确保默认订阅套餐存在

    Args:
        session: 数据库会话
    """
    for code, name, price_cents, duration_days, flags in DEFAULT_PLANS:
        plan = await ServiceBase._get_by_filters(
            session,
            SubscriptionPlan,
            {"code": code},
        )
        if plan is None:
            session.add(
                SubscriptionPlan(
                    code=code,
                    name=name,
                    price_cents=price_cents,
                    duration_days=duration_days,
                    feature_flags=flags,
                )
            )
    await session.flush()


async def get_or_create_chat_subscription(session: AsyncSession, chat_id: int) -> ChatSubscription:
    """
    获取或创建群组订阅

    Args:
        session: 数据库会话
        chat_id: 群组 ID

    Returns:
        ChatSubscription: 订阅对象
    """
    await ensure_default_plans(session)

    sub = await ServiceBase._get_by_filters(
        session,
        ChatSubscription,
        {"chat_id": chat_id},
    )
    if sub is not None:
        return sub

    free = await ServiceBase._get_by_filters(
        session,
        SubscriptionPlan,
        {"code": "free"},
    )
    if free is None:
        raise ValueError("免费套餐不存在，请确保默认套餐已创建")

    sub = ChatSubscription(
        chat_id=chat_id,
        plan_id=free.id,
        status=SubscriptionStatus.active.value,
        start_at=dt.datetime.now(dt.UTC),
        end_at=None,
    )
    session.add(sub)
    await session.flush()
    return sub


async def get_plan(session: AsyncSession, plan_id: int) -> SubscriptionPlan | None:
    """
    获取订阅套餐

    Args:
        session: 数据库会话
        plan_id: 套餐 ID

    Returns:
        SubscriptionPlan: 套餐对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_id(session, SubscriptionPlan, plan_id)


async def list_plans(session: AsyncSession) -> list[SubscriptionPlan]:
    result = await ServiceBase._get_list(
        session,
        SubscriptionPlan,
        filters=None,
        order_by="duration_days",
        descending=False,
    )
    plans = list(result)
    plans.sort(key=lambda plan: (plan.duration_days, plan.price_cents, plan.id))
    return plans


async def get_subscription_overview(
    session: AsyncSession,
    *,
    chat_id: int,
    chat_title: str | None,
) -> SubscriptionOverview:
    await ensure_chat(
        session,
        chat_id=chat_id,
        chat_type="supergroup" if chat_id < 0 else "private",
        title=chat_title,
    )
    subscription = await get_or_create_chat_subscription(session, chat_id)
    current_plan = await get_plan(session, subscription.plan_id)
    plans = await list_plans(session)

    version_name = current_plan.name if current_plan is not None else "未配置"
    renewal_price_text = _build_renewal_price_text(current_plan, plans)
    expires_at_text = _format_expire_at(subscription.end_at)

    return SubscriptionOverview(
        chat_id=chat_id,
        chat_title=chat_title or f"群组{chat_id}",
        version_name=version_name,
        renewal_price_text=renewal_price_text,
        expires_at_text=expires_at_text,
        status=subscription.status,
    )



