from __future__ import annotations

from backend.features.admin.runtime import admin_runtime
from backend.features.admin.support import *


async def admin_command_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.info("admin_command_called")

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        log.warning("admin_command_missing_update_data")
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        allowed = await ensure_command_enabled(context, update, command_key="admin")
        if not allowed:
            return

    if chat.type != "private":
        await _handle_group_admin_command(update, context, chat, user)
        return

    await _handle_private_admin_command(update, context, user)


async def show_private_admin_menu_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await admin_runtime._show_main_menu(update, context, chat_id)


async def _handle_group_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, chat, user) -> None:
    try:
        is_admin = await is_user_admin(context, chat.id, user.id)
    except TelegramError as exc:
        log.error("admin_command_get_chat_member_failed", error=str(exc))
        await update.effective_message.reply_text("无法获取管理员信息，请确保 bot 有读取群成员的权限")
        return

    if not is_admin:
        await update.effective_message.reply_text("此命令仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    await set_user_current_chat(db, user.id, chat.id)

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await session.commit()

    message = await update.effective_message.reply_text(
        f"欢迎使用 @{context.bot.username}:\n\n"
        f"1) 点击下方按钮选择设置（仅限管理员）\n"
        f"2) 点击机器人对话框底部[开始]按钮\n\n"
        f"🟩 功能更新提醒: 在机器人私聊中发送 /start 也可打开管理菜单",
        reply_markup=create_guide_keyboard(context.bot.username),
    )

    async def delete_later() -> None:
        try:
            await asyncio.sleep(10)
            await message.delete()
        except Exception as exc:
            log.warning("delete_message_failed", error=str(exc))

    asyncio.create_task(delete_later())


async def _handle_private_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, user) -> None:
    try:
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, user.id, context.bot)
        current_chat_id = await ChatResolver.get_current_chat(db, user.id)

        if not chats:
            await update.effective_message.reply_text(
                "👋 欢迎使用群管理 Bot！\n\n"
                "暂无群组，请先将 bot 添加到群组中并设为管理员..."
            )
            return

        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
            await set_user_current_chat(db, user.id, current_chat_id)

        await show_private_admin_menu_impl(update, context, current_chat_id)
    except Exception as exc:
        log.exception("admin_command_error", user_id=user.id, error=str(exc))
        await update.effective_message.reply_text(
            f"发生错误：{build_public_error_text(exc, fallback='请稍后重试')}"
        )
