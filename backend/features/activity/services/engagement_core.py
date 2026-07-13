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
_PARSE_REWARD_PLAN_THRESHOLD_7 = 7



DEFAULT_CHAT_REWARD_PLAN = [30, 50, 70, 90, 110, 130, 150]


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
        reward = EngagementChatReward(chat_id=chat_id, reward_points_plan=DEFAULT_CHAT_REWARD_PLAN.copy())
        session.add(reward)
        await session.flush()
    return reward


async def get_or_create_chat_stat(session: AsyncSession, chat_id: int, user_id: int, *, biz_date: dt.date) -> EngagementChatStat:
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
    if len(parts) != _PARSE_REWARD_PLAN_THRESHOLD_7:
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


def _normalize_egg_template_key(key: str) -> str:
    normalized = re.sub(r"\s+", "", key.strip().strip("【】"))
    clue_reward = re.fullmatch(r"线索([1-4])奖励", normalized)
    if clue_reward:
        return f"奖励{clue_reward.group(1)}"
    clue_time = re.fullmatch(r"线索([1-4])时间", normalized)
    if clue_time:
        return f"时间{clue_time.group(1)}"
    aliases = {
        "活动标题": "标题",
        "谜底": "答案",
        "群id": "群ID",
        "群Id": "群ID",
        "群ID": "群ID",
    }
    return aliases.get(normalized, normalized)


def _parse_egg_template_line(line: str) -> tuple[str, str] | None:
    if re.fullmatch(r"(?:@\w+\s+)?添加彩蛋", line, flags=re.IGNORECASE):
        return None
    if line in {"新建彩蛋的", "有奖彩蛋"}:
        return None

    bracket_match = re.fullmatch(r"【([^】]+)】\s*(.*)", line)
    if bracket_match:
        return _normalize_egg_template_key(bracket_match.group(1)), bracket_match.group(2).strip()

    if "=" in line:
        key, value = [part.strip() for part in line.split("=", 1)]
        return _normalize_egg_template_key(key), value

    colon_match = re.fullmatch(r"([^:：]{1,16})[:：]\s*(.*)", line)
    if colon_match:
        return _normalize_egg_template_key(colon_match.group(1)), colon_match.group(2).strip()

    raise ValidationError(f"彩蛋模板格式错误：`{line}`，请使用 【字段】内容 或 键=值。")


def _parse_reward_points(raw: str, reward_key: str) -> int:
    value = raw.strip()
    if re.fullmatch(r"\d+", value):
        return int(value)
    match = re.fullmatch(r"(\d+)\s*(?:积分|主积分)", value)
    if match:
        return int(match.group(1))
    raise ValidationError(f"{reward_key} 只支持积分奖励，请填写 300 或 300积分。")


def _parse_clue_time(raw: str, time_key: str) -> str:
    match = re.search(r"(?:^|\s)([01]\d|2[0-3]):([0-5]\d)(?:$|\s)", raw.strip())
    if not match:
        raise ValidationError(f"{time_key} 必须包含 HH:MM，例如 09:00 或 2026-04-15 09:00。")
    return f"{match.group(1)}:{match.group(2)}"


def _parse_template_chat_id(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.search(r"-?\d+", raw)
    return int(match.group(0)) if match else None


def _parse_clue_rows(mapping: dict[str, str]) -> tuple[list[str], list[int], list[str]]:
    clues: list[str] = []
    rewards: list[int] = []
    times: list[str] = []
    for idx in range(1, 5):
        clue_key = f"线索{idx}"
        reward_key = f"奖励{idx}"
        time_key = f"时间{idx}"
        if clue_key not in mapping or reward_key not in mapping or time_key not in mapping:
            raise ValidationError(
                f"彩蛋模板缺少 `{clue_key}` / `{reward_key}` / `{time_key}`，"
                f"也支持 `【线索{idx}】` / `【线索{idx}奖励】` / `【线索{idx}时间】`。"
            )
        clue_text = mapping[clue_key].strip()
        if not clue_text:
            raise ValidationError(f"{clue_key} 不能为空。")
        clues.append(clue_text)
        rewards.append(_parse_reward_points(mapping[reward_key], reward_key))
        times.append(_parse_clue_time(mapping[time_key], time_key))
    return clues, rewards, times


def parse_egg_template(raw: str) -> dict:
    mapping: dict[str, str] = {}
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        parsed_line = _parse_egg_template_line(line)
        if parsed_line is None:
            continue
        key, value = parsed_line
        mapping[key] = value
    if "答案" not in mapping:
        raise ValidationError("彩蛋模板缺少 `答案=` 或 `【答案】`。")
    clues, rewards, times = _parse_clue_rows(mapping)
    answer = mapping["答案"].strip()
    if not answer:
        raise ValidationError("彩蛋答案不能为空。")
    return {
        "title": mapping.get("标题", "").strip() or None,
        "chat_id": _parse_template_chat_id(mapping.get("群ID")),
        "answer": answer,
        "clues": clues,
        "clue_rewards": rewards,
        "clue_times": times,
    }
