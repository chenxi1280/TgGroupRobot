from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.auto_reply_runtime import (
    auto_reply_config_handler_impl,
    auto_reply_message_handler_impl,
)

async def auto_reply_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_config_handler_impl(update, context)


async def auto_reply_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_message_handler_impl(update, context)
