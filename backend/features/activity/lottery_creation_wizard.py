from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_service import (
    ParsedLotteryConfig,
    create_lottery,
    format_lottery_announcement_text,
    get_or_create_lottery_setting,
)
from backend.features.activity.lottery_creation_config import (
    _qualification_rules_from_config,
    _validate_lottery_publish_config,
)
from backend.features.activity.lottery_creation_wizard_messages import (
    _handle_lottery_wizard_message as _handle_lottery_wizard_message,
)
from backend.features.activity.lottery_creation_wizard_prompts import (
    _edit_wizard_step_prompt as _edit_wizard_step_prompt,
    _reply_next_prompt as _reply_next_prompt,
    _reply_preset_confirm as _reply_preset_confirm,
)

log = structlog.get_logger(__name__)

async def _create_and_publish_lottery(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    target_chat_id: int,
    creator_user_id: int,
    config: ParsedLotteryConfig,
):
    await _validate_lottery_publish_config(context, config)
    lottery = await create_lottery(
        session,
        chat_id=target_chat_id,
        created_by_user_id=creator_user_id,
        title=config.title,
        draw_time=config.draw_time,
        prizes=config.prizes,
        description=config.description,
        lottery_type=config.lottery_type,
        draw_mode="random",
        qualification_rules=_qualification_rules_from_config(config),
        min_points=config.min_points,
        max_participants=config.max_participants,
        participation_cost=config.participation_cost,
        join_end_time=config.draw_time if config.draw_trigger == "time_deadline" else None,
        requirement_days=config.requirement_days,
    )

    announcement_text = format_lottery_announcement_text(config)
    keyboard = None
    if config.selection_mode != "ranking_random":
        from backend.features.activity.ui.lottery import get_join_keyboard

        keyboard = get_join_keyboard(lottery.id)
    sent_message = await context.bot.send_message(
        chat_id=target_chat_id,
        text=announcement_text,
        reply_markup=keyboard,
    )
    lottery.message_id = getattr(sent_message, "message_id", None)
    setting = await get_or_create_lottery_setting(session, target_chat_id)
    if setting.publish_pin_enabled and lottery.message_id:
        try:
            await context.bot.pin_chat_message(chat_id=target_chat_id, message_id=lottery.message_id)
        except Exception as exc:
            log.warning("lottery_publish_pin_failed", lottery_id=lottery.id, chat_id=target_chat_id, message_id=lottery.message_id, error=str(exc))
    log.info("lottery_announcement_sent", lottery_id=lottery.id, target_chat_id=target_chat_id)
    return lottery

