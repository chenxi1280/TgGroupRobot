from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.invite.invite_shared import (
    _invite_link_handler,
    export_invite_csv,
    format_invite_preview,
    reset_invite_data,
)
from backend.shared.button_layout_editor import show_layout_menu, ButtonEditorContext
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import set_user_state
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext
from backend.shared.services.chat_service import get_chat_settings

log = structlog.get_logger(__name__)


async def _resolve_invite_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_index: int,
) -> int | None:
    return await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )


async def invite_link_cover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_cover_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "🖼️ 邀请链接 | 修改封面\n\n请发送图片或视频，发送“清空”可移除封面。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_text_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "📝 邀请链接 | 修改文本\n\n"
        f"当前模板：\n{settings.invite_link_text_template}\n\n"
        "支持变量：{inviter} {invitee} {group}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await session.commit()
        await show_layout_menu(
            update,
            context,
            ButtonEditorContext("invite", target_chat_id, 0),
            session=session,
        )
        await session.commit()


async def invite_link_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await session.commit()
    preview_text, keyboard = format_invite_preview(settings, str(target_chat_id))
    if settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "photo":
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    elif settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "video":
        await context.bot.send_video(chat_id=update.effective_chat.id, video=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=preview_text, reply_markup=keyboard)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=3)
    if target_chat_id is None:
        return
    reset_type = CallbackParser.parse(q.data or "").get(2)
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        toast, links = await reset_invite_data(session, reset_type=reset_type, chat_id=target_chat_id)
        await session.commit()
    if toast is None:
        await answer_callback_query_safely(update, "无效重置类型", show_alert=True)
        return
    if links:
        for link in links:
            try:
                await context.bot.revoke_chat_invite_link(chat_id=target_chat_id, invite_link=link.invite_link)
            except Exception as exc:
                log.warning(
                    "invite_bulk_revoke_failed",
                    chat_id=target_chat_id,
                    link_id=getattr(link, "id", None),
                    error=str(exc),
                )
                continue
    await q.answer(toast, show_alert=True)
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    target_chat_id = await _resolve_invite_target_chat_id(update, context, chat_index=2)
    if target_chat_id is None:
        return
    await export_invite_csv(context, chat_id=target_chat_id, reply_chat_id=update.effective_chat.id)
    await _invite_link_handler.show_menu(update, context, target_chat_id)
