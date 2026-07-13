from __future__ import annotations

import traceback

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_helpers import resolve_state_chat_id, resolve_verification_config_state
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService

log = structlog.get_logger(__name__)


async def verification_config_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
            state = await resolve_verification_config_state(session, db, chat, user=user)
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
            await parse_verification_config_impl(update, session, state, text=text)
    except Exception as exc:
        log.exception("verification_config_handler_error", error=str(exc), error_type=type(exc).__name__, exc_info=True)


async def parse_verification_config_impl(update: Update, session, state, *, text: str) -> None:
    try:
        config = _parse_verification_config_text(text)
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
        settings.verification_enabled = config["enabled"]
        settings.verification_mode = config["mode"]
        settings.verification_timeout_seconds = config["timeout_seconds"]
        settings.verification_timeout_action = config["timeout_action"]
        settings.verification_mute_duration = config["mute_duration"]
        settings.verification_direct_mute_duration = config["direct_mute_duration"]
        settings.verification_restrict_can_send = config["restrict_can_send"]
        if update.effective_user is not None:
            await ConversationStateService.clear(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()

        mode_label = {
            "button": "简单接受条约",
            "math": "简单加减法",
            "mute": "直接禁言新人",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(config["mode"], config["mode"])
        result_text = (
            "✅ 验证配置已更新！\n\n"
            "📋 配置内容：\n"
            f"• 状态: {'开启' if config['enabled'] else '关闭'}\n"
            f"• 验证方式: {mode_label}\n"
            f"• 超时时间: {config['timeout_seconds']} 秒\n"
            f"• 超时处理: {_verification_action_label(config['timeout_action'])}\n"
        )
        if config["timeout_action"] == "mute":
            result_text += f"• 禁言时长: {config['mute_duration']} 秒\n"
        if config["mode"] == "mute":
            result_text += f"• 直接禁言时长: {config['direct_mute_duration']} 秒（0=永久）\n"
        result_text += f"• 限制发言: {'是' if config['restrict_can_send'] else '否'}\n"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔙 返回验证菜单", callback_data=f"adm:menu:verification:{target_chat_id}")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
            ]
        )
        await update.effective_message.reply_text(result_text, reply_markup=keyboard)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置格式错误: {str(exc)}\n\n请重新发送配置或使用 /cancel 取消。")
    except Exception as exc:
        log.exception("parse_verification_config_error", error=str(exc))
        await update.effective_message.reply_text(f"❌ 配置失败: {str(exc)}")


def _parse_verification_config_text(text: str) -> dict:
    config = {
        "enabled": False,
        "mode": "button",
        "timeout_seconds": 180,
        "timeout_action": "mute",
        "mute_duration": 86400,
        "direct_mute_duration": 0,
        "restrict_can_send": False,
    }
    for line in [item.strip() for item in text.strip().split("\n")]:
        if line.startswith("状态:"):
            config["enabled"] = line.split(":", 1)[1].strip().lower() in ["开启", "open", "true", "1", "yes", "on"]
        elif line.startswith("验证方式:"):
            raw_mode = line.split(":", 1)[1].strip()
            config["mode"] = {
                "简单接受条约": "button",
                "按钮验证": "button",
                "button": "button",
                "简单加减法": "math",
                "数学题": "math",
                "math": "math",
                "直接禁言新人": "mute",
                "禁言新人": "mute",
                "mute": "mute",
            }.get(raw_mode, raw_mode)
        elif line.startswith("超时时间:"):
            config["timeout_seconds"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("超时处理:"):
            action_str = line.split(":", 1)[1].strip()
            if action_str in ["无", "不处理", "不额外处理", "none"]:
                config["timeout_action"] = "none"
            elif action_str in ["踢出", "踢出群聊", "kick"]:
                config["timeout_action"] = "kick"
            else:
                config["timeout_action"] = "mute"
        elif line.startswith("禁言时长:"):
            config["mute_duration"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("直接禁言时长:") or line.startswith("禁言新人时长:"):
            config["direct_mute_duration"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("限制发言:"):
            config["restrict_can_send"] = line.split(":", 1)[1].strip().lower() in ["是", "yes", "true", "1", "开启"]
    if config["mode"] not in {"button", "math", "mute"}:
        raise ValueError("验证方式仅支持：简单接受条约、简单加减法、直接禁言新人")
    return config


def _verification_action_label(action: str) -> str:
    return {
        "none": "不额外处理",
        "mute": "禁言",
        "kick": "踢出",
    }.get(action, action)


async def verification_cancel_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, reopen_menu) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    query = update.callback_query
    parts = CallbackParser.parse(query.data or "")
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
        state = await resolve_verification_config_state(session, db, chat, user=user)
        resolved_chat_id = resolve_state_chat_id(state, target_chat_id) if state is not None else target_chat_id
        allowed, reason = await PermissionPolicyService.require_manage(context, chat_id=resolved_chat_id, user_id=user.id, capability="settings")
        if not allowed:
            await session.commit()
            await answer_callback_query_safely(update, reason or "需要管理员权限", show_alert=True)
            return
        await ConversationStateService.clear(session, resolved_chat_id, user.id)
        await session.commit()
    await query.answer()
    mark_callback_query_answered(update)
    await reopen_menu(update, context, resolved_chat_id)
