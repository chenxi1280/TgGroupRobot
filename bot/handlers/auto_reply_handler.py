from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.models.enums import AutoReplyMatchType, ConversationStateType
from bot.services.moderation.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    toggle_auto_reply_rule,
    CreateResult,
)
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.core.permission_service import is_user_admin
from bot.services.core.user_service import ensure_user


# ============================================
# 回调处理器
# ============================================

# Handler 类定义（使用 BaseHandler）
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
        from bot.services.integration.chat_group_service import get_user_managed_chats

        db = context.application.bot_data["db"]
        chats = await get_user_managed_chats(db, update.effective_user.id, context.bot)
        await _show_private_admin_menu(update, context, target_chat_id, chats)

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
        from bot.keyboards.auto_reply import auto_reply_menu_keyboard
        return auto_reply_menu_keyboard()


# Handler 实例
_auto_reply_menu_handler = AutoReplyMenuHandler()


# 适配器函数（保持 Router 兼容）
async def auto_reply_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复菜单回调（适配器函数）"""
    await _auto_reply_menu_handler.handle_callback(update, context)


async def auto_reply_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建自动回复规则流程"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的自动回复创建 - 优先从 callback_data 获取目标群组ID
    target_chat_id = None
    target_chat_title = None
    if chat.type == "private":
        # 优先从 callback_data 提取 chat_id
        if q.data.startswith("auto_reply:create:"):
            parts = q.data.split(":")
            if len(parts) >= 3:
                try:
                    target_chat_id = int(parts[2])
                except ValueError:
                    pass

        # 如果 callback_data 中没有 chat_id，从数据库获取
        if target_chat_id is None:
            from bot.services.integration.chat_group_service import get_user_current_chat
            from bot.models.core import TgChat
            from sqlalchemy import select
            db: Database = context.application.bot_data["db"]
            target_chat_id = await get_user_current_chat(db, user.id)
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
    text += "回复内容:\n"
    text += "你好呀！欢迎来到我们的群组！\n"
    text += "```"

    await q.edit_message_text(text, parse_mode="Markdown")


# Handler 类定义（使用 BaseHandler）
class AutoReplyToggleHandler(BaseHandler):
    """自动回复切换状态 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 不需要管理员权限检查，因为这是在群组内的操作
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理自动回复规则状态切换"""
        from bot.utils.callback_parser import CallbackParser

        q = update.callback_query

        # 解析规则 ID
        callback_data = CallbackParser.parse(q.data)
        rule_id = callback_data.get_int(2)

        if rule_id == 0:
            await self.message_helper.safe_answer(update, "规则不存在", show_alert=True)
            return

        # 切换规则状态
        success = await self._toggle_rule(context, rule_id)

        if success:
            await self.message_helper.safe_answer(update, "状态已切换")
            # 刷新菜单
            await _auto_reply_menu_handler.handle_callback(update, context, require_admin=False)
        else:
            await self.message_helper.safe_answer(update, "规则不存在", show_alert=True)

    async def _toggle_rule(self, context: ContextTypes.DEFAULT_TYPE, rule_id: int) -> bool:
        """切换规则状态

        Args:
            context: Bot 上下文
            rule_id: 规则 ID

        Returns:
            bool: 是否成功
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            success = await toggle_auto_reply_rule(session, rule_id)
            await session.commit()
        return success


# Handler 实例
_auto_reply_toggle_handler = AutoReplyToggleHandler()


# 适配器函数（保持 Router 兼容）
async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换自动回复规则状态回调（适配器函数）"""
    await _auto_reply_toggle_handler.handle_callback(update, context, require_admin=False)


# Handler 类定义（使用 BaseHandler）
class AutoReplyDeleteHandler(BaseHandler):
    """自动回复删除规则 Handler"""

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理自动回复规则删除"""
        from bot.utils.callback_parser import CallbackParser

        q = update.callback_query
        await q.answer()

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
        success = await self._delete_rule(context, rule_id)

        if success:
            await self.message_helper.safe_answer(update, "规则已删除")
            # 刷新菜单（不需要权限检查，因为已经检查过了）
            await _auto_reply_menu_handler.handle_callback(update, context, require_admin=False)
        else:
            await self.message_helper.safe_answer(update, "删除失败", show_alert=True)

    async def _delete_rule(self, context: ContextTypes.DEFAULT_TYPE, rule_id: int) -> bool:
        """删除规则

        Args:
            context: Bot 上下文
            rule_id: 规则 ID

        Returns:
            bool: 是否成功
        """
        db = context.application.bot_data["db"]
        async with db.session_factory() as session:
            success = await delete_auto_reply_rule(session, rule_id)
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

