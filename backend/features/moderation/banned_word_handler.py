from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.chat_context import PrivateChatContext
from backend.platform.telegram.errors import mark_callback_query_answered
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
from backend.features.moderation.banned_word_menu import BannedWordMenuHandler, _banned_word_menu_handler
from backend.features.moderation.banned_word_toggle import BannedWordToggleHandler as _BannedWordToggleHandlerBase
from backend.features.moderation.banned_word_input import (
    banned_word_config_handler,
    banned_word_check_handler,
    _get_match_type_label,
    _get_action_label,
)
from backend.features.moderation.banned_word_cancel import banned_word_cancel_callback


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

        text = self._format_list_text(words, total_triggers)
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

    # 构建列表文本
    text = f"📋 违禁词列表\n\n"
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

    from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
    await q.edit_message_text(text, reply_markup=banned_word_list_keyboard(words, target_chat_id))


async def banned_word_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始添加违禁词流程"""
    log.info("banned_word_add_start_called", user_id=update.effective_user.id if update.effective_user else None)

    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    data = q.data or ""

    try:
        # 私聊中的违禁词创建 - 优先从 callback_data 获取目标群组ID
        target_chat_id = None
        target_chat_title = None
        if chat.type == "private":
            # 优先从 callback_data 提取 chat_id
            if data.startswith("banned_word:add:"):
                cb = CallbackParser.parse(data)
                target_chat_id = cb.get_int(2)

            # 如果 callback_data 中没有 chat_id，从数据库获取
            if target_chat_id == 0:
                from backend.platform.db.schema.models.core import TgChat
                from sqlalchemy import select
                db: Database = context.application.bot_data["db"]
                target_chat_id = await ChatResolver.get_current_chat(db, user.id)
                if target_chat_id is None:
                    await q.edit_message_text("请先选择一个群组")
                    return

            if not await is_user_admin(context, target_chat_id, user.id):
                await q.edit_message_text("你没有该群组的管理权限")
                return

            # 获取群组信息用于后续操作
            from backend.platform.db.schema.models.core import TgChat
            from sqlalchemy import select
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                chat_stmt = select(TgChat).where(TgChat.id == target_chat_id)
                chat_result = await session.execute(chat_stmt)
                target_chat_obj = chat_result.scalar_one_or_none()
                target_chat_title = target_chat_obj.title if target_chat_obj else f"群组{target_chat_id}"
                await session.commit()
        else:
            if not await is_user_admin(context, chat.id, user.id):
                await q.edit_message_text("需要管理员权限。")
                return
            target_chat_id = chat.id
            target_chat_title = chat.title

        log.info("pre_checks_passed", target_chat_id=target_chat_id)

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 确保目标群组存在
            await ensure_chat(session, chat_id=target_chat_id, chat_type="group", title=target_chat_title)
            log.info("target_chat_ensured", target_chat_id=target_chat_id)

            # 私聊模式下，也要确保私聊 chat 记录存在（用于状态保存）
            if chat.type == "private":
                await ensure_chat(session, chat_id=user.id, chat_type="private", title=chat.title)
                log.info("private_chat_ensured", chat_id=user.id)

            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            log.info("user_ensured", user_id=user.id)

            # 统一使用目标群组 ID 保存状态（无论私聊还是群聊）
            # 这样在群里发送消息时，状态查询可以直接匹配
            state_chat_id = target_chat_id

            # 清除旧状态（避免状态冲突）
            await clear_user_state(session, chat_id=state_chat_id, user_id=user.id)

            log.info(
                "banned_word_setting_state",
                user_id=user.id,
                state_chat_id=state_chat_id,
                target_chat_id=target_chat_id,
            )

            await set_user_state(
                session,
                chat_id=state_chat_id,
                user_id=user.id,
                state_type=ConversationStateType.banned_word_add.value,
                state_data={"step": "config", "target_chat_id": target_chat_id},
            )

            log.info("banned_word_state_set_success")
            await session.commit()
            log.info("session_committed")

            # 验证状态是否真的被保存了
            verification_state = await get_user_state(session, chat_id=state_chat_id, user_id=user.id)
            log.info(
                "state_verification",
                chat_id=state_chat_id,
                user_id=user.id,
                state_found=verification_state is not None,
                state_type=verification_state.state_type if verification_state else None,
            )

        log.info("banned_word_add_start_success")

    except Exception as e:
        log.exception("banned_word_add_start_error", error=str(e))
        await q.edit_message_text(f"❌ 启动失败: {str(e)}")
        return

    text = "🔇 添加违禁词  ( /cancel 取消)\n\n"
    text += "请按以下格式发送配置：\n\n"
    text += "```\n"
    text += "违禁词\n"
    text += "匹配类型: contains\n"
    text += "惩罚动作: delete\n"
    text += "禁言时长: 60\n"
    text += "删除提醒: true\n"
    text += "提醒消息: 您的消息因包含违禁词被删除\n"
    text += "```\n\n"
    text += "匹配类型:\n"
    text += "• exact - 精确匹配\n"
    text += "• contains - 包含匹配（默认）\n"
    text += "• regex - 正则表达式\n\n"
    text += "惩罚动作:\n"
    text += "• delete - 删除消息（默认）\n"
    text += "• mute - 删除并禁言\n"
    text += "• ban - 删除并封禁\n\n"
    text += "示例:\n"
    text += "```\n"
    text += "垃圾广告\n"
    text += "匹配类型: exact\n"
    text += "惩罚动作: mute\n"
    text += "禁言时长: 300\n"
    text += "删除提醒: true\n"
    text += "提醒消息: 请不要发送垃圾广告！\n"
    text += "```"

    # 添加取消按钮
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ 取消配置", callback_data=f"keywords:cancel:{target_chat_id}")]
    ])

    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


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

        # 构建列表文本
        text = f"📋 违禁词列表\n\n"
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

        from backend.features.moderation.ui.banned_word import banned_word_list_keyboard
        await q.edit_message_text(text, reply_markup=banned_word_list_keyboard(words, target_chat_id))
    else:
        await answer_callback_query_safely(update, "删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================
