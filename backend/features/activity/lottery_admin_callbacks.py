from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.activity.services.lottery_service_parsing import decode_lottery_type, decode_selection_mode
from backend.shared.callback_parser import CallbackParser


async def lottery_menu_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler, is_user_admin_fn) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    data = q.data or ""
    target_chat_id = CallbackParser.parse(data).get_int(2) if data.startswith("lot:menu:") else None
    if target_chat_id is None:
        if chat.type == "private":
            await handler.message_helper.safe_edit(update, "请在群里使用。")
            return
        target_chat_id = chat.id
    if not await is_user_admin_fn(context, target_chat_id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    await handler.show_menu(update, context, target_chat_id)


async def lottery_create_menu_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    if target_chat_id is None and update.effective_chat.type != "private":
        target_chat_id = update.effective_chat.id
    if target_chat_id is None:
        await q.answer("❌ 群组参数无效，请返回重试", show_alert=True)
        return
    await handler.show_create_type_menu(update, context, target_chat_id)


async def lottery_mode_menu_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    lottery_type = decode_lottery_type(cb.get(3, "invite") or "invite")
    if target_chat_id is None:
        return
    await handler.show_mode_menu(update, context, target_chat_id, lottery_type=lottery_type)


async def lottery_draw_condition_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    lottery_type = decode_lottery_type(cb.get(3, "common") or "common")
    selection_mode = decode_selection_mode(cb.get(4, "threshold_random") or "threshold_random")
    if target_chat_id is None:
        return
    await handler.show_draw_condition_menu(update, context, target_chat_id, lottery_type=lottery_type, selection_mode=selection_mode)


async def lottery_list_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    status = cb.get(3, "all") or "all"
    lottery_type = cb.get(4, "all") or "all"
    page = cb.get_int(5, default=0)
    if target_chat_id is None:
        return
    await handler.show_activity_list(update, context, target_chat_id, status=status, lottery_type=lottery_type, page=page)


async def lottery_detail_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    lottery_id = cb.get_int_optional(3)
    if target_chat_id is None or lottery_id is None:
        return
    await handler.show_activity_detail(update, context, target_chat_id, lottery_id=lottery_id)


async def lottery_settings_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    if target_chat_id is None:
        return
    await handler.show_settings_menu(update, context, target_chat_id)


async def lottery_setting_toggle_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    update_lottery_setting_fn,
) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    setting_key = cb.get(3)
    enabled = cb.get(4) == "1"
    if target_chat_id is None or not setting_key:
        return
    field_map = {
        "publish_pin": "publish_pin_enabled",
        "result_pin": "result_pin_enabled",
        "delete_join": "delete_join_message_enabled",
    }
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        field = field_map.get(setting_key)
        if field:
            await update_lottery_setting_fn(session, target_chat_id, **{field: enabled})
        await session.commit()
    await handler.show_settings_menu(update, context, target_chat_id)


async def lottery_admin_draw_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    cb = CallbackParser.parse(q.data or "")
    target_chat_id = cb.get_int_optional(2)
    lottery_id = cb.get_int_optional(3)
    if target_chat_id is None or lottery_id is None:
        return
    if not await is_user_admin_fn(context, target_chat_id, update.effective_user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    await handler.handle_draw(update, context, lottery_id, target_chat_id=target_chat_id)
