from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.base import ValidationError
from backend.features.garage.services.garage_forward_service import GarageForwardService


log = structlog.get_logger(__name__)


def _message_has_media(message) -> bool:
    return any(
        [
            getattr(message, "photo", None),
            getattr(message, "video", None),
            getattr(message, "document", None),
            getattr(message, "animation", None),
            getattr(message, "audio", None),
            getattr(message, "voice", None),
            getattr(message, "video_note", None),
            getattr(message, "sticker", None),
        ]
    )


async def garage_forward_channel_post_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    message = update.effective_message
    if chat.type != "channel":
        return

    source_channel_id = int(chat.id)
    source_message_id = int(message.message_id)
    text = message.text or message.caption or ""
    has_media = _message_has_media(message)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        destinations = await GarageForwardService.list_destinations_by_source(session, source_channel_id)
        await session.commit()

    if not destinations:
        return

    for setting, source in destinations:
        dest_chat_id = int(setting.chat_id)
        if dest_chat_id == source_channel_id:
            continue

        if setting.sync_mode == "keyword":
            should_forward = GarageForwardService.matches_keywords(text, setting.keyword_rules)
        else:
            should_forward = GarageForwardService.should_forward(setting.sync_mode, text, has_media)
        if not should_forward:
            continue

        reply_markup = None
        if getattr(setting, "button_template_enabled", False) and getattr(setting, "button_template", None):
            try:
                reply_markup = GarageForwardService.build_button_markup(setting.button_template)
            except ValidationError:
                reply_markup = None

        async with db.session_factory() as session:
            reservation = await GarageForwardService.claim_forward_slot(
                session,
                chat_id=dest_chat_id,
                source_channel_id=source_channel_id,
                source_message_id=source_message_id,
            )
            if reservation is None:
                await GarageForwardService.append_audit(
                    session,
                    chat_id=dest_chat_id,
                    source_channel_id=source_channel_id,
                    source_message_id=source_message_id,
                    action="copy",
                    result="skipped",
                    reason="duplicate_message",
                )
                await session.commit()
                continue
            reservation_id = int(reservation.id)
            await session.commit()

        try:
            copied = await context.bot.copy_message(
                chat_id=dest_chat_id,
                from_chat_id=source_channel_id,
                message_id=source_message_id,
                reply_markup=reply_markup,
            )
            async with db.session_factory() as session:
                await GarageForwardService.finalize_forward(
                    session,
                    message_map_id=reservation_id,
                    target_message_id=int(copied.message_id),
                )
                await GarageForwardService.append_audit(
                    session,
                    chat_id=dest_chat_id,
                    source_channel_id=source_channel_id,
                    source_message_id=source_message_id,
                    action="copy",
                    result="success",
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "garage_forward_copy_failed",
                chat_id=dest_chat_id,
                source_channel_id=source_channel_id,
                source_message_id=source_message_id,
                error=str(exc),
            )
            async with db.session_factory() as session:
                await GarageForwardService.abandon_forward_slot(session, message_map_id=reservation_id)
                await GarageForwardService.append_audit(
                    session,
                    chat_id=dest_chat_id,
                    source_channel_id=source_channel_id,
                    source_message_id=source_message_id,
                    action="copy",
                    result="failed",
                    reason=str(exc)[:500],
                )
                await session.commit()