async def auto_reply_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理自动回复创建流程中的消息"""
    try:
        # 诊断日志
        import structlog
        log = structlog.get_logger(__name__)
        log.warning("=== AUTO_REPLY_CONFIG_HANDLER CALLED ===")

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
            # 获取用户状态 - 私聊中使用 user.id 查询状态，与其他处理器保持一致
            state_chat_id = user.id if chat.type == "private" else chat.id
            state = await get_user_state(session, chat_id=state_chat_id, user_id=user.id)

            # 静默忽略非自动回复创建状态，避免干扰其他功能
            if state is None or state.state_type != ConversationStateType.auto_reply_create.value:
                log.info("auto_reply_state_not_match", state_type=state.state_type if state else None)
                # 不要在这里 return，让代码继续执行到块结束
            else:
                step = state.state_data.get("step")
                log.info("auto_reply_step", step=step)

                if step == "config":
                    log.info("auto_reply_calling_parse")
                    await _parse_auto_reply_config(update, session, state, text)
                    log.info("auto_reply_parse_done")
                    # 注意：_parse_auto_reply_config 内部已经 commit 了会话，不需要再次 commit
                else:
                    await session.commit()
            log.info("auto_reply_handler_done")
    except Exception as e:
        # 确保异常被记录但不会阻止后续处理器
        import structlog
        log = structlog.get_logger(__name__)
        log.exception(
            "auto_reply_config_handler_error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=True
        )
        # 明确返回，不重新抛出异常，让后续处理器继续执行
        return


async def _parse_auto_reply_config(update: Update, session, state: object, text: str) -> None:
    """解析自动回复配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < 4:
            raise ValueError("配置格式不完整")

        # 解析关键词（第一行）
        keywords_line = lines[0].strip()
        keywords = [k.strip() for k in keywords_line.split(",") if k.strip()]
        if not keywords:
            raise ValueError("关键词不能为空")

        # 解析匹配类型
        match_type = AutoReplyMatchType.contains.value  # 默认
        case_sensitive = False  # 默认

        # 解析匹配类型和区分大小写
        for i in range(1, min(3, len(lines))):
            line = lines[i].strip()
            if line.startswith("匹配类型:"):
                match_type = line.split(":", 1)[1].strip()
            elif line.startswith("区分大小写:"):
                case_sensitive_str = line.split(":", 1)[1].strip().lower()
                case_sensitive = case_sensitive_str in ["true", "1", "yes"]

        # 解析回复内容
        reply_start = False
        reply_lines = []
        for i in range(2, len(lines)):
            line = lines[i]
            if line.strip().startswith("回复内容:"):
                reply_start = True
                # 如果同一行有内容，提取冒号后的部分
                if ":" in line:
                    content_after = line.split(":", 1)[1]
                    if content_after.strip():
                        reply_lines.append(content_after.strip())
                continue
            if reply_start:
                reply_lines.append(line)

        reply_content = "\n".join(reply_lines).strip()
        if not reply_content:
            raise ValueError("回复内容不能为空")

        # 获取目标群组ID（从状态数据中获取）
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id

        # 创建自动回复规则
        result = await create_auto_reply_rule(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            keywords=keywords,
            reply_content=reply_content,
            match_type=match_type,
            case_sensitive=case_sensitive,
        )

        if not result.success:
            error_messages = {
                "invalid_keywords": "关键词格式无效",
                "invalid_reply": "回复内容无效",
                "invalid_match_type": "匹配类型无效",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态（使用与保存/获取状态相同的 chat_id）
        state_chat_id = update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id
        await clear_user_state(session, chat_id=state_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        reply_text = f"✅ 自动回复规则创建成功！\n\n"
        reply_text += f"🔑 关键词: {', '.join(keywords)}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"🔤 区分大小写: {'是' if case_sensitive else '否'}\n"
        reply_text += f"💬 回复: {reply_content[:50]}{'...' if len(reply_content) > 50 else ''}\n"
        reply_text += f"\n规则ID: {result.rule.id}"

        # 只显示一个返回按钮
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("« 返回管理菜单", callback_data=f"adm:menu:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def auto_reply_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理群组消息，触发自动回复"""
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    message_text = update.effective_message.text or ""

    if chat.type == "private" or not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    if result.matched and result.reply_content:
        try:
            await update.effective_message.reply_text(result.reply_content)
        except Exception:
            pass  # 静默失败，避免循环


def _get_match_type_label(match_type: str) -> str:
    """获取匹配类型标签"""
    labels = {
        "exact": "精确匹配",
        "contains": "包含匹配",
        "starts_with": "开头匹配",
        "ends_with": "结尾匹配",
        "regex": "正则表达式",
    }
    return labels.get(match_type, match_type)
