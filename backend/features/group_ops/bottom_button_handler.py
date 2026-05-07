from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.bottom_button_service import get_layout, resolve_layout_trigger_text
from backend.features.group_ops.text_trigger_runtime import try_group_text_trigger
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely

log = structlog.get_logger(__name__)


async def bottom_button_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    data = CallbackParser.parse(query.data or "")
    action = data.get(1)
    if action == "noop":
        await answer_callback_query_safely(update, "暂无可用按钮")
        return
    if action != "send":
        await answer_callback_query_safely(update, "暂不支持该操作")
        return

    chat_id = data.get_int_optional(2)
    layout_id = data.get_int_optional(3)
    if chat_id is None or layout_id is None:
        await answer_callback_query_safely(update, "按钮参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        layout = await get_layout(session, chat_id, layout_id)
        payload = await resolve_layout_trigger_text(session, chat_id, layout) if layout is not None else None
        await session.commit()
    if layout is None:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    if not payload:
        await answer_callback_query_safely(update, "按钮事件未配置", show_alert=True)
        return

    try:
        handled = await try_group_text_trigger(update, context, chat_id, payload)
    except Exception as exc:
        log.warning(
            "bottom_button_text_trigger_failed",
            chat_id=chat_id,
            layout_id=layout_id,
            payload_preview=payload[:50],
            error=str(exc),
        )
        await answer_callback_query_safely(update, "触发失败，请重试", show_alert=True)
        return

    if handled:
        await answer_callback_query_safely(update, f"已触发：{layout.button_text}")
        return

    await answer_callback_query_safely(update, f"已发送：{layout.button_text}")
    try:
        await context.bot.send_message(chat_id=chat_id, text=payload)
    except Exception as exc:
        log.warning("bottom_button_send_message_failed", chat_id=chat_id, layout_id=layout_id, error=str(exc))
