from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from telegram import InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes

from backend.shared.async_tasks import spawn_background_task

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    message_id: int | None = None
    detail: str = "ok"


class PublishService:
    """统一 Telegram 消息发布接口。"""

    @staticmethod
    async def send(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def reply(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def send_photo(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def send_video(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        video: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_video(
            chat_id=chat_id,
            video=video,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def send_document(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        document: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_document(
            chat_id=chat_id,
            document=document,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def send_sticker(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        sticker: str,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_sticker(
            chat_id=chat_id,
            sticker=sticker,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def send_animation(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        animation: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        msg: Message = await context.bot.send_animation(
            chat_id=chat_id,
            animation=animation,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=msg.message_id)

    @staticmethod
    async def edit(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        return PublishResult(ok=True, message_id=message_id)

    @staticmethod
    async def delete(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        message_id: int,
    ) -> PublishResult:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        return PublishResult(ok=True, message_id=message_id)

    @staticmethod
    async def pin(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        message_id: int,
        disable_notification: bool = True,
    ) -> PublishResult:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            disable_notification=disable_notification,
        )
        return PublishResult(ok=True, message_id=message_id)

    @staticmethod
    async def unpin(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        message_id: int | None = None,
    ) -> PublishResult:
        if message_id is None:
            await context.bot.unpin_all_chat_messages(chat_id=chat_id)
            return PublishResult(ok=True, detail="unpinned_all")
        await context.bot.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        return PublishResult(ok=True, message_id=message_id)

    @staticmethod
    async def safe_edit_or_send(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        text: str,
        message_id: int | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        if message_id is not None:
            try:
                return await PublishService.edit(
                    context,
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    **kwargs,
                )
            except Exception as exc:
                log.warning(
                    "publish_safe_edit_fallback_to_send",
                    chat_id=chat_id,
                    message_id=message_id,
                    error=str(exc),
                )
        return await PublishService.send(
            context,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )

    @staticmethod
    async def send_temporary(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        text: str,
        delete_after_seconds: int | None = None,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        **kwargs: Any,
    ) -> PublishResult:
        result = await PublishService.send(
            context,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        if result.message_id is not None and delete_after_seconds and delete_after_seconds > 0:
            spawn_background_task(
                context,
                PublishService._delete_later(
                    context,
                    chat_id=chat_id,
                    message_id=result.message_id,
                    delay_seconds=delete_after_seconds,
                ),
                name="publish_service.delete_later",
            )
        return result

    @staticmethod
    async def _delete_later(
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
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            log.warning("publish_delete_later_failed", chat_id=chat_id, message_id=message_id, error=str(exc))
            return
