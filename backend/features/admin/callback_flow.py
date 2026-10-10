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
        await admin_runtime.message_helper.safe_edit(update, "此旧入口缺少可信群信息，请选择群组后重新打开功能。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("选择管理群", callback_data="adm:switch_group")]]))
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


async def _handle_group_verification_mode(update, *, session, settings, cb) -> bool:
    if cb.get(1) != "vfy_mode" or cb.get(2) not in {"button", "math", "mute"}:
        return False
    settings.verification_mode = cb.get(2)
    settings.verification_enabled = True
    await session.commit()
    text = format_verification_menu_text(
        chat_title="群组", enabled=settings.verification_enabled,
        verification_mode=settings.verification_mode,
        timeout_seconds=settings.verification_timeout_seconds,
        restrict_can_send=settings.verification_restrict_can_send,
        timeout_action=settings.verification_timeout_action,
        mute_duration=settings.verification_mute_duration,
    )
    await admin_runtime.message_helper.safe_edit(
        update, text,
        reply_markup=verification_mode_menu(settings.verification_mode),
    )
    return True


async def group_admin_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    callback = update.callback_query
    chat = update.effective_chat
    if not await _group_callback_allowed(update, context):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        cb = CallbackParser.parse(callback.data or "")
        if await _handle_group_verification_mode(
            update, session=session, settings=settings, cb=cb
        ):
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


async def _group_callback_allowed(update, context):
    chat, user, callback = update.effective_chat, update.effective_user, update.callback_query
    allowed, reason = await PermissionPolicyService.require_manage(context, chat.id, user.id)
    if not allowed:
        await admin_runtime.message_helper.safe_edit(update, reason or "此操作仅限符合群策略的管理员使用")
        return
    bound_chat = _resolve_private_scoped_target_chat_id(CallbackParser.parse(callback.data or ""))
    if bound_chat not in {None, 0, chat.id}:
        await admin_runtime.message_helper.safe_edit(update, "此按钮属于其他群，请在对应群或机器人私聊重新打开。")
        return
    return True
