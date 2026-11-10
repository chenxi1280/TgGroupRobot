from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def mini_app_url(bot, scene: str) -> str:
    return f"https://t.me/{bot.username}?startapp={scene}"


def verification_link(bot, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 点击验证", url=mini_app_url(bot, f"verify_{token}"))],
    ])


def game_link(bot, chat_id: int, *, game: str) -> InlineKeyboardMarkup:
    label = "🃏 打开黑杰克牌桌" if game == "blackjack" else "🎲 打开快三骰桌"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, url=mini_app_url(bot, f"game_{game}_{-chat_id}"))],
    ])
