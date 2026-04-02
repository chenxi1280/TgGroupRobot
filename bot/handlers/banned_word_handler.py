from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
from bot.models.enums import BannedWordMatchType, ConversationStateType
from bot.services.moderation.banned_word_service import (
    create_banned_word,
    delete_banned_word,
    get_banned_word_in_chat,
    get_chat_banned_words,
    get_trigger_stats,
    match_banned_words,
    toggle_banned_word,
    CreateResult,
)
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.core.permission_service import is_user_admin
from bot.services.core.user_service import ensure_user
from bot.utils.callback_parser import CallbackParser
from bot.utils.chat_context import PrivateChatContext
from bot.utils.telegram_errors import answer_callback_query_safely, mark_callback_query_answered


log = structlog.get_logger(__name__)


# ============================================
# 回调处理器
# ============================================

# Handler 类定义（使用 BaseHandler）
class BannedWordMenuHandler(BaseHandler):
    """违禁词菜单 Handler"""

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理违禁词菜单"""
        q = update.callback_query
        await q.answer()

        chat = update.effective_chat

        # 私聊场景：返回到管理面板
        if self.chat_resolver.is_private_chat(update):
            await self._handle_private_chat(update, context, target_chat_id)
            return

        # 群组场景：显示菜单
        await self._handle_group_chat(update, context, target_chat_id, chat)

    async def _handle_private_chat(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理私聊场景 - 返回管理面板"""
        from bot.handlers.admin_handler import _show_private_admin_menu

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
        from bot.keyboards.content.banned_word import banned_word_menu_keyboard
        return banned_word_menu_keyboard()


# Handler 实例
_banned_word_menu_handler = BannedWordMenuHandler()


# 适配器函数（保持 Router 兼容）
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

    from bot.keyboards.content.banned_word import banned_word_list_keyboard
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
                from bot.models.core import TgChat
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
            from bot.models.core import TgChat
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
        from bot.utils.callback_parser import CallbackParser

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

        return text

    def _get_list_keyboard(self, words: list, target_chat_id: int):
        """获取列表键盘

        Args:
            words: 违禁词列表
            target_chat_id: 目标群组 ID

        Returns:
            InlineKeyboardMarkup: 列表键盘
        """
        from bot.keyboards.content.banned_word import banned_word_list_keyboard
        return banned_word_list_keyboard(words, target_chat_id)


# Handler 实例
_banned_word_toggle_handler = BannedWordToggleHandler()


