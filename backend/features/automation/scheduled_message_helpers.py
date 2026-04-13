from __future__ import annotations

import json
import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.base import ValidationError
from backend.shared.services.permission_service import PermissionPolicyService


def is_clear_command(text: str) -> bool:
    """判断是否为 /clear 命令（兼容 /clear@BotName）。"""
    cmd = (text or "").strip().split(maxsplit=1)[0].lower()
    return cmd == "/clear" or cmd.startswith("/clear@")


def resolve_state_chat_id(update: Update, target_chat_id: int) -> int:
    if update.effective_chat is None:
        return target_chat_id
    return update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id


def parse_buttons_text(text: str) -> list[list[dict[str, str]]]:
    """解析按钮输入，兼容逐行格式和 JSON。"""
    raw_text = (text or "").strip()
    if not raw_text:
        return []

    if raw_text.startswith("["):
        return ScheduledMessageService.normalize_buttons_config(json.loads(raw_text))

    rows: list[list[dict[str, str]]] = []
    for row_index, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        buttons_in_row: list[dict[str, str]] = []
        items = [item.strip() for item in re.split(r"\s*[;；]\s*", line) if item.strip()]
        for col_index, item in enumerate(items, start=1):
            if "|" not in item:
                raise ValidationError(
                    f"第 {row_index} 行第 {col_index} 个按钮格式错误，请使用 文本|链接"
                )
            button_text, button_url = item.split("|", 1)
            buttons_in_row.append(
                {
                    "text": button_text.strip(),
                    "url": button_url.strip(),
                }
            )

        rows.append(buttons_in_row)

    return ScheduledMessageService.normalize_buttons_config(rows)


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

    candidate_ids: list[int] = []
    if parser is not None:
        callback_chat_id = parser.get_int_optional(2)
        if callback_chat_id not in (None, 0):
            candidate_ids.append(callback_chat_id)

    db: Database = context.application.bot_data["db"]
    current_chat_id = await ChatResolver.get_current_chat(db, user.id)
    if current_chat_id not in (None, 0) and current_chat_id not in candidate_ids:
        candidate_ids.append(current_chat_id)

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
