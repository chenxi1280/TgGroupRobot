from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.keyboards.chat_group import chat_group_list_keyboard, chat_group_selected_keyboard
from bot.services.chat_group_service import get_user_current_chat, get_user_managed_chats, set_user_current_chat

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
    parts = data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    db: Database = context.application.bot_data["db"]
    chats = await get_user_managed_chats(db, user.id, context.bot)
    current_chat_id = await get_user_current_chat(db, user.id)

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
    """选择群组"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    chat_id = int(parts[2])

    # 获取群组标题
    db: Database = context.application.bot_data["db"]
    chats = await get_user_managed_chats(db, user.id, context.bot)

    selected_chat = None
    for cid, title, _ in chats:
        if cid == chat_id:
            selected_chat = (cid, title)
            break

    if not selected_chat:
        await q.edit_message_text("❌ 群组不存在，请刷新列表")
        return

    chat_id, chat_title = selected_chat

    # 设置当前选中的群组
    await set_user_current_chat(db, user.id, chat_id)

    text = f"✅ 已选中群组\n\n"
    text += f"📌 {chat_title}\n\n"
    text += f"现在可以对该群组进行管理操作。"

    await q.edit_message_text(
        text,
        reply_markup=chat_group_selected_keyboard(chat_id, chat_title),
    )


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
    current_chat_id = await get_user_current_chat(db, user.id)

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
    """进入选中群组的管理界面"""
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    chat_id = int(parts[2])

    # 获取群组标题和设置
    db: Database = context.application.bot_data["db"]
    from bot.services.chat_service import get_chat_settings
    from bot.models.core import TgChat
    from sqlalchemy import select

    async with db.session_factory() as session:
        # 获取群组信息
        chat_stmt = select(TgChat).where(TgChat.id == chat_id)
        chat_result = await session.execute(chat_stmt)
        chat = chat_result.scalar_one_or_none()

        settings = await get_chat_settings(session, chat_id)
        await session.commit()

    from bot.keyboards.admin import admin_main_menu

    chat_title = chat.title if chat else f"群组{chat_id}"
    text = f"⚙️ [{chat_title}] 群组设置\n\n"
    text += f"选择要更改的项目："

    # 这里需要注意，admin_callback 期望在群组上下文中调用
    # 但我们在私聊中，所以需要特殊处理
    # 我们可以模拟一个群组上下文，或者修改管理面板

    await q.edit_message_text(
        text,
        reply_markup=admin_main_menu(),
    )
