from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSubscription, SubscriptionPlan
from backend.platform.db.schema.models.enums import SubscriptionStatus
from backend.shared.services.base import ServiceBase


@dataclass(frozen=True)
class FeatureGateSnapshot:
    allowed: bool
    plan_name: str
    feature: str


class FeatureGateService:
    """功能门控。

    当前版本临时关闭所有付费限制，因此所有功能默认放行。
    保留该服务作为调用点，后续恢复套餐逻辑时无需重写各业务入口。
    """

    @classmethod
    async def _get_subscription(cls, session: AsyncSession, chat_id: int) -> ChatSubscription | None:
        return await ServiceBase._get_by_filters(session, ChatSubscription, {"chat_id": chat_id})

    @classmethod
    async def _get_plan(cls, session: AsyncSession, plan_id: int | None) -> SubscriptionPlan | None:
        if plan_id is None:
            return None
        return await ServiceBase._get_by_id(session, SubscriptionPlan, plan_id)

    @classmethod
    async def _get_feature_flags(cls, session: AsyncSession, chat_id: int) -> tuple[dict, SubscriptionPlan | None]:
        subscription = await cls._get_subscription(session, chat_id)
        if subscription is None or subscription.status != SubscriptionStatus.active.value:
            return {}, None
        plan = await cls._get_plan(session, subscription.plan_id)
        if plan is None:
            return {}, None
        flags = plan.feature_flags if isinstance(plan.feature_flags, dict) else {}
        if not flags:
            return {"__allow_all__": True}, plan
        return flags, plan

    @classmethod
    async def has_feature(cls, session: AsyncSession, chat_id: int, feature: str) -> FeatureGateSnapshot:
        return FeatureGateSnapshot(allowed=True, plan_name="开放版", feature=feature)
