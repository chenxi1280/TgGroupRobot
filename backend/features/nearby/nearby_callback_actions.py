from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.callback_parser import CallbackParser

log = structlog.get_logger(__name__)


async def _close_nearby_panel(q) -> None:
    try:
        await q.message.delete()
    except Exception as exc:
        log.warning("nearby_panel_delete_failed", error=str(exc))
        await q.edit_message_text("已关闭。")


async def _handle_close_action(action: str, q) -> bool:
    if action != "close":
        return False
    await _close_nearby_panel(q)
    return True


async def _dispatch_profile_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    *,
    action: str,
    chat_id: int,
    cb: CallbackParser,
    start_edit_state_func,
    toggle_visible_func,
    handle_clear_func,
    show_mydata_panel_func,
) -> bool:
    if action == "my":
        await show_mydata_panel_func(update, context, chat_id)
        return True
    if action == "set":
        await start_edit_state_func(update, context, db, chat_id, cb.get(3))
        return True
    if action == "toggle":
        await toggle_visible_func(update, context, db, chat_id)
        return True
    if action == "clear":
        await handle_clear_func(update, context, db, chat_id, cb.get(3))
        return True
    return False


async def _dispatch_browse_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    action: str,
    cb: CallbackParser,
    show_nearby_list_func,
    show_member_detail_func,
) -> bool:
    if action in {"list", "refresh"}:
        await show_nearby_list_func(update, context, chat_id, page=cb.get_int(3, default=0))
        return True
    if action == "detail":
        await show_member_detail_func(
            update,
            context,
            chat_id,
            cb.get_int(3),
            cb.get_int(4, default=0),
        )
        return True
    return False


async def _resolve_callback_chat_id(update: Update, cb: CallbackParser, reply_or_edit_func) -> int | None:
    chat_id = cb.get_int_optional(2)
    if chat_id in {None, 0}:
        await reply_or_edit_func(update, "群组参数错误。")
        return None
    return chat_id


def _parse_nearby_callback(update: Update) -> tuple[object, CallbackParser] | None:
    if update.callback_query is None or update.effective_user is None:
        return None
    return update.callback_query, CallbackParser.parse(update.callback_query.data or "")


async def callback_handler_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    start_edit_state_func,
    toggle_visible_func,
    handle_clear_func,
    show_mydata_panel_func,
    show_nearby_list_func,
    show_member_detail_func,
    reply_or_edit_func,
) -> None:
    parsed = _parse_nearby_callback(update)
    if parsed is None:
        return
    q, cb = parsed
    await q.answer()
    action = cb.get(1)
    db: Database = context.application.bot_data["db"]
    if await _handle_close_action(action, q):
        return
    chat_id = await _resolve_callback_chat_id(update, cb, reply_or_edit_func)
    if chat_id is None:
        return
    handled = await _dispatch_profile_action(
        update,
        context,
        db,
        action=action,
        chat_id=chat_id,
        cb=cb,
        start_edit_state_func=start_edit_state_func,
        toggle_visible_func=toggle_visible_func,
        handle_clear_func=handle_clear_func,
        show_mydata_panel_func=show_mydata_panel_func,
    )
    if handled:
        return
    handled = await _dispatch_browse_action(
        update,
        context,
        chat_id,
        action=action,
        cb=cb,
        show_nearby_list_func=show_nearby_list_func,
        show_member_detail_func=show_member_detail_func,
    )
    if handled:
        return
    await reply_or_edit_func(update, "未知操作。")
