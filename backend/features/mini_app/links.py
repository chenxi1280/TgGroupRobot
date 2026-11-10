from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def mini_app_url(bot, scene: str) -> str:
    return f"https://t.me/{bot.username}?startapp={scene}"


def verification_link(bot, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 点击验证", url=mini_app_url(bot, f"verify_{token}"))],
    ])


def game_link(bot, chat_id: int, *, game: str, round_id: int | None = None) -> InlineKeyboardMarkup:
    label = "🃏 打开黑杰克牌桌" if game == "blackjack" else "🎲 打开快三骰桌"
    scene = f"game_{game}_{-chat_id}"
    if round_id is not None:
        scene += f"_{round_id}"
        label = "查看本局结算" if game == "blackjack" else "查看本局开奖"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, url=mini_app_url(bot, scene))],
    ])
