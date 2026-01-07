"""抽奖服务模块 - 拆分后的抽奖管理功能"""

from bot.services.lottery.manager_service import (
    create_lottery,
    get_lottery,
    get_chat_lotteries,
    get_lottery_stats,
    get_lottery_participants,
    get_lottery_participant_count,
    get_lottery_winners,
    get_user_lottery_history,
    JoinResult,
)
from bot.services.lottery.validator_service import (
    can_join_lottery,
    join_lottery,
)
from bot.services.lottery.draw_service import (
    perform_random_draw,
    generate_lottery_announcement,
    distribute_lottery_rewards,
)

__all__ = [
    # 管理功能
    "create_lottery",
    "get_lottery",
    "get_chat_lotteries",
    "get_lottery_stats",
    "get_lottery_participants",
    "get_lottery_participant_count",
    "get_lottery_winners",
    "get_user_lottery_history",
    "JoinResult",
    # 验证功能
    "can_join_lottery",
    "join_lottery",
    # 开奖功能
    "perform_random_draw",
    "generate_lottery_announcement",
    "distribute_lottery_rewards",
]
