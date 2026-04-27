from __future__ import annotations

import datetime as dt
import re

from backend.features.activity.services.lottery_subscription import (
    format_lottery_subscribe_targets,
    parse_lottery_subscribe_targets,
)
from backend.features.activity.services.lottery_service_types import ParsedLotteryConfig


LOTTERY_TYPE_CODES = {
    "common": "c",
    "points": "p",
    "invite": "i",
    "activity": "a",
    "subscribe": "s",
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
    "关注目标",
}
DIRECT_USER_ID_LINK_PATTERNS = (
    re.compile(r"tg://user\?id=(\d+)", flags=re.IGNORECASE),
    re.compile(r"tg://openmessage\?user_id=(\d+)", flags=re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/user\?id=(\d+)", flags=re.IGNORECASE),
)
USERNAME_REFERENCE_PATTERNS = (
    re.compile(r"(?<![\w/])@([A-Za-z][A-Za-z0-9_]{4,31})"),
    re.compile(
        r"(?:https?://)?(?:t\.me|telegram\.me)/(?!user\?id=|c/|joinchat/|\+)(@?[A-Za-z][A-Za-z0-9_]{4,31})(?:[/?#]|$)",
        flags=re.IGNORECASE,
    ),
    re.compile(r"tg://resolve\?domain=([A-Za-z][A-Za-z0-9_]{4,31})", flags=re.IGNORECASE),
)
CLEAR_WINNER_MARKERS = ("可选", "无", "不设置", "留空", "跳过", "随机", "0")
RANDOM_WINNER_MARKERS = {"随机", "不内定", "无", "跳过", "留空", "0"}


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
        "subscribe": "📣 强制订阅抽奖",
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


def parse_direct_winner_ids(value: str) -> list[int]:
    ids: list[int] = []
    for pattern in DIRECT_USER_ID_LINK_PATTERNS:
        for match in pattern.finditer(value):
            user_id = int(match.group(1))
            if user_id > 0 and user_id not in ids:
                ids.append(user_id)
    for raw_token in re.split(r"[\s,，、;；\n]+", value):
        token = raw_token.strip().strip("<>()[]{}，,。.;；")
        if re.fullmatch(r"\d+", token):
            user_id = int(token)
            if user_id > 0 and user_id not in ids:
                ids.append(user_id)
    return ids


def extract_winner_usernames(value: str) -> list[str]:
    usernames: list[str] = []
    seen: set[str] = set()
    for pattern in USERNAME_REFERENCE_PATTERNS:
        for match in pattern.finditer(value):
            username = match.group(1).lstrip("@")
            normalized = username.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            usernames.append(username)
    return usernames


def collect_winner_reference_values(text: str) -> list[str]:
    values: list[str] = []
    winner_block = False
    for raw_line in text.strip().split("\n")[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if line == "奖品:":
            winner_block = False
            continue
        split_line = _split_config_line(line)
        if _is_winner_field(line):
            field_value = split_line[1]
            if field_value:
                values.append(field_value)
            else:
                winner_block = True
            continue
        if winner_block:
            if split_line is None or split_line[0] not in CONFIG_FIELD_NAMES:
                values.append(line)
                continue
            winner_block = False
    return values


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


def _parse_winner_ids(value: str, *, allow_unresolved_refs: bool = False) -> list[int]:
    ids = parse_direct_winner_ids(value)
    usernames = extract_winner_usernames(value)
    has_content = bool(value.strip()) and not any(marker in value for marker in CLEAR_WINNER_MARKERS)
    if usernames and not allow_unresolved_refs:
        raise ValueError("内定中奖人如使用 @用户名或用户链接，请通过分步创建发送，或填写数字用户ID")
    if has_content and not ids and not usernames and not allow_unresolved_refs:
        raise ValueError("内定中奖人请填写 Telegram 数字用户ID，多个ID用逗号分隔")
    return ids


def validate_unique_prize_names(prizes: list[dict]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for prize in prizes:
        name = str(prize.get("name") or "").strip()
        if not name:
            continue
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        raise ValueError("奖品名称不能重复：" + "、".join(duplicates))


def _split_preset_assignment_value(value: str, prizes: list[dict]) -> tuple[str | None, str]:
    text = value.strip()
    prize_names = sorted(_prize_names(prizes), key=len, reverse=True)
    for prize_name in prize_names:
        for separator in (":", "：", "=", "＝"):
            prefix = f"{prize_name}{separator}"
            if text.startswith(prefix):
                return prize_name, text[len(prefix):].strip()
    _raise_if_malformed_preset_assignment(text, prize_names)
    return None, text


def _prize_names(prizes: list[dict]) -> set[str]:
    return {str(prize.get("name") or "").strip() for prize in prizes if str(prize.get("name") or "").strip()}


def _format_available_prize_names(prize_names: list[str]) -> str:
    return "、".join(prize_names) if prize_names else "无"


def _has_winner_reference(value: str) -> bool:
    return bool(parse_direct_winner_ids(value) or extract_winner_usernames(value))


def _raise_if_malformed_preset_assignment(text: str, prize_names: list[str]) -> None:
    if not text or re.match(r"^(?:https?|tg)://", text, flags=re.IGNORECASE):
        return
    separator_match = re.match(r"^([^:：=＝]{1,80})\s*[:：=＝]\s*(.+)$", text)
    if separator_match and _has_winner_reference(separator_match.group(2)):
        prize_name = separator_match.group(1).strip()
        raise ValueError(
            f"内定中奖奖品不存在：{prize_name}。"
            f"可用奖品：{_format_available_prize_names(prize_names)}"
        )
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return
    maybe_prize, winner_value = parts
    if not _has_winner_reference(winner_value) or _has_winner_reference(maybe_prize):
        return
    if maybe_prize in prize_names:
        raise ValueError(f"指定奖品请使用格式：{maybe_prize}: 用户")
    raise ValueError(
        f"内定中奖奖品不存在：{maybe_prize}。"
        f"如需指定奖品，请使用格式：奖品名称: 用户；"
        f"可用奖品：{_format_available_prize_names(prize_names)}"
    )


def _requires_prize_assignment(prizes: list[dict]) -> bool:
    return len(_prize_names(prizes)) > 1


def _prize_quantity_by_name(prizes: list[dict]) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for prize in prizes:
        name = str(prize.get("name") or "").strip()
        if not name:
            continue
        quantities[name] = quantities.get(name, 0) + int(prize.get("quantity", 1) or 1)
    return quantities


def validate_preset_winner_assignments(assignments: list[dict], prizes: list[dict]) -> None:
    if not assignments:
        return
    quantity_by_name = _prize_quantity_by_name(prizes)
    counts: dict[str, int] = {}
    for item in assignments:
        prize_name = str(item.get("prize_name") or "").strip()
        if prize_name not in quantity_by_name:
            raise ValueError(f"内定中奖奖品不存在：{prize_name}")
        counts[prize_name] = counts.get(prize_name, 0) + 1
    for prize_name, count in counts.items():
        if count > quantity_by_name[prize_name]:
            raise ValueError(f"内定中奖人超过奖品「{prize_name}」的中奖人数")


def parse_preset_winner_values(
    values: list[str],
    prizes: list[dict],
    *,
    allow_unresolved_refs: bool = False,
) -> tuple[list[int], list[dict]]:
    preset_winner_ids: list[int] = []
    preset_winner_assignments: list[dict] = []
    require_assignment = _requires_prize_assignment(prizes)
    for value in values:
        prize_name, winner_value = _split_preset_assignment_value(value, prizes)
        winner_value = winner_value.strip()
        if not winner_value or winner_value in RANDOM_WINNER_MARKERS:
            continue
        if require_assignment and prize_name is None and _has_winner_reference(winner_value):
            raise ValueError(
                "多个奖品时，请逐个奖品设置内定中奖人，格式：奖品名称: 用户；"
                "不指定的奖品请写：奖品名称: 随机"
            )
        for user_id in _parse_winner_ids(
            winner_value,
            allow_unresolved_refs=allow_unresolved_refs,
        ):
            if user_id not in preset_winner_ids:
                preset_winner_ids.append(user_id)
            if prize_name is not None and not any(
                int(item.get("user_id") or 0) == user_id for item in preset_winner_assignments
            ):
                preset_winner_assignments.append({"user_id": user_id, "prize_name": prize_name})
    validate_preset_winner_assignments(preset_winner_assignments, prizes)
    return preset_winner_ids, preset_winner_assignments


def parse_lottery_config_text(
    text: str,
    lottery_type: str = "common",
    selection_mode: str = "threshold_random",
    draw_trigger: str = "time_deadline",
    allow_unresolved_winner_refs: bool = False,
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
    preset_winner_values: list[str] = []
    preset_winner_assignments: list[dict] = []
    subscribe_target_values: list[str] = []
    winner_block = False
    subscribe_target_block = False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if line == "奖品:":
            winner_block = False
            subscribe_target_block = False
            continue
        if _is_winner_field(line) and not _split_config_line(line)[1]:
            winner_block = True
            subscribe_target_block = False
            continue
        split_line = _split_config_line(line)
        if subscribe_target_block:
            if split_line is None or split_line[0] not in CONFIG_FIELD_NAMES | set(WINNER_FIELD_PREFIXES):
                subscribe_target_values.append(line)
                continue
            subscribe_target_block = False
        if winner_block:
            if split_line is None or split_line[0] not in CONFIG_FIELD_NAMES:
                preset_winner_values.append(line)
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
        if field_name == "关注目标":
            if field_value:
                subscribe_target_values.append(field_value)
            else:
                subscribe_target_block = True
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
            preset_winner_values.append(field_value)

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
    validate_unique_prize_names(prizes)
    preset_winner_ids, preset_winner_assignments = parse_preset_winner_values(
        preset_winner_values,
        prizes,
        allow_unresolved_refs=allow_unresolved_winner_refs,
    )
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
    subscribe_targets = None
    if lottery_type == "subscribe":
        if not subscribe_target_values:
            raise ValueError("强制订阅抽奖必须配置关注目标，格式如：关注目标: @channel")
        subscribe_targets = parse_lottery_subscribe_targets("\n".join(subscribe_target_values))

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
        subscribe_targets=subscribe_targets,
        subscribe_check_mode="all",
        preset_winner_assignments=preset_winner_assignments,
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
    if config.lottery_type == "subscribe":
        target_text = format_lottery_subscribe_targets(config.subscribe_targets or [])
        text += f"\n📣 参与条件: 需先关注：{target_text}"
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
        text += "\n\n💡 本玩法无需点击参与；系统会在开奖时按邀请/活跃排行生成入围名单，再随机开奖。"
        text += "\n想提高中奖机会，请在截止前继续完成对应的邀请或活跃任务。"
    else:
        text += "\n\n💡 点击下方按钮参与抽奖；参与成功后会在群内看到确认消息。"
    return text
