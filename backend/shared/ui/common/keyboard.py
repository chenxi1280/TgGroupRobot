from __future__ import annotations

from collections.abc import Iterable, Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.automation.services.scheduled_message_service_validation import (
    ScheduledMessageValidationMixin,
)

NOOP_CALLBACK = "_noop"


def noop_button(text: str = " ") -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=NOOP_CALLBACK)


def back_button(callback_data: str, text: str = "🔙 返回") -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=callback_data)


def url_button(text: str, url: str) -> InlineKeyboardButton:
    normalized_url = ScheduledMessageValidationMixin._normalize_button_url(url)
    return InlineKeyboardButton(text.strip(), url=normalized_url)


def pagination_row(
    *,
    page: int,
    total_pages: int,
    previous_callback: str | None,
    next_callback: str | None,
) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if previous_callback:
        row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=previous_callback))
    row.append(noop_button(f"📄 {page + 1}/{max(total_pages, 1)}"))
    if next_callback:
        row.append(InlineKeyboardButton("下一页 ➡️", callback_data=next_callback))
    return row


def toggle_row(
    label: str,
    *,
    enabled: bool,
    on_callback: str,
    off_callback: str,
) -> list[InlineKeyboardButton]:
    return [
        noop_button(label),
        InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=on_callback),
        InlineKeyboardButton("✅ 关闭" if not enabled else "关闭", callback_data=off_callback),
    ]


def confirm_delete_keyboard(
    *,
    confirm_callback: str,
    cancel_callback: str,
    confirm_text: str = "✅ 确认删除",
    cancel_text: str = "❌ 取消",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(confirm_text, callback_data=confirm_callback),
        InlineKeyboardButton(cancel_text, callback_data=cancel_callback),
    ]])


def keyboard_with_back(
    rows: Iterable[Sequence[InlineKeyboardButton]],
    *,
    back_callback: str,
    back_text: str = "🔙 返回",
) -> InlineKeyboardMarkup:
    keyboard_rows = [list(row) for row in rows]
    keyboard_rows.append([back_button(back_callback, back_text)])
    return InlineKeyboardMarkup(keyboard_rows)
