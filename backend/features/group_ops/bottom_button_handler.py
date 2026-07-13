from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.group_ops.services.bottom_button_service import get_layout, resolve_layout_trigger_text
from backend.features.group_ops.text_trigger_runtime import try_group_text_trigger
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely

async def _load_button_payload(db: Database, chat_id: int, layout_id: int):
    async with db.session_factory() as session:
        layout = await get_layout(session, chat_id, layout_id)
        payload = await resolve_layout_trigger_text(session, chat_id, layout) if layout is not None else None
        await session.commit()
    return layout, payload


async def _execute_button_payload(update, context, *, chat_id: int, layout, payload: str) -> None:
    try:
        handled = await try_group_text_trigger(update, context, chat_id, payload=payload)
    except Exception:
        await answer_callback_query_safely(update, "触发失败，请重试", show_alert=True)
        raise
    if handled:
        await answer_callback_query_safely(update, f"已触发：{layout.button_text}")
        return
    await answer_callback_query_safely(update, f"已发送：{layout.button_text}")
    await context.bot.send_message(chat_id=chat_id, text=payload)


async def _accept_send_action(update, action: str | None) -> bool:
    if action == "send":
        return True
    message = "暂无可用按钮" if action == "noop" else "暂不支持该操作"
    await answer_callback_query_safely(update, message)
    return False


async def bottom_button_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    data = CallbackParser.parse(query.data or "")
    action = data.get(1)
    if not await _accept_send_action(update, action):
        return

    chat_id = data.get_int_optional(2)
    layout_id = data.get_int_optional(3)
    if chat_id is None or layout_id is None:
        await answer_callback_query_safely(update, "按钮参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    layout, payload = await _load_button_payload(db, chat_id, layout_id)
    if layout is None:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    if not payload:
        await answer_callback_query_safely(update, "按钮事件未配置", show_alert=True)
        return

    await _execute_button_payload(
        update,
        context,
        chat_id=chat_id,
        layout=layout,
        payload=payload,
    )
