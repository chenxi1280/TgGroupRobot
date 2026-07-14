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
from backend.features.moderation.banned_word_input import _get_action_label, _get_match_type_label

class BannedWordToggleHandler(BaseHandler):
    """违禁词切换状态 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 从 callback data 解析的 chat_id 会作为 target_chat_id 传入
        self._use_callback_chat_id = True

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理违禁词状态切换"""
        q = update.callback_query

        # 解析违禁词 ID
        callback_data = CallbackParser.parse(q.data)
        word_id = callback_data.get_int(2)

        if word_id == 0:
            await self.message_helper.safe_answer(update, "违禁词不存在", show_alert=True)
            return

        # 切换违禁词状态
        success = await self._toggle_word(context, word_id, target_chat_id)

        if success:
            await self.message_helper.safe_answer(update, "状态已切换")
            # 刷新列表显示
            await self._refresh_list(update, context, target_chat_id)
        else:
            await self.message_helper.safe_answer(update, "违禁词不存在", show_alert=True)

    async def _toggle_word(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        word_id: int,
        target_chat_id: int,
    ) -> bool:
        """切换违禁词状态

        Args:
            context: Bot 上下文
            word_id: 违禁词 ID

        Returns:
            bool: 是否成功
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            success = await toggle_banned_word(session, word_id, chat_id=target_chat_id)
            await session.commit()
        return success

    async def _refresh_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """刷新违禁词列表显示

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            target_chat_id: 目标群组 ID
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            words = await get_chat_banned_words(session, target_chat_id)
            total_triggers = await get_trigger_stats(session, target_chat_id)
            await session.commit()

        text = self._format_list_text(words, total_triggers)
        keyboard = self._get_list_keyboard(words, target_chat_id)

        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    def _format_list_text(self, words: list, total_triggers: int) -> str:
        """格式化列表文本

        Args:
            words: 违禁词列表
            total_triggers: 总触发次数

        Returns:
            str: 格式化后的列表文本
        """
        text = "📋 违禁词列表\n\n"

        if words:
            active_count = sum(1 for w in words if w.is_active)
            text += f"总计: {len(words)} 条  |  激活: {active_count} 条  |  总触发: {total_triggers} 次\n\n"

            for w in words:
                status = "🟢 激活" if w.is_active else "🔴 暂停"
                match_type_label = _get_match_type_label(w.match_type)
                action_label = _get_action_label(w.action)
                notify_label = "📢" if w.notify else "🔇"
                text += f"{status} [{w.id}] {w.word[:30]}\n"
                text += f"   匹配: {match_type_label} | 处罚: {action_label} {notify_label}\n\n"
        else:
            text += "暂无违禁词"

        return text

    def _get_list_keyboard(self, words: list, target_chat_id: int):
        """获取列表键盘

        Args:
            words: 违禁词列表
            target_chat_id: 目标群组 ID

        Returns:
            InlineKeyboardMarkup: 列表键盘
        """
        from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
        return banned_word_list_keyboard(words, target_chat_id)


# Handler 实例
_banned_word_toggle_handler = BannedWordToggleHandler()


# 适配器函数（保持 Router 兼容）
