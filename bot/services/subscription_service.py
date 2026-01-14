from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSubscription, SubscriptionPlan
from bot.models.enums import SubscriptionStatus
from bot.services.base import ServiceBase


DEFAULT_PLANS: list[tuple[str, str, int, int, dict]] = [
    ("free", "免费版", 0, 0, {"ads": False, "keywords": False}),
    ("pro_monthly", "Pro（月付）", 990, 30, {"ads": True, "keywords": True}),
    ("pro_yearly", "Pro（年付）", 9990, 365, {"ads": True, "keywords": True}),
]


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





