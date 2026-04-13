from __future__ import annotations

import datetime as dt
import re

from backend.features.activity.services.lottery_service_types import ParsedLotteryConfig


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


def parse_lottery_config_text(
    text: str,
    lottery_type: str = "common",
    selection_mode: str = "threshold_random",
) -> ParsedLotteryConfig:
    lines = text.strip().split("\n")
    if len(lines) < 7:
        raise ValueError("配置格式不完整")

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

    draw_time_line = lines[1].strip()
    if not draw_time_line.startswith("开奖时间:"):
        raise ValueError("开奖时间格式错误，应为: 开奖时间: 2025-12-30 12:00")
    time_pattern = r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{1,2})"
    match = re.search(time_pattern, draw_time_line)
    if not match:
        raise ValueError("开奖时间格式错误，请使用: YYYY-MM-DD HH:MM")
    year, month, day, hour, minute = map(int, match.groups())
    local_tz = dt.timezone(dt.timedelta(hours=8))
    draw_time = dt.datetime(year, month, day, hour, minute, tzinfo=local_tz)
    draw_time_utc = draw_time.astimezone(dt.timezone.utc)
    if draw_time_utc <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("开奖时间必须是未来时间")

    min_points = 0
    participation_cost = 0
    max_participants = 0
    requirement_days = 0
    qualification_window_days = 0
    required_invites = 0
    required_activity_count = 0
    finalist_limit = 0
    for line in lines[2:]:
        line = line.strip()
        if not line or line == "奖品:":
            continue
        if line.startswith("最低积分:"):
            try:
                min_points = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("最低积分必须是有效数字")
        elif line.startswith("参与费用:"):
            try:
                participation_cost = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("参与费用必须是有效数字")
        elif line.startswith("最大人数:"):
            try:
                max_participants = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("最大人数必须是有效数字")
        elif line.startswith("入群天数:"):
            try:
                requirement_days = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("入群天数必须是有效数字")
        elif line.startswith("邀请人数:"):
            try:
                required_invites = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("邀请人数必须是有效数字")
        elif line.startswith("活跃消息数:"):
            try:
                required_activity_count = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("活跃消息数必须是有效数字")
        elif line.startswith("统计天数:"):
            try:
                qualification_window_days = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("统计天数必须是有效数字")
        elif line.startswith("入围人数:"):
            try:
                finalist_limit = max(0, int(line.split(":", 1)[1].strip()))
            except ValueError:
                raise ValueError("入围人数必须是有效数字")

    prizes = []
    prize_start = False
    for line in lines[6:]:
        line = line.strip()
        if line == "奖品:":
            prize_start = True
            continue
        if prize_start and line:
            parts = line.split(",")
            if len(parts) < 2:
                raise ValueError(f"奖品格式错误: {line}")
            prize_name = parts[0].strip()
            quantity = int(parts[1].strip())
            points_reward = 0
            if len(parts) >= 3:
                try:
                    points_reward = int(parts[2].strip().replace("积分", "").strip())
                except ValueError:
                    raise ValueError(f"积分奖励格式错误: {parts[2]}")
            prizes.append({"name": prize_name, "quantity": quantity, "points_reward": points_reward})

    if not prizes:
        raise ValueError("至少需要一个奖品")
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
        min_points=min_points,
        participation_cost=participation_cost,
        max_participants=max_participants,
        requirement_days=requirement_days,
        qualification_window_days=qualification_window_days,
        required_invites=required_invites,
        required_activity_count=required_activity_count,
        finalist_limit=finalist_limit,
        selection_mode=selection_mode,
        prizes=prizes,
    )


def format_lottery_announcement_text(config: ParsedLotteryConfig) -> str:
    text = f"{lottery_type_label(config.lottery_type)}\n\n"
    text += f"📢 {config.title}"
    if config.description:
        text += f"\n\n{config.description}"
    text += f"\n\n🕐 开奖时间: {config.draw_time.strftime('%Y-%m-%d %H:%M')}"
    if config.min_points > 0:
        text += f"\n💰 最低积分: {config.min_points}"
    if config.participation_cost > 0:
        text += f"\n💸 参与费用: {config.participation_cost} 积分"
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
