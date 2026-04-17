from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.chat_context import PrivateChatContext


def ensure_callback_update(update: Update) -> bool:
    return not (
        update.callback_query is None
        or update.effective_chat is None
        or update.effective_user is None
    )


def ensure_message_update(update: Update, require_user: bool = True) -> bool:
    if update.effective_chat is None or update.effective_message is None:
        return False
    if require_user and update.effective_user is None:
        return False
    return True


async def resolve_auto_reply_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_index: int = 2,
) -> int | None:
    return await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )


def get_match_type_label(match_type: str) -> str:
    labels = {
        "exact": "精确匹配",
        "contains": "包含匹配",
        "starts_with": "开头匹配",
        "ends_with": "结尾匹配",
        "regex": "正则表达式",
    }
    return labels.get(match_type, match_type)
