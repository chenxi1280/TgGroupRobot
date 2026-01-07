"""
积分服务适配器 - 保持向后兼容

此文件重新导出拆分后的所有函数，确保现有代码无需修改
"""

# 账户管理
from bot.services.points.account_service import (
    get_balance,
    change_points,
    _get_or_create_account,
)

# 签到功能
from bot.services.points.sign_in_service import sign_in, SignResult

# 活动积分
from bot.services.points.activity_service import (
    add_message_points,
    add_invite_points,
    PointsResult,
)

# 排行榜
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
