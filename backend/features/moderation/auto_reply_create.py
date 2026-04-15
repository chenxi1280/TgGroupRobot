from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import ensure_callback_update, resolve_auto_reply_target_chat_id
from backend.features.moderation.auto_reply_views import show_auto_reply_rule_detail
from backend.features.moderation.services.auto_reply_service import create_auto_reply_draft
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import TgChat
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.user_service import ensure_user
from sqlalchemy import select


async def auto_reply_create_start_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ensure_callback_update(update):
        return
    query = update.callback_query

    chat = update.effective_chat
    user = update.effective_user
    target_chat_id = await resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return
    await query.answer()

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_chat_title = await _load_target_chat_title(session, chat.type, chat.title, target_chat_id)
        await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        rule = await create_auto_reply_draft(
            session,
            chat_id=target_chat_id,
            created_by_user_id=user.id,
        )
        rule_id = rule.id
        await session.commit()

    await show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def _load_target_chat_title(session, chat_type: str, chat_title: str | None, target_chat_id: int) -> str:
    if chat_type != "private":
        return chat_title or f"群组{target_chat_id}"

    chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
    chat_result = await session.execute(chat_stmt)
    target_chat = chat_result.scalar_one_or_none()
    return target_chat.title if target_chat else f"群组{target_chat_id}"
