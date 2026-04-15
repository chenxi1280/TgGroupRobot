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
from backend.features.moderation.auto_reply_helpers import _get_match_type_label, _render_auto_reply_list

class AutoReplyMenuHandler(BaseHandler):
    """自动回复菜单 Handler"""

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理自动回复菜单"""
        q = update.callback_query
        await q.answer()

        await _render_auto_reply_list(update, context, target_chat_id=target_chat_id)

    async def _handle_private_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理私聊场景 - 返回管理面板"""
        from backend.features.admin.admin_handler import _show_private_admin_menu

        await _show_private_admin_menu(update, context, target_chat_id)

    async def _handle_group_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat,
    ) -> None:
        """处理群组场景 - 显示菜单"""
        # 获取数据
        rules, total_matches = await self._fetch_data(context, target_chat_id, chat)

        # 发送响应
        await self.message_helper.safe_edit(
            update,
            text=self._format_menu_text(chat.title, rules, total_matches),
            reply_markup=self._get_menu_keyboard(),
        )

    async def _fetch_data(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat,
    ) -> tuple[list, int]:
        """获取自动回复数据

        Returns:
            tuple[list, int]: (规则列表, 总匹配次数)
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=target_chat_id, chat_type=chat.type, title=chat.title)
            rules = await get_chat_auto_reply_rules(session, target_chat_id)
            total_matches = await get_match_count(session, target_chat_id)
            await session.commit()
        return rules, total_matches

    def _format_menu_text(
        self,
        chat_title: str,
        rules: list,
        total_matches: int,
    ) -> str:
        """格式化菜单文本

        Args:
            chat_title: 群组标题
            rules: 自动回复规则列表
            total_matches: 总匹配次数

        Returns:
            str: 格式化后的菜单文本
        """
        text = f"💬 [{chat_title}] 自动回复\n\n"
        text += f"规则总数: {len(rules)}  |  总匹配次数: {total_matches}\n\n"

        if rules:
            for rule in rules[:10]:
                text += self._format_rule_item(rule)
            if len(rules) > 10:
                text += f"\n... 还有 {len(rules) - 10} 条规则"
        else:
            text += "暂无自动回复规则"

        return text

    def _format_rule_item(self, rule) -> str:
        """格式化单个规则项

        Args:
            rule: 自动回复规则对象

        Returns:
            str: 格式化后的规则项文本
        """
        status = "🟢" if rule.is_active else "🔴"
        match_type_label = _get_match_type_label(rule.match_type)
        keywords_preview = self._truncate_keywords(rule.keywords)
        reply_preview = self._truncate_text(rule.reply_content, 30)

        text = f"{status} [{rule.id}] {match_type_label}\n"
        text += f"   关键词: {keywords_preview}\n"
        text += f"   回复: {reply_preview}\n\n"
        return text

    @staticmethod
    def _truncate_keywords(keywords: list[str], max_show: int = 3) -> str:
        """截断关键词列表

        Args:
            keywords: 关键词列表
            max_show: 最多显示的关键词数量

        Returns:
            str: 截断后的关键词字符串
        """
        preview = ", ".join(keywords[:max_show])
        if len(keywords) > max_show:
            preview += f" ...(+{len(keywords) - max_show})"
        return preview

    @staticmethod
    def _truncate_text(text: str, max_length: int) -> str:
        """截断文本

        Args:
            text: 原始文本
            max_length: 最大长度

        Returns:
            str: 截断后的文本
        """
        return text[:max_length] + "..." if len(text) > max_length else text

    def _get_menu_keyboard(self):
        """获取菜单键盘

        Returns:
            InlineKeyboardMarkup: 菜单键盘
        """
        from backend.features.moderation.ui.auto_reply import auto_reply_menu_keyboard
        return auto_reply_menu_keyboard()


# Handler 实例
_auto_reply_menu_handler = AutoReplyMenuHandler()
