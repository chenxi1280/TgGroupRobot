"""
邀请服务适配器 - 保持向后兼容

此文件重新导出合并后的所有函数，确保现有代码无需修改

合并了原来的 invite_service.py 和 invite_link_service.py
"""

# 链接管理
from bot.services.invite.link_service import (
    create_invite_link,
    get_chat_invite_links,
    get_invite_link,
    revoke_invite_link,
    update_invite_link_info,
    delete_invite_link,
    get_link_stats,
    can_create_link,
    get_user_links,
    CreateResult,
    RevokeResult,
)

# 统计功能
from bot.services.invite.stats_service import (
    get_user_invite_stats,
    get_invite_leaderboard,
    get_user_rank,
    InviteStats,
)

# 奖励功能
from bot.services.invite.reward_service import (
    track_and_award_invite,
    clear_invite_data,
)

__all__ = [
    # 链接管理
    "create_invite_link",
    "get_chat_invite_links",
    "get_invite_link",
    "revoke_invite_link",
    "update_invite_link_info",
    "delete_invite_link",
    "get_link_stats",
    "can_create_link",
    "get_user_links",
    "CreateResult",
    "RevokeResult",
    # 统计功能
    "get_user_invite_stats",
    "get_invite_leaderboard",
    "get_user_rank",
    "InviteStats",
    # 奖励功能
    "track_and_award_invite",
    "clear_invite_data",
]
