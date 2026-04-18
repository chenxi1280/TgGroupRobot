from __future__ import annotations

import datetime as dt
import re

from backend.features.activity.services.lottery_service_types import ParsedLotteryConfig


LOTTERY_TYPE_CODES = {
    "common": "c",
    "points": "p",
    "invite": "i",
    "activity": "a",
}
LOTTERY_TYPE_BY_CODE = {code: value for value, code in LOTTERY_TYPE_CODES.items()}
SELECTION_MODE_CODES = {
    "threshold_random": "t",
    "ranking_random": "r",
}
SELECTION_MODE_BY_CODE = {code: value for value, code in SELECTION_MODE_CODES.items()}
DRAW_TRIGGER_CODES = {
    "full_participants": "f",
    "time_deadline": "d",
}
DRAW_TRIGGER_BY_CODE = {code: value for value, code in DRAW_TRIGGER_CODES.items()}
WINNER_FIELD_PREFIXES = ("内定中奖人", "内设中奖人", "预设中奖人", "指定中奖人", "中奖人员")
CONFIG_FIELD_NAMES = {
    "开奖时间",
    "最低积分",
    "参与费用",
    "最大人数",
    "满员人数",
    "入群天数",
    "邀请人数",
    "活跃消息数",
    "统计天数",
    "入围人数",
}


def encode_lottery_type(lottery_type: str) -> str:
    return LOTTERY_TYPE_CODES.get(lottery_type, lottery_type)


def decode_lottery_type(value: str | None) -> str:
    if not value:
        return "common"
    return LOTTERY_TYPE_BY_CODE.get(value, value)


def encode_selection_mode(selection_mode: str) -> str:
    return SELECTION_MODE_CODES.get(selection_mode, selection_mode)


def decode_selection_mode(value: str | None) -> str:
    if not value:
        return "threshold_random"
    return SELECTION_MODE_BY_CODE.get(value, value)


def encode_draw_trigger(draw_trigger: str) -> str:
    return DRAW_TRIGGER_CODES.get(draw_trigger, draw_trigger)


def decode_draw_trigger(value: str | None) -> str:
    if not value:
        return "time_deadline"
    return DRAW_TRIGGER_BY_CODE.get(value, value)


def format_lottery_stats_message(stats: dict[str, int]) -> str:
    return (
        f"🎁 抽奖统计\n\n"
        f"创建的抽奖次数: {stats['total']}\n\n"
        f"已开奖: {stats['completed']}       未开奖: {stats['pending']}"
    )


def lottery_type_label(lottery_type: str) -> str:
    return {
        "common": "🎁 通用抽奖",
        "points": "💰 积分抽奖",
        "invite": "👥 邀请抽奖",
        "activity": "🔥 群活跃抽奖",
    }.get(lottery_type, "🎁 抽奖")


def lottery_draw_trigger_label(draw_trigger: str) -> str:
    return {
        "full_participants": "👥 满人开奖",
        "time_deadline": "⏰ 定时开奖",
    }.get(draw_trigger, "⏰ 定时开奖")


