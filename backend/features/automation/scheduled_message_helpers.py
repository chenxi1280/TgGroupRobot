from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.ui.button_input import is_clear_button_input, parse_button_rows


def is_clear_command(text: str) -> bool:
    """判断是否为 /clear 命令（兼容 /clear@BotName）。"""
    return is_clear_button_input(text)


def resolve_state_chat_id(update: Update, target_chat_id: int) -> int:
    if update.effective_chat is None:
        return target_chat_id
    return update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id


def parse_buttons_text(text: str) -> list[list[dict[str, str]]]:
    """解析按钮输入，兼容逐行格式和 JSON。"""
    return parse_button_rows(text, allow_empty=True)


async def _target_candidates(update, context, parser: CallbackParser | None) -> list[int]:
    candidates: list[int] = []
    if parser is not None:
        callback_chat_id = parser.get_int_optional(2)
        if callback_chat_id not in (None, 0):
            candidates.append(callback_chat_id)
    db: Database = context.application.bot_data["db"]
    current_chat_id = await ChatResolver.get_current_chat(db, update.effective_user.id)
    if current_chat_id not in (None, 0) and current_chat_id not in candidates:
        candidates.append(current_chat_id)
    return candidates


async def resolve_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parser: CallbackParser | None = None,
) -> int | None:
    if update.effective_chat is None or update.effective_user is None:
        return None

    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        allowed = await PermissionPolicyService.can_manage(context, chat.id, user.id, capability="automation")
        if not allowed:
            await answer_callback_query_safely(update, "❌ 需要管理员权限", show_alert=True)
            return None
        return chat.id

    candidate_ids = await _target_candidates(update, context, parser)

    for candidate_chat_id in candidate_ids:
        allowed = await PermissionPolicyService.can_manage(
            context,
            candidate_chat_id,
            user.id,
            capability="automation",
        )
        if allowed:
            return candidate_chat_id

    if candidate_ids:
        await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
    else:
        await answer_callback_query_safely(update, "请先选择一个群组", show_alert=True)
    return None
