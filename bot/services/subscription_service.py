from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSubscription, SubscriptionPlan
from bot.models.enums import SubscriptionStatus


DEFAULT_PLANS: list[tuple[str, str, int, int, dict]] = [
    ("free", "免费版", 0, 0, {"ads": False, "keywords": False}),
    ("pro_monthly", "Pro（月付）", 990, 30, {"ads": True, "keywords": True}),
    ("pro_yearly", "Pro（年付）", 9990, 365, {"ads": True, "keywords": True}),
]


async def ensure_default_plans(session: AsyncSession) -> None:
    for code, name, price_cents, duration_days, flags in DEFAULT_PLANS:
        res = await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
        plan = res.scalar_one_or_none()
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
    await ensure_default_plans(session)
    res = await session.execute(select(ChatSubscription).where(ChatSubscription.chat_id == chat_id))
    sub = res.scalar_one_or_none()
    if sub is not None:
        return sub

    res2 = await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == "free"))
    free = res2.scalar_one_or_none()
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
    """获取订阅套餐"""
    res = await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    return res.scalar_one_or_none()





