from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.banned_word_common import (
    get_action_label,
    get_compact_match_type_label,
)
from backend.features.moderation.banned_word_runtime import (
    banned_word_check_handler_impl,
    banned_word_config_handler_impl,
)


async def banned_word_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_config_handler_impl(update, context)


async def banned_word_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_check_handler_impl(update, context)


def _get_match_type_label(match_type: str) -> str:
    return get_compact_match_type_label(match_type)


def _get_action_label(action: str) -> str:
    return get_action_label(action)
