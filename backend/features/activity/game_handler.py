from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.game_message_actions import handle_game_message
from backend.features.activity.game_runtime_actions import handle_game_runtime_callback


async def game_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await handle_game_message(update, context)


async def game_runtime_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_game_runtime_callback(update, context)
