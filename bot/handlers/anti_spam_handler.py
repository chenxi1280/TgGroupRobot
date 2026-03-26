from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.db.session import Database
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.user_service import ensure_user
from bot.services.moderation.anti_spam_service import (
    detect_spam_violation,
)
from bot.services.moderation.moderation_service import (
    build_moderation_action_label,
    build_moderation_notice,
    normalize_moderation_actor_id,
    record_violation,
    resolve_effective_action,
    should_exempt_admin,
    send_temporary_notice,
)
from bot.services.shared.action_executor import ActionExecutor


log = structlog.get_logger(__name__)


async def execute_spam_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    actor_id: int,
    action: str,
    *,
    message_ids: list[int] | None = None,
    mute_seconds: int = 600,
    sender_chat_id: int | None = None,
    reason: str | None = None,
) -> bool:
    """兼容旧处罚入口，内部统一走 ActionExecutor。"""
    try:
        if message_ids:
            await ActionExecutor.delete_many(
                context,
                chat_id=chat_id,
                message_ids=sorted(set(message_ids)),
            )

        if action == "delete":
            return True

        execute_result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=actor_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
        return execute_result.applied
    except Exception as exc:
        log.warning(
            "anti_spam_punishment_failed",
            chat_id=chat_id,
            actor_id=actor_id,
            action=action,
            error=str(exc),
        )
        return False


async def anti_spam_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    actor_id = normalize_moderation_actor_id(user.id if user is not None else None, sender_chat.id if sender_chat is not None else None)

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
        if await should_exempt_admin(context, chat.id, user.id if user is not None else None, settings.anti_spam_exempt_admin):
            await session.commit()
            log.info("spam_skip_admin_exempt", chat_id=chat.id, user_id=user.id if user is not None else None)
            return

        violation = await detect_spam_violation(settings, message, chat.id, actor_id)

        if not violation.blocked:
            await session.commit()
            return

        resolution = await resolve_effective_action(
            context,
            chat.id,
            user.id if user is not None else actor_id,
            settings.anti_spam_action,
            sender_chat_id=sender_chat.id if sender_chat is not None else None,
        )
        action = resolution.action
        fallback_reason = resolution.fallback_reason

        # 先落库，便于排查策略命中；审计动作必须记录最终实际动作
        if user is not None and user.id > 0:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            await record_violation(
                session,
                chat_id=chat.id,
                user_id=user.id,
                message_id=message.message_id,
                rule=violation.rule,
                detail=violation.detail,
                action=action,
            )

        await session.commit()

    action = resolution.action
    fallback_reason = resolution.fallback_reason
    message_ids = [message.message_id, *getattr(violation, "message_ids_to_delete", [])]
    success = await execute_spam_punishment(
        context,
        chat.id,
        user.id if user is not None else actor_id,
        action,
        message_ids=message_ids,
        mute_seconds=settings.anti_spam_mute_duration,
        sender_chat_id=sender_chat.id if sender_chat is not None else None,
        reason=violation.rule,
    )

    if not success:
        return

    action_label = build_moderation_action_label(action, settings.anti_spam_mute_duration)
    notice = build_moderation_notice(
        "🚫 反垃圾已拦截消息",
        user.mention_html() if user is not None else "频道身份发言",
        violation.rule,
        action_label,
        fallback_reason=fallback_reason,
    )

    await send_temporary_notice(
        context.bot,
        chat_id=chat.id,
        text=notice,
        delete_after_seconds=settings.anti_spam_delete_notify_seconds if settings.anti_spam_delete_notify else None,
    )

    log.info(
        "anti_spam_blocked",
        chat_id=chat.id,
        user_id=actor_id,
        rule=violation.rule,
        action=action,
    )
    raise ApplicationHandlerStop
