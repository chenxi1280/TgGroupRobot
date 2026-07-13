from __future__ import annotations

import structlog
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
_ADMIN_VERIFY_CALLBACK_IMPL_THRESHOLD_4 = 4
_VERIFICATION_TIMEOUT_HELP_CALLBACK_IMPL_THRESHOLD_3 = 3


log = structlog.get_logger(__name__)


async def admin_verify_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    query = update.callback_query
    parts = CallbackParser.parse(query.data or "")
    if parts.action != "adm_vfy" or parts.length() < _ADMIN_VERIFY_CALLBACK_IMPL_THRESHOLD_4:
        await answer_callback_query_safely(update, "验证回调无效", show_alert=True)
        return
    try:
        user_id = parts.require_int(1, label="user_id")
        token = parts.get(2)
        action = parts.get(3)
    except ValueError:
        await answer_callback_query_safely(update, "验证参数格式错误", show_alert=True)
        return
    if action not in {"approve", "reject"}:
        await answer_callback_query_safely(update, "验证操作无效", show_alert=True)
        return
    chat = update.effective_chat
    actor = update.effective_user
    if chat is None or actor is None:
        return

    allowed, reason = await PermissionPolicyService.require_manage(context, chat_id=chat.id, user_id=actor.id, capability="moderation")
    if not allowed:
        await answer_callback_query_safely(update, reason or "仅群管理员可执行该操作", show_alert=True)
        return
    await query.answer()
    mark_callback_query_answered(update)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        if action == "approve":
            challenge = await solve_by_token_scoped(session, token, expected_chat_id=chat.id, expected_user_id=user_id)
            await session.commit()
            if not (challenge and challenge.solved):
                await query.edit_message_text("❌ 验证已过期或不存在")
                return
            if settings.join_self_review_enabled:
                target_user = await context.bot.get_chat_member(chat.id, user_id)
                started = await start_self_review_if_needed(context, session, chat, user=target_user.user, settings=settings)
                await session.commit()
                await query.edit_message_text(f"✅ 已通过用户 {user_id} 的{'初步验证，已进入自助审核。' if started else '验证'}")
                if started:
                    return
            await unrestrict_and_notify(context, chat.id, user_id, language=settings.language)
            await send_after_verify_welcome(context, chat.id, user_id)
            await query.edit_message_text(f"✅ 已通过用户 {user_id} 的验证")
            return

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
            await query.edit_message_text(f"❌ 已拒绝并踢出用户 {user_id}")
        except Exception as exc:
            await session.rollback()
            log.warning("kick_user_failed", user_id=user_id, chat_id=chat.id, error=str(exc))
            await query.edit_message_text(f"⚠️ 操作失败：{build_public_error_text(exc)}")


async def verification_timeout_help_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    parts = CallbackParser.parse(query.data or "")
    if parts.action != "vfy_help" or parts.length() < _VERIFICATION_TIMEOUT_HELP_CALLBACK_IMPL_THRESHOLD_3:
        await answer_callback_query_safely(update, "操作无效", show_alert=True)
        return
    action = parts.get(1)
    try:
        target_user_id = parts.require_int(2, label="user_id")
    except ValueError:
        await answer_callback_query_safely(update, "用户参数无效", show_alert=True)
        return

    chat = update.effective_chat
    actor = update.effective_user
    if action == "appeal":
        if actor.id != target_user_id:
            await answer_callback_query_safely(update, "仅被禁言用户本人可发起解封申请", show_alert=True)
            return
        try:
            keyboard = __import__(
                "backend.shared.ui.common.verification",
                fromlist=["verification_timeout_help_keyboard"],
            ).verification_timeout_help_keyboard(target_user_id)
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🆘 {actor.mention_html()} 请求协助解封，请等待管理员处理。",
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            await query.answer("已通知管理员，请等待处理", show_alert=True)
            mark_callback_query_answered(update)
        except Exception as exc:
            log.warning("verification_admin_notify_success_feedback_failed", chat_id=chat.id, user_id=actor.id, target_user_id=target_user_id, error=str(exc))
            await answer_callback_query_safely(update, "通知管理员失败，请稍后重试", show_alert=True)
        return

    if action != "unmute":
        return
    allowed, reason = await PermissionPolicyService.require_manage(context, chat_id=chat.id, user_id=actor.id, capability="moderation")
    if not allowed:
        await answer_callback_query_safely(update, reason or "仅群管理员可解封", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()
    await unrestrict_and_notify(context, chat.id, target_user_id, language=settings.language)
    await query.answer()
    mark_callback_query_answered(update)
    await query.edit_message_text(
        f"✅ 管理员 {actor.mention_html()} 已解封用户 {user_mention_html(target_user_id)}\n方式: 按钮解封",
        parse_mode="HTML",
    )
