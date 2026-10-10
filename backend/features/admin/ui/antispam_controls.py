"""Compact rule controls with explicit boolean targets."""
from telegram import InlineKeyboardButton
from backend.shared.ui.common.keyboard import toggle_row


def setting_row(label: str, callback: str, value: str, *, enabled: bool | None = None) -> list[InlineKeyboardButton]:
    if enabled is None:
        return [InlineKeyboardButton(f"{label.rstrip(':：')} · {value}", callback_data=callback)]
    _, _, rule_id, field, chat_id = callback.split(":")
    return toggle_row(label, enabled=enabled, label_callback=f"gg:rule:{rule_id}:{chat_id}",
                      on_callback=f"gg:set:{rule_id}:{field}:{chat_id}:1",
                      off_callback=f"gg:set:{rule_id}:{field}:{chat_id}:0")
