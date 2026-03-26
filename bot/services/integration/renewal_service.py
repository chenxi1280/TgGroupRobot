from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import TgChat, ChatSubscription, SubscriptionPlan
from bot.services.base import ServiceBase
from bot.services.subscription_service import get_or_create_chat_subscription, get_plan


@dataclass
class RenewalSnapshot:
    chat_id: int
    group_title: str
    version_name: str
    renew_price_text: str
    end_at_text: str
    subscription: ChatSubscription
    plan: SubscriptionPlan | None


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


def format_renewal_entry_text(snapshot: RenewalSnapshot, contact_username: str | None) -> str:
    contact_hint = "续费卡密请点击下方按钮联系购买"
    if contact_username:
        contact_hint = f"续费卡密请联系 @{contact_username.lstrip('@')} 购买"

    return (
        "🔐 续费入口\n\n"
        f"当前版本：{snapshot.version_name}\n"
        f"群组名字：{snapshot.group_title}\n"
        f"续费价格：{snapshot.renew_price_text}\n"
        f"到期时间：{snapshot.end_at_text}\n\n"
        f"{contact_hint}\n\n"
        "👉 请输入续费卡密："
    )
