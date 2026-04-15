from __future__ import annotations

from backend.features.admin.runtime import admin_runtime
from backend.features.admin.support import *


async def private_admin_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    callback = update.callback_query
    data = callback.data or ""
    cb = CallbackParser.parse(data)
    if cb.get(0) not in {"adm", "ali", "gfw", "grg", "tsearch", "crv", "auc", "btm", "gm", "guess", "act", "qpub"}:
        return

    target_chat_id = _resolve_private_scoped_target_chat_id(cb)
    if target_chat_id is None:
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


async def group_admin_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    callback = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    is_admin = await is_user_admin(context, chat.id, user.id)
    if not is_admin:
        await admin_runtime.message_helper.safe_edit(callback, "此操作仅限管理员使用")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        cb = CallbackParser.parse(callback.data or "")
        if cb.get(1) == "menu":
            menu = cb.get(2)
            if menu == "main":
                await session.commit()
                await admin_runtime.message_helper.safe_edit(callback, t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return
            if menu == "settings":
                await session.commit()
                await admin_runtime.message_helper.safe_edit(
                    callback,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return
            if menu == "verification":
                await session.commit()
                await admin_runtime._show_verification_menu(update, context, chat.id)
                return

        if cb.get(1) == "toggle":
            field = cb.get(2)
            if hasattr(settings, field):
                setattr(settings, field, not bool(getattr(settings, field)))
                await session.commit()
                await admin_runtime.message_helper.safe_edit(
                    callback,
                    "开关设置：",
                    reply_markup=toggle_menu(get_settings_toggle_rows(settings), back_to="main"),
                )
                return

        if cb.get(1) == "vfy_mode":
            selected_mode = cb.get(2)
            if selected_mode in {"button", "math", "mute"}:
                settings.verification_mode = selected_mode
                settings.verification_enabled = True
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
                await admin_runtime.message_helper.safe_edit(callback, text, reply_markup=verification_mode_menu(settings.verification_mode))
                return

        await session.commit()

    await admin_runtime.process(update, context, chat.id)


async def admin_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == "private":
        await private_admin_callback_impl(update, context)
        return
    await group_admin_callback_impl(update, context)
