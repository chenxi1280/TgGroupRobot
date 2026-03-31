from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import TgUser
from bot.models.enums import PointsTxnType
from bot.models.expansion import (
    EngagementChatReward,
    EngagementChatStat,
    EngagementEgg,
    EngagementEggEvent,
    EngagementEggHistory,
    EngagementSetting,
)
from bot.services.activity.points_service import change_points
from bot.services.base import ValidationError
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.user_service import ensure_user


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> EngagementSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(EngagementSetting, chat_id)
    if setting is None:
        setting = EngagementSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def get_or_create_egg(session: AsyncSession, chat_id: int) -> EngagementEgg:
    await get_or_create_setting(session, chat_id)
    egg = await session.get(EngagementEgg, chat_id)
    if egg is None:
        egg = EngagementEgg(chat_id=chat_id)
        session.add(egg)
        await session.flush()
    return egg


async def get_or_create_chat_reward(session: AsyncSession, chat_id: int) -> EngagementChatReward:
    await get_or_create_setting(session, chat_id)
    reward = await session.get(EngagementChatReward, chat_id)
    if reward is None:
        reward = EngagementChatReward(chat_id=chat_id, reward_points_plan=[10, 20, 30, 40, 50, 60, 70])
        session.add(reward)
        await session.flush()
    return reward


async def get_or_create_chat_stat(session: AsyncSession, chat_id: int, user_id: int, biz_date: dt.date) -> EngagementChatStat:
    stmt = select(EngagementChatStat).where(
        EngagementChatStat.chat_id == chat_id,
        EngagementChatStat.user_id == user_id,
        EngagementChatStat.biz_date == biz_date,
    )
    result = await session.execute(stmt)
    stat = result.scalar_one_or_none()
    if stat is None:
        stat = EngagementChatStat(chat_id=chat_id, user_id=user_id, biz_date=biz_date)
        session.add(stat)
        await session.flush()
    return stat


def parse_reward_plan(raw: str) -> list[int]:
    parts = [item for item in re.split(r"[\s,，]+", raw.strip()) if item]
    if len(parts) != 7:
        raise ValidationError("奖励数组必须正好包含 7 个数字，使用空格分隔。")
    numbers: list[int] = []
    for item in parts:
        if not re.fullmatch(r"\d+", item):
            raise ValidationError("奖励数组只能包含非负整数。")
        numbers.append(int(item))
    for prev, current in zip(numbers, numbers[1:]):
        if current < prev:
            raise ValidationError("后面的数字不能比前面的数字小。")
    return numbers


def parse_egg_template(raw: str) -> dict:
    mapping: dict[str, str] = {}
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        if "=" not in line:
            raise ValidationError(f"彩蛋模板格式错误：`{line}`，请使用 键=值。")
        key, value = [part.strip() for part in line.split("=", 1)]
        mapping[key] = value
    if "答案" not in mapping:
        raise ValidationError("彩蛋模板缺少 `答案=`。")
    clues: list[str] = []
    rewards: list[int] = []
    times: list[str] = []
    for idx in range(1, 5):
        clue_key = f"线索{idx}"
        reward_key = f"奖励{idx}"
        time_key = f"时间{idx}"
        if clue_key not in mapping or reward_key not in mapping or time_key not in mapping:
            raise ValidationError(f"彩蛋模板缺少 `{clue_key}` / `{reward_key}` / `{time_key}`。")
        clues.append(mapping[clue_key])
        if not re.fullmatch(r"\d+", mapping[reward_key]):
            raise ValidationError(f"{reward_key} 必须是整数。")
        rewards.append(int(mapping[reward_key]))
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", mapping[time_key]):
            raise ValidationError(f"{time_key} 必须是 HH:MM。")
        times.append(mapping[time_key])
    return {
        "title": mapping.get("标题", "").strip() or None,
        "answer": mapping["答案"],
        "clues": clues,
        "clue_rewards": rewards,
        "clue_times": times,
    }


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
    event.updated_at = _now()
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
    egg.updated_at = _now()
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
    event.updated_at = _now()
    await session.flush()
    return event


async def update_chat_reward(session: AsyncSession, chat_id: int, **updates) -> EngagementChatReward:
    reward = await get_or_create_chat_reward(session, chat_id)
    for key, value in updates.items():
        if hasattr(reward, key):
            setattr(reward, key, value)
    reward.updated_at = _now()
    await session.flush()
    return reward


async def increase_message_count(session: AsyncSession, chat_id: int, user_id: int) -> EngagementChatStat:
    biz_date = _now().date()
    stat = await get_or_create_chat_stat(session, chat_id, user_id, biz_date)
    stat.message_count += 1
    stat.updated_at = _now()
    await session.flush()
    return stat


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
        event.updated_at = _now()
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
    event.updated_at = _now()
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


async def get_recent_chat_reward_stats(session: AsyncSession, chat_id: int, days: int = 7) -> list[dict]:
    start_date = _now().date() - dt.timedelta(days=max(days - 1, 0))
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


async def get_chat_reward_top_users(session: AsyncSession, chat_id: int, days: int = 7, limit: int = 5) -> list[dict]:
    start_date = _now().date() - dt.timedelta(days=max(days - 1, 0))
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
    reward = await get_or_create_chat_reward(session, chat_id)
    if not reward.enabled:
        return None
    today = _now().date()
    stat = await get_or_create_chat_stat(session, chat_id, user_id, today)
    if stat.reward_claimed:
        raise ValidationError("今天已经领取过水群奖励了。")
    if stat.message_count < reward.daily_message_target:
        raise ValidationError(f"今日发言数还未达标，当前 {stat.message_count}/{reward.daily_message_target}。")

    yesterday = today - dt.timedelta(days=1)
    prev = await get_or_create_chat_stat(session, chat_id, user_id, yesterday)
    previous_streak = prev.streak_days if prev.reward_claimed else 0
    streak = previous_streak + 1
    if reward.after_7d_mode == "reset" and streak > 7:
        streak = 1
    stat.streak_days = streak
    plan = reward.reward_points_plan or [10, 20, 30, 40, 50, 60, 70]
    if reward.reward_type == "weekly_cycle":
        index = (streak - 1) % len(plan)
    else:
        index = min(streak - 1, len(plan) - 1)
    points = plan[index]
    stat.reward_claimed = True
    stat.rewarded_points = points
    stat.updated_at = _now()
    if points > 0:
        await ensure_user(session, user_id, None, None, None, None)
        await change_points(
            session,
            chat_id,
            user_id,
            points,
            PointsTxnType.reward.value,
            reason="水群激励奖励",
        )
    await session.flush()
    return points, streak
