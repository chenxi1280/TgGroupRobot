from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.expansion import (
    EngagementChatReward,
    EngagementChatStat,
    EngagementEgg,
    EngagementSetting,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService


def now_utc() -> dt.datetime:
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
