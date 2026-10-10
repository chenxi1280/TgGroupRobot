from __future__ import annotations

from backend.features.admin.runtime import admin_runtime
from backend.features.admin.support import *
from backend.shared.async_tasks import spawn_background_task


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
        await _handle_group_admin_command(update, context, chat, user=user)
        return

    await _handle_private_admin_command(update, context, user)


async def show_private_admin_menu_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await admin_runtime._show_main_menu(update, context, chat_id)


async def _handle_group_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, chat, *, user) -> None:
    try:
        is_admin, reason = await PermissionPolicyService.require_manage(context, chat.id, user.id)
    except TelegramError as exc:
        log.error("admin_command_get_chat_member_failed", error=str(exc))
        await update.effective_message.reply_text("无法获取管理员信息，请确保 bot 有读取群成员的权限")
        return

    if not is_admin:
        await update.effective_message.reply_text(reason or "此命令仅限管理员使用")
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
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("前往本群管理", url=f"https://t.me/{context.bot.username}?start=manage_{chat.id}")]]),
    )

    async def delete_later() -> None:
        try:
            await asyncio.sleep(getattr(context.application.bot_data.get("settings"), "group_guide_message_delete_seconds", 30))
            await message.delete()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("delete_message_failed", error=str(exc))

    spawn_background_task(context, delete_later(), name="admin_command.delete_later")


async def _handle_private_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, user) -> None:
    try:
        db: Database = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, user.id, context.bot)
        current_chat_id = await ChatResolver.get_current_chat(db, user.id)

        available_ids = {item[0] for item in chats}
        if current_chat_id not in available_ids:
            current_chat_id = chats[0][0] if len(chats) == 1 else None
        if current_chat_id is None:
            await admin_runtime._show_group_selection(update, chats, None)
            return
        await set_user_current_chat(db, user.id, current_chat_id)

        await show_private_admin_menu_impl(update, context, current_chat_id)
    except Exception as exc:
        log.exception("admin_command_error", user_id=user.id, error=str(exc))
        await update.effective_message.reply_text(
            f"发生错误：{build_public_error_text(exc, fallback='请稍后重试')}"
        )