def _format_local_time(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")


def _split_config_line(line: str) -> tuple[str, str] | None:
    for separator in (":", "："):
        if separator in line:
            key, value = line.split(separator, 1)
            return key.strip(), value.strip()
    return None


def _is_winner_field(line: str) -> bool:
    split = _split_config_line(line)
    if split is None:
        return False
    key, _value = split
    return key in WINNER_FIELD_PREFIXES


def _parse_future_time(value: str) -> dt.datetime:
    time_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})"
    match = re.search(time_pattern, value)
    if not match:
        raise ValueError("开奖时间格式错误，请使用: YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    local_tz = dt.timezone(dt.timedelta(hours=8))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz)
    draw_time_utc = draw_time.astimezone(dt.timezone.utc)
    if draw_time_utc <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("开奖时间必须是未来时间")
    return draw_time_utc


def _parse_non_negative_int(value: str, field_name: str) -> int:
    try:
        return max(0, int(value.strip()))
    except ValueError:
        raise ValueError(f"{field_name}必须是有效数字")


def _parse_winner_ids(value: str) -> list[int]:
    ids: list[int] = []
    for raw in re.findall(r"\d+", value):
        user_id = int(raw)
        if user_id > 0 and user_id not in ids:
            ids.append(user_id)
    if value.strip() and not ids and not any(marker in value for marker in ("可选", "无", "不设置", "留空")):
        raise ValueError("内定中奖人请填写 Telegram 数字用户ID，多个ID用逗号分隔")
    return ids


def parse_lottery_config_text(
    text: str,
    lottery_type: str = "common",
    selection_mode: str = "threshold_random",
    draw_trigger: str = "time_deadline",
) -> ParsedLotteryConfig:
    lines = text.strip().split("\n")
    if len(lines) < 4:
        raise ValueError("配置格式不完整")
    lottery_type = decode_lottery_type(lottery_type)
    selection_mode = decode_selection_mode(selection_mode)
    draw_trigger = decode_draw_trigger(draw_trigger)
    if draw_trigger not in {"time_deadline", "full_participants"}:
        draw_trigger = "time_deadline"

    title_line = lines[0].strip()
    if "|" in title_line:
        title, description = title_line.split("|", 1)
        title = title.strip()
        description = description.strip()
    else:
        title = title_line.strip()
        description = None
    if not title:
        raise ValueError("标题不能为空")

    draw_time_utc: dt.datetime | None = None
    min_points = 0
    participation_cost = 0
    max_participants = 0
    requirement_days = 0
    qualification_window_days = 0
    required_invites = 0
    required_activity_count = 0
    finalist_limit = 0
    preset_winner_ids: list[int] = []
    winner_block = False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if line == "奖品:":
            winner_block = False
            continue
        if _is_winner_field(line) and not _split_config_line(line)[1]:
            winner_block = True
            continue
        split_line = _split_config_line(line)
        if winner_block:
            if split_line is None or split_line[0] not in CONFIG_FIELD_NAMES:
                preset_winner_ids.extend(user_id for user_id in _parse_winner_ids(line) if user_id not in preset_winner_ids)
                continue
            winner_block = False
        else:
            winner_block = False
        if split_line is None:
            continue
        field_name, field_value = split_line
        if field_name == "开奖时间":
            draw_time_utc = _parse_future_time(field_value)
            continue
        if field_name == "最低积分":
            min_points = _parse_non_negative_int(field_value, "最低积分")
        elif field_name == "参与费用":
            participation_cost = _parse_non_negative_int(field_value, "参与费用")
        elif field_name in {"最大人数", "满员人数"}:
            max_participants = _parse_non_negative_int(field_value, "最大人数")
        elif field_name == "入群天数":
            requirement_days = _parse_non_negative_int(field_value, "入群天数")
        elif field_name == "邀请人数":
            required_invites = _parse_non_negative_int(field_value, "邀请人数")
        elif field_name == "活跃消息数":
            required_activity_count = _parse_non_negative_int(field_value, "活跃消息数")
        elif field_name == "统计天数":
            qualification_window_days = _parse_non_negative_int(field_value, "统计天数")
        elif field_name == "入围人数":
            finalist_limit = _parse_non_negative_int(field_value, "入围人数")
        elif field_name in WINNER_FIELD_PREFIXES:
            preset_winner_ids.extend(user_id for user_id in _parse_winner_ids(field_value) if user_id not in preset_winner_ids)

    prizes = []
    prize_start = False
    for line in lines[1:]:
        line = line.strip()
        if line == "奖品:":
            prize_start = True
            continue
        if _is_winner_field(line):
            prize_start = False
            continue
        if prize_start and line:
            parts = line.split(",")
            if len(parts) < 2:
                raise ValueError(f"奖品格式错误: {line}")
            prize_name = parts[0].strip()
            if not prize_name:
                raise ValueError(f"奖品名称不能为空: {line}")
            try:
                quantity = int(parts[1].strip())
            except ValueError:
                raise ValueError(f"奖品数量必须是有效数字: {line}")
            if quantity <= 0:
                raise ValueError(f"奖品数量必须大于 0: {line}")
            points_reward = 0
            if len(parts) >= 3:
                try:
                    points_reward = int(parts[2].strip().replace("积分", "").strip())
                except ValueError:
                    raise ValueError(f"积分奖励格式错误: {parts[2]}")
            prizes.append({"name": prize_name, "quantity": quantity, "points_reward": points_reward})

    if not prizes:
        raise ValueError("至少需要一个奖品")
    prize_slot_count = sum(int(prize.get("quantity", 1)) for prize in prizes)
    if len(preset_winner_ids) > prize_slot_count:
        raise ValueError("内定中奖人数不能超过奖品总数量")
    if draw_trigger == "time_deadline" and draw_time_utc is None:
        raise ValueError("定时开奖必须配置开奖时间，格式如：开奖时间: 2025-12-30 12:00")
    if draw_trigger == "full_participants" and max_participants <= 0:
        raise ValueError("满人开奖必须配置最大人数或满员人数，且必须大于 0")
    if draw_time_utc is None:
        draw_time_utc = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3650)
    if lottery_type == "invite" and required_invites <= 0:
        raise ValueError("邀请抽奖必须配置邀请人数，格式如：邀请人数: 3")
    if lottery_type == "activity" and required_activity_count <= 0:
        raise ValueError("群活跃抽奖必须配置活跃消息数，格式如：活跃消息数: 200")
    if lottery_type in {"invite", "activity"} and qualification_window_days <= 0:
        qualification_window_days = 7
    if selection_mode == "ranking_random" and finalist_limit <= 0:
        raise ValueError("排名入围随机玩法必须配置入围人数，格式如：入围人数: 10")

    return ParsedLotteryConfig(
        lottery_type=lottery_type,
        title=title,
        description=description,
        draw_time=draw_time_utc,
        draw_trigger=draw_trigger,
        min_points=min_points,
        participation_cost=participation_cost,
        max_participants=max_participants,
        requirement_days=requirement_days,
        qualification_window_days=qualification_window_days,
        required_invites=required_invites,
        required_activity_count=required_activity_count,
        finalist_limit=finalist_limit,
        selection_mode=selection_mode,
        preset_winner_ids=preset_winner_ids,
        prizes=prizes,
        point_type_id=None,
        point_type_name=None,
    )


