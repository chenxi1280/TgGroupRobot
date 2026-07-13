from __future__ import annotations

import datetime as dt

import structlog
from telegram import Bot, ChatPermissions

log = structlog.get_logger(__name__)


async def _delete_spam_messages(bot: Bot, chat_id: int, message_ids: list[int]) -> None:
    for message_id in sorted(set(message_ids)):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as exc:
            log.warning("spam_delete_message_failed", chat_id=chat_id, message_id=message_id, error=str(exc))


def _muted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=False, can_send_audios=False, can_send_documents=False,
        can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
        can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
        can_add_web_page_previews=False, can_change_info=False, can_invite_users=False,
        can_pin_messages=False, can_manage_topics=False,
    )


async def _apply_spam_action(bot: Bot, chat_id: int, user_id: int, *, action: str, mute_duration: int) -> bool:
    if action == "delete":
        return True
    if action == "mute":
        await bot.restrict_chat_member(
            chat_id=chat_id, user_id=user_id, permissions=_muted_permissions(),
            until_date=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=max(mute_duration, 1)),
        )
        return True
    if action == "ban":
        await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        return True
    return False


async def execute_spam_punishment(
    bot: Bot,
    chat_id: int,
    user_id: int,
    *, action: str,
    mute_duration: int,
    message_ids: list[int],
) -> bool:
    try:
        await _delete_spam_messages(bot, chat_id, message_ids)
        return await _apply_spam_action(bot, chat_id, user_id, action=action, mute_duration=mute_duration)
    except Exception as e:
        log.warning(
            "spam_punishment_failed",
            chat_id=chat_id,
            user_id=user_id,
            action=action,
            error=str(e),
        )
        return False
