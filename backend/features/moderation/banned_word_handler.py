from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.banned_word_create import banned_word_add_start_impl
from backend.features.moderation.banned_word_input import (
    _get_action_label,
    _get_match_type_label,
    banned_word_check_handler,
    banned_word_config_handler,
)
from backend.features.moderation.banned_word_menu import BannedWordMenuHandler, _banned_word_menu_handler
from backend.features.moderation.banned_word_toggle import BannedWordToggleHandler as _BannedWordToggleHandlerBase
from backend.features.moderation.banned_word_views import build_banned_word_list_text
from backend.features.moderation.banned_word_cancel import banned_word_cancel_callback
from backend.features.moderation.services.banned_word_service import (
    delete_banned_word,
    get_chat_banned_words,
    get_trigger_stats,
    toggle_banned_word,
)
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import is_user_admin


class BannedWordToggleHandler(_BannedWordToggleHandlerBase):
    async def _toggle_word(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        word_id: int,
        target_chat_id: int,
    ) -> bool:
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
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            words = await get_chat_banned_words(session, target_chat_id)
            total_triggers = await get_trigger_stats(session, target_chat_id)
            await session.commit()

        text = build_banned_word_list_text(words, total_triggers)
        keyboard = self._get_list_keyboard(words, target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


_banned_word_toggle_handler = BannedWordToggleHandler()

async def banned_word_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """违禁词菜单回调（适配器函数）"""
    await _banned_word_menu_handler.handle_callback(update, context)


async def banned_word_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """违禁词列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 使用 PrivateChatContext 解析目标群组
    target_chat_id = await PrivateChatContext.require_current_chat(update, context)
    if target_chat_id is None:
        return  # 错误消息已发送

    # 获取违禁词列表
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        words = await get_chat_banned_words(session, target_chat_id)
        total_triggers = await get_trigger_stats(session, target_chat_id)
        await session.commit()

    from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
    await q.edit_message_text(
        build_banned_word_list_text(words, total_triggers),
        reply_markup=banned_word_list_keyboard(words, target_chat_id),
    )


async def banned_word_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_add_start_impl(update, context)


# Handler 类定义（使用 BaseHandler）

async def banned_word_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换违禁词状态回调（适配器函数）"""
    await _banned_word_toggle_handler.handle_callback(update, context)


async def banned_word_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除违禁词回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    chat = update.effective_chat
    user = update.effective_user
    data = q.data
    if not data.startswith("banned_word_delete_"):
        return

    # 解析 word_id 和可能的 chat_id
    # 格式：banned_word_delete_{word_id} 或 banned_word_delete_{word_id}:{chat_id}
    params = data.split("_")[-1]
    cb = CallbackParser.parse(params, separator=":")
    word_id = cb.get_int(0)
    if word_id == 0:
        return

    # 如果在私聊模式，提取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        target_chat_id = cb.get_int(1)
        # 如果 callback_data 中没有 chat_id，从数据库获取
        if target_chat_id == 0:
            db: Database = context.application.bot_data["db"]
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)
            if target_chat_id is None:
                await answer_callback_query_safely(update, "请先选择一个群组", show_alert=True)
                return
    else:
        target_chat_id = chat.id

    if not await is_user_admin(context, target_chat_id, user.id):
        await answer_callback_query_safely(update, "没有该群组的管理权限", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_banned_word(session, word_id, chat_id=target_chat_id)
        await session.commit()

    if success:
        await q.answer("违禁词已删除")
        mark_callback_query_answered(update)
        # 重新显示列表
        async with db.session_factory() as session:
            words = await get_chat_banned_words(session, target_chat_id)
            total_triggers = await get_trigger_stats(session, target_chat_id)
            await session.commit()

        from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
        await q.edit_message_text(
            build_banned_word_list_text(words, total_triggers),
            reply_markup=banned_word_list_keyboard(words, target_chat_id),
        )
    else:
        await answer_callback_query_safely(update, "删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================
