from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_helpers import (
    extract_unmute_name_token,
    mark_challenge_released,
    resolve_name_from_db,
    resolve_username_to_user_id,
    user_mention_html,
)
from backend.features.verification.verification_runtime import unrestrict_and_notify
from backend.platform.db.runtime.session import Database
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.permission_service import PermissionPolicyService

log = structlog.get_logger(__name__)


async def _resolve_unmute_target(context, session, message, *, text: str, id_extractor, name_extractor) -> int | None:
    target_user_id = id_extractor(message, text)
    if target_user_id is None:
        target_user_id = await resolve_username_to_user_id(context, text)
    if target_user_id is not None:
        return target_user_id
    token = (name_extractor or extract_unmute_name_token)(text) or ""
    return await resolve_name_from_db(session, token)


async def _reply_unmute_success(message, actor, target_user_id: int) -> None:
    await message.reply_text(
        f"✅ 管理员解封完成\n管理员: {actor.mention_html()}\n"
        f"用户: {user_mention_html(target_user_id)}\n方式: 文本解封",
        parse_mode="HTML",
    )


def _is_unmute_request(chat, text: str) -> bool:
    if chat.type == "private" or not text:
        return False
    return "解封" in text or text.lower().startswith("/unmute")


async def _reply_missing_unmute_target(message) -> None:
    await message.reply_text("请回复目标用户消息或使用“解封 @用户ID / 解封 @username / 解封 用户名”。")


async def try_admin_manual_unmute_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    extract_target_user_id,
    extract_target_name_token=None,
) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    chat = update.effective_chat
    actor = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip()
    if not _is_unmute_request(chat, text):
        return False
    if not await PermissionPolicyService.can_manage(context, chat.id, actor.id, capability="moderation"):
        return False

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_user_id = await _resolve_unmute_target(
            context, session, message, text=text,
            id_extractor=extract_target_user_id, name_extractor=extract_target_name_token,
        )
        if target_user_id is None:
            try:
                await _reply_missing_unmute_target(message)
            except Exception as exc:
                log.warning("verification_unmute_hint_failed", chat_id=chat.id, actor_user_id=actor.id, error=str(exc))
            return True
        settings = await get_chat_settings(session, chat.id)
        await mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()
    await unrestrict_and_notify(context, chat.id, target_user_id, language=settings.language)
    try:
        await _reply_unmute_success(message, actor, target_user_id)
    except Exception as exc:
        log.warning("verification_unmute_success_reply_failed", chat_id=chat.id, actor_user_id=actor.id, target_user_id=target_user_id, error=str(exc))
    return True
