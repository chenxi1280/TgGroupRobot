from __future__ import annotations

from dataclasses import dataclass

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.base import ValidationError
from backend.features.garage.services.garage_forward_service import GarageForwardService
from backend.features.garage.services.garage_features_service import TeacherSearchService


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _ForwardPost:
    source_channel_id: int
    source_message_id: int
    text: str
    has_media: bool


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


def _extract_forward_post(update: Update) -> _ForwardPost | None:
    if update.effective_chat is None or update.effective_message is None:
        return None
    if update.effective_chat.type != "channel":
        return None
    message = update.effective_message
    return _ForwardPost(
        source_channel_id=int(update.effective_chat.id),
        source_message_id=int(message.message_id),
        text=message.text or message.caption or "",
        has_media=_message_has_media(message),
    )


def _should_forward_post(setting, post: _ForwardPost) -> bool:
    if setting.sync_mode == "keyword":
        return GarageForwardService.matches_keywords(post.text, setting.keyword_rules)
    return GarageForwardService.should_forward(setting.sync_mode, post.text, post.has_media)


def _build_reply_markup(setting):
    if not getattr(setting, "button_template_enabled", False):
        return None
    if not getattr(setting, "button_template", None):
        return None
    try:
        return GarageForwardService.build_button_markup(setting.button_template)
    except ValidationError:
        return None


async def _index_forwarded_teacher_post(
    db: Database,
    *,
    dest_chat_id: int,
    source_channel_id: int,
    source_message_id: int,
    text: str,
) -> None:
    if not TeacherSearchService.has_channel_post_contact(text):
        return
    async with db.session_factory() as session:
        result = await TeacherSearchService.index_channel_post_teacher_profile(
            session,
            chat_id=dest_chat_id,
            channel_id=source_channel_id,
            message_id=source_message_id,
            text=text,
        )
        await session.commit()
    log.info(
        "garage_forward_teacher_post_indexed",
        chat_id=dest_chat_id,
        source_channel_id=source_channel_id,
        source_message_id=source_message_id,
        indexed=result.indexed,
        reason=result.reason,
        user_id=result.user_id,
        username=result.username,
        label_count=result.label_count,
    )


async def _index_linked_channel_teacher_post(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    post: _ForwardPost,
) -> None:
    if not TeacherSearchService.has_channel_post_contact(post.text):
        return
    get_chat = getattr(context.bot, "get_chat", None)
    if get_chat is None:
        return
    try:
        channel_chat = await get_chat(post.source_channel_id)
    except Exception as exc:
        log.warning(
            "garage_linked_channel_lookup_failed",
            source_channel_id=post.source_channel_id,
            source_message_id=post.source_message_id,
            error=str(exc),
        )
        return
    linked_chat_id = getattr(channel_chat, "linked_chat_id", None)
    if linked_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await TeacherSearchService.index_channel_post_teacher_profile(
            session,
            chat_id=int(linked_chat_id),
            channel_id=post.source_channel_id,
            message_id=post.source_message_id,
            text=post.text,
            channel_username=getattr(channel_chat, "username", None),
            channel_title=getattr(channel_chat, "title", None),
        )
        await session.commit()
    log.info(
        "garage_linked_channel_teacher_post_indexed",
        chat_id=int(linked_chat_id),
        source_channel_id=post.source_channel_id,
        source_message_id=post.source_message_id,
        indexed=result.indexed,
        reason=result.reason,
        username=result.username,
        source_url=getattr(result, "source_url", None),
    )


async def _list_destinations(db: Database, source_channel_id: int):
    async with db.session_factory() as session:
        destinations = await GarageForwardService.list_destinations_by_source(session, source_channel_id)
        await session.commit()
    return destinations


