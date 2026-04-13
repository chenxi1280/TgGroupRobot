from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.activity.services.guess_service import (
    format_event_runtime,
    get_running_event_by_keyword,
    place_bet,
)
from backend.shared.services.base import ValidationError
from backend.shared.services.publish_service import PublishService


async def guess_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_chat is None or update.effective_message is None or update.effective_user is None:
        return False
    if update.effective_chat.type == "private":
        return False

    text = (update.effective_message.text or update.effective_message.caption or "").strip()
    if not text:
        return False

    parts = text.split()
    keyword = parts[0]
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        event = await get_running_event_by_keyword(session, update.effective_chat.id, keyword)
        if event is None:
            await session.commit()
            return False
        if len(parts) == 1:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text=format_event_runtime(event),
                reply_to_message_id=update.effective_message.message_id,
                parse_mode="Markdown",
            )
            return True
        if len(parts) < 3:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text=f"格式错误，请发送：{event.command_keyword} 选项 积分",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        option_key = parts[1]
        try:
            amount = int(parts[2])
        except ValueError:
            await session.commit()
            await PublishService.reply(
                context,
                chat_id=update.effective_chat.id,
                text="下注积分必须是整数。",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        try:
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
                chat_id=update.effective_chat.id,
                text=f"❌ {exc}",
                reply_to_message_id=update.effective_message.message_id,
            )
            return True
        await session.commit()
        await PublishService.reply(
            context,
            chat_id=update.effective_chat.id,
            text=f"✅ 已下注：{option_key} / {amount} 积分",
            reply_to_message_id=update.effective_message.message_id,
        )
        return True