# 适配器函数（保持 Router 兼容）
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

        from bot.keyboards.content.banned_word import banned_word_list_keyboard
        await q.edit_message_text(text, reply_markup=banned_word_list_keyboard(words, target_chat_id))
    else:
        await answer_callback_query_safely(update, "删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================

async def banned_word_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理违禁词添加流程中的消息"""
    # 添加诊断日志
    log.warning(
        "=== BANNED_WORD_CONFIG_HANDLER CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or "")[:50] if update.effective_message else "",
    )

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    # 只在私聊或群聊中处理
    if not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取用户状态
        if chat.type == "private":
            # 私聊模式：优先从目标群组查询（新版本逻辑）
            target_chat_id = await ChatResolver.get_current_chat(db, user_id=user.id)

            state = None
            state_source = None

            if target_chat_id:
                # 首先尝试从目标群组查询
                state = await get_user_state(session, chat_id=target_chat_id, user_id=user.id)
                if state:
                    state_source = f"target_chat_id:{target_chat_id}"

            # 如果在目标群组找不到，尝试从 user.id 查询（兼容旧版本）
            if state is None:
                state = await get_user_state(session, chat_id=user.id, user_id=user.id)
                if state:
                    state_source = f"user.id:{user.id}"

            # 添加诊断日志
            log.info(
                "banned_word_state_query",
                user_id=user.id,
                target_chat_id=target_chat_id,
                state_source=state_source,
                state_found=state is not None,
                state_type=state.state_type if state else None,
                expected_state=ConversationStateType.banned_word_add.value,
            )

            # 静默忽略非违禁词添加状态，避免干扰其他功能
            if state is None or state.state_type != ConversationStateType.banned_word_add.value:
                log.info(
                    "banned_word_state_not_match",
                    state_type=state.state_type if state else None,
                )
                await session.commit()
                return

            # 验证状态中是否有目标群组ID
            state_target_chat_id = state.state_data.get("target_chat_id")
            if state_target_chat_id is None:
                # 如果状态中没有 target_chat_id，使用当前选择的群组
                if target_chat_id is None:
                    await update.effective_message.reply_text(
                        "❌ 状态数据不完整\n\n"
                        "请先选择一个群组，然后重新点击「添加违禁词」"
                    )
                    await session.commit()
                    return
                # 使用当前选择的群组作为目标群组
                target_chat_id = target_chat_id
            else:
                target_chat_id = state_target_chat_id
        else:
            # 群聊模式：从当前群组获取状态
            state = await get_user_state(session, chat_id=chat.id, user_id=user.id)

        if state is None or state.state_type != ConversationStateType.banned_word_add.value:
            log.warning(
                "no_valid_banned_word_state",
                chat_id=chat.id,
                user_id=user.id,
                chat_type=chat.type,
                state_exists=state is not None,
                state_type=state.state_type if state else None,
            )
            await session.commit()
            return

        step = state.state_data.get("step")

        if step == "config":
            await _parse_banned_word_config(update, session, state, text)
        else:
            await session.commit()


async def _parse_banned_word_config(update: Update, session, state: object, text: str) -> None:
    """解析违禁词配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("配置格式不完整")

        # 解析违禁词（第一行）
        word = lines[0].strip()
        if not word:
            raise ValueError("违禁词不能为空")

        # 默认值
        match_type = BannedWordMatchType.contains.value
        action = "delete"
        mute_duration = 60
        notify = True
        notify_message = None

        # 解析配置
        for i in range(1, len(lines)):
            line = lines[i].strip()
            if line.startswith("匹配类型:"):
                match_type = line.split(":", 1)[1].strip()
            elif line.startswith("惩罚动作:"):
                action = line.split(":", 1)[1].strip()
            elif line.startswith("禁言时长:"):
                duration_str = line.split(":", 1)[1].strip()
                if duration_str:  # 只有非空时才解析
                    try:
                        mute_duration = int(duration_str)
                    except ValueError:
                        raise ValueError("禁言时长必须是数字")
                # 否则使用默认值（对于 delete 和 ban 动作，默认值不会被使用）
            elif line.startswith("删除提醒:"):
                notify_str = line.split(":", 1)[1].strip().lower()
                notify = notify_str in ["true", "1", "yes"]
            elif line.startswith("提醒消息:"):
                # 提取冒号后的内容
                if ":" in line:
                    notify_message = line.split(":", 1)[1].strip()

        # 获取目标群组ID（从状态数据中获取）
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id

        # 创建违禁词
        result = await create_banned_word(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            word=word,
            match_type=match_type,
            action=action,
            mute_duration=mute_duration,
            notify=notify,
            notify_message=notify_message,
        )

        if not result.success:
            error_messages = {
                "invalid_word": "❌ 违禁词格式无效\n\n违禁词不能为空",
                "invalid_match_type": "❌ 匹配类型无效\n\n有效选项：exact（精确匹配）、contains（包含匹配）、regex（正则表达式）",
                "invalid_action": "❌ 惩罚动作无效\n\n有效选项：delete（删除消息）、mute（禁言）、ban（封禁）\n\n注意：contains 是匹配类型，不是惩罚动作",
                "duplicate": "❌ 该违禁词已存在",
            }
            raise ValueError(error_messages.get(result.reason, "❌ 创建失败"))

        # 清除状态 - 统一使用目标群组 ID（与保存逻辑一致）
        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        reply_text = f"✅ 违禁词添加成功！\n\n"
        reply_text += f"🔇 违禁词: {word}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"⚖️ 惩罚动作: {_get_action_label(action)}\n"
        if action == "mute":
            reply_text += f"⏱️ 禁言时长: {mute_duration} 秒\n"
        reply_text += f"📢 删除提醒: {'是' if notify else '否'}\n"
        if notify_message:
            reply_text += f"💬 提醒消息: {notify_message}\n"
        reply_text += f"\n违禁词ID: {result.entity.id}"

        # 显示多级返回按钮：返回违禁词管理 / 返回主菜单
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回违禁词管理", callback_data=f"keywords:menu:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def banned_word_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """检测消息中的违禁词"""
    # 强制日志 - 必须在最开始输出，用于诊断 handler 是否被调用
    log.warning(
        "=== BANNED_WORD_CHECK_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
    )

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if chat.type == "private":
        return

    # 诊断日志：记录 handler 被调用
    log.info(
        "banned_word_check_called",
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        message_text_preview=(message.text or message.caption or "")[:50],
    )

    # 跳过管理员
    try:
        if await is_user_admin(context, chat.id, user.id):
            log.info("banned_word_check_skipped_admin", chat_id=chat.id, user_id=user.id)
            return
    except Exception as e:
        log.warning("admin_check_failed", chat_id=chat.id, user_id=user.id, error=str(e))
        return

    message_text = message.text or message.caption or ""
    if not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)

        # 诊断日志：记录查询结果
        words = await get_chat_banned_words(session, chat.id)
        log.info(
            "banned_word_check_result",
            chat_id=chat.id,
            user_id=user.id,
            message_text_preview=message_text[:50],
            total_words_count=len(words),
            active_words_count=sum(1 for w in words if w.is_active),
            matched_count=len(matched_words),
        )

        await session.commit()

    if matched_words:
        # 使用第一个匹配的违禁词的配置
        word = matched_words[0]

        log.info(
            "banned_word_detected",
            chat_id=chat.id,
            user_id=user.id,
            username=user.username,
            word=word.word,
            action=word.action,
        )

        # 删除消息
        try:
            await message.delete()
        except Exception as e:
            log.warning("delete_message_failed", chat_id=chat.id, user_id=user.id, error=str(e))

        # 发送提醒
        if word.notify:
            notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
            try:
                await context.bot.send_message(chat_id=chat.id, text=notify_msg)
            except Exception as e:
                log.warning("send_notify_failed", chat_id=chat.id, error=str(e))

        # 执行惩罚
        if word.action == "mute":
            try:
                import datetime as dt
                until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=word.mute_duration) if word.mute_duration else None
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user.id,
                    permissions={"can_send_messages": False, "can_send_media_messages": False},
                    until_date=until_date,
                )
            except Exception as e:
                log.warning("mute_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))
        elif word.action == "ban":
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception as e:
                log.warning("ban_user_failed", chat_id=chat.id, user_id=user.id, error=str(e))


def _get_match_type_label(match_type: str) -> str:
    """获取匹配类型标签"""
    labels = {
        "exact": "精确匹配",
        "contains": "包含匹配",
        "regex": "正则表达式",
    }
    return labels.get(match_type, match_type)


def _get_action_label(action: str) -> str:
    """获取惩罚动作标签"""
    labels = {
        "delete": "删除",
        "mute": "禁言",
        "ban": "封禁",
    }
    return labels.get(action, action)


# ==================== 取消回调处理器 ====================

async def banned_word_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消违禁词配置，返回违禁词菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 解析参数：keywords:cancel:{chat_id}
    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        await q.edit_message_text("❌ 无法获取群组信息")
        return

    try:
        target_chat_id = int(parts[2])
    except ValueError:
        await q.edit_message_text("❌ 群组ID格式错误")
        return

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 清除配置状态
        state_chat_id = user.id if chat.type == "private" else chat.id
        await clear_user_state(session, state_chat_id, user.id)
        await session.commit()

    # 返回管理面板
    # 不调用菜单回调（因为它会从状态中获取 target_chat_id，但状态已被清除）
    # 直接调用管理面板，传递 target_chat_id
    from bot.handlers.admin_handler import _show_private_admin_menu

    await _show_private_admin_menu(update, context, target_chat_id)
