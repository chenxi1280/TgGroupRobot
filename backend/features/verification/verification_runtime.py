from __future__ import annotations

import datetime as dt

from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.features.verification.welcome_service import WelcomeService
from backend.platform.db.runtime.session import Database


def verification_locked_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
        can_manage_topics=False,
    )


async def restrict_for_verification(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    *,
    duration_seconds: int = 0,
) -> None:
    kwargs = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": verification_locked_permissions(),
    }
    if duration_seconds and duration_seconds > 0:
        kwargs["until_date"] = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=duration_seconds)
    await context.bot.restrict_chat_member(**kwargs)


async def apply_verification_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    settings,
    *,
    action: str | None = None,
    mute_seconds: int | None = None,
) -> str:
    selected = action or getattr(settings, "verification_timeout_action", "mute") or "mute"
    if selected == "none":
        await unrestrict_and_notify(context, chat_id, user_id, getattr(settings, "language", "zh-CN"))
        return "none"
    if selected == "kick":
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        return "kick"
    duration = int(
        mute_seconds
        if mute_seconds is not None
        else (getattr(settings, "verification_mute_duration", 86400) or 86400)
    )
    await restrict_for_verification(context, chat_id, user_id, duration_seconds=duration)
    return "mute"


async def unrestrict_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, language: str) -> None:
    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
            can_manage_topics=False,
        ),
    )


async def send_after_verify_welcome(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await WelcomeService.send_for_mode(context, session, chat_id=chat_id, mode="after_verify", user_ids=[user_id])
        await session.commit()
