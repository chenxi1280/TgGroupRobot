from __future__ import annotations

import structlog

from sqlalchemy import func, select
from telegram.error import BadRequest

from backend.platform.db.schema.models.core import TgUser

log = structlog.get_logger(__name__)

WAIT_VALUE = 0


async def safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息。"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise


async def resolve_points_target_user(session, raw: str) -> TgUser | None:
    token = raw.strip()
    if not token:
        return None

    if token.lstrip("-").isdigit():
        return await session.get(TgUser, int(token))

    username = token[1:] if token.startswith("@") else token
    username = username.strip().lower()
    if not username:
        return None

    result = await session.execute(
        select(TgUser).where(func.lower(TgUser.username) == username)
    )
    return result.scalar_one_or_none()
