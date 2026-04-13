from __future__ import annotations

from backend.features.admin.runtime import admin_runtime
from backend.features.admin.support import *


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    log.info("admin_command_chat_info", chat_type=chat.type, chat_id=chat.id, user_id=user.id)

    if chat.type != "private":
        log.info("admin_command_group_chat")
        try:
            is_admin = await is_user_admin(context, chat.id, user.id)
        except TelegramError as e:
            log.error("admin_command_get_chat_member_failed", error=str(e))
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

        keyboard = create_guide_keyboard(context.bot.username)
        msg = await update.effective_message.reply_text(
            f"欢迎使用 @{context.bot.username}:\n\n"
            f"1) 点击下方按钮选择设置（仅限管理员）\n"
            f"2) 点击机器人对话框底部[开始]按钮\n\n"
            f"🟩 功能更新提醒: 在机器人私聊中发送 /start 也可打开管理菜单",
            reply_markup=keyboard,
        )

        async def delete_later():
            try:
                await asyncio.sleep(10)
                await msg.delete()
            except Exception as e:
                log.warning("delete_message_failed", error=str(e))

        asyncio.create_task(delete_later())
        return

    log.info("admin_command_private_chat")

    try:
        db: Database = context.application.bot_data["db"]
        log.info("admin_command_fetching_chats", user_id=user.id)
        chats = await get_user_managed_chats(db, user.id, context.bot)
        log.info("admin_command_chats_fetched", user_id=user.id, chat_count=len(chats))

        current_chat_id = await ChatResolver.get_current_chat(db, user.id)
        log.info("admin_command_current_chat", user_id=user.id, current_chat_id=current_chat_id)

        if not chats:
            log.info("admin_command_no_chats")
            await update.effective_message.reply_text(
                "👋 欢迎使用群管理 Bot！\n\n"
                "暂无群组，请先将 bot 添加到群组中并设为管理员..."
            )
            return

        if current_chat_id is None and chats:
            current_chat_id = chats[0][0]
            log.info("admin_command_setting_default_chat", user_id=user.id, default_chat_id=current_chat_id)
            await set_user_current_chat(db, user.id, current_chat_id)

        log.info("admin_command_showing_menu", user_id=user.id, current_chat_id=current_chat_id)
        await _show_private_admin_menu(update, context, current_chat_id)
        log.info("admin_command_menu_shown", user_id=user.id)
    except Exception as e:
        log.exception("admin_command_error", user_id=user.id, error=str(e))
        await update.effective_message.reply_text(
            f"发生错误：{build_public_error_text(e, fallback='请稍后重试')}"
        )


async def _show_private_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await admin_runtime._show_main_menu(update, context, chat_id)


async def private_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.get(0) not in {"adm", "ali", "gfw", "grg", "tsearch", "crv", "auc", "btm", "gm", "guess", "act", "qpub"}:
        return

    action = cb.get(1)
    log.info("=== ADMIN_CALLBACK_ACTION ===", action=action, cb_parts=[cb.get(i) for i in range(cb.length())])
    target_chat_id = _resolve_private_scoped_target_chat_id(cb)
    log.info("=== ADMIN_CALLBACK_TARGET_CHAT_ID ===", target_chat_id=target_chat_id)

    if target_chat_id is None:
        log.warning("admin_callback_invalid_chat_id", callback_data=data)
        await answer_callback_query_safely(update, "❌ 群组参数无效，请返回重试", show_alert=True)
        return

    if target_chat_id != 0:
        allowed, error_text = await PermissionPolicyService.require_manage(
            context,
            target_chat_id,
            update.effective_user.id,
            capability="manage",
        )
        if not allowed:
            await admin_runtime.message_helper.safe_edit(update, error_text or "你没有该群组的管理权限")
            return

    await admin_runtime.process(update, context, target_chat_id)


async def group_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    data = q.data or ""
    user = update.effective_user
    chat = update.effective_chat
    is_admin = await is_user_admin(context, chat.id, user.id)
    log.info("admin_permission_check", chat_id=chat.id, user_id=user.id, is_admin=is_admin)
    if not is_admin:
        log.warning("admin_permission_denied", callback_data=data, chat_id=chat.id, user_id=user.id)
        await admin_runtime.message_helper.safe_edit(q, "此操作仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        cb = CallbackParser.parse(data)
        if cb.get(1) == "menu":
            menu = cb.get(2)
            if menu == "main":
                await session.commit()
                await admin_runtime.message_helper.safe_edit(q, t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return

            if menu == "settings":
                await session.commit()
                await admin_runtime.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

            if menu == "verification":
                text = format_verification_menu_text(
                    chat_title="群组",
                    enabled=settings.verification_enabled,
                    verification_mode=settings.verification_mode,
                    timeout_seconds=settings.verification_timeout_seconds,
                    restrict_can_send=settings.verification_restrict_can_send,
                    timeout_action=settings.verification_timeout_action,
                    mute_duration=settings.verification_mute_duration,
                )
                await session.commit()
                await admin_runtime.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return

        if cb.get(1) == "toggle":
            field = cb.get(2)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()
                await admin_runtime.message_helper.safe_edit(
                    q,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

        if cb.get(1) == "vfy_mode":
            selected_mode = cb.get(2)
            if selected_mode in ["button", "question"]:
                settings.verification_mode = selected_mode
                await session.commit()
                text = format_verification_menu_text(
                    chat_title="群组",
                    enabled=settings.verification_enabled,
                    verification_mode=settings.verification_mode,
                    timeout_seconds=settings.verification_timeout_seconds,
                    restrict_can_send=settings.verification_restrict_can_send,
                    timeout_action=settings.verification_timeout_action,
                    mute_duration=settings.verification_mute_duration,
                )
                await admin_runtime.message_helper.safe_edit(q, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    data = update.callback_query.data or ""
    log.warning(
        "=== ADMIN_CALLBACK CALLED ===",
        callback_data=data,
        chat_type=update.effective_chat.type,
        user_id=update.effective_user.id,
    )

    if update.effective_chat.type == "private":
        await private_admin_callback(update, context)
        return

    await group_admin_callback(update, context)
