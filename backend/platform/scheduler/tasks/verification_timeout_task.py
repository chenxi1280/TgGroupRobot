"""验证超时检查定时任务

定期检查超时的验证挑战，并根据配置执行超时处理（禁言或踢出）。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace
import structlog

from telegram.ext import Application
from telegram import ChatPermissions

from backend.platform.db.runtime.session import Database
from backend.shared.ui.common.verification import verification_timeout_help_keyboard
from backend.platform.db.schema.models.core import VerificationChallenge
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.publish_service import PublishService
from backend.features.verification.verification_runtime import verification_locked_permissions
from backend.features.verification.verification_service import is_self_review_question
from backend.features.moderation.services.user_action_runtime import execute_user_action, restrict_user_safely
from sqlalchemy import select


log = structlog.get_logger(__name__)


def _task_context(app: Application):
    return SimpleNamespace(bot=app.bot, application=app)


@dataclass(frozen=True)
class VerificationTimeoutPlan:
    challenge_id: int | None
    challenge_ref: object | None
    chat_id: int
    user_id: int
    action: str
    duration: int
    is_self_review: bool
    language: str


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
    try:
        until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=duration)
        result = await restrict_user_safely(
            _task_context(app),
            feature="进群验证",
            chat_id=chat_id,
            user_id=user_id,
            permissions=verification_locked_permissions(),
            until_date=until_date,
            detail="验证超时，按配置禁言成员",
        )
        log.info("user_muted_for_verification_timeout", chat_id=chat_id, user_id=user_id, duration=duration)
        return result.punishment_applied
    except Exception as e:
        log.warning("mute_user_failed", chat_id=chat_id, user_id=user_id, error=str(e))
        return False


async def kick_user(app: Application, chat_id: int, user_id: int) -> bool:
    """
    踢出用户

    Args:
        app: Bot 应用实例
        chat_id: 群组 ID
        user_id: 用户 ID
    """
    try:
        result = await execute_user_action(
            _task_context(app),
            feature="进群验证",
            chat_id=chat_id,
            user_id=user_id,
            action="ban",
            detail="验证超时，按配置移出/封禁成员",
        )
        log.info("user_kicked_for_verification_timeout", chat_id=chat_id, user_id=user_id)
        return result.punishment_applied
    except Exception as e:
        log.warning("kick_user_failed", chat_id=chat_id, user_id=user_id, error=str(e))
        return False


async def unrestrict_user(app: Application, chat_id: int, user_id: int) -> bool:
    """解除验证期间的发言限制。"""
    try:
        result = await restrict_user_safely(
            _task_context(app),
            feature="进群验证",
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
            detail="验证超时动作是不处罚，解除发言限制",
        )
        log.info("user_unrestricted_for_verification_timeout_none", chat_id=chat_id, user_id=user_id)
        return result.punishment_applied
    except Exception as e:
        log.warning("unrestrict_user_failed", chat_id=chat_id, user_id=user_id, error=str(e))
        return False


async def check_verification_timeouts(app: Application) -> None:
    """
    检查并处理验证超时

    Args:
        app: Bot 应用实例
    """
    db: Database = app.bot_data["db"]
    started_at = dt.datetime.now(dt.UTC)
    processed = 0
    telegram_failures = 0
    db_commit_failures = 0

    async with db.session_factory() as session:
        plans = await _build_verification_timeout_plans(session)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            log.exception("verification_timeout_claim_commit_failed", error=str(exc))
            return

    if not plans:
        return

    log.info("processing_verification_timeouts", count=len(plans))

    for plan in plans:
        ok = await _execute_verification_timeout_plan(app, plan)
        if not ok:
            telegram_failures += 1
            continue

        async with db.session_factory() as session:
            try:
                await _mark_verification_timeout_handled(session, plan)
                await session.commit()
                processed += 1
            except Exception as exc:
                db_commit_failures += 1
                await session.rollback()
                log.exception(
                    "verification_timeout_finalize_failed",
                    chat_id=plan.chat_id,
                    user_id=plan.user_id,
                    error=str(exc),
                )

    duration = (dt.datetime.now(dt.UTC) - started_at).total_seconds()
    log.info(
        "verification_timeouts_processed",
        count=len(plans),
        processed=processed,
        telegram_failures=telegram_failures,
        db_commit_failures=db_commit_failures,
        duration=round(duration, 3),
    )


async def _build_verification_timeout_plans(session) -> list[VerificationTimeoutPlan]:
    expired_challenges = await get_expired_challenges(session)
    plans: list[VerificationTimeoutPlan] = []

    for ch in expired_challenges:
        if ch.verification_type == "admin":
            ch.timeout_handled = True
            continue

        try:
            settings = await get_chat_settings(session, ch.chat_id)
            is_self_review = is_self_review_question(ch.question)
            action = "mute"
            if is_self_review and settings.join_self_review_timeout_action == "reject_block":
                action = "kick"
            elif settings.verification_timeout_action == "none":
                action = "unrestrict"
            elif settings.verification_timeout_action == "kick":
                action = "kick"

            plans.append(
                VerificationTimeoutPlan(
                    challenge_id=getattr(ch, "id", None),
                    challenge_ref=ch,
                    chat_id=int(ch.chat_id),
                    user_id=int(ch.user_id),
                    action=action,
                    duration=int(getattr(settings, "verification_mute_duration", 86400) or 86400),
                    is_self_review=is_self_review,
                    language=getattr(settings, "language", "zh-CN"),
                )
            )
        except Exception as exc:
            log.exception(
                "build_verification_timeout_plan_failed",
                chat_id=ch.chat_id,
                user_id=ch.user_id,
                error=str(exc),
            )
    return plans


async def _execute_verification_timeout_plan(app: Application, plan: VerificationTimeoutPlan) -> bool:
    if plan.action == "unrestrict":
        return await unrestrict_user(app, plan.chat_id, plan.user_id)
    if plan.action == "kick":
        return await kick_user(app, plan.chat_id, plan.user_id)

    muted = await mute_user(app, plan.chat_id, plan.user_id, plan.duration)
    if not muted:
        return False

    mention = f'<a href="tg://user?id={plan.user_id}">用户</a>'
    reason_text = (
        f"⛔ {mention} 自助审核超时，已按配置处理。\n"
        if plan.is_self_review
        else f"⛔ {mention} 验证超时，已被禁言 {plan.duration} 秒。\n"
    )
    try:
        await PublishService.send(
            type("BotContext", (), {"bot": app.bot, "application": app})(),
            chat_id=plan.chat_id,
            text=reason_text + "如需协助，请联系管理员处理。",
            parse_mode="HTML",
            reply_markup=verification_timeout_help_keyboard(plan.user_id),
        )
    except Exception as exc:
        log.warning(
            "send_verification_timeout_notice_failed",
            chat_id=plan.chat_id,
            user_id=plan.user_id,
            error=str(exc),
        )
    return True


async def _mark_verification_timeout_handled(session, plan: VerificationTimeoutPlan) -> None:
    challenge = None
    if plan.challenge_id is not None:
        challenge = await session.get(VerificationChallenge, plan.challenge_id)
    if challenge is None:
        challenge = plan.challenge_ref
    if challenge is None:
        return
    if plan.action == "unrestrict":
        challenge.solved = True
    challenge.timeout_handled = True


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
