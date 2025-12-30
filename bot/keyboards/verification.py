from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def verification_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("我不是机器人", callback_data=f"vfy:{token}")]])





