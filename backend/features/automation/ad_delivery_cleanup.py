from __future__ import annotations

import asyncio

import structlog
from telegram.ext import ContextTypes

from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


async def delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    try:
        await PublishService.delete(context, chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        log.warning(
            "ad_rotation_message_delete_failed",
            chat_id=chat_id,
            message_id=message_id,
            error=str(exc),
        )


async def delete_later(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    delay_seconds: int,
) -> None:
    try:
        await asyncio.sleep(max(delay_seconds, 1))
    except asyncio.CancelledError:
        raise
    await delete_message_safely(context, chat_id=chat_id, message_id=message_id)
