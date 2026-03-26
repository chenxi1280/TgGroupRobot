from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.user_service import ensure_user
from bot.services.moderation.anti_flood_service import (
    get_tracker,
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


async def execute_flood_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    actor_id: int,
    action: str,
    *,
    tracker,
    message_ids: list[int] | None = None,
    cleanup_messages: bool = False,
    mute_seconds: int = 60,
    sender_chat_id: int | None = None,
    reason: str | None = None,
) -> bool:
    """兼容旧处罚入口，内部统一走 ActionExecutor。"""
    try:
        if cleanup_messages or action == "delete":
            await ActionExecutor.delete_many(
                context,
                chat_id=chat_id,
                message_ids=message_ids or [],
            )

        if action == "delete":
            return True

        if action == "mute":
            if await tracker.is_muted(chat_id, actor_id):
                return True
            action_result = await ActionExecutor.execute(
                context,
                action="mute",
                chat_id=chat_id,
                user_id=actor_id,
                mute_seconds=mute_seconds,
                sender_chat_id=sender_chat_id,
                reason=reason,
            )
            if action_result.applied:
                await tracker.mark_muted(chat_id, actor_id, mute_seconds)
            return action_result.applied

        action_result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=actor_id,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
        return action_result.applied
    except Exception as exc:
        log.warning(
            "anti_flood_punishment_failed",
            chat_id=chat_id,
            actor_id=actor_id,
            action=action,
            error=str(exc),
        )
        return False


async def anti_flood_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """反刷屏消息处理器"""
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    actor_id = normalize_moderation_actor_id(user.id if user is not None else None, sender_chat.id if sender_chat is not None else None)

    # 只在群组中启用
    if chat.type == "private":
        return

    # 跳过普通机器人账号（频道身份消息不跳过，仍做删除拦截）
    if user is not None and user.is_bot and sender_chat is None:
        return

    # 获取群组设置
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    # 检查是否启用反刷屏
    if not settings.anti_flood_enabled:
        return

    # 管理员豁免（可配置）
    if await should_exempt_admin(context, chat.id, user.id if user is not None else None, settings.anti_flood_exempt_admin):
        log.info("flood_skip_admin_exempt", chat_id=chat.id, user_id=user.id if user is not None else None)
        return

    tracker = get_tracker()

    # 添加消息记录
    await tracker.add_message(chat.id, actor_id, message.message_id)

    # 检测刷屏
    flood_result = await tracker.check_flood(
        chat.id,
        actor_id,
        settings.anti_flood_messages,
        settings.anti_flood_seconds,
    )

    if flood_result.is_flooding:
        resolution = await resolve_effective_action(
            context,
            chat.id,
            actor_id,
            settings.anti_flood_action,
            sender_chat_id=sender_chat.id if sender_chat is not None else None,
        )
        action = resolution.action
        fallback_reason = resolution.fallback_reason

        log.info(
            "flood_detected",
            chat_id=chat.id,
            user_id=actor_id,
            username=user.username if user is not None else None,
            message_count=flood_result.message_count,
            time_span=flood_result.time_span,
            action=action,
            fallback_reason=fallback_reason or None,
        )

        if user is not None and user.id > 0:
            async with db.session_factory() as session:
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
                    rule="anti_flood",
                    detail=f"count={flood_result.message_count},span={flood_result.time_span:.3f}",
                    action=action,
                )
                await session.commit()

        # 执行惩罚：统一通过 ActionExecutor，tracker 仅负责记录和禁言去重
        if hasattr(tracker, "get_and_clear_messages"):
            message_ids = await tracker.get_and_clear_messages(chat.id, actor_id)
        else:
            message_ids = [message.message_id]
        mute_duration = settings.anti_flood_mute_duration if action == "mute" else 60
        success = await execute_flood_punishment(
            context,
            chat.id,
            actor_id,
            action,
            tracker=tracker,
            message_ids=message_ids,
            cleanup_messages=settings.anti_flood_cleanup_messages,
            mute_seconds=mute_duration,
            sender_chat_id=sender_chat.id if sender_chat is not None else None,
            reason=f"count={flood_result.message_count},span={flood_result.time_span:.3f}",
        )

        if success:
            action_text = build_moderation_action_label(action, mute_duration)
            warning_msg = build_moderation_notice(
                "🚫 检测到刷屏行为！",
                user.mention_html() if user is not None else "频道身份发言",
                f"{flood_result.time_span:.1f} 秒内发送了 {flood_result.message_count} 条消息",
                action_text,
                fallback_reason=fallback_reason,
            )

            await send_temporary_notice(
                context.bot,
                chat_id=chat.id,
                text=warning_msg,
                delete_after_seconds=settings.anti_flood_delete_notify_seconds if settings.anti_flood_delete_notify else None,
            )

            log.info(
                "flood_punishment_executed",
                chat_id=chat.id,
                user_id=actor_id,
                action=action,
            )
            raise ApplicationHandlerStop
        else:
            log.warning(
                "flood_punishment_failed",
                chat_id=chat.id,
                user_id=actor_id,
                action=action,
            )


async def anti_flood_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """定期清理旧记录的定时任务"""
    tracker = get_tracker()
    await tracker.cleanup_old_records(max_age_seconds=300)
    log.debug("anti_flood_cleanup_done")
