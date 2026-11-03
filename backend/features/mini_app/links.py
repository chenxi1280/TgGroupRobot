from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def mini_app_url(bot, scene: str) -> str:
    return f"https://t.me/{bot.username}?startapp={scene}"


def verification_link(bot, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 点击验证", url=mini_app_url(bot, f"verify_{token}"))],
    ])
