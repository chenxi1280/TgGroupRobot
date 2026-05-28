"""积分服务 - 处理积分账户、签到、活动和排行榜"""

from __future__ import annotations

from backend.features.points.services.points_service_accounts import (
    _get_or_create_account,
    change_points,
    get_balance,
)
from backend.features.points.services.points_service_activity import (
    _get_or_create_daily_stats,
    add_invite_points,
    add_message_points,
    sign_in,
)
from backend.features.points.services.points_service_leaderboard import (
    get_daily_points_leaderboard,
    get_leaderboard,
    get_user_rank,
)
from backend.features.points.services.points_service_messages import (
    format_balance_message,
    format_daily_points_leaderboard_message,
    format_leaderboard_message,
    format_sign_in_already_message,
    format_sign_in_success_message,
)
from backend.features.points.services.points_service_types import PointsResult, SignResult

__all__ = [
    "PointsResult",
    "SignResult",
    "format_sign_in_success_message",
    "format_sign_in_already_message",
    "format_balance_message",
    "format_leaderboard_message",
    "format_daily_points_leaderboard_message",
    "get_balance",
    "_get_or_create_account",
    "change_points",
    "sign_in",
    "add_message_points",
    "add_invite_points",
    "_get_or_create_daily_stats",
    "get_leaderboard",
    "get_daily_points_leaderboard",
    "get_user_rank",
]
