from __future__ import annotations

import re

from sqlalchemy import func, or_, select
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.core import ConversationState, TgUser


def user_mention_html(user_id: int) -> str:
    return f'<a href="tg://user?id={user_id}">{user_id}</a>'


def extract_unmute_target_user_id(message, message_text: str) -> int | None:
    if getattr(message, "reply_to_message", None) is not None:
        reply_user = getattr(message.reply_to_message, "from_user", None)
        if reply_user is not None:
            return reply_user.id
    for entity in [*(message.entities or [])]:
        entity_type = getattr(entity.type, "value", entity.type)
        if entity_type == "text_mention" and entity.user is not None:
            return entity.user.id
    for pattern in [r"@(-?\d{5,})", r"(?:user_id|uid|用户id)\s*[:： ]\s*(-?\d{5,})"]:
        match = re.search(pattern, message_text, flags=re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


async def resolve_username_to_user_id(context: ContextTypes.DEFAULT_TYPE, message_text: str) -> int | None:
    username: str | None = None
    match = re.search(r"@([A-Za-z0-9_]{5,})", message_text)
    if match:
        username = match.group(1)
    if username is None:
        match = re.search(r"(?:^|\s)(?:解封|/unmute)\s+([A-Za-z][A-Za-z0-9_]{4,})", message_text, flags=re.IGNORECASE)
        if match:
            username = match.group(1)
    if not username:
        return None
    try:
        target_chat = await context.bot.get_chat(f"@{username}")
        target_id = getattr(target_chat, "id", None)
        if isinstance(target_id, int) and target_id > 0:
            return target_id
    except Exception:
        return None
    return None


def extract_unmute_name_token(message_text: str) -> str | None:
    match = re.search(r"(?:^|\s)(?:解封|/unmute)\s+([^\s]+)", message_text, flags=re.IGNORECASE)
    if not match:
        return None
    token = match.group(1).strip().lstrip("@").strip()
    return token or None


async def resolve_name_from_db(session, name_token: str) -> int | None:
    if not name_token:
        return None
    token = name_token.lower()
    stmt = (
        select(TgUser.id)
        .where(or_(func.lower(TgUser.username) == token, func.lower(TgUser.first_name) == token))
        .limit(2)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return int(rows[0]) if len(rows) == 1 else None


def resolve_state_chat_id(state: ConversationState, fallback_chat_id: int | None = None) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    if fallback_chat_id and fallback_chat_id != 0:
        return fallback_chat_id
    return None
