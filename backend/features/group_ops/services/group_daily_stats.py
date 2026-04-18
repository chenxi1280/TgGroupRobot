from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSubscription, GroupDailyStats, SignInLog
from backend.shared.time_helper import LOCAL_TIMEZONE


ANNOUNCEMENT_LINK_TEXT = "保安公告栏 👉 点击关注 (https://t.me/abaoantips)"


@dataclass(frozen=True)
class GroupDayCounts:
    joins: int = 0
    leaves: int = 0
    signs: int = 0


@dataclass(frozen=True)
class AdminMenuStats:
    today: GroupDayCounts
    yesterday: GroupDayCounts
    expires_at_text: str


def _today(now: dt.datetime | None = None) -> dt.date:
    return (now or dt.datetime.now(dt.UTC)).astimezone(LOCAL_TIMEZONE).date()


async def _get_or_create_stats(session: AsyncSession, chat_id: int, stat_date: dt.date) -> GroupDailyStats:
    result = await session.execute(
        select(GroupDailyStats).where(
            and_(
                GroupDailyStats.chat_id == chat_id,
                GroupDailyStats.stat_date == stat_date,
            )
        )
    )
    stats = result.scalar_one_or_none()
    if stats is None:
        stats = GroupDailyStats(chat_id=chat_id, stat_date=stat_date)
        session.add(stats)
        await session.flush()
    return stats


async def record_group_join_event(
    session: AsyncSession,
    chat_id: int,
    count: int = 1,
    *,
    stat_date: dt.date | None = None,
) -> None:
    if count <= 0:
        return
    stats = await _get_or_create_stats(session, chat_id, stat_date or _today())
    stats.join_count += count
    stats.updated_at = dt.datetime.now(dt.UTC)


async def record_group_leave_event(
    session: AsyncSession,
    chat_id: int,
    count: int = 1,
    *,
    stat_date: dt.date | None = None,
) -> None:
    if count <= 0:
        return
    stats = await _get_or_create_stats(session, chat_id, stat_date or _today())
    stats.leave_count += count
    stats.updated_at = dt.datetime.now(dt.UTC)


def _format_expire_at(end_at: dt.datetime | None) -> str:
    if end_at is None:
        return "永久"
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=dt.UTC)
    return end_at.astimezone(LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M")


async def _sign_count(session: AsyncSession, chat_id: int, sign_date: dt.date) -> int:
    start_at = dt.datetime.combine(sign_date, dt.time.min, tzinfo=LOCAL_TIMEZONE).astimezone(dt.UTC)
    end_at = start_at + dt.timedelta(days=1)
    result = await session.execute(
        select(func.count(SignInLog.id)).where(
            and_(
                SignInLog.chat_id == chat_id,
                SignInLog.created_at >= start_at,
                SignInLog.created_at < end_at,
            )
        )
    )
    return int(result.scalar() or 0)


async def _day_counts(session: AsyncSession, chat_id: int, stat_date: dt.date) -> GroupDayCounts:
    result = await session.execute(
        select(GroupDailyStats).where(
            and_(
                GroupDailyStats.chat_id == chat_id,
                GroupDailyStats.stat_date == stat_date,
            )
        )
    )
    stats = result.scalar_one_or_none()
    signs = await _sign_count(session, chat_id, stat_date)
    if stats is None:
        return GroupDayCounts(signs=signs)
    return GroupDayCounts(
        joins=int(stats.join_count or 0),
        leaves=int(stats.leave_count or 0),
        signs=signs,
    )


async def get_admin_menu_stats(
    session: AsyncSession,
    chat_id: int,
    *,
    now: dt.datetime | None = None,
) -> AdminMenuStats:
    today = _today(now)
    yesterday = today - dt.timedelta(days=1)
    subscription_result = await session.execute(
        select(ChatSubscription.end_at).where(ChatSubscription.chat_id == chat_id)
    )

    return AdminMenuStats(
        today=await _day_counts(session, chat_id, today),
        yesterday=await _day_counts(session, chat_id, yesterday),
        expires_at_text=_format_expire_at(subscription_result.scalar_one_or_none()),
    )
