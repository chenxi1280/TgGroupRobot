from __future__ import annotations

import structlog
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

log = structlog.get_logger(__name__)


async def _delete_source_if_needed(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    delete_mode: str,
) -> None:
    if delete_mode != "delete":
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        log.warning("guess_source_delete_failed", chat_id=chat_id, message_id=message_id, error=str(exc))
        return


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

    parts = text.split()
    keyword = parts[0]
    chat_id = update.effective_chat.id
    message_id = update.effective_message.message_id
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if await is_reserved_group_text_command_for_chat(session, chat_id, text):
            await session.commit()
            return False
        event = await get_running_event_by_keyword(session, chat_id, keyword)
        if event is None:
            await session.commit()
            return False
        setting = await get_or_create_setting(session, chat_id)
        if len(parts) == 1:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat_id,
                text=format_event_runtime(event),
                reply_to_message_id=message_id,
                parse_mode="Markdown",
            )
            await _delete_source_if_needed(context, chat_id, message_id, setting.delete_message_mode)
            return True
        if len(parts) < 3:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat_id,
                text=f"格式错误，请发送：{event.command_keyword} 选项 积分",
                reply_to_message_id=message_id,
            )
            await _delete_source_if_needed(context, chat_id, message_id, setting.delete_message_mode)
            return True
        option_key = parts[1]
        try:
            amount = int(parts[2])
        except ValueError:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat_id,
                text="下注积分必须是整数。",
                reply_to_message_id=message_id,
            )
            await _delete_source_if_needed(context, chat_id, message_id, setting.delete_message_mode)
            return True
        try:
            await ensure_user(
                session,
                user_id=update.effective_user.id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
                language_code=update.effective_user.language_code,
            )
            await place_bet(
                session,
                event=event,
                user_id=update.effective_user.id,
                option_key=option_key,
                amount=amount,
            )
        except ValidationError as exc:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=chat_id,
                text=f"❌ {exc}",
                reply_to_message_id=message_id,
            )
            await _delete_source_if_needed(context, chat_id, message_id, setting.delete_message_mode)
            return True
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=chat_id,
            text=f"✅ 已下注：{option_key} / {amount} 积分",
            reply_to_message_id=message_id,
        )
        await _delete_source_if_needed(context, chat_id, message_id, setting.delete_message_mode)
        return True
