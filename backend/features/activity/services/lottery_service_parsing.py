"""抽奖文本配置解析与公告格式化。"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from backend.features.activity.services.lottery_service_types import ParsedLotteryConfig
from backend.features.activity.services.lottery_subscription import (
    format_lottery_subscribe_targets,
    parse_lottery_subscribe_targets,
)
from backend.features.activity.services.lottery_winner_parsing import (
    CONFIG_FIELD_NAMES,
    WINNER_FIELD_PREFIXES,
    collect_winner_reference_values,
    is_winner_field,
    parse_preset_winner_values,
    split_config_line,
    validate_unique_prize_names,
)

LOTTERY_TYPE_CODES = {
    "common": "c",
    "points": "p",
    "invite": "i",
    "activity": "a",
    "subscribe": "s",
}
LOTTERY_TYPE_BY_CODE = {code: value for value, code in LOTTERY_TYPE_CODES.items()}
SELECTION_MODE_CODES = {"threshold_random": "t", "ranking_random": "r"}
SELECTION_MODE_BY_CODE = {code: value for value, code in SELECTION_MODE_CODES.items()}
DRAW_TRIGGER_CODES = {"full_participants": "f", "time_deadline": "d"}
DRAW_TRIGGER_BY_CODE = {code: value for value, code in DRAW_TRIGGER_CODES.items()}

MIN_CONFIG_LINES = 4
MIN_PRIZE_PARTS = 2
POINTS_REWARD_INDEX = 2
DEFAULT_QUALIFICATION_DAYS = 7
FAR_FUTURE_DAYS = 3650
LOCAL_TIMEZONE_HOURS = 8
VALID_DRAW_TRIGGERS = {"time_deadline", "full_participants"}
NUMERIC_FIELDS = {
    "最低积分": ("min_points", "最低积分"),
    "参与费用": ("participation_cost", "参与费用"),
    "最大人数": ("max_participants", "最大人数"),
    "满员人数": ("max_participants", "最大人数"),
    "入群天数": ("requirement_days", "入群天数"),
    "邀请人数": ("required_invites", "邀请人数"),
    "活跃消息数": ("required_activity_count", "活跃消息数"),
    "统计天数": ("qualification_window_days", "统计天数"),
    "入围人数": ("finalist_limit", "入围人数"),
}


@dataclass(slots=True)
class _ConfigValues:
    draw_time: dt.datetime | None = None
    min_points: int = 0
    participation_cost: int = 0
    max_participants: int = 0
    requirement_days: int = 0
    qualification_window_days: int = 0
    required_invites: int = 0
    required_activity_count: int = 0
    finalist_limit: int = 0
    subscribe_values: list[str] = field(default_factory=list)


def encode_lottery_type(lottery_type: str) -> str:
    return LOTTERY_TYPE_CODES.get(lottery_type, lottery_type)


def decode_lottery_type(value: str | None) -> str:
    return LOTTERY_TYPE_BY_CODE.get(value, value) if value else "common"


def encode_selection_mode(selection_mode: str) -> str:
    return SELECTION_MODE_CODES.get(selection_mode, selection_mode)


def decode_selection_mode(value: str | None) -> str:
    return SELECTION_MODE_BY_CODE.get(value, value) if value else "threshold_random"


def encode_draw_trigger(draw_trigger: str) -> str:
    return DRAW_TRIGGER_CODES.get(draw_trigger, draw_trigger)


def decode_draw_trigger(value: str | None) -> str:
    return DRAW_TRIGGER_BY_CODE.get(value, value) if value else "time_deadline"


def format_lottery_stats_message(stats: dict[str, int]) -> str:
    return (
        f"🎁 抽奖统计\n\n创建的抽奖次数: {stats['total']}\n\n"
        f"已开奖: {stats['completed']}       未开奖: {stats['pending']}"
    )


def lottery_type_label(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
        "subscribe": "📣 强制订阅抽奖",
    }.get(lottery_type, "🎁 抽奖")


def lottery_draw_trigger_label(draw_trigger: str) -> str:
    return {
        "full_participants": "👥 满人开奖",
        "time_deadline": "⏰ 定时开奖",
    }.get(draw_trigger, "⏰ 定时开奖")


def _format_local_time(value: dt.datetime) -> str:
    timezone = dt.timezone(dt.timedelta(hours=LOCAL_TIMEZONE_HOURS))
    return value.astimezone(timezone).strftime("%Y-%m-%d %H:%M")


def _parse_future_time(value: str) -> dt.datetime:
    pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})"
    match = re.search(pattern, value)
    if not match:
        raise ValueError("开奖时间格式错误，请使用: YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    timezone = dt.timezone(dt.timedelta(hours=LOCAL_TIMEZONE_HOURS))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=timezone)
    draw_time_utc = draw_time.astimezone(dt.UTC)
    if draw_time_utc <= dt.datetime.now(dt.UTC):
        raise ValueError("开奖时间必须是未来时间")
    return draw_time_utc


def _parse_non_negative_int(value: str, field_name: str) -> int:
    try:
        return max(0, int(value.strip()))
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是有效数字") from exc


def _parse_title(line: str) -> tuple[str, str | None]:
    title, separator, description = line.strip().partition("|")
    title = title.strip()
    if not title:
        raise ValueError("标题不能为空")
    return title, description.strip() if separator else None


def _collect_subscribe_values(text: str) -> list[str]:
    values: list[str] = []
    target_block = False
    field_names = CONFIG_FIELD_NAMES | set(WINNER_FIELD_PREFIXES)
    for raw_line in text.strip().split("\n")[1:]:
        line = raw_line.strip()
        if not line or line == "奖品:" or is_winner_field(line):
            target_block = False
            continue
        split_line = split_config_line(line)
        if split_line and split_line[0] == "关注目标":
            if split_line[1]:
                values.append(split_line[1])
            else:
                target_block = True
            continue
        if target_block and (split_line is None or split_line[0] not in field_names):
            values.append(line)
        elif target_block:
            target_block = False
    return values


def _apply_field(values: _ConfigValues, field_name: str, field_value: str) -> None:
    if field_name == "开奖时间":
        values.draw_time = _parse_future_time(field_value)
        return
    numeric = NUMERIC_FIELDS.get(field_name)
    if numeric is not None:
        attribute, label = numeric
        setattr(values, attribute, _parse_non_negative_int(field_value, label))


def _parse_fields(text: str, lines: list[str]) -> _ConfigValues:
    values = _ConfigValues(subscribe_values=_collect_subscribe_values(text))
    for line in lines[1:]:
        split_line = split_config_line(line.strip())
        if split_line is not None:
            _apply_field(values, *split_line)
    return values


def _parse_prize(line: str) -> dict:
    parts = line.split(",")
    if len(parts) < MIN_PRIZE_PARTS:
        raise ValueError(f"奖品格式错误: {line}")
    prize_name = parts[0].strip()
    if not prize_name:
        raise ValueError(f"奖品名称不能为空: {line}")
    try:
        quantity = int(parts[1].strip())
    except ValueError as exc:
        raise ValueError(f"奖品数量必须是有效数字: {line}") from exc
    try:
        points = (
            int(parts[POINTS_REWARD_INDEX].strip().replace("积分", "").strip())
            if len(parts) > POINTS_REWARD_INDEX
            else 0
        )
    except ValueError as exc:
        raise ValueError(f"积分奖励格式错误: {parts[POINTS_REWARD_INDEX]}") from exc
    if quantity <= 0:
        raise ValueError(f"奖品数量必须大于 0: {line}")
    return {"name": prize_name, "quantity": quantity, "points_reward": points}


def _parse_prizes(lines: list[str]) -> list[dict]:
    prizes = []
    prize_block = False
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if line == "奖品:":
            prize_block = True
            continue
        if is_winner_field(line):
            prize_block = False
            continue
        if prize_block and line:
            prizes.append(_parse_prize(line))
    if not prizes:
        raise ValueError("至少需要一个奖品")
    validate_unique_prize_names(prizes)
    return prizes


def _validate_values(
    values: _ConfigValues,
    *,
    lottery_type: str,
    selection_mode: str,
    draw_trigger: str,
) -> None:
    if draw_trigger == "time_deadline" and values.draw_time is None:
        raise ValueError("定时开奖必须配置开奖时间，格式如：开奖时间: 2025-12-30 12:00")
    if draw_trigger == "full_participants" and values.max_participants <= 0:
        raise ValueError("满人开奖必须配置最大人数或满员人数，且必须大于 0")
    if lottery_type == "invite" and values.required_invites <= 0:
        raise ValueError("邀请抽奖必须配置邀请人数，格式如：邀请人数: 3")
    if lottery_type == "activity" and values.required_activity_count <= 0:
        raise ValueError("群活跃抽奖必须配置活跃消息数，格式如：活跃消息数: 200")
    if lottery_type in {"invite", "activity"} and values.qualification_window_days <= 0:
        values.qualification_window_days = DEFAULT_QUALIFICATION_DAYS
    if selection_mode == "ranking_random" and values.finalist_limit <= 0:
        raise ValueError("排名入围随机玩法必须配置入围人数，格式如：入围人数: 10")
    if lottery_type == "subscribe" and not values.subscribe_values:
        raise ValueError("强制订阅抽奖必须配置关注目标，格式如：关注目标: @channel")


def parse_lottery_config_text(
    text: str,
    lottery_type: str = "common",
    selection_mode: str = "threshold_random",
    *,
    draw_trigger: str = "time_deadline",
    allow_unresolved_winner_refs: bool = False,
) -> ParsedLotteryConfig:
    lines = text.strip().split("\n")
    if len(lines) < MIN_CONFIG_LINES:
        raise ValueError("配置格式不完整")
    lottery_type = decode_lottery_type(lottery_type)
    selection_mode = decode_selection_mode(selection_mode)
    draw_trigger = decode_draw_trigger(draw_trigger)
    draw_trigger = (
        draw_trigger if draw_trigger in VALID_DRAW_TRIGGERS else "time_deadline"
    )
    title, description = _parse_title(lines[0])
    values = _parse_fields(text, lines)
    prizes = _parse_prizes(lines)
    winner_values = collect_winner_reference_values(text)
    winner_ids, assignments = parse_preset_winner_values(
        winner_values,
        prizes,
        allow_unresolved_refs=allow_unresolved_winner_refs,
    )
    if len(winner_ids) > sum(int(prize.get("quantity", 1)) for prize in prizes):
        raise ValueError("内定中奖人数不能超过奖品总数量")
    _validate_values(
        values,
        lottery_type=lottery_type,
        selection_mode=selection_mode,
        draw_trigger=draw_trigger,
    )
    draw_time = values.draw_time or dt.datetime.now(dt.UTC) + dt.timedelta(
        days=FAR_FUTURE_DAYS
    )
    subscribe_targets = (
        parse_lottery_subscribe_targets("\n".join(values.subscribe_values))
        if lottery_type == "subscribe"
        else None
    )
    return _build_parsed_config(
        values,
        lottery_type=lottery_type,
        selection_mode=selection_mode,
        draw_trigger=draw_trigger,
        title=title,
        description=description,
        draw_time=draw_time,
        prizes=prizes,
        winner_ids=winner_ids,
        assignments=assignments,
        subscribe_targets=subscribe_targets,
    )


def _build_parsed_config(values: _ConfigValues, **kwargs) -> ParsedLotteryConfig:
    return ParsedLotteryConfig(
        lottery_type=kwargs["lottery_type"],
        title=kwargs["title"],
        description=kwargs["description"],
        draw_time=kwargs["draw_time"],
        draw_trigger=kwargs["draw_trigger"],
        min_points=values.min_points,
        participation_cost=values.participation_cost,
        max_participants=values.max_participants,
        requirement_days=values.requirement_days,
        qualification_window_days=values.qualification_window_days,
        required_invites=values.required_invites,
        required_activity_count=values.required_activity_count,
        finalist_limit=values.finalist_limit,
        selection_mode=kwargs["selection_mode"],
        preset_winner_ids=kwargs["winner_ids"],
        prizes=kwargs["prizes"],
        point_type_id=None,
        point_type_name=None,
        subscribe_targets=kwargs["subscribe_targets"],
        subscribe_check_mode="all",
        preset_winner_assignments=kwargs["assignments"],
    )


def _qualification_lines(config: ParsedLotteryConfig) -> list[str]:
    lines = []
    if config.min_points > 0:
        lines.append(f"💰 最低积分: {config.min_points}")
    if config.participation_cost > 0:
        lines.append(
            f"💸 参与费用: {config.participation_cost} {config.point_type_name or '积分'}"
        )
    if config.required_invites > 0:
        lines.append(f"👥 邀请人数门槛: {config.required_invites}")
    if config.required_activity_count > 0:
        lines.append(f"🔥 活跃消息门槛: {config.required_activity_count}")
    if config.qualification_window_days > 0:
        lines.append(f"📊 统计天数: 最近 {config.qualification_window_days} 天")
    if config.max_participants > 0:
        lines.append(f"👥 最大人数: {config.max_participants}")
    if config.requirement_days > 0:
        lines.append(f"📅 入群天数: {config.requirement_days}")
    return lines


def format_lottery_announcement_text(config: ParsedLotteryConfig) -> str:
    lines = [lottery_type_label(config.lottery_type), "", f"📢 {config.title}"]
    if config.description:
        lines.extend(("", config.description))
    lines.extend(("", f"🎛 开奖条件: {lottery_draw_trigger_label(config.draw_trigger)}"))
    if config.draw_trigger == "time_deadline":
        lines.append(f"🕐 截止开奖时间: {_format_local_time(config.draw_time)}")
    lines.extend(_qualification_lines(config))
    if config.lottery_type == "subscribe":
        targets = format_lottery_subscribe_targets(config.subscribe_targets or [])
        lines.append(f"📣 参与条件: 需先关注：{targets}")
    if config.selection_mode == "ranking_random" and config.finalist_limit > 0:
        lines.append(f"🏆 排名入围人数: 前 {config.finalist_limit} 名")
    lines.extend(("", "🎁 奖品:"))
    lines.extend(
        f"  • {prize['name']} x {prize['quantity']}" for prize in config.prizes
    )
    lines.extend(("", _participation_hint(config.selection_mode)))
    return "\n".join(lines)


def _participation_hint(selection_mode: str) -> str:
    if selection_mode == "ranking_random":
        return (
            "💡 本玩法无需点击参与；系统会在开奖时按邀请/活跃排行生成入围名单，再随机开奖。\n"
            "想提高中奖机会，请在截止前继续完成对应的邀请或活跃任务。"
        )
    return "💡 点击下方按钮参与抽奖；参与成功后会在群内看到确认消息。"
