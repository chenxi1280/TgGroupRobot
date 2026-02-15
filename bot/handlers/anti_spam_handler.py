from __future__ import annotations

import asyncio

import structlog
from telegram import Message, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.db.session import Database
from bot.models.core import ModerationViolation
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.permission_service import is_bot_admin_user
from bot.services.core.user_service import ensure_user
from bot.services.moderation.anti_spam_service import (
    detect_spam_violation,
    execute_spam_punishment,
)


log = structlog.get_logger(__name__)


async def _delete_later(msg: Message, delay_seconds: int) -> None:
    await asyncio.sleep(max(delay_seconds, 1))
    try:
        await msg.delete()
    except Exception:
        pass


async def anti_spam_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    actor_id = user.id if (user is not None and sender_chat is None) else -(sender_chat.id if sender_chat is not None else 0)

    if chat.type == "private":
        return

    # 机器人账号不参与反垃圾检测（频道身份消息除外）
    if user is not None and user.is_bot and message.sender_chat is None:
        return

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        if not settings.anti_spam_enabled:
            await session.commit()
            return

        # 管理员豁免（可配置）
        if settings.anti_spam_exempt_admin and user is not None:
            if is_bot_admin_user(user.id, context):
                await session.commit()
                return

        violation = await detect_spam_violation(settings, message, chat.id, actor_id)

        if not violation.blocked:
            await session.commit()
            return

        # 先落库，便于排查策略命中
        if user is not None:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            session.add(
                ModerationViolation(
                    chat_id=chat.id,
                    user_id=user.id,
                    message_id=message.message_id,
                    rule=violation.rule,
                    detail=violation.detail,
                    action=settings.anti_spam_action,
                )
            )

        await session.commit()

    action = settings.anti_spam_action if sender_chat is None else "delete"
    fallback_reason = ""
    if sender_chat is None and user is not None and action in {"mute", "ban"}:
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            if member.status in {"creator", "administrator"}:
                action = "delete"
                fallback_reason = "目标为群主/管理员，无法禁言，已改为删除"
        except Exception as e:
            log.warning("antispam_check_member_status_failed", chat_id=chat.id, user_id=user.id, error=str(e))
    message_ids = [message.message_id, *violation.message_ids_to_delete]
    success = await execute_spam_punishment(
        context.bot,
        chat.id,
        user.id if user is not None else actor_id,
        action,
        settings.anti_spam_mute_duration,
        message_ids,
    )

    if not success:
        return

    action_label = {
        "delete": "删除消息",
        "mute": f"禁言 {settings.anti_spam_mute_duration} 秒",
        "ban": "封禁用户",
    }.get(action, action)

    notice = (
        f"🚫 反垃圾已拦截消息\n"
        f"用户: {user.mention_html() if user is not None else '频道身份发言'}\n"
        f"规则: {violation.rule}\n"
        f"处罚: {action_label}"
    )
    if fallback_reason:
        notice += f"\n说明: {fallback_reason}"

    try:
        sent = await context.bot.send_message(
            chat_id=chat.id,
            text=notice,
            parse_mode="HTML",
        )
        if settings.anti_spam_delete_notify:
            asyncio.create_task(_delete_later(sent, settings.anti_spam_delete_notify_seconds))
    except Exception as e:
        log.warning("send_antispam_notice_failed", chat_id=chat.id, user_id=actor_id, error=str(e))

    log.info(
        "anti_spam_blocked",
        chat_id=chat.id,
        user_id=actor_id,
        rule=violation.rule,
        action=action,
    )
    raise ApplicationHandlerStop
