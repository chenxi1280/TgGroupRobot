from __future__ import annotations

import datetime as dt

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.engagement_core import (
    DEFAULT_CHAT_REWARD_PLAN,
    get_or_create_chat_reward,
    get_or_create_chat_stat,
    now_utc,
)
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import EngagementChatReward, EngagementChatStat
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user
_TRY_CLAIM_CHAT_REWARD_THRESHOLD_7 = 7



async def update_chat_reward(session: AsyncSession, chat_id: int, **updates) -> EngagementChatReward:
    valid = {"reward_type": {"daily", "daily_increment", "weekly_cycle"}, "after_7d_mode": {"reset", "continue"}}
    for field, values in valid.items():
        if field in updates and updates[field] not in values:
            raise ValidationError("无效的水群奖励类型或七日后策略")
    reward = await get_or_create_chat_reward(session, chat_id)
    for key, value in updates.items():
        if hasattr(reward, key):
            setattr(reward, key, value)
    reward.updated_at = now_utc()
    await session.flush()
    return reward


async def increase_message_count(session: AsyncSession, chat_id: int, user_id: int) -> EngagementChatStat:
    biz_date = business_date()
    stat = await get_or_create_chat_stat(session, chat_id, user_id, biz_date=biz_date)
    stat.message_count += 1
    stat.updated_at = now_utc()
    await session.flush()
    return stat


async def get_recent_chat_reward_stats(session: AsyncSession, chat_id: int, days: int = 7) -> list[dict]:
    start_date = business_date() - dt.timedelta(days=max(days - 1, 0))
    stmt = (
        select(
            EngagementChatStat.biz_date,
            func.coalesce(func.sum(EngagementChatStat.message_count), 0),
            func.coalesce(func.sum(EngagementChatStat.rewarded_points), 0),
            func.coalesce(func.sum(func.cast(EngagementChatStat.reward_claimed, Integer)), 0),
        )
        .where(
            EngagementChatStat.chat_id == chat_id,
            EngagementChatStat.biz_date >= start_date,
        )
        .group_by(EngagementChatStat.biz_date)
        .order_by(EngagementChatStat.biz_date.desc())
    )
    result = await session.execute(stmt)
    rows = []
    for biz_date, message_total, reward_total, claim_count in result.all():
        rows.append(
            {
                "biz_date": biz_date,
                "message_total": int(message_total or 0),
                "reward_total": int(reward_total or 0),
                "claim_count": int(claim_count or 0),
            }
        )
    return rows


async def get_recent_chat_reward_claims(session: AsyncSession, chat_id: int, limit: int = 10) -> list[dict]:
    stmt = (
        select(EngagementChatStat, TgUser)
        .join(TgUser, TgUser.id == EngagementChatStat.user_id)
        .where(
            EngagementChatStat.chat_id == chat_id,
            EngagementChatStat.reward_claimed.is_(True),
        )
        .order_by(EngagementChatStat.biz_date.desc(), EngagementChatStat.rewarded_points.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = []
    for stat, user in result.all():
        name = f"@{user.username}" if user.username else (user.first_name or str(stat.user_id))
        rows.append(
            {
                "user_id": stat.user_id,
                "label": name,
                "biz_date": stat.biz_date,
                "rewarded_points": stat.rewarded_points,
                "streak_days": stat.streak_days,
                "message_count": stat.message_count,
            }
        )
    return rows


async def get_chat_reward_top_users(session: AsyncSession, chat_id: int, days: int = 7, *, limit: int = 5) -> list[dict]:
    start_date = business_date() - dt.timedelta(days=max(days - 1, 0))
    stmt = (
        select(
            EngagementChatStat.user_id,
            func.coalesce(func.sum(EngagementChatStat.message_count), 0).label("message_total"),
            TgUser.username,
            TgUser.first_name,
        )
        .join(TgUser, TgUser.id == EngagementChatStat.user_id)
        .where(
            EngagementChatStat.chat_id == chat_id,
            EngagementChatStat.biz_date >= start_date,
        )
        .group_by(EngagementChatStat.user_id, TgUser.username, TgUser.first_name)
        .order_by(func.sum(EngagementChatStat.message_count).desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = []
    for user_id, message_total, username, first_name in result.all():
        rows.append(
            {
                "user_id": user_id,
                "label": f"@{username}" if username else (first_name or str(user_id)),
                "message_total": int(message_total or 0),
            }
        )
    return rows


async def try_claim_chat_reward(session: AsyncSession, chat_id: int, user_id: int) -> tuple[int, int] | None:
    from backend.features.activity.services.engagement_claim_receipts import reward_receipt,previous_streak as receipt_streak
    reward = await get_or_create_chat_reward(session, chat_id)
    if not reward.enabled:
        return None
    today = business_date()
    stat = await get_or_create_chat_stat(session, chat_id, user_id, biz_date=today)
    if stat.reward_claimed or await reward_receipt(session,chat_id,user_id,day=today) is not None:
        raise ValidationError("今天已经领取过水群奖励了。")
    if stat.message_count < reward.daily_message_target:
        raise ValidationError(f"今日发言数还未达标，当前 {stat.message_count}/{reward.daily_message_target}。")

    yesterday = today - dt.timedelta(days=1)
    prev = await get_or_create_chat_stat(session, chat_id, user_id, biz_date=yesterday)
    previous_streak = await receipt_streak(session,chat_id,user_id,day=yesterday,
        fallback=prev.streak_days if prev.reward_claimed else 0)
    streak = previous_streak + 1
    if reward.after_7d_mode == "reset" and streak > _TRY_CLAIM_CHAT_REWARD_THRESHOLD_7:
        streak = 1
    stat.streak_days = streak
    plan = reward.reward_points_plan or DEFAULT_CHAT_REWARD_PLAN
    index = reward_plan_index(reward.reward_type, streak=streak, size=len(plan))
    points = plan[index]
    stat.reward_claimed = True
    stat.rewarded_points = points
    stat.updated_at = now_utc()
    if points > 0:
        await ensure_user(session, user_id, None, first_name=None, last_name=None, language_code=None)
        await change_points(
            session,
            chat_id,
            user_id,
            amount=points,
            txn_type=PointsTxnType.reward.value,
            reason="水群激励奖励",
        )
    await session.flush()
    return points, streak


def reward_plan_index(mode: str, *, streak: int, size: int) -> int:
    if mode == "daily":
        return 0
    if mode == "weekly_cycle":
        return (streak - 1) % size
    return min(streak - 1, size - 1)


def business_date():
    from backend.shared.time_helper import LOCAL_TIMEZONE
    return now_utc().astimezone(LOCAL_TIMEZONE).date()
