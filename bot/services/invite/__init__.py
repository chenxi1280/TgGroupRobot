"""邀请服务模块 - 合并后的邀请链接管理功能"""

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
from bot.services.invite.stats_service import (
    get_user_invite_stats,
    get_invite_leaderboard,
    get_user_rank,
    InviteStats,
)
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
