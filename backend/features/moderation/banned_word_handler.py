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
from backend.features.moderation.banned_word_message import safe_edit_banned_word_message
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
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
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
        await safe_edit_banned_word_message(update.callback_query, text, reply_markup=keyboard)


_banned_word_toggle_handler = BannedWordToggleHandler()

async def banned_word_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """违禁词菜单回调（适配器函数）"""
    await _banned_word_menu_handler.handle_callback(update, context)


async def banned_word_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """违禁词列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    cb = CallbackParser.parse(q.data or "")
    if update.effective_chat.type == "private":
        target_chat_id = cb.get_int_optional(2)
        if target_chat_id is None:
            await answer_callback_query_safely(update, "❌ 群组参数无效，请返回重试", show_alert=True)
            return
    else:
        target_chat_id = update.effective_chat.id

    await q.answer()
    mark_callback_query_answered(update)

    # 获取违禁词列表
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        words = await get_chat_banned_words(session, target_chat_id)
        total_triggers = await get_trigger_stats(session, target_chat_id)
        await session.commit()

    from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
    await safe_edit_banned_word_message(
        q,
        build_banned_word_list_text(words, total_triggers),
        reply_markup=banned_word_list_keyboard(words, target_chat_id),
    )


async def banned_word_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_add_start_impl(update, context)


# Handler 类定义（使用 BaseHandler）

async def banned_word_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换违禁词状态回调（适配器函数）"""
    await _banned_word_toggle_handler.handle_callback(update, context)


def _parse_delete_word_callback(data: str) -> tuple[int, int]:
    if not data.startswith("banned_word_delete_"):
        return 0, 0
    cb = CallbackParser.parse(data.split("_")[-1], separator=":")
    return cb.get_int(0), cb.get_int(1)


async def _resolve_delete_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_chat_id: int,
) -> int | None:
    chat = update.effective_chat
    user = update.effective_user
    if chat.type != "private":
        return chat.id
    if callback_chat_id != 0:
        return callback_chat_id
    db: Database = context.application.bot_data["db"]
    target_chat_id = await ChatResolver.get_current_chat(db, user.id)
    if target_chat_id is None:
        await answer_callback_query_safely(update, "请先选择一个群组", show_alert=True)
    return target_chat_id


async def _delete_word_record(
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    word_id: int,
) -> bool:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_banned_word(session, word_id, chat_id=target_chat_id)
        await session.commit()
    return success


async def _refresh_banned_word_list(q, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
    from backend.features.moderation.ui.banned_word import banned_word_list_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        words = await get_chat_banned_words(session, target_chat_id)
        total_triggers = await get_trigger_stats(session, target_chat_id)
        await session.commit()
    await safe_edit_banned_word_message(
        q,
        build_banned_word_list_text(words, total_triggers),
        reply_markup=banned_word_list_keyboard(words, target_chat_id),
    )


async def banned_word_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除违禁词回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    user = update.effective_user
    word_id, callback_chat_id = _parse_delete_word_callback(q.data or "")
    if word_id == 0:
        await answer_callback_query_safely(update, "违禁词参数无效", show_alert=True)
        return
    target_chat_id = await _resolve_delete_chat_id(update, context, callback_chat_id)
    if target_chat_id is None:
        return
    if not await is_user_admin(context, target_chat_id, user.id):
        await answer_callback_query_safely(update, "没有该群组的管理权限", show_alert=True)
        return
    if not await _delete_word_record(context, target_chat_id, word_id):
        await answer_callback_query_safely(update, "删除失败", show_alert=True)
        return
    await answer_callback_query_safely(update, "违禁词已删除", show_alert=False)
    await _refresh_banned_word_list(q, context, target_chat_id)


# ============================================
# 消息处理器
# ============================================
