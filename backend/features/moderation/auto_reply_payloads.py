from __future__ import annotations

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import normalize_button_rows, parse_button_rows

log = structlog.get_logger(__name__)


def parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    try:
        return parse_button_rows(raw_text, allow_empty=False)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc


def build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    raw_buttons = getattr(rule, "buttons", None) or []
    if not raw_buttons:
        return None
    try:
        normalized = normalize_button_rows(raw_buttons)
    except Exception:
        return None

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for row in normalized:
        button_row: list[InlineKeyboardButton] = []
        for item in row:
            text = str(item.get("text") or "").strip()
            url = str(item.get("url") or "").strip()
            callback_data = str(item.get("callback_data") or "").strip()
            if text and url:
                button_row.append(InlineKeyboardButton(text, url=url))
            elif text and callback_data:
                button_row.append(InlineKeyboardButton(text, callback_data=callback_data))
        if button_row:
            keyboard_rows.append(button_row)
    return InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None


async def _send_auto_reply_text(context: ContextTypes.DEFAULT_TYPE, kwargs: dict) -> object:
    try:
        return await context.bot.send_message(**kwargs)
    except TelegramError as exc:
        if not kwargs.get("reply_to_message_id"):
            raise
        retry_kwargs = dict(kwargs)
        retry_kwargs["reply_to_message_id"] = None
        log.warning(
            "auto_reply_reply_reference_failed_fallback_plain",
            chat_id=kwargs.get("chat_id"),
            error=str(exc),
        )
        return await context.bot.send_message(**retry_kwargs)


async def send_auto_reply_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    rule,
    reply_to_message_id: int | None = None,
    message_thread_id: int | None = None,
) -> object:
    reply_markup = build_auto_reply_markup(rule)
    cover_type = getattr(rule, "cover_media_type", None)
    cover_file_id = getattr(rule, "cover_media_file_id", None)
    fallback_kwargs = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
        "reply_to_message_id": reply_to_message_id,
        "allow_sending_without_reply": True,
    }
    if message_thread_id is not None:
        fallback_kwargs["message_thread_id"] = message_thread_id
    log.info(
        "auto_reply_payload_send_attempt",
        chat_id=chat_id,
        send_mode=cover_type if cover_type in {"photo", "video"} and cover_file_id else "text",
        has_reply_markup=reply_markup is not None,
        reply_to_message_id=reply_to_message_id,
        message_thread_id=message_thread_id,
    )
    if cover_type == "photo" and cover_file_id:
        try:
            kwargs = {
                "chat_id": chat_id,
                "photo": cover_file_id,
                "caption": text,
                "reply_markup": reply_markup,
                "reply_to_message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
            if message_thread_id is not None:
                kwargs["message_thread_id"] = message_thread_id
            return await context.bot.send_photo(**kwargs)
        except TelegramError as exc:
            log.warning(
                "auto_reply_cover_send_failed_fallback_text",
                chat_id=chat_id,
                cover_type=cover_type,
                error=str(exc),
            )
            return await _send_auto_reply_text(context, fallback_kwargs)
    if cover_type == "video" and cover_file_id:
        try:
            kwargs = {
                "chat_id": chat_id,
                "video": cover_file_id,
                "caption": text,
                "reply_markup": reply_markup,
                "reply_to_message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
            if message_thread_id is not None:
                kwargs["message_thread_id"] = message_thread_id
            return await context.bot.send_video(**kwargs)
        except TelegramError as exc:
            log.warning(
                "auto_reply_cover_send_failed_fallback_text",
                chat_id=chat_id,
                cover_type=cover_type,
                error=str(exc),
            )
            return await _send_auto_reply_text(context, fallback_kwargs)
    return await _send_auto_reply_text(context, fallback_kwargs)
