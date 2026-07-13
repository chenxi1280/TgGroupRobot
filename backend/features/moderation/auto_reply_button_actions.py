from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_buttons import (
    AUTO_REPLY_TEXT_TRIGGER,
    find_auto_reply_button,
)
from backend.features.moderation.services.auto_reply_service import get_auto_reply_rule_in_chat
from backend.features.group_ops.text_trigger_runtime import try_group_text_trigger
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser

log = structlog.get_logger(__name__)


async def auto_reply_text_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    data = CallbackParser.parse(update.callback_query.data or "")
    action = data.get(1)
    chat_id = data.get_int_optional(2)
    rule_id = data.get_int_optional(3)
    row_index = data.get_int_optional(4)
    col_index = data.get_int_optional(5)
    if action != "text" or chat_id is None or rule_id is None or row_index is None or col_index is None:
        await answer_callback_query_safely(update, "按钮参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        await session.commit()

    if rule is None:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    button = find_auto_reply_button(rule, row_index, col_index)
    if button is None or button.get("action_type") != AUTO_REPLY_TEXT_TRIGGER:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    trigger_text = str(button.get("payload") or "").strip()
    if not trigger_text:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    if update.effective_chat is None or update.effective_message is None:
        await answer_callback_query_safely(update, "按钮上下文无效", show_alert=True)
        return

    try:
        handled = await try_group_text_trigger(update, context, chat_id, payload=trigger_text)
    except Exception as exc:
        log.warning(
            "auto_reply_text_button_trigger_failed",
            chat_id=chat_id,
            rule_id=rule_id,
            row_index=row_index,
            col_index=col_index,
            trigger_preview=trigger_text[:50],
            error=str(exc),
        )
        await answer_callback_query_safely(update, "触发失败，请重试", show_alert=True)
        return

    if not handled:
        await answer_callback_query_safely(update, "暂不支持该触发文字", show_alert=True)
        return

    await answer_callback_query_safely(update, f"已触发：{trigger_text}", show_alert=False)
