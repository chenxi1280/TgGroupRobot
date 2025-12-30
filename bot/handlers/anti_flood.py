from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.services.anti_flood_service import (
    execute_flood_punishment,
    get_tracker,
    FloodDetectionResult,
)
from bot.services.chat_service import get_chat_settings
from bot.services.telegram_perm import is_user_admin


log = structlog.get_logger(__name__)


async def anti_flood_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """反刷屏消息处理器"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    # 只在群组中启用
    if chat.type == "private":
        return

    # 跳过管理员
    try:
        if await is_user_admin(context, chat.id, user.id):
            return
    except Exception:
        # 如果无法获取管理员信息，跳过处理
        return

    # 获取群组设置
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    # 检查是否启用反刷屏
    if not settings.anti_flood_enabled:
        return

    tracker = get_tracker()

    # 添加消息记录
    await tracker.add_message(chat.id, user.id, message.message_id)

    # 检测刷屏
    result = await tracker.check_flood(
        chat.id,
        user.id,
        settings.anti_flood_messages,
        settings.anti_flood_seconds,
    )

    if result.is_flooding:
        log.info(
            "flood_detected",
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            message_count=result.message_count,
            time_span=result.time_span,
            action=settings.anti_flood_action,
        )

        # 执行惩罚
        mute_duration = settings.anti_flood_mute_duration if settings.anti_flood_action == "mute" else 60
        success = await execute_flood_punishment(
            context.bot,
            chat.id,
            user.id,
            settings.anti_flood_action,
            mute_duration,
        )

        if success:
            # 发送警告消息
            action_text = {
                "delete": "消息已删除",
                "mute": f"已被禁言 {mute_duration} 秒",
                "ban": "已被封禁",
            }.get(settings.anti_flood_action, "已处理")

            warning_msg = (
                f"🚫 检测到刷屏行为！\n"
                f"用户: {user.mention_html()}\n"
                f"在 {result.time_span:.1f} 秒内发送了 {result.message_count} 条消息\n"
                f"处罚: {action_text}"
            )

            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=warning_msg,
                    parse_mode="HTML",
                )
            except Exception:
                pass

            log.info(
                "flood_punishment_executed",
                chat_id=chat.id,
                user_id=user.id,
                action=settings.anti_flood_action,
            )
        else:
            log.warning(
                "flood_punishment_failed",
                chat_id=chat.id,
                user_id=user.id,
                action=settings.anti_flood_action,
            )


async def anti_flood_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """定期清理旧记录的定时任务"""
    tracker = get_tracker()
    await tracker.cleanup_old_records(max_age_seconds=300)
    log.debug("anti_flood_cleanup_done")
