from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.lottery_admin_callbacks import (
    lottery_admin_draw_callback_impl,
    lottery_create_menu_callback_impl,
    lottery_detail_callback_impl,
    lottery_draw_condition_callback_impl,
    lottery_list_callback_impl,
    lottery_menu_callback_impl,
    lottery_mode_menu_callback_impl,
    lottery_setting_toggle_callback_impl,
    lottery_settings_callback_impl,
)
from backend.features.activity.lottery_creation import LotteryCreationMixin, handle_lottery_wizard_callback
from backend.features.activity.lottery_drawing import LotteryDrawMixin
from backend.features.activity.lottery_manual_draw_callbacks import (
    manual_draw_complete_callback_impl,
    manual_draw_menu_callback_impl,
    manual_draw_select_prize_callback_impl,
    manual_draw_select_winner_callback_impl,
    manual_draw_winner_page_callback_impl,
)
from backend.features.activity.lottery_menus import LotteryMenuMixin
from backend.features.activity.lottery_message_callbacks import (
    draw_lottery_callback_impl,
    join_lottery_callback_impl,
    lottery_cancel_callback_impl,
    lottery_create_start_impl,
    lottery_message_handler_impl,
    parse_lottery_config_impl,
)
from backend.features.activity.lottery_participation import LotteryParticipationMixin
from backend.features.activity.services.lottery_service import (
    JoinResult,
    ParsedLotteryConfig,
    count_lotteries_by_type,
    create_lottery,
    create_lottery_winner,
    format_lottery_announcement_text,
    format_lottery_stats_message,
    generate_lottery_announcement,
    get_chat_lotteries,
    get_lottery,
    get_lottery_participant_count,
    get_lottery_participants,
    get_lottery_stats,
    get_or_create_lottery_setting,
    join_lottery,
    parse_lottery_config_text,
    update_lottery_setting,
    distribute_lottery_rewards,
)
from backend.features.activity.ui.lottery import (
    lottery_menu_keyboard,
    lottery_draw_condition_keyboard,
    lottery_mode_keyboard,
    lottery_type_keyboard,
    manual_draw_prize_keyboard,
    manual_draw_summary_keyboard,
    manual_draw_summary_keyboard_with_winners,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.services.permission_service import is_user_admin

log = structlog.get_logger(__name__)


class LotteryHandler(
    LotteryMenuMixin,
    LotteryCreationMixin,
    LotteryParticipationMixin,
    LotteryDrawMixin,
    BaseHandler,
):
    def __init__(self) -> None:
        super().__init__()
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        pass


_lottery_handler = LotteryHandler()


async def lottery_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_menu_callback_impl(update, context, handler=_lottery_handler, is_user_admin_fn=is_user_admin)


async def lottery_create_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_create_menu_callback_impl(update, context, handler=_lottery_handler)


async def lottery_mode_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_mode_menu_callback_impl(update, context, handler=_lottery_handler)


async def lottery_draw_condition_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_draw_condition_callback_impl(update, context, handler=_lottery_handler)


async def lottery_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_list_callback_impl(update, context, handler=_lottery_handler)


async def lottery_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_detail_callback_impl(update, context, handler=_lottery_handler)


async def lottery_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_settings_callback_impl(update, context, handler=_lottery_handler)


async def lottery_setting_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_setting_toggle_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        update_lottery_setting_fn=update_lottery_setting,
    )


async def lottery_admin_draw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_admin_draw_callback_impl(update, context, handler=_lottery_handler, is_user_admin_fn=is_user_admin)


async def lottery_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_create_start_impl(update, context, handler=_lottery_handler, is_user_admin_fn=is_user_admin)


async def lottery_wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_lottery_wizard_callback(update, context)


async def lottery_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_message_handler_impl(update, context, parse_config_fn=_parse_lottery_config)


async def _parse_lottery_config(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    await parse_lottery_config_impl(update, context, session, state, text)


async def join_lottery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await join_lottery_callback_impl(update, context, handler=_lottery_handler)


async def draw_lottery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await draw_lottery_callback_impl(update, context, handler=_lottery_handler, is_user_admin_fn=is_user_admin)


async def manual_draw_select_prize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await manual_draw_select_prize_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        is_user_admin_fn=is_user_admin,
        get_lottery_fn=get_lottery,
        get_lottery_participants_fn=get_lottery_participants,
    )


async def manual_draw_select_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await manual_draw_select_winner_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        is_user_admin_fn=is_user_admin,
        get_lottery_fn=get_lottery,
        get_user_state_fn=get_user_state,
        set_user_state_fn=set_user_state,
    )


async def manual_draw_complete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await manual_draw_complete_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        is_user_admin_fn=is_user_admin,
        get_user_state_fn=get_user_state,
        get_lottery_fn=get_lottery,
        create_lottery_winner_fn=create_lottery_winner,
        clear_user_state_fn=clear_user_state,
        distribute_lottery_rewards_fn=distribute_lottery_rewards,
        generate_lottery_announcement_fn=generate_lottery_announcement,
    )


async def manual_draw_winner_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await manual_draw_winner_page_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        is_user_admin_fn=is_user_admin,
        get_lottery_fn=get_lottery,
        get_lottery_participants_fn=get_lottery_participants,
    )


async def manual_draw_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await manual_draw_menu_callback_impl(
        update,
        context,
        handler=_lottery_handler,
        is_user_admin_fn=is_user_admin,
        get_user_state_fn=get_user_state,
        get_lottery_fn=get_lottery,
    )


async def lottery_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await lottery_cancel_callback_impl(update, context, handler=_lottery_handler, clear_user_state_fn=clear_user_state)
