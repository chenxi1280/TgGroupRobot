from __future__ import annotations

import structlog

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.callback_parser import CallbackParser

log = structlog.get_logger(__name__)


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
    if update.callback_query is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    action = cb.get(1)
    db: Database = context.application.bot_data["db"]

    try:
        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                await q.edit_message_text("已关闭。")
            return

        if action == "my":
            chat_id = cb.get_int(2)
            if chat_id == 0:
                await q.edit_message_text("群组参数错误")
                return
            await show_mydata_panel_func(update, context, chat_id)
            return

        if action == "set":
            chat_id = cb.get_int(2)
            field = cb.get(3)
            await start_edit_state_func(update, context, db, chat_id, field)
            return

        if action == "toggle":
            chat_id = cb.get_int(2)
            await toggle_visible_func(update, context, db, chat_id)
            return

        if action == "clear":
            chat_id = cb.get_int(2)
            step = cb.get(3)
            await handle_clear_func(update, context, db, chat_id, step)
            return

        if action in {"list", "refresh"}:
            chat_id = cb.get_int(2)
            page = cb.get_int(3, default=0)
            await show_nearby_list_func(update, context, chat_id, page=page)
            return

        if action == "detail":
            chat_id = cb.get_int(2)
            target_user_id = cb.get_int(3)
            back_page = cb.get_int(4, default=0)
            await show_member_detail_func(update, context, chat_id, target_user_id, back_page)
            return

        if action in {"fav", "report"}:
            label = "收藏" if action == "fav" else "举报"
            await reply_or_edit_func(update, f"{label}功能即将上线。")
            return

        await reply_or_edit_func(update, "未知操作。")
    except Exception as exc:
        log.exception("nearby_callback_error", data=data, error=str(exc))
        await q.edit_message_text(f"操作失败: {exc}")
