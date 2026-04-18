from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import Lottery, LotteryParticipant, LotteryWinner
from backend.platform.db.schema.models.expansion import LotterySetting


async def create_lottery(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    draw_time,
    prizes: list[dict],
    description: str | None = None,
    lottery_type: str = "common",
    draw_mode: str = "random",
    qualification_rules: dict | None = None,
    min_points: int = 0,
    max_participants: int = 0,
    participation_cost: int = 0,
    join_start_time=None,
    join_end_time=None,
    requirement_days: int = 0,
) -> Lottery:
    lottery = Lottery(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        title=title,
        description=description,
        lottery_type=lottery_type,
        draw_time=draw_time,
        prizes=prizes,
        draw_mode=draw_mode,
        status="pending",
        qualification_rules=qualification_rules or {},
        min_points=min_points,
        max_participants=max_participants,
        participation_cost=participation_cost,
        join_start_time=join_start_time,
        join_end_time=join_end_time,
        requirement_days=requirement_days,
    )
    session.add(lottery)
    await session.flush()
    return lottery


async def get_or_create_lottery_setting(session: AsyncSession, chat_id: int) -> LotterySetting:
    setting = await session.get(LotterySetting, chat_id)
    if setting is None:
        setting = LotterySetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_lottery_setting(session: AsyncSession, chat_id: int, **updates) -> LotterySetting:
    setting = await get_or_create_lottery_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    await session.flush()
    return setting


async def get_lottery(session: AsyncSession, lottery_id: int) -> Lottery | None:
    result = await session.execute(select(Lottery).where(Lottery.id == lottery_id))
    return result.scalar_one_or_none()


async def get_chat_lotteries(
    session: AsyncSession,
    chat_id: int,
    status: str | None = None,
    lottery_type: str | None = None,
) -> list[Lottery]:
    stmt = select(Lottery).where(Lottery.chat_id == chat_id)
    if status:
        stmt = stmt.where(Lottery.status == status)
    if lottery_type and lottery_type != "all":
        stmt = stmt.where(Lottery.lottery_type == lottery_type)
    result = await session.execute(stmt.order_by(Lottery.created_at.desc()))
    return list(result.scalars().all())


async def count_lotteries_by_type(session: AsyncSession, chat_id: int) -> dict[str, int]:
    stmt = (
        select(Lottery.lottery_type, func.count(Lottery.id))
        .where(Lottery.chat_id == chat_id)
        .group_by(Lottery.lottery_type)
    )
    result = await session.execute(stmt)
    counts = {"common": 0, "points": 0, "invite": 0, "activity": 0}
    for lottery_type, count in result.all():
        counts[lottery_type] = int(count)
    return counts


async def get_lottery_stats(session: AsyncSession, chat_id: int) -> dict[str, int]:
    stmt = (
        select(Lottery.status, func.count(Lottery.id))
        .where(Lottery.chat_id == chat_id)
        .group_by(Lottery.status)
    )
    result = await session.execute(stmt)
    stats: dict[str, int] = {"total": 0, "pending": 0, "completed": 0, "cancelled": 0}
    for status, count in result.all():
        stats[status] = count
        stats["total"] += count
    return stats


async def get_lottery_participants(session: AsyncSession, lottery_id: int) -> list[LotteryParticipant]:
    result = await session.execute(select(LotteryParticipant).where(LotteryParticipant.lottery_id == lottery_id))
    return list(result.scalars().all())


async def get_lottery_participant_count(session: AsyncSession, lottery_id: int) -> int:
    result = await session.execute(select(func.count(LotteryParticipant.id)).where(LotteryParticipant.lottery_id == lottery_id))
    return result.scalar() or 0


async def get_user_lottery_history(session: AsyncSession, user_id: int, chat_id: int | None = None) -> list[LotteryWinner]:
    stmt = select(LotteryWinner).join(Lottery).where(LotteryWinner.user_id == user_id)
    if chat_id is not None:
        stmt = stmt.where(Lottery.chat_id == chat_id)
    result = await session.execute(stmt.order_by(LotteryWinner.created_at.desc()))
    return list(result.scalars().all())
