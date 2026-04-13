from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.activity.services.engagement_core import (
    get_or_create_egg,
    get_or_create_setting,
    now_utc,
    parse_egg_template,
)
from backend.features.points.services.points_service import change_points
from backend.platform.db.schema.models.enums import PointsTxnType
from backend.platform.db.schema.models.expansion import EngagementEgg, EngagementEggEvent, EngagementEggHistory


async def create_egg_event(session: AsyncSession, chat_id: int, title: str | None = None) -> EngagementEggEvent:
    await get_or_create_setting(session, chat_id)
    event = EngagementEggEvent(chat_id=chat_id, title=(title or "彩蛋活动").strip()[:128] or "彩蛋活动")
    session.add(event)
    await session.flush()
    return event


async def get_egg_event(session: AsyncSession, chat_id: int, event_id: int) -> EngagementEggEvent | None:
    stmt = select(EngagementEggEvent).where(
        EngagementEggEvent.chat_id == chat_id,
        EngagementEggEvent.id == event_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_egg_events(
    session: AsyncSession,
    chat_id: int,
    status: str | None = None,
    limit: int = 20,
) -> list[EngagementEggEvent]:
    stmt = select(EngagementEggEvent).where(EngagementEggEvent.chat_id == chat_id)
    if status and status != "all":
        stmt = stmt.where(EngagementEggEvent.status == status)
    stmt = stmt.order_by(
        EngagementEggEvent.created_at.desc(),
        EngagementEggEvent.id.desc(),
    ).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_egg_event_counts(session: AsyncSession, chat_id: int) -> dict[str, int]:
    stmt = (
        select(EngagementEggEvent.status, func.count(EngagementEggEvent.id))
        .where(EngagementEggEvent.chat_id == chat_id)
        .group_by(EngagementEggEvent.status)
    )
    result = await session.execute(stmt)
    counts = {"all": 0, "idle": 0, "running": 0, "finished": 0}
    for status, count in result.all():
        counts[str(status)] = int(count or 0)
        counts["all"] += int(count or 0)
    return counts


async def update_egg_event(session: AsyncSession, event: EngagementEggEvent, **updates) -> EngagementEggEvent:
    for key, value in updates.items():
        if hasattr(event, key):
            setattr(event, key, value)
    event.updated_at = now_utc()
    await session.flush()
    return event


async def update_egg_from_template(session: AsyncSession, chat_id: int, raw: str) -> EngagementEgg:
    parsed = parse_egg_template(raw)
    egg = await get_or_create_egg(session, chat_id)
    await archive_egg_snapshot(session, egg, reward_points=0)
    egg.enabled = True
    egg.answer = parsed["answer"]
    egg.clues = parsed["clues"]
    egg.clue_rewards = parsed["clue_rewards"]
    egg.clue_times = parsed["clue_times"]
    egg.status = "running"
    egg.winner_user_id = None
    egg.published_clue_count = 0
    egg.updated_at = now_utc()
    await session.flush()
    return egg


async def update_egg_event_from_template(
    session: AsyncSession,
    chat_id: int,
    raw: str,
    event_id: int | None = None,
) -> EngagementEggEvent:
    parsed = parse_egg_template(raw)
    event = await get_egg_event(session, chat_id, event_id) if event_id else None
    if event is None:
        event = await create_egg_event(session, chat_id, title=parsed.get("title"))
    else:
        await archive_egg_snapshot(session, event, reward_points=0)
    event.title = (parsed.get("title") or event.title or "彩蛋活动")[:128]
    event.enabled = True
    event.answer = parsed["answer"]
    event.clues = parsed["clues"]
    event.clue_rewards = parsed["clue_rewards"]
    event.clue_times = parsed["clue_times"]
    event.status = "running"
    event.winner_user_id = None
    event.published_clue_count = 0
    event.updated_at = now_utc()
    await session.flush()
    return event


async def try_claim_egg(session: AsyncSession, chat_id: int, user_id: int, answer: str) -> int | None:
    stmt = (
        select(EngagementEggEvent)
        .where(
            EngagementEggEvent.chat_id == chat_id,
            EngagementEggEvent.enabled.is_(True),
            EngagementEggEvent.status == "running",
            EngagementEggEvent.answer.is_not(None),
            EngagementEggEvent.winner_user_id.is_(None),
        )
        .order_by(EngagementEggEvent.created_at.asc(), EngagementEggEvent.id.asc())
    )
    result = await session.execute(stmt)
    events = list(result.scalars().all())
    normalized_answer = answer.strip().lower()
    for event in events:
        if (event.answer or "").strip().lower() != normalized_answer:
            continue
        event.winner_user_id = user_id
        event.status = "finished"
        published = max(event.published_clue_count, 1)
        reward_index = min(published - 1, max(len(event.clue_rewards) - 1, 0))
        reward_points = event.clue_rewards[reward_index] if event.clue_rewards else 0
        if reward_points > 0:
            ok, _ = await change_points(
                session,
                chat_id,
                user_id,
                reward_points,
                PointsTxnType.reward.value,
                reason=f"彩蛋奖励：{event.title}",
            )
            if not ok:
                reward_points = 0
        event.updated_at = now_utc()
        await archive_egg_snapshot(session, event, reward_points=reward_points)
        await session.flush()
        return reward_points
    return None


async def get_due_clues(session: AsyncSession, hhmm: str) -> list[tuple[EngagementEggEvent, int]]:
    stmt = select(EngagementEggEvent).where(
        EngagementEggEvent.enabled.is_(True),
        EngagementEggEvent.status == "running",
    )
    result = await session.execute(stmt)
    events = list(result.scalars().all())
    due: list[tuple[EngagementEggEvent, int]] = []
    for event in events:
        next_index = event.published_clue_count
        if next_index < len(event.clue_times) and event.clue_times[next_index] == hhmm:
            due.append((event, next_index))
    return due


async def mark_clue_published(session: AsyncSession, event: EngagementEggEvent, clue_index: int) -> None:
    event.published_clue_count = max(event.published_clue_count, clue_index + 1)
    event.updated_at = now_utc()
    await session.flush()


async def publish_next_clue(
    session: AsyncSession,
    chat_id: int,
    event_id: int | None = None,
) -> tuple[EngagementEggEvent, int, str, int] | None:
    event = await get_egg_event(session, chat_id, event_id) if event_id else None
    if event is None:
        stmt = (
            select(EngagementEggEvent)
            .where(
                EngagementEggEvent.chat_id == chat_id,
                EngagementEggEvent.enabled.is_(True),
                EngagementEggEvent.status == "running",
            )
            .order_by(EngagementEggEvent.created_at.asc(), EngagementEggEvent.id.asc())
        )
        result = await session.execute(stmt)
        event = result.scalars().first()
    if event is None or not event.enabled or event.status != "running":
        return None
    next_index = event.published_clue_count
    if next_index >= len(event.clues):
        return None
    clue_text = event.clues[next_index]
    reward_points = event.clue_rewards[next_index] if next_index < len(event.clue_rewards) else 0
    await mark_clue_published(session, event, next_index)
    return event, next_index, clue_text, reward_points


async def archive_egg_snapshot(
    session: AsyncSession,
    egg: EngagementEgg | EngagementEggEvent,
    reward_points: int = 0,
) -> None:
    if not egg.answer and not egg.clues and egg.winner_user_id is None:
        return
    history = EngagementEggHistory(
        chat_id=egg.chat_id,
        event_id=getattr(egg, "id", None),
        title=getattr(egg, "title", None),
        answer=egg.answer,
        winner_user_id=egg.winner_user_id,
        reward_points=reward_points,
        status=egg.status,
        published_clue_count=egg.published_clue_count,
        snapshot_data={
            "clues": egg.clues or [],
            "clue_rewards": egg.clue_rewards or [],
            "clue_times": egg.clue_times or [],
        },
    )
    session.add(history)
    await session.flush()


async def list_egg_history(session: AsyncSession, chat_id: int, limit: int = 10) -> list[EngagementEggHistory]:
    stmt = (
        select(EngagementEggHistory)
        .where(EngagementEggHistory.chat_id == chat_id)
        .order_by(EngagementEggHistory.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_latest_running_egg_event(session: AsyncSession, chat_id: int) -> EngagementEggEvent | None:
    stmt = (
        select(EngagementEggEvent)
        .where(
            EngagementEggEvent.chat_id == chat_id,
            EngagementEggEvent.enabled.is_(True),
            EngagementEggEvent.status == "running",
        )
        .order_by(EngagementEggEvent.created_at.desc(), EngagementEggEvent.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()
