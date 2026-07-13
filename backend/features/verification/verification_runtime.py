from __future__ import annotations

import datetime as dt

from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.features.moderation.services.user_action_runtime import execute_user_action, restrict_user_safely
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
    await restrict_user_safely(
        context,
        feature="进群验证",
        chat_id=chat_id,
        user_id=user_id,
        permissions=kwargs["permissions"],
        until_date=kwargs.get("until_date"),
        detail="进群验证期间限制发言",
        raise_on_failure=True,
    )


async def apply_verification_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    *, settings,
    action: str | None = None,
    mute_seconds: int | None = None,
) -> str:
    selected = action or getattr(settings, "verification_timeout_action", "mute") or "mute"
    if selected == "none":
        await unrestrict_and_notify(context, chat_id, user_id, language=getattr(settings, "language", "zh-CN"))
        return "none"
    if selected == "kick":
        await execute_user_action(
            context,
            feature="进群验证",
            chat_id=chat_id,
            user_id=user_id,
            action="ban",
            detail="进群验证失败，按配置移出/封禁成员",
            raise_on_failure=True,
        )
        return "kick"
    duration = int(
        mute_seconds
        if mute_seconds is not None
        else (getattr(settings, "verification_mute_duration", 86400) or 86400)
    )
    await restrict_for_verification(context, chat_id, user_id, duration_seconds=duration)
    return "mute"


async def unrestrict_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, *, language: str) -> None:
    await restrict_user_safely(
        context,
        feature="进群验证",
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
        detail="验证完成或超时不处罚，解除发言限制",
        raise_on_failure=True,
    )


async def send_after_verify_welcome(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await WelcomeService.send_for_mode(context, session, chat_id=chat_id, mode="after_verify", user_ids=[user_id])
        await session.commit()
