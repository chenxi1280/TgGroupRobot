from __future__ import annotations

import structlog
from dataclasses import dataclass
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.activity.services.guess_service import (
    format_event_runtime,
    get_or_create_setting,
    get_running_event_by_keyword,
    place_bet,
)
from backend.features.group_ops.text_trigger_runtime import (
    is_reserved_group_text_command,
    is_reserved_group_text_command_for_chat,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService
from backend.shared.services.user_service import ensure_user
_GUESS_MESSAGE_HANDLER_THRESHOLD_3 = 3


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GuessResponse:
    text: str
    delete_mode: str
    parse_mode: str | None = None


async def _delete_source_if_needed(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    *, delete_mode: str,
) -> None:
    if delete_mode != "delete":
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        log.warning(
            "guess_source_delete_failed", chat_id=chat_id,
            message_id=message_id, error=str(exc),
        )


async def _process_guess_message(update, session, *, chat_id: int, text: str):
    if await is_reserved_group_text_command_for_chat(session, chat_id, text):
        await session.commit()
        return None
    parts = text.split()
    event = await get_running_event_by_keyword(session, chat_id, parts[0])
    if event is None:
        await session.commit()
        return None
    setting = await get_or_create_setting(session, chat_id)
    if len(parts) == 1:
        await session.commit()
        return GuessResponse(
            format_event_runtime(event), setting.delete_message_mode, "Markdown"
        )
    if len(parts) < _GUESS_MESSAGE_HANDLER_THRESHOLD_3:
        await session.commit()
        return GuessResponse(
            f"格式错误，请发送：{event.command_keyword} 选项 积分",
            setting.delete_message_mode,
        )
    try:
        amount = int(parts[2])
    except ValueError:
        await session.commit()
        return GuessResponse("下注积分必须是整数。", setting.delete_message_mode)
    try:
        await ensure_user(
            session, user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            language_code=update.effective_user.language_code,
        )
        await place_bet(
            session, event=event, user_id=update.effective_user.id,
            option_key=parts[1], amount=amount,
        )
    except ValidationError as exc:
        await session.commit()
        return GuessResponse(f"❌ {exc}", setting.delete_message_mode)
    await session.commit()
    return GuessResponse(
        f"✅ 已下注：{parts[1]} / {amount} 积分", setting.delete_message_mode
    )
async def guess_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return False
    if update.effective_chat.type == "private":
        return False

    text = (update.effective_message.text or update.effective_message.caption or "").strip()
    if not text:
        return False
    if is_reserved_group_text_command(text):
        return False

    chat_id = update.effective_chat.id
    message_id = update.effective_message.message_id
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        response = await _process_guess_message(
            update, session, chat_id=chat_id, text=text
        )
    if response is None:
        return False
    await PublishService.reply(
        context, chat_id=chat_id, text=response.text,
        reply_to_message_id=message_id, parse_mode=response.parse_mode,
    )
    await _delete_source_if_needed(
        context, chat_id, message_id, delete_mode=response.delete_mode
    )
    return True
