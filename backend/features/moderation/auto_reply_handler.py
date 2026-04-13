from __future__ import annotations

import asyncio
import json
import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


log = structlog.get_logger(__name__)

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.platform.db.schema.models.enums import AutoReplyMatchType, ConversationStateType
from backend.features.moderation.services.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_auto_reply_rule,
    get_auto_reply_rule_in_chat,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    move_auto_reply_rule,
    toggle_auto_reply_rule,
    update_auto_reply_rule,
    CreateResult,
)
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user
from backend.shared.chat_context import PrivateChatContext
from backend.features.moderation.auto_reply_helpers import (
    _ensure_callback_update,
    _ensure_message_update,
    _resolve_auto_reply_target_chat_id,
    _format_auto_reply_rule_detail,
    _parse_auto_reply_buttons_input,
    _build_auto_reply_markup,
    _send_auto_reply_payload,
    _show_auto_reply_rule_detail,
    _extract_auto_reply_list_page,
    _render_auto_reply_list,
    _get_match_type_label,
)
from backend.features.moderation.auto_reply_menu import _auto_reply_menu_handler
from backend.features.moderation.auto_reply_toggle import _auto_reply_toggle_handler
from backend.features.moderation.auto_reply_delete import _auto_reply_delete_handler
from backend.features.moderation.auto_reply_input import (
    auto_reply_config_handler,
    auto_reply_message_handler,
)
from backend.features.moderation.auto_reply_management_actions import (
    auto_reply_delete_confirm_action,
    auto_reply_delete_do_action,
    auto_reply_detail_action,
    auto_reply_edit_action,
    auto_reply_move_action,
    auto_reply_preview_action,
    auto_reply_rule_config_action,
)
from backend.features.moderation.auto_reply_cancel import auto_reply_cancel_callback

async def auto_reply_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复菜单回调（适配器函数）"""
    await _auto_reply_menu_handler.handle_callback(update, context)


async def auto_reply_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复规则列表回调"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    await _render_auto_reply_list(
        update,
        context,
        target_chat_id=target_chat_id,
        page=_extract_auto_reply_list_page(q.data),
    )


async def auto_reply_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建自动回复规则流程"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    target_chat_title = chat.title
    if chat.type == "private":
        from backend.platform.db.schema.models.core import TgChat
        from sqlalchemy import select

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
            chat_result = await session.execute(chat_stmt)
            target_chat_obj = chat_result.scalar_one_or_none()
            target_chat_title = target_chat_obj.title if target_chat_obj else f"群组{target_chat_id}"
            await session.commit()

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )

        # 设置状态：等待输入配置，保存目标群组ID
        # 保存到私聊的 chat.id（避免与其他状态冲突）
        state_chat_id = chat.id if chat.type == "private" else target_chat_id
        await set_user_state(
            session,
            chat_id=state_chat_id,
            user_id=user.id,
            state_type=ConversationStateType.auto_reply_create.value,
            state_data={"step": "config", "target_chat_id": target_chat_id},
        )
        await session.commit()

    text = "💬 创建自动回复规则  ( /cancel 取消)\n\n"
    text += "请按以下格式发送配置：\n\n"
    text += "```\n"
    text += "关键词1,关键词2,关键词3\n"
    text += "匹配类型: contains\n"
    text += "区分大小写: false\n"
    text += "停止继续匹配: true\n"
    text += "删除来源: false\n"
    text += "延迟删除: 0\n"
    text += "回复内容:\n"
    text += "这是自动回复的内容\n"
    text += "可以多行\n"
    text += "```\n\n"
    text += "匹配类型选项:\n"
    text += "• exact - 精确匹配\n"
    text += "• contains - 包含匹配（默认）\n"
    text += "• starts_with - 以...开头\n"
    text += "• ends_with - 以...结尾\n"
    text += "• regex - 正则表达式\n\n"
    text += "示例:\n"
    text += "```\n"
    text += "你好,hi,hello\n"
    text += "匹配类型: contains\n"
    text += "区分大小写: false\n"
    text += "停止继续匹配: true\n"
    text += "删除来源: false\n"
    text += "延迟删除: 0\n"
    text += "回复内容:\n"
    text += "你好呀！欢迎来到我们的群组！\n"
    text += "```"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ 取消配置", callback_data=f"autoreply:cancel:{target_chat_id}")]
    ])

    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def auto_reply_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_detail_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        show_rule_detail_func=_show_auto_reply_rule_detail,
    )


async def auto_reply_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_preview_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        send_auto_reply_payload_func=_send_auto_reply_payload,
    )


async def auto_reply_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_edit_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        set_user_state_func=set_user_state,
    )


async def auto_reply_rule_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_rule_config_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
        update_rule_func=update_auto_reply_rule,
        show_rule_detail_func=_show_auto_reply_rule_detail,
    )


async def auto_reply_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_move_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        move_rule_func=move_auto_reply_rule,
        render_list_func=_render_auto_reply_list,
    )


async def auto_reply_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_delete_confirm_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        get_rule_in_chat_func=get_auto_reply_rule_in_chat,
    )


async def auto_reply_delete_do_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await auto_reply_delete_do_action(
        update,
        context,
        ensure_callback_update_func=_ensure_callback_update,
        resolve_target_chat_id_func=_resolve_auto_reply_target_chat_id,
        delete_rule_func=delete_auto_reply_rule,
        render_list_func=_render_auto_reply_list,
    )


# Handler 类定义（使用 BaseHandler）

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换自动回复规则状态回调（兼容新旧格式）"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query

    data = q.data or ""
    if data.startswith("auto_reply:toggle:"):
        target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
        if target_chat_id is None:
            return
        parts = data.split(":")
        if len(parts) < 4:
            await q.answer("规则不存在", show_alert=True)
            return
        try:
            rule_id = int(parts[3])
        except ValueError:
            await q.answer("规则不存在", show_alert=True)
            return

        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            success = await toggle_auto_reply_rule(session, rule_id, chat_id=target_chat_id)
            await session.commit()

        if not success:
            await q.answer("规则不存在", show_alert=True)
            return

        await q.answer("状态已切换")
        await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)
        return

    await _auto_reply_toggle_handler.handle_callback(update, context, require_admin=False)


# 适配器函数（保持 Router 兼容）
async def auto_reply_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除自动回复规则回调（适配器函数）"""
    await _auto_reply_delete_handler.handle_callback(update, context)


# ============================================
# 消息处理器
# ============================================
