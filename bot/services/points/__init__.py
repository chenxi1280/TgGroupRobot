"""积分服务模块 - 拆分后的积分管理功能"""

from bot.services.points.account_service import (
    get_balance,
    change_points,
    _get_or_create_account,
)
from bot.services.points.sign_in_service import sign_in, SignResult
from bot.services.points.activity_service import (
    add_message_points,
    add_invite_points,
    PointsResult,
)
from bot.services.points.leaderboard_service import (
    get_leaderboard,
    get_user_rank,
)

__all__ = [
    # 账户管理
    "get_balance",
    "change_points",
    "_get_or_create_account",
    # 签到功能
    "sign_in",
    "SignResult",
    # 活动积分
    "add_message_points",
    "add_invite_points",
    "PointsResult",
    # 排行榜
    "get_leaderboard",
    "get_user_rank",
]
