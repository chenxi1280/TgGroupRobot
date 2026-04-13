from __future__ import annotations

from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.features.verification.welcome_service import WelcomeService
from backend.platform.db.runtime.session import Database


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
