from __future__ import annotations

import asyncio

from telegram.ext import ContextTypes

from backend.shared.async_tasks import spawn_background_task
from backend.shared.services.publish_service import PublishService


async def _maybe_delete_trigger_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int | None,
    delete_mode: str,
) -> None:
    if delete_mode != "delete" or message_id is None:
        return
    try:
        await PublishService.delete(context, chat_id=chat_id, message_id=message_id)
    except Exception:
        return


async def _reply_garage_feedback(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    delete_mode: str = "none",
    reply_markup=None,
) -> None:
    await PublishService.reply(
        context,
        chat_id=chat_id,
        text=text,
        reply_to_message_id=message_id,
        reply_markup=reply_markup,
    )
    await _maybe_delete_trigger_message(
        context,
        chat_id=chat_id,
        message_id=message_id,
        delete_mode=delete_mode,
    )


def _extract_car_review_media_file_ids(message) -> list[str]:
    media_ids: list[str] = []
    for target in (message, getattr(message, "reply_to_message", None)):
        if target is None:
            continue
        photos = getattr(target, "photo", None) or []
        if photos:
            file_id = getattr(photos[-1], "file_id", None)
            if file_id:
                media_ids.append(file_id)
                break
    return media_ids


async def _delete_message_later(message, seconds: int) -> None:
    try:
        await asyncio.sleep(max(seconds, 1))
    except asyncio.CancelledError:
        raise
    try:
        await message.delete()
    except Exception:
        return


def _schedule_message_delete(
    context: ContextTypes.DEFAULT_TYPE,
    message,
    seconds: int,
    *,
    name: str = "group_hooks.delete_message_later",
) -> None:
    if seconds <= 0:
        return
    spawn_background_task(context, _delete_message_later(message, seconds), name=name)
