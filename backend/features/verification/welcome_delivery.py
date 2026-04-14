from __future__ import annotations

import asyncio

from telegram.ext import ContextTypes

from backend.platform.db.schema.models.enums import WelcomeDeleteMode


async def send_rendered_payload(context: ContextTypes.DEFAULT_TYPE, chat_id: int, *, payload):
    try:
        if payload.media_type == "photo" and payload.media_file_id:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=payload.media_file_id,
                caption=payload.text,
                reply_markup=payload.reply_markup,
                parse_mode=payload.parse_mode,
            )
        if payload.media_type == "video" and payload.media_file_id:
            return await context.bot.send_video(
                chat_id=chat_id,
                video=payload.media_file_id,
                caption=payload.text,
                reply_markup=payload.reply_markup,
                parse_mode=payload.parse_mode,
            )
        return await context.bot.send_message(
            chat_id=chat_id,
            text=payload.text,
            reply_markup=payload.reply_markup,
            parse_mode=payload.parse_mode,
        )
    except Exception:
        return None


async def apply_welcome_delete_strategy(session, welcome, message_id: int, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    if welcome.delete_mode == WelcomeDeleteMode.delete_prev.value and welcome.last_sent_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=welcome.last_sent_message_id)
        except Exception:
            pass
        welcome.last_sent_message_id = message_id
        await session.flush()
        return

    if welcome.delete_mode == WelcomeDeleteMode.keep.value:
        welcome.last_sent_message_id = message_id
        await session.flush()
        return

    if welcome.delete_mode == WelcomeDeleteMode.seconds.value:
        welcome.last_sent_message_id = message_id
        await session.flush()
        delay = int(welcome.delete_delay_seconds or 0)
        if delay > 0:
            asyncio.create_task(delete_welcome_later(context, chat_id, message_id, delay))


async def delete_welcome_later(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int) -> None:
    try:
        await asyncio.sleep(delay)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        return
