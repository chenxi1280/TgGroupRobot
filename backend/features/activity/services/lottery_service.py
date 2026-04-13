"""抽奖服务 - 处理抽奖的创建、参与、开奖和统计"""

from __future__ import annotations

from backend.features.activity.services.lottery_service_drawing import (
    build_ranked_finalists,
    create_lottery_winner,
    distribute_lottery_rewards,
    generate_lottery_announcement,
    perform_random_draw,
)
from backend.features.activity.services.lottery_service_parsing import (
    format_lottery_announcement_text,
    format_lottery_stats_message,
    parse_lottery_config_text,
)
from backend.features.activity.services.lottery_service_participation import (
    can_join_lottery,
    join_lottery,
)
from backend.features.activity.services.lottery_service_queries import (
    count_lotteries_by_type,
    create_lottery,
    get_chat_lotteries,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    get_lottery_stats,
    get_or_create_lottery_setting,
    get_user_lottery_history,
    update_lottery_setting,
)
from backend.features.activity.services.lottery_service_types import JoinResult, ParsedLotteryConfig
