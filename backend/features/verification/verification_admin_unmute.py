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
    normalized = text.lower()
    if chat.type == "private" or not text or not (("解封" in text) or normalized.startswith("/unmute")):
        return False
    if not await PermissionPolicyService.can_manage(context, chat.id, actor.id, capability="moderation"):
        return False

    target_user_id = extract_target_user_id(message, text)
    if target_user_id is None:
        target_user_id = await resolve_username_to_user_id(context, text)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if target_user_id is None:
            token = (extract_target_name_token or extract_unmute_name_token)(text) or ""
            target_user_id = await resolve_name_from_db(session, token)
        if target_user_id is None:
            try:
                await message.reply_text("请回复目标用户消息或使用“解封 @用户ID / 解封 @username / 解封 用户名”。")
            except Exception as exc:
                log.warning("verification_unmute_hint_failed", chat_id=chat.id, actor_user_id=actor.id, error=str(exc))
            return True
        settings = await get_chat_settings(session, chat.id)
        await mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()
    await unrestrict_and_notify(context, chat.id, target_user_id, settings.language)
    try:
        await message.reply_text(
            f"✅ 管理员解封完成\n管理员: {actor.mention_html()}\n用户: {user_mention_html(target_user_id)}\n方式: 文本解封",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.warning("verification_unmute_success_reply_failed", chat_id=chat.id, actor_user_id=actor.id, target_user_id=target_user_id, error=str(exc))
    return True
