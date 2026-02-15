"""验证超时检查定时任务

定期检查超时的验证挑战，并根据配置执行超时处理（禁言或踢出）。
"""
from __future__ import annotations

import datetime as dt
import structlog

from telegram.ext import Application

from bot.db.session import Database
from bot.keyboards.common.verification import verification_timeout_help_keyboard
from bot.models.core import VerificationChallenge
from bot.services.automation.scheduler.core import ScheduledTask
from bot.services.automation.scheduler.task_config import TASK_CONFIG
from bot.services.base import ServiceBase
from bot.services.core.chat_service import get_chat_settings
from sqlalchemy import select


log = structlog.get_logger(__name__)


async def get_expired_challenges(session) -> list:
    """
    获取所有超时且未处理的验证挑战

    Args:
        session: 数据库会话

    Returns:
        list: 超时且未处理的验证挑战列表
    """
    now = dt.datetime.now(dt.UTC)
    result = await session.execute(
        select(VerificationChallenge)
        .where(
            VerificationChallenge.expires_at < now,
            VerificationChallenge.solved == False,
            VerificationChallenge.timeout_handled == False,
        )
    )
    return list(result.scalars().all())


async def mute_user(app: Application, chat_id: int, user_id: int, duration: int = 86400) -> bool:
    """
    禁言用户

    Args:
        app: Bot 应用实例
        chat_id: 群组 ID
        user_id: 用户 ID
        duration: 禁言时长（秒），默认 1 天
    """
    from telegram import ChatPermissions

    try:
        # 禁言直到指定时间
        until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=duration)
        await app.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
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
            ),
            until_date=until_date,
        )
        log.info("user_muted_for_verification_timeout", chat_id=chat_id, user_id=user_id, duration=duration)
        return True
    except Exception as e:
        log.warning("mute_user_failed", chat_id=chat_id, user_id=user_id, error=str(e))
        return False


async def kick_user(app: Application, chat_id: int, user_id: int) -> None:
    """
    踢出用户

    Args:
        app: Bot 应用实例
        chat_id: 群组 ID
        user_id: 用户 ID
    """
    try:
        await app.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        log.info("user_kicked_for_verification_timeout", chat_id=chat_id, user_id=user_id)
    except Exception as e:
        log.warning("kick_user_failed", chat_id=chat_id, user_id=user_id, error=str(e))


async def check_verification_timeouts(app: Application) -> None:
    """
    检查并处理验证超时

    Args:
        app: Bot 应用实例
    """
    db: Database = app.bot_data["db"]
    async with db.session_factory() as session:
        # 获取所有超时且未处理的验证挑战
        expired_challenges = await get_expired_challenges(session)

        if not expired_challenges:
            return

        log.info("processing_verification_timeouts", count=len(expired_challenges))

        for ch in expired_challenges:
            # 跳过管理员确认模式的超时处理（管理员模式永久等待）
            if ch.verification_type == "admin":
                ch.timeout_handled = True
                continue

            try:
                # 获取群组设置
                settings = await get_chat_settings(session, ch.chat_id)

                # 根据配置执行超时处理
                if settings.verification_timeout_action == "kick":
                    # 踢出群聊
                    await kick_user(app, ch.chat_id, ch.user_id)
                else:
                    # 默认禁言
                    duration = settings.verification_mute_duration
                    muted = await mute_user(app, ch.chat_id, ch.user_id, duration)

                    if muted:
                        mention = f'<a href="tg://user?id={ch.user_id}">用户</a>'
                        try:
                            await app.bot.send_message(
                                chat_id=ch.chat_id,
                                text=(
                                    f"⛔ {mention} 验证超时，已被禁言 {duration} 秒。\n"
                                    f"管理员可直接点击“管理员一键解封”，"
                                    f"或回复该用户消息发送“解封”。"
                                ),
                                parse_mode="HTML",
                                reply_markup=verification_timeout_help_keyboard(ch.user_id),
                            )
                        except Exception as e:
                            log.warning(
                                "send_verification_timeout_notice_failed",
                                chat_id=ch.chat_id,
                                user_id=ch.user_id,
                                error=str(e),
                            )

                # 标记为已处理
                ch.timeout_handled = True

            except Exception as e:
                log.exception(
                    "handle_verification_timeout_failed",
                    chat_id=ch.chat_id,
                    user_id=ch.user_id,
                    error=str(e),
                )

        await session.commit()

    if expired_challenges:
        log.info("verification_timeouts_processed", count=len(expired_challenges))


class VerificationTimeoutTask(ScheduledTask):
    """验证超时检查任务"""

    def __init__(self):
        # 每分钟检查一次
        super().__init__(
            name="verification_timeout",
            interval=60,  # 60 秒
            enabled=True,
            max_consecutive_failures=3,
        )

    async def execute(self, app) -> None:
        """执行验证超时检查"""
        await check_verification_timeouts(app)