def format_lottery_announcement_text(config: ParsedLotteryConfig) -> str:
    text = f"{lottery_type_label(config.lottery_type)}\n\n"
    text += f"📢 {config.title}"
    if config.description:
        text += f"\n\n{config.description}"
    text += f"\n\n🎛 开奖条件: {lottery_draw_trigger_label(config.draw_trigger)}"
    if config.draw_trigger == "time_deadline":
        text += f"\n🕐 截止开奖时间: {_format_local_time(config.draw_time)}"
    if config.min_points > 0:
        text += f"\n💰 最低积分: {config.min_points}"
    if config.participation_cost > 0:
        point_type_name = config.point_type_name or "积分"
        text += f"\n💸 参与费用: {config.participation_cost} {point_type_name}"
    if config.required_invites > 0:
        text += f"\n👥 邀请人数门槛: {config.required_invites}"
    if config.required_activity_count > 0:
        text += f"\n🔥 活跃消息门槛: {config.required_activity_count}"
    if config.qualification_window_days > 0:
        text += f"\n📊 统计天数: 最近 {config.qualification_window_days} 天"
    if config.selection_mode == "ranking_random" and config.finalist_limit > 0:
        text += f"\n🏆 排名入围人数: 前 {config.finalist_limit} 名"
    if config.max_participants > 0:
        text += f"\n👥 最大人数: {config.max_participants}"
    if config.requirement_days > 0:
        text += f"\n📅 入群天数: {config.requirement_days}"
    text += "\n\n🎁 奖品:"
    for prize in config.prizes:
        text += f"\n  • {prize['name']} x {prize['quantity']}"
    if config.selection_mode == "ranking_random":
        text += "\n\n💡 本玩法会在开奖时按排行自动生成入围名单，再随机开奖。"
    else:
        text += "\n\n💡 点击下方按钮参与抽奖！"
    return text