async def _claim_forward_slot(db: Database, *, dest_chat_id: int, post: _ForwardPost):
    async with db.session_factory() as session:
        reservation = await GarageForwardService.claim_forward_slot(
            session,
            chat_id=dest_chat_id,
            source_channel_id=post.source_channel_id,
            source_message_id=post.source_message_id,
        )
        if reservation is None:
            await GarageForwardService.append_audit(
                session,
                chat_id=dest_chat_id,
                source_channel_id=post.source_channel_id,
                source_message_id=post.source_message_id,
                action="copy",
                result="skipped",
                reason="duplicate_message",
            )
            await session.commit()
            return None
        reservation_id = int(reservation.id)
        await session.commit()
        return reservation_id


async def _record_forward_success(
    db: Database,
    *,
    dest_chat_id: int,
    post: _ForwardPost,
    reservation_id: int,
    copied,
) -> None:
    async with db.session_factory() as session:
        await GarageForwardService.finalize_forward(
            session,
            message_map_id=reservation_id,
            target_message_id=int(copied.message_id),
        )
        await GarageForwardService.append_audit(
            session,
            chat_id=dest_chat_id,
            source_channel_id=post.source_channel_id,
            source_message_id=post.source_message_id,
            action="copy",
            result="success",
        )
        await session.commit()


async def _record_forward_failure(
    db: Database,
    *,
    dest_chat_id: int,
    post: _ForwardPost,
    reservation_id: int,
    exc: Exception,
) -> None:
    log.warning(
        "garage_forward_copy_failed",
        chat_id=dest_chat_id,
        source_channel_id=post.source_channel_id,
        source_message_id=post.source_message_id,
        error=str(exc),
    )
    async with db.session_factory() as session:
        await GarageForwardService.abandon_forward_slot(session, message_map_id=reservation_id)
        await GarageForwardService.append_audit(
            session,
            chat_id=dest_chat_id,
            source_channel_id=post.source_channel_id,
            source_message_id=post.source_message_id,
            action="copy",
            result="failed",
            reason=str(exc)[:500],
        )
        await session.commit()


async def _copy_forward_post(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    dest_chat_id: int,
    post: _ForwardPost,
    reply_markup,
) -> None:
    db: Database = context.application.bot_data["db"]
    reservation_id = await _claim_forward_slot(db, dest_chat_id=dest_chat_id, post=post)
    if reservation_id is None:
        return
    try:
        copied = await context.bot.copy_message(
            chat_id=dest_chat_id,
            from_chat_id=post.source_channel_id,
            message_id=post.source_message_id,
            reply_markup=reply_markup,
        )
        await _record_forward_success(
            db,
            dest_chat_id=dest_chat_id,
            post=post,
            reservation_id=reservation_id,
            copied=copied,
        )
    except Exception as exc:
        await _record_forward_failure(
            db,
            dest_chat_id=dest_chat_id,
            post=post,
            reservation_id=reservation_id,
            exc=exc,
        )


async def _process_forward_destination(context: ContextTypes.DEFAULT_TYPE, *, setting, post: _ForwardPost) -> None:
    dest_chat_id = int(setting.chat_id)
    if dest_chat_id == post.source_channel_id:
        return
    if not _should_forward_post(setting, post):
        return
    db: Database = context.application.bot_data["db"]
    await _index_forwarded_teacher_post(
        db,
        dest_chat_id=dest_chat_id,
        source_channel_id=post.source_channel_id,
        source_message_id=post.source_message_id,
        text=post.text,
    )
    await _copy_forward_post(
        context,
        dest_chat_id=dest_chat_id,
        post=post,
        reply_markup=_build_reply_markup(setting),
    )


async def garage_forward_channel_post_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    post = _extract_forward_post(update)
    if post is None:
        return
    db: Database = context.application.bot_data["db"]
    destinations = await _list_destinations(db, post.source_channel_id)
    if not destinations:
        await _index_linked_channel_teacher_post(context, post=post)
        return
    await _index_linked_channel_teacher_post(context, post=post)
    for setting, _source in destinations:
        await _process_forward_destination(context, setting=setting, post=post)
