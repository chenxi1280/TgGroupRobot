from __future__ import annotations

import json

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_buttons import (
    AUTO_REPLY_TEXT_TRIGGER,
    normalize_auto_reply_button_rows,
)
from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import parse_button_rows

log = structlog.get_logger(__name__)


def parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    try:
        raw = (raw_text or "").strip()
        if raw.startswith("["):
            return normalize_auto_reply_button_rows(json.loads(raw))
        return parse_button_rows(raw_text, allow_empty=False)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc


def _auto_reply_button(item, rule, *, row_index: int, col_index: int) -> InlineKeyboardButton | None:
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    url = str(item.get("url") or "").strip()
    if url:
        return InlineKeyboardButton(text, url=url)
    rule_id = getattr(rule, "id", None)
    chat_id = getattr(rule, "chat_id", None)
    if item.get("action_type") == AUTO_REPLY_TEXT_TRIGGER and rule_id is not None and chat_id is not None:
        callback = f"arbtn:text:{chat_id}:{rule_id}:{row_index}:{col_index}"
        return InlineKeyboardButton(text, callback_data=callback)
    callback_data = str(item.get("callback_data") or "").strip()
    return InlineKeyboardButton(text, callback_data=callback_data) if callback_data else None


def _auto_reply_button_row(row, rule, row_index: int) -> list[InlineKeyboardButton]:
    buttons = [
        _auto_reply_button(item, rule, row_index=row_index, col_index=col_index)
        for col_index, item in enumerate(row)
    ]
    return [button for button in buttons if button is not None]


def build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    raw_buttons = getattr(rule, "buttons", None) or []
    if not raw_buttons:
        return None
    try:
        normalized = normalize_auto_reply_button_rows(raw_buttons)
    except Exception as exc:
        log.warning("auto_reply_markup_normalize_failed", error=str(exc))
        return None

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for row_index, row in enumerate(normalized):
        button_row = _auto_reply_button_row(row, rule, row_index)
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


def _auto_reply_send_kwargs(chat_id: int, text: str, *, reply_markup, reply_to_message_id, message_thread_id) -> dict:
    kwargs = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
        "reply_to_message_id": reply_to_message_id,
        "allow_sending_without_reply": True,
    }
    if message_thread_id is not None:
        kwargs["message_thread_id"] = message_thread_id
    return kwargs


def _auto_reply_media_kwargs(fallback_kwargs: dict, cover_type: str, cover_file_id: str) -> dict:
    kwargs = dict(fallback_kwargs)
    kwargs.pop("text")
    kwargs[cover_type] = cover_file_id
    kwargs["caption"] = fallback_kwargs["text"]
    return kwargs


async def _send_auto_reply_media(context, fallback_kwargs: dict, *, cover_type: str, cover_file_id: str):
    kwargs = _auto_reply_media_kwargs(fallback_kwargs, cover_type, cover_file_id)
    sender = context.bot.send_photo if cover_type == "photo" else context.bot.send_video
    try:
        return await sender(**kwargs)
    except TelegramError as exc:
        log.warning(
            "auto_reply_cover_send_failed_fallback_text",
            chat_id=fallback_kwargs["chat_id"],
            cover_type=cover_type,
            error=str(exc),
        )
        return await _send_auto_reply_text(context, fallback_kwargs)


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
    fallback_kwargs = _auto_reply_send_kwargs(
        chat_id,
        text,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
        message_thread_id=message_thread_id,
    )
    log.info(
        "auto_reply_payload_send_attempt",
        chat_id=chat_id,
        send_mode=cover_type if cover_type in {"photo", "video"} and cover_file_id else "text",
        has_reply_markup=reply_markup is not None,
        reply_to_message_id=reply_to_message_id,
        message_thread_id=message_thread_id,
    )
    if cover_type in {"photo", "video"} and cover_file_id:
        return await _send_auto_reply_media(
            context,
            fallback_kwargs,
            cover_type=cover_type,
            cover_file_id=cover_file_id,
        )
    return await _send_auto_reply_text(context, fallback_kwargs)
