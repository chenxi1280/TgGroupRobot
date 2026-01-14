"""Services 模块统一导出"""

# 基础类
from bot.services.base import BaseService, ServiceError, ServiceResult

# 核心服务
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.user_service import ensure_user
from bot.services.core.permission_service import is_user_admin

# 状态管理
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state

# 活动服务
from bot.services.activity.lottery_service import (
    can_join_lottery,
    create_lottery,
    create_lottery_winner,
    distribute_lottery_rewards,
    generate_lottery_announcement,
    get_chat_lotteries,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    get_lottery_stats,
    get_user_lottery_history,
    join_lottery,
    perform_random_draw,
    JoinResult,
)
from bot.services.activity.points_service import (
    add_invite_points,
    add_message_points,
    change_points,
    get_balance,
    get_leaderboard,
    get_user_rank,
    sign_in,
    PointsResult,
    SignResult,
)
from bot.services.activity.solitaire_service import (
    close_solitaire,
    create_solitaire,
    get_chat_solitaires,
    get_solitaire,
)

# 审核服务
from bot.services.moderation.auto_reply_service import match_auto_reply
from bot.services.moderation.banned_word_service import match_banned_words

# 自动化服务
from bot.services.automation.ad_service import create_ad_campaign, get_chat_ads
from bot.services.automation.scheduled_service import (
    create_scheduled_message,
    get_chat_scheduled_messages,
)

# 集成服务
from bot.services.integration.invite_service import (
    can_create_link,
    create_invite_link,
    create_user_invite_link,
    get_chat_invite_links,
    get_invite_link,
    get_link_stats,
    get_user_links,
    revoke_invite_link,
    track_and_award_invite,
    update_invite_link_info,
    CreateResult,
    InviteStats,
    RevokeResult,
)
from bot.services.integration.chat_group_service import (
    get_user_current_chat,
    get_user_managed_chats,
    set_user_current_chat,
)


__all__ = [
    # 基础
    "BaseService",
    "ServiceError",
    "ServiceResult",
    # 核心
    "ensure_chat",
    "get_chat_settings",
    "ensure_user",
    "is_user_admin",
    # 状态
    "clear_user_state",
    "get_user_state",
    "set_user_state",
    # 活动
    "can_join_lottery",
    "create_lottery",
    "create_lottery_winner",
    "distribute_lottery_rewards",
    "generate_lottery_announcement",
    "get_chat_lotteries",
    "get_lottery",
    "get_lottery_participant_count",
    "get_lottery_participants",
    "get_lottery_stats",
    "get_user_lottery_history",
    "join_lottery",
    "perform_random_draw",
    "JoinResult",
    "add_invite_points",
    "add_message_points",
    "change_points",
    "get_balance",
    "get_leaderboard",
    "get_user_rank",
    "sign_in",
    "PointsResult",
    "SignResult",
    "close_solitaire",
    "create_solitaire",
    "get_chat_solitaires",
    "get_solitaire",
    # 审核
    "match_auto_reply",
    "match_banned_words",
    # 自动化
    "create_ad_campaign",
    "get_chat_ads",
    "create_scheduled_message",
    "get_chat_scheduled_messages",
    # 集成
    "can_create_link",
    "create_invite_link",
    "create_user_invite_link",
    "get_chat_invite_links",
    "get_invite_link",
    "get_link_stats",
    "get_user_links",
    "revoke_invite_link",
    "track_and_award_invite",
    "update_invite_link_info",
    "CreateResult",
    "InviteStats",
    "RevokeResult",
    "get_user_current_chat",
    "get_user_managed_chats",
    "set_user_current_chat",
]
