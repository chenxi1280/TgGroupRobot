from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.ui.common.chat_group import chat_group_list_keyboard
from backend.features.group_ops.services.chat_group_service import get_user_managed_chats, set_user_current_chat
from backend.shared.callback_parser import CallbackParser

log = structlog.get_logger(__name__)


async def chat_group_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示群组列表"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    page = cb.get_int(2, default=0)

    db: Database = context.application.bot_data["db"]
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await ChatResolver.get_current_chat(db, user.id)

    if not chats:
        await q.edit_message_text(
            "📋 群组管理\n\n"
            "暂无群组，请先将 bot 添加到群组中，并确保你具有管理员权限。\n\n"
            "💡 提示：添加 bot 到群组后，点击「刷新列表」按钮即可。",
        )
        return

    text = f"📋 群组列表\n\n"
    text += f"共 {len(chats)} 个群组\n"
    text += f"请选择要管理的群组："

    await q.edit_message_text(
        text,
        reply_markup=chat_group_list_keyboard(chats, current_chat_id, page),
    )


async def chat_group_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """选择群组 - 直接显示管理菜单"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    chat_id = cb.get_int(2)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await q.answer("无效的群组ID", show_alert=True)
        return

    # 设置当前选中的群组
    db: Database = context.application.bot_data["db"]
    await set_user_current_chat(db, user.id, chat_id)

    # 直接显示管理菜单（调用 admin.py 的 _show_private_admin_menu）
    from backend.features.admin.admin_handler import _show_private_admin_menu

    await _show_private_admin_menu(update, context, chat_id)


async def chat_group_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """刷新群组列表"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await ChatResolver.get_current_chat(db, user.id)

    if not chats:
        await q.edit_message_text(
            "📋 群组管理\n\n"
            "暂无群组，请先将 bot 添加到群组中，并确保你具有管理员权限。",
        )
        return

    text = f"📋 群组列表\n\n"
    text += f"共 {len(chats)} 个群组\n"
    text += f"列表已刷新，请选择要管理的群组："

    await q.edit_message_text(
        text,
        reply_markup=chat_group_list_keyboard(chats, current_chat_id, page=0),
    )


async def chat_group_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """进入选中群组的管理界面 - 直接调用 admin.py 的 _show_private_admin_menu"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)
    chat_id = cb.get_int(2)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await q.answer("无效的群组ID", show_alert=True)
        return

    # 直接显示管理菜单
    from backend.features.admin.admin_handler import _show_private_admin_menu

    await _show_private_admin_menu(update, context, chat_id)
