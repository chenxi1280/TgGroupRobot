from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_common import (
    ensure_callback_update,
    ensure_message_update,
    get_match_type_label,
    resolve_auto_reply_target_chat_id,
)
from backend.features.moderation.auto_reply_payloads import (
    build_auto_reply_markup,
    parse_auto_reply_buttons_input,
    send_auto_reply_payload,
)
from backend.features.moderation.auto_reply_views import (
    extract_auto_reply_list_page,
    format_auto_reply_rule_detail,
    render_auto_reply_list,
    show_auto_reply_delay_page,
    show_auto_reply_rule_detail,
)

def _ensure_callback_update(update: Update) -> bool:
    return ensure_callback_update(update)


def _ensure_message_update(update: Update, require_user: bool = True) -> bool:
    return ensure_message_update(update, require_user=require_user)


async def _resolve_auto_reply_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_index: int = 2,
) -> int | None:
    return await resolve_auto_reply_target_chat_id(update, context, chat_index=chat_index)


def _format_auto_reply_rule_detail(rule) -> str:
    return format_auto_reply_rule_detail(rule)


def _parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    return parse_auto_reply_buttons_input(raw_text)


def _build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    return build_auto_reply_markup(rule)


async def _send_auto_reply_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    rule,
    reply_to_message_id: int | None = None,
    message_thread_id: int | None = None,
) -> object:
    return await send_auto_reply_payload(
        context,
        chat_id=chat_id,
        text=text,
        rule=rule,
        reply_to_message_id=reply_to_message_id,
        message_thread_id=message_thread_id,
    )


async def _show_auto_reply_rule_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    rule_id: int,
) -> None:
    await show_auto_reply_rule_detail(update, context, chat_id=chat_id, rule_id=rule_id)


async def _show_auto_reply_delay_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    rule_id: int,
) -> None:
    await show_auto_reply_delay_page(update, context, chat_id=chat_id, rule_id=rule_id)


def _extract_auto_reply_list_page(callback_data: str | None) -> int:
    return extract_auto_reply_list_page(callback_data)


async def _render_auto_reply_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    target_chat_id: int,
    page: int = 0,
) -> None:
    await render_auto_reply_list(update, context, target_chat_id=target_chat_id, page=page)


# ============================================
# 回调处理器
# ============================================

# Handler 类定义（使用 BaseHandler）

def _get_match_type_label(match_type: str) -> str:
    return get_match_type_label(match_type)
