"""积分消息格式化。"""

from __future__ import annotations


def format_sign_in_success_message(
    points: int,
    balance: int,
    consecutive_days: int = 0,
    bonus_points: int = 0,
) -> str:
    msg = "✅ 签到成功！\n"
    msg += f"获得 {points} 积分\n"
    msg += f"当前余额：{balance} 积分"
    if consecutive_days > 1:
        msg += f"\n连续签到：{consecutive_days} 天"
    if bonus_points > 0:
        msg += f"\n🎉 连续签到奖励：+{bonus_points} 积分"
    return msg


def format_sign_in_already_message(balance: int, consecutive_days: int = 0) -> str:
    msg = "❌ 今日已签到\n"
    msg += f"当前余额：{balance} 积分"
    if consecutive_days > 0:
        msg += f"\n连续签到：{consecutive_days} 天"
    return msg


def format_balance_message(balance: int, rank: int | None = None) -> str:
    msg = f"💰 你的积分：{balance}"
    if rank:
        msg += f"\n🏆 排名：第 {rank} 名"
    return msg


def format_leaderboard_message(
    leaderboard: list[tuple[int, int, str | None]],
) -> str:
    if not leaderboard:
        return "暂无积分排行数据"

    msg = "🏆 积分排行榜（前10名）\n\n"
    for i, (user_id, balance, username) in enumerate(leaderboard, 1):
        name = username or f"用户{user_id}"
        msg += f"{i}. {name} - {balance} 积分\n"
    return msg
