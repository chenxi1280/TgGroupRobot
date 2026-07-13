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


def _button_coordinates(data: CallbackParser) -> tuple[int, int, int, int] | None:
    values = tuple(data.get_int_optional(index) for index in range(2, 6))
    if data.get(1) != "text" or any(value is None for value in values):
        return None
    return values


async def _load_trigger(db: Database, coordinates: tuple[int, int, int, int]):
    chat_id, rule_id, row_index, col_index = coordinates
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule_in_chat(session, chat_id, rule_id)
        await session.commit()
    button = find_auto_reply_button(rule, row_index, col_index) if rule is not None else None
    if button is None or button.get("action_type") != AUTO_REPLY_TEXT_TRIGGER:
        return None
    return str(button.get("payload") or "").strip() or None


async def auto_reply_text_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    data = CallbackParser.parse(update.callback_query.data or "")
    coordinates = _button_coordinates(data)
    if coordinates is None:
        await answer_callback_query_safely(update, "按钮参数无效", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    trigger_text = await _load_trigger(db, coordinates)
    if not trigger_text:
        await answer_callback_query_safely(update, "按钮已失效", show_alert=True)
        return

    if update.effective_chat is None or update.effective_message is None:
        await answer_callback_query_safely(update, "按钮上下文无效", show_alert=True)
        return

    chat_id, rule_id, row_index, col_index = coordinates
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
