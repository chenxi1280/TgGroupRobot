from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService


def parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    raw = raw_text.strip()
    if not raw:
        raise ValueError("按钮配置不能为空。")

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"按钮 JSON 格式错误：{exc.msg}") from exc
        return ScheduledMessageService.normalize_buttons_config(parsed)

    rows: list[list[dict[str, str]]] = []
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        if "|" not in line:
            raise ValueError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValueError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValueError("未解析到有效按钮。")
    return ScheduledMessageService.normalize_buttons_config(rows)


def build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    raw_buttons = getattr(rule, "buttons", None) or []
    if not raw_buttons:
        return None
    try:
        normalized = ScheduledMessageService.normalize_buttons_config(raw_buttons)
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


async def send_auto_reply_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    rule,
    reply_to_message_id: int | None = None,
) -> object:
    reply_markup = build_auto_reply_markup(rule)
    cover_type = getattr(rule, "cover_media_type", None)
    cover_file_id = getattr(rule, "cover_media_file_id", None)
    if cover_type == "photo" and cover_file_id:
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    if cover_type == "video" and cover_file_id:
        return await context.bot.send_video(
            chat_id=chat_id,
            video=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )
