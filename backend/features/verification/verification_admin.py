from __future__ import annotations

import traceback

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_helpers import (
    extract_unmute_name_token,
    mark_challenge_released,
    resolve_name_from_db,
    resolve_state_chat_id,
    resolve_username_to_user_id,
    resolve_verification_config_state,
    start_self_review_if_needed,
    user_mention_html,
)
from backend.features.verification.verification_runtime import send_after_verify_welcome, unrestrict_and_notify
from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    get_challenge_by_token,
    solve_by_token_scoped,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService

log = structlog.get_logger(__name__)


async def try_admin_manual_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE, *, extract_target_user_id, t, extract_target_name_token=None) -> bool:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False
    chat = update.effective_chat
    actor = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip()
    if chat.type == "private" or not text:
        return False
    normalized = text.lower()
    wants_unmute = ("解封" in text) or normalized.startswith("/unmute")
    if not wants_unmute:
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
            except Exception:
                pass
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
    except Exception:
        pass
    return True


async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    parts = CallbackParser.parse(q.data or "")
    if parts.action != "adm_vfy" or parts.length() < 4:
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
    await q.answer()
    mark_callback_query_answered(update)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        if action == "approve":
            ch = await solve_by_token_scoped(session, token, expected_chat_id=chat.id, expected_user_id=user_id)
            await session.commit()
            if ch and ch.solved:
                if settings.join_self_review_enabled:
                    target_user = await context.bot.get_chat_member(chat.id, user_id)
                    started = await start_self_review_if_needed(context, session, chat, target_user.user, settings)
                    await session.commit()
                    await q.edit_message_text(f"✅ 已通过用户 {user_id} 的{'初步验证，已进入自助审核。' if started else '验证'}")
                    if started:
                        return
                await unrestrict_and_notify(context, chat.id, user_id, settings.language)
                await send_after_verify_welcome(context, chat.id, user_id)
                await q.edit_message_text(f"✅ 已通过用户 {user_id} 的验证")
            else:
                await q.edit_message_text("❌ 验证已过期或不存在")
        else:
            try:
                await mark_challenge_released(session, chat.id, user_id)
                await session.commit()
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user_id)
                await q.edit_message_text(f"❌ 已拒绝并踢出用户 {user_id}")
            except Exception as exc:
                log.warning("kick_user_failed", user_id=user_id, chat_id=chat.id, error=str(exc))
                await q.edit_message_text(f"⚠️ 操作失败：{build_public_error_text(exc)}")


async def verification_timeout_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    parts = CallbackParser.parse(q.data or "")
    if parts.action != "vfy_help" or parts.length() < 3:
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
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🆘 {actor.mention_html()} 请求管理员协助解封。\n管理员可点击下方按钮直接解封。",
                parse_mode="HTML",
                reply_markup=__import__("backend.shared.ui.common.verification", fromlist=["verification_timeout_help_keyboard"]).verification_timeout_help_keyboard(target_user_id),
            )
            await q.answer("已通知管理员，请等待处理", show_alert=True)
            mark_callback_query_answered(update)
        except Exception:
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
    await unrestrict_and_notify(context, chat.id, target_user_id, settings.language)
    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(
        f"✅ 管理员 {actor.mention_html()} 已解封用户 {user_mention_html(target_user_id)}\n方式: 按钮解封",
        parse_mode="HTML",
    )


async def verification_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.critical(
        "=== VERIFICATION_CONFIG_HANDLER CALLED ===",
        has_update=update is not None,
        has_chat=update.effective_chat is not None if update else False,
        has_user=update.effective_user is not None if update else False,
    )
    log.warning(
        "=== VERIFICATION_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        traceback=traceback.format_stack(),
    )
    try:
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return
        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""
        if not text:
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state = await resolve_verification_config_state(session, db, chat, user)
            if state is None:
                await session.commit()
                return
            target_chat_id = resolve_state_chat_id(state, chat.id if chat.type != "private" else None)
            if target_chat_id is None:
                await session.commit()
                await update.effective_message.reply_text("❌ 无法获取群组ID，请重新进入配置。")
                return
            allowed, reason = await PermissionPolicyService.require_manage(context, chat_id=target_chat_id, user_id=user.id, capability="settings")
            if not allowed:
                await ConversationStateService.clear(session, target_chat_id, user.id)
                await session.commit()
                await update.effective_message.reply_text(f"❌ {reason or '需要管理员权限'}")
                return
            await parse_verification_config(update, session, state, text)
    except Exception as exc:
        log.exception("verification_config_handler_error", error=str(exc), error_type=type(exc).__name__, exc_info=True)


async def parse_verification_config(update: Update, session, state, text: str) -> None:
    try:
        lines = text.strip().split("\n")
        enabled = False
        mode = "button"
        timeout_seconds = 180
        timeout_action = "mute"
        mute_duration = 86400
        restrict_can_send = False
        for line in lines:
            line = line.strip()
            if line.startswith("状态:"):
                enabled = line.split(":", 1)[1].strip().lower() in ["开启", "open", "true", "1", "yes", "on"]
            elif line.startswith("验证方式:"):
                mode = {
                    "按钮验证": "button",
                    "button": "button",
                    "数学题": "math",
                    "math": "math",
                    "验证码": "captcha",
                    "captcha": "captcha",
                    "管理员确认": "admin",
                    "admin": "admin",
                    "管理员": "admin",
                }.get(line.split(":", 1)[1].strip(), line.split(":", 1)[1].strip())
            elif line.startswith("超时时间:"):
                timeout_seconds = int(line.split(":", 1)[1].strip())
            elif line.startswith("超时处理:"):
                action_str = line.split(":", 1)[1].strip()
                if action_str in ["踢出", "踢出群聊", "kick"]:
                    timeout_action = "kick"
            elif line.startswith("禁言时长:"):
                mute_duration = int(line.split(":", 1)[1].strip())
            elif line.startswith("限制发言:"):
                restrict_can_send = line.split(":", 1)[1].strip().lower() in ["是", "yes", "true", "1", "开启"]

        target_chat_id = resolve_state_chat_id(state, update.effective_chat.id if update.effective_chat else None)
        if target_chat_id is None:
            raise ValueError("无法获取群组ID")
        await ModuleSettingsService.ensure(
            session,
            chat_id=target_chat_id,
            chat_type="supergroup" if target_chat_id < 0 else "private",
            user_id=update.effective_user.id if update.effective_user else None,
        )
        settings = await get_chat_settings(session, target_chat_id)
        settings.verification_enabled = enabled
        settings.verification_mode = mode
        settings.verification_timeout_seconds = timeout_seconds
        settings.verification_timeout_action = timeout_action
        settings.verification_mute_duration = mute_duration
        settings.verification_restrict_can_send = restrict_can_send
        if update.effective_user is not None:
            await ConversationStateService.clear(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()

        mode_label = {"button": "按钮验证", "math": "数学题", "captcha": "验证码", "admin": "管理员确认"}.get(mode, mode)
        result_text = (
            "✅ 验证配置已更新！\n\n"
            "📋 配置内容：\n"
            f"• 状态: {'开启' if enabled else '关闭'}\n"
            f"• 验证方式: {mode_label}\n"
            f"• 超时时间: {timeout_seconds} 秒\n"
            f"• 超时处理: {'禁言' if timeout_action == 'mute' else '踢出'}\n"
        )
        if timeout_action == "mute":
            result_text += f"• 禁言时长: {mute_duration} 秒\n"
        result_text += f"• 限制发言: {'是' if restrict_can_send else '否'}\n"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回验证菜单", callback_data=f"adm:menu:verification:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
        ])
        await update.effective_message.reply_text(result_text, reply_markup=keyboard)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置格式错误: {str(exc)}\n\n请重新发送配置或使用 /cancel 取消。")
    except Exception as exc:
        log.exception("parse_verification_config_error", error=str(exc))
        await update.effective_message.reply_text(f"❌ 配置失败: {str(exc)}")


async def verification_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    parts = CallbackParser.parse(q.data or "")
    if parts.action != "verification" or parts.length() < 3:
        await answer_callback_query_safely(update, "无法获取群组信息", show_alert=True)
        return
    try:
        target_chat_id = parts.require_int(2, label="chat_id")
    except ValueError:
        await answer_callback_query_safely(update, "群组ID格式错误", show_alert=True)
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await resolve_verification_config_state(session, db, chat, user)
        resolved_chat_id = resolve_state_chat_id(state, target_chat_id) if state is not None else target_chat_id
        allowed, reason = await PermissionPolicyService.require_manage(context, chat_id=resolved_chat_id, user_id=user.id, capability="settings")
        if not allowed:
            await session.commit()
            await answer_callback_query_safely(update, reason or "需要管理员权限", show_alert=True)
            return
        await ConversationStateService.clear(session, resolved_chat_id, user.id)
        await session.commit()
    await q.answer()
    mark_callback_query_answered(update)
    await admin_verification_menu_callback(update, context, resolved_chat_id)


async def admin_verification_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    await handler._show_verification_menu(update, context, target_chat_id)
