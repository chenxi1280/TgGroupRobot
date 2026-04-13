from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.invite.invite_shared import _invite_link_handler
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.permission_service import is_user_admin


async def invite_link_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        db: Database = context.application.bot_data["db"]
        target_chat_id = await ChatResolver.get_current_chat(db, user.id)
        if target_chat_id is None:
            await _invite_link_handler.message_helper.safe_edit(update, "请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await _invite_link_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
            return
        from backend.features.admin.admin_handler import _show_private_admin_menu

        await _show_private_admin_menu(update, context, target_chat_id)
        return

    if not await is_user_admin(context, chat.id, user.id):
        await _invite_link_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
        return

    await _invite_link_handler.show_menu(update, context, chat.id, chat.title)


async def invite_link_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_list(update, context, target_chat_id, CallbackParser.parse(q.data or "").get_int(2, default=0))


async def invite_link_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_stats(update, context, target_chat_id)


async def invite_link_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    cb = CallbackParser.parse(q.data or "")
    field = cb.get(2)
    value = cb.get_int_optional(4)
    if value not in {0, 1}:
        await answer_callback_query_safely(update, "无效开关值", show_alert=True)
        return

    field_map = {"enabled": "invite_link_enabled", "remind": "invite_link_notify"}
    setting_field = field_map.get(field)
    if setting_field is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        setattr(settings, setting_field, bool(value))
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    mode = CallbackParser.parse(q.data or "").get(3)
    if mode not in {"relay", "direct"}:
        await answer_callback_query_safely(update, "无效模式", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        settings.invite_link_mode = mode
        await session.commit()
    await q.answer()
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)
