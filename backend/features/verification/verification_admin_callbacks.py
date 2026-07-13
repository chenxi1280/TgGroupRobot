from __future__ import annotations

import structlog
from dataclasses import dataclass
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_helpers import (
    mark_challenge_released,
    start_self_review_if_needed,
    user_mention_html,
)
from backend.features.verification.verification_runtime import send_after_verify_welcome, unrestrict_and_notify
from backend.features.verification.verification_service import solve_by_token_scoped
from backend.features.moderation.services.user_action_runtime import execute_user_action
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.permission_service import PermissionPolicyService
from backend.shared.ui.common.verification import verification_timeout_help_keyboard

_ADMIN_VERIFY_CALLBACK_PARTS = 4
_TIMEOUT_HELP_CALLBACK_PARTS = 3


log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class _AdminVerifyCommand:
    user_id: int
    token: str
    action: str


async def _admin_verify_command(update: Update) -> _AdminVerifyCommand | None:
    parts = CallbackParser.parse(update.callback_query.data or "")
    if parts.action != "adm_vfy" or parts.length() < _ADMIN_VERIFY_CALLBACK_PARTS:
        await answer_callback_query_safely(update, "验证回调无效", show_alert=True)
        return None
    try:
        command = _AdminVerifyCommand(
            user_id=parts.require_int(1, label="user_id"),
            token=parts.get(2),
            action=parts.get(3),
        )
    except ValueError:
        await answer_callback_query_safely(update, "验证参数格式错误", show_alert=True)
        return None
    if command.action not in {"approve", "reject"}:
        await answer_callback_query_safely(update, "验证操作无效", show_alert=True)
        return None
    return command


async def _require_moderator(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    fallback: str = "仅群管理员可执行该操作",
) -> bool:
    chat = update.effective_chat
    actor = update.effective_user
    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=chat.id,
        user_id=actor.id,
        capability="moderation",
    )
    if allowed:
        return True
    await answer_callback_query_safely(update, reason or fallback, show_alert=True)
    return False


async def _start_approved_self_review(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, user_id: int, settings) -> bool:
    if not settings.join_self_review_enabled:
        return False
    chat = update.effective_chat
    target_user = await context.bot.get_chat_member(chat.id, user_id)
    started = await start_self_review_if_needed(context, session, chat, user=target_user.user, settings=settings)
    await session.commit()
    suffix = "初步验证，已进入自助审核。" if started else "验证"
    await update.callback_query.edit_message_text(f"✅ 已通过用户 {user_id} 的{suffix}")
    return started


async def _approve_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, command: _AdminVerifyCommand, settings) -> None:
    chat = update.effective_chat
    challenge = await solve_by_token_scoped(
        session,
        command.token,
        expected_chat_id=chat.id,
        expected_user_id=command.user_id,
    )
    await session.commit()
    if not (challenge and challenge.solved):
        await update.callback_query.edit_message_text("❌ 验证已过期或不存在")
        return
    if await _start_approved_self_review(
        update,
        context,
        session,
        user_id=command.user_id,
        settings=settings,
    ):
        return
    await unrestrict_and_notify(context, chat.id, command.user_id, language=settings.language)
    await send_after_verify_welcome(context, chat.id, command.user_id)
    await update.callback_query.edit_message_text(f"✅ 已通过用户 {command.user_id} 的验证")


async def _reject_verification(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, user_id: int) -> None:
    chat = update.effective_chat
    actor = update.effective_user
    try:
        await execute_user_action(
            context,
            feature="进群验证",
            chat_id=chat.id,
            user_id=user_id,
            action="ban",
            detail="管理员拒绝入群验证，按配置移出/封禁成员",
            actor_user_id=actor.id,
            raise_on_failure=True,
        )
        await mark_challenge_released(session, chat.id, user_id)
        await session.commit()
        await update.callback_query.edit_message_text(f"❌ 已拒绝并踢出用户 {user_id}")
    except Exception as exc:
        await session.rollback()
        log.warning("kick_user_failed", user_id=user_id, chat_id=chat.id, error=str(exc))
        await update.callback_query.edit_message_text(f"⚠️ 操作失败：{build_public_error_text(exc)}")


async def admin_verify_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    command = await _admin_verify_command(update)
    if command is None:
        return
    chat = update.effective_chat
    actor = update.effective_user
    if chat is None or actor is None:
        return
    if not await _require_moderator(update, context):
        return
    query = update.callback_query
    await query.answer()
    mark_callback_query_answered(update)
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        if command.action == "approve":
            await _approve_verification(update, context, session, command=command, settings=settings)
            return
        await _reject_verification(update, context, session, user_id=command.user_id)


async def _timeout_help_command(update: Update) -> tuple[str, int] | None:
    parts = CallbackParser.parse(update.callback_query.data or "")
    if parts.action != "vfy_help" or parts.length() < _TIMEOUT_HELP_CALLBACK_PARTS:
        await answer_callback_query_safely(update, "操作无效", show_alert=True)
        return None
    action = parts.get(1)
    try:
        target_user_id = parts.require_int(2, label="user_id")
    except ValueError:
        await answer_callback_query_safely(update, "用户参数无效", show_alert=True)
        return None
    return action, target_user_id


async def _request_unmute_help(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> None:
    chat = update.effective_chat
    actor = update.effective_user
    if actor.id != target_user_id:
        await answer_callback_query_safely(update, "仅被禁言用户本人可发起解封申请", show_alert=True)
        return
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=f"🆘 {actor.mention_html()} 请求协助解封，请等待管理员处理。",
            parse_mode="HTML",
            reply_markup=verification_timeout_help_keyboard(target_user_id),
        )
        await update.callback_query.answer("已通知管理员，请等待处理", show_alert=True)
        mark_callback_query_answered(update)
    except Exception as exc:
        log.warning(
            "verification_admin_notify_success_feedback_failed",
            chat_id=chat.id,
            user_id=actor.id,
            target_user_id=target_user_id,
            error=str(exc),
        )
        await answer_callback_query_safely(update, "通知管理员失败，请稍后重试", show_alert=True)


async def _unmute_verified_user(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id: int) -> None:
    chat = update.effective_chat
    actor = update.effective_user
    if not await _require_moderator(update, context, fallback="仅群管理员可解封"):
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()
    await unrestrict_and_notify(context, chat.id, target_user_id, language=settings.language)
    await update.callback_query.answer()
    mark_callback_query_answered(update)
    await update.callback_query.edit_message_text(
        f"✅ 管理员 {actor.mention_html()} 已解封用户 {user_mention_html(target_user_id)}\n方式: 按钮解封",
        parse_mode="HTML",
    )


async def verification_timeout_help_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    command = await _timeout_help_command(update)
    if command is None:
        return
    action, target_user_id = command
    if action == "appeal":
        await _request_unmute_help(update, context, target_user_id)
        return
    if action == "unmute":
        await _unmute_verified_user(update, context, target_user_id)
        return
    await answer_callback_query_safely(update, "不支持的解封操作", show_alert=True)
