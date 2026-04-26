from __future__ import annotations

import structlog
from telegram.error import BadRequest

log = structlog.get_logger(__name__)


async def safe_edit_banned_word_message(q, text: str, **kwargs) -> None:
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            log.debug("banned_word_message_not_modified", callback_data=getattr(q, "data", None))
            return
        raise
