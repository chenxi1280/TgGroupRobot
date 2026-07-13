from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.platform.db.schema.models.enums import BannedWordMatchType, ConversationStateType
from backend.features.moderation.services.banned_word_service import (
    create_banned_word,
    delete_banned_word,
    get_banned_word_in_chat,
    get_chat_banned_words,
    get_trigger_stats,
    match_banned_words,
    toggle_banned_word,
    CreateResult,
)
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.services.permission_service import is_user_admin
from backend.shared.services.user_service import ensure_user
from backend.shared.callback_parser import CallbackParser

class BannedWordMenuHandler(BaseHandler):
    """违禁词菜单 Handler"""

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理违禁词菜单"""
        chat = update.effective_chat

        # 私聊场景：返回到管理面板
        if self.chat_resolver.is_private_chat(update):
            await self._handle_private_chat(update, context, target_chat_id)
            return

        # 群组场景：显示菜单
        await self._handle_group_chat(update, context, target_chat_id, chat=chat)

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
        *, chat,
    ) -> None:
        """处理群组场景 - 显示菜单"""
        # 获取数据
        words, total_triggers = await self._fetch_data(context, target_chat_id, chat)

        # 发送响应
        await self.message_helper.safe_edit(
            update,
            text=self._format_menu_text(chat.title, words, total_triggers),
            reply_markup=self._get_menu_keyboard(),
        )

    async def _fetch_data(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat,
    ) -> tuple[list, int]:
        """获取违禁词数据

        Returns:
            tuple[list, int]: (违禁词列表, 总触发次数)
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ensure_chat(session, chat_id=target_chat_id, chat_type=chat.type, title=chat.title)
            words = await get_chat_banned_words(session, target_chat_id)
            total_triggers = await get_trigger_stats(session, target_chat_id)
            await session.commit()
        return words, total_triggers

    def _format_menu_text(
        self,
        chat_title: str,
        words: list,
        total_triggers: int,
    ) -> str:
        """格式化菜单文本

        Args:
            chat_title: 群组标题
            words: 违禁词列表
            total_triggers: 总触发次数

        Returns:
            str: 格式化后的菜单文本
        """
        text = f"🔇 [{chat_title}] 违禁词管理\n\n"
        text += f"违禁词总数: {len(words)}  |  总触发次数: {total_triggers}\n\n"

        if words:
            for w in words[:15]:
                text += self._format_word_item(w)
            if len(words) > 15:
                text += f"\n... 还有 {len(words) - 15} 条"
        else:
            text += "暂无违禁词"

        return text

    def _format_word_item(self, word) -> str:
        """格式化单个违禁词项

        Args:
            word: 违禁词对象

        Returns:
            str: 格式化后的违禁词项文本
        """
        status = "🟢" if word.is_active else "🔴"
        match_type_label = _get_match_type_label(word.match_type)
        action_label = _get_action_label(word.action)
        notify_label = "📢" if word.notify else "🔇"

        text = f"{status} [{word.id}] {word.word[:30]}\n"
        text += f"   匹配: {match_type_label} | 处罚: {action_label} {notify_label}\n\n"
        return text

    def _get_menu_keyboard(self):
        """获取菜单键盘

        Returns:
            InlineKeyboardMarkup: 菜单键盘
        """
        from backend.features.moderation.ui.banned_word import banned_word_menu_keyboard
        return banned_word_menu_keyboard()


# Handler 实例
_banned_word_menu_handler = BannedWordMenuHandler()


# 适配器函数（保持 Router 兼容）
