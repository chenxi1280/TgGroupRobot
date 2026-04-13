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
from backend.features.moderation.auto_reply_menu import _auto_reply_menu_handler

class AutoReplyDeleteHandler(BaseHandler):
    """自动回复删除规则 Handler"""

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理自动回复规则删除"""
        from backend.shared.callback_parser import CallbackParser

        q = update.callback_query

        # 只在群组中处理
        if self.chat_resolver.is_private_chat(update):
            return

        # 解析规则 ID
        callback_data = CallbackParser.parse(q.data)
        rule_id = callback_data.get_int(2)

        if rule_id == 0:
            await self.message_helper.safe_answer(update, "删除失败", show_alert=True)
            return

        # 删除规则
        success = await self._delete_rule(context, target_chat_id, rule_id)

        if success:
            # 刷新菜单（不需要权限检查，因为已经检查过了）
            await _auto_reply_menu_handler.handle_callback(update, context, require_admin=False)
        else:
            await self.message_helper.safe_answer(update, "删除失败", show_alert=True)

    async def _delete_rule(self, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int, rule_id: int) -> bool:
        """删除规则

        Args:
            context: Bot 上下文
            rule_id: 规则 ID

        Returns:
            bool: 是否成功
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            success = await delete_auto_reply_rule(session, rule_id, chat_id=target_chat_id)
            await session.commit()
        return success


# Handler 实例
_auto_reply_delete_handler = AutoReplyDeleteHandler()


# 适配器函数（保持 Router 兼容）
async def auto_reply_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除自动回复规则回调（适配器函数）"""
    await _auto_reply_delete_handler.handle_callback(update, context)


# ============================================
# 消息处理器
# ============================================
