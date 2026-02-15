from __future__ import annotations

import asyncio
import structlog
from telegram import Message
from telegram import Update
from telegram.ext import ContextTypes
from telegram.ext import ApplicationHandlerStop

from bot.services.moderation.anti_flood_service import (
    execute_flood_punishment,
    get_tracker,
)
from bot.services.core.chat_service import get_chat_settings
from bot.services.core.permission_service import is_bot_admin_user


log = structlog.get_logger(__name__)


async def _delete_later(msg: Message, delay_seconds: int) -> None:
    await asyncio.sleep(max(delay_seconds, 1))
    try:
        await msg.delete()
    except Exception:
        pass


async def anti_flood_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """反刷屏消息处理器"""
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    actor_id = user.id if (user is not None and sender_chat is None) else -(sender_chat.id if sender_chat is not None else 0)

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
    if settings.anti_flood_exempt_admin:
        if user is not None and is_bot_admin_user(user.id, context):
            return

    tracker = get_tracker()

    # 添加消息记录
    await tracker.add_message(chat.id, actor_id, message.message_id)

    # 检测刷屏
    result = await tracker.check_flood(
        chat.id,
        actor_id,
        settings.anti_flood_messages,
        settings.anti_flood_seconds,
    )

    if result.is_flooding:
        action = settings.anti_flood_action
        fallback_reason = ""

        # 频道/匿名身份发言无法禁言或封禁，仅支持删除
        if sender_chat is not None and action in {"mute", "ban"}:
            action = "delete"
            fallback_reason = "频道身份发言仅支持删除"

        # 群主管理员无法被机器人禁言/封禁，自动降级为删除
        if sender_chat is None and user is not None and action in {"mute", "ban"}:
            try:
                member = await context.bot.get_chat_member(chat.id, user.id)
                if member.status in {"creator", "administrator"}:
                    action = "delete"
                    fallback_reason = "目标为群主/管理员，无法禁言，已改为删除"
            except Exception as e:
                log.warning("flood_check_member_status_failed", chat_id=chat.id, user_id=user.id, error=str(e))

        log.info(
            "flood_detected",
            chat_id=chat.id,
            user_id=actor_id,
            username=user.username if user is not None else None,
            message_count=result.message_count,
            time_span=result.time_span,
            action=action,
            fallback_reason=fallback_reason or None,
        )

        # 执行惩罚
        mute_duration = settings.anti_flood_mute_duration if action == "mute" else 60
        success = await execute_flood_punishment(
            context.bot,
            chat.id,
            actor_id,
            action,
            mute_duration,
            cleanup_messages=settings.anti_flood_cleanup_messages,
        )

        if success:
            # 发送警告消息
            action_text = {
                "delete": "消息已删除",
                "mute": f"已被禁言 {mute_duration} 秒",
                "ban": "已被封禁",
            }.get(action, "已处理")

            warning_msg = (
                f"🚫 检测到刷屏行为！\n"
                f"用户: {user.mention_html() if user is not None else '频道身份发言'}\n"
                f"在 {result.time_span:.1f} 秒内发送了 {result.message_count} 条消息\n"
                f"处罚: {action_text}"
            )
            if fallback_reason:
                warning_msg += f"\n说明: {fallback_reason}"

            try:
                warning_message = await context.bot.send_message(
                    chat_id=chat.id,
                    text=warning_msg,
                    parse_mode="HTML",
                )
                if settings.anti_flood_delete_notify:
                    asyncio.create_task(
                        _delete_later(warning_message, settings.anti_flood_delete_notify_seconds)
                    )
            except Exception as e:
                log.warning("send_flood_warning_failed", chat_id=chat.id, user_id=user.id, error=str(e))

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
