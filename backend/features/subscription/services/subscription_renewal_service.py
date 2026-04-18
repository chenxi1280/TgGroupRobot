from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSubscription, SubscriptionPlan, TgChat
from backend.shared.services.base import ServiceBase
from backend.features.subscription.services.subscription_service import ensure_default_plans, get_or_create_chat_subscription

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class RenewalPageData:
    chat_title: str
    current_plan: SubscriptionPlan
    renewal_plan: SubscriptionPlan
    subscription: ChatSubscription

    @property
    def current_version_text(self) -> str:
        return self.current_plan.name or "开放版"

    @property
    def renewal_price_text(self) -> str:
        cents = max(0, int(self.renewal_plan.price_cents or 0))
        if cents <= 0:
            return "免费"
        return f"¥{cents / 100:.2f}"

    @property
    def expiry_text(self) -> str:
        if self.subscription.end_at is None:
            return "永久"
        end_at = self.subscription.end_at
        if end_at.tzinfo is None:
            end_at = end_at.replace(tzinfo=dt.UTC)
        local = end_at.astimezone(_SHANGHAI_TZ)
        suffix = "（已过期）" if local < dt.datetime.now(_SHANGHAI_TZ) else ""
        return f"{local.strftime('%Y-%m-%d %H:%M')}{suffix}"


def build_contact_url(bot_username: str | None) -> str:
    username = (bot_username or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}"
    return ""


def format_renewal_page(data: RenewalPageData, *, contact_hint: str = "当前版本所有功能默认开放。") -> str:
    return (
        "💳 续费订阅\n\n"
        "请使用后台生成的续费卡密延长群组有效期。\n"
        "卡密核销后会绑定当前群组，无法再次使用。\n\n"
        f"当前版本：{data.current_version_text}\n"
        f"群组名称：{data.chat_title}\n"
        f"到期时间：{data.expiry_text}"
    )


async def load_renewal_page(session: AsyncSession, chat_id: int, *, fallback_title: str | None = None) -> RenewalPageData:
    await ensure_default_plans(session)
    subscription = await get_or_create_chat_subscription(session, chat_id)

    current_plan = await ServiceBase._get_by_id(session, SubscriptionPlan, subscription.plan_id)
    if current_plan is None:
        current_plan = await _get_free_plan(session)

    renewal_plan = current_plan

    chat = await ServiceBase._get_by_id(session, TgChat, chat_id)
    chat_title = (chat.title if chat and chat.title else None) or fallback_title or f"群组{chat_id}"

    return RenewalPageData(
        chat_title=chat_title,
        current_plan=current_plan,
        renewal_plan=renewal_plan,
        subscription=subscription,
    )


async def _get_free_plan(session: AsyncSession) -> SubscriptionPlan:
    plan = await ServiceBase._get_by_filters(session, SubscriptionPlan, {"code": "free"})
    if plan is None:
        raise ValueError("免费套餐不存在")
    return plan


async def _get_pro_monthly_plan(session: AsyncSession) -> SubscriptionPlan:
    plan = await ServiceBase._get_by_filters(session, SubscriptionPlan, {"code": "pro_monthly"})
    if plan is None:
        raise ValueError("续费套餐不存在")
    return plan
