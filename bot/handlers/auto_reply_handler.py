from __future__ import annotations

import asyncio
import json
import structlog

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes


log = structlog.get_logger(__name__)

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
from bot.models.enums import AutoReplyMatchType, ConversationStateType
from bot.services.moderation.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_auto_reply_rule,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    move_auto_reply_rule,
    toggle_auto_reply_rule,
    update_auto_reply_rule,
    CreateResult,
)
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.core.permission_service import is_user_admin
from bot.services.core.user_service import ensure_user
from bot.utils.chat_context import PrivateChatContext


# ============================================
# 辅助函数
# ============================================

def _ensure_callback_update(update: Update) -> bool:
    """
    确保 Update 包含回调所需的所有字段

    Args:
        update: Telegram Update 对象

    Returns:
        bool: 如果包含所有必需字段则返回 True
    """
    return not (
        update.callback_query is None
        or update.effective_chat is None
        or update.effective_user is None
    )


def _ensure_message_update(update: Update, require_user: bool = True) -> bool:
    """
    确保 Update 包含消息所需的所有字段

    Args:
        update: Telegram Update 对象
        require_user: 是否要求用户字段

    Returns:
        bool: 如果包含所有必需字段则返回 True
    """
    if update.effective_chat is None or update.effective_message is None:
        return False
    if require_user and update.effective_user is None:
        return False
    return True


async def _resolve_auto_reply_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_index: int = 2,
) -> int | None:
    """统一解析自动回复管理目标群组。"""
    return await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
    )


def _format_auto_reply_rule_detail(rule) -> str:
    status = "🟢 启用" if rule.is_active else "🔴 停用"
    delete_source = "删除" if getattr(rule, "delete_source", False) else "保留"
    delete_delay = getattr(rule, "delete_reply_delay_seconds", 0)
    match_type_label = _get_match_type_label(rule.match_type)
    keywords = ", ".join(rule.keywords)
    cover_label = "未设置"
    if getattr(rule, "cover_media_file_id", None):
        cover_type = getattr(rule, "cover_media_type", None) or "media"
        cover_label = f"已设置（{cover_type}）"
    button_rows = getattr(rule, "buttons", None) or []
    button_count = sum(len(row) for row in button_rows if isinstance(row, list))
    return "\n".join([
        f"💬 自动回复规则 #{rule.sort_order}",
        "",
        f"ID: {rule.id}",
        f"状态: {status}",
        f"匹配方式: {match_type_label}",
        f"区分大小写: {'是' if rule.case_sensitive else '否'}",
        f"删除触发源: {delete_source}",
        f"回复延迟删除: {delete_delay} 秒" if delete_delay else "回复延迟删除: 不删除",
        f"命中次数: {rule.match_count}",
        f"封面: {cover_label}",
        f"按钮: {button_count} 个",
        "",
        f"关键词: {keywords}",
        "",
        "回复内容:",
        rule.reply_content,
    ])


def _parse_auto_reply_buttons_input(raw_text: str) -> list[list[dict[str, str]]]:
    raw = raw_text.strip()
    if not raw:
        raise ValueError("按钮配置不能为空。")

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"按钮 JSON 格式错误：{exc.msg}") from exc
        return ScheduledMessageService.normalize_buttons_config(parsed)

    rows: list[list[dict[str, str]]] = []
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        if "|" not in line:
            raise ValueError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValueError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValueError("未解析到有效按钮。")
    return ScheduledMessageService.normalize_buttons_config(rows)


def _build_auto_reply_markup(rule) -> InlineKeyboardMarkup | None:
    raw_buttons = getattr(rule, "buttons", None) or []
    if not raw_buttons:
        return None
    try:
        normalized = ScheduledMessageService.normalize_buttons_config(raw_buttons)
    except Exception:
        return None

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for row in normalized:
        button_row: list[InlineKeyboardButton] = []
        for item in row:
            text = str(item.get("text") or "").strip()
            url = str(item.get("url") or "").strip()
            callback_data = str(item.get("callback_data") or "").strip()
            if text and url:
                button_row.append(InlineKeyboardButton(text, url=url))
            elif text and callback_data:
                button_row.append(InlineKeyboardButton(text, callback_data=callback_data))
        if button_row:
            keyboard_rows.append(button_row)
    return InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None


async def _send_auto_reply_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    text: str,
    rule,
    reply_to_message_id: int | None = None,
) -> object:
    reply_markup = _build_auto_reply_markup(rule)
    cover_type = getattr(rule, "cover_media_type", None)
    cover_file_id = getattr(rule, "cover_media_file_id", None)
    if cover_type == "photo" and cover_file_id:
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    if cover_type == "video" and cover_file_id:
        return await context.bot.send_video(
            chat_id=chat_id,
            video=cover_file_id,
            caption=text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to_message_id,
        )
    return await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )


async def _show_auto_reply_rule_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    rule_id: int,
) -> None:
    from bot.keyboards.content.auto_reply import auto_reply_detail_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule(session, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != chat_id:
        if update.callback_query is not None:
            await update.callback_query.edit_message_text("规则不存在")
        return

    text = _format_auto_reply_rule_detail(rule)
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=auto_reply_detail_keyboard(rule, chat_id),
        )


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
        from bot.keyboards.content.auto_reply import auto_reply_menu_keyboard
        return auto_reply_menu_keyboard()


# Handler 实例
_auto_reply_menu_handler = AutoReplyMenuHandler()


# 适配器函数（保持 Router 兼容）
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

    # 获取自动回复规则列表
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rules = await get_chat_auto_reply_rules(session, target_chat_id)
        total_matches = await get_match_count(session, target_chat_id)
        await session.commit()

    # 构建列表文本
    text = f"📋 自动回复规则列表\n\n"
    if rules:
        active_count = sum(1 for r in rules if r.is_active)
        text += f"总计: {len(rules)} 条  |  激活: {active_count} 条  |  总匹配: {total_matches} 次\n\n"

        for r in rules:
            status = "🟢 激活" if r.is_active else "🔴 暂停"
            match_type_label = _get_match_type_label(r.match_type)
            keywords_display = ", ".join(r.keywords[:3]) + ("..." if len(r.keywords) > 3 else "")
            delete_source = "删源" if getattr(r, "delete_source", False) else "留源"
            delete_delay = getattr(r, "delete_reply_delay_seconds", 0)
            delay_label = f"{delete_delay}s删回复" if delete_delay else "不删回复"
            cover_label = "有封面" if getattr(r, "cover_media_file_id", None) else "无封面"
            button_count = sum(len(row) for row in (getattr(r, "buttons", None) or []) if isinstance(row, list))
            text += f"{status} #{r.sort_order} [{r.id}] {keywords_display}\n"
            text += (
                f"   匹配: {match_type_label} | {delete_source} | {delay_label}\n"
                f"   展示: {cover_label} | 按钮 {button_count} 个\n"
                f"   回复: {r.reply_content[:30]}{'...' if len(r.reply_content) > 30 else ''}\n\n"
            )
    else:
        text += "暂无自动回复规则"

    from bot.keyboards.content.auto_reply import auto_reply_list_keyboard
    await q.edit_message_text(text, reply_markup=auto_reply_list_keyboard(rules, target_chat_id))


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
        from bot.models.core import TgChat
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
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 4:
        await q.edit_message_text("规则不存在")
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        return

    await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 4:
        await q.edit_message_text("规则不存在")
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        return

    from bot.keyboards.content.auto_reply import auto_reply_preview_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule(session, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != target_chat_id:
        await q.edit_message_text("规则不存在")
        return

    if getattr(rule, "cover_media_file_id", None):
        await _send_auto_reply_payload(
            context,
            chat_id=update.effective_chat.id,
            text=rule.reply_content,
            rule=rule,
        )
        await q.edit_message_text(
            "👁️ 预览已发送到当前会话，请查看最新一条机器人消息。",
            reply_markup=auto_reply_preview_keyboard(rule.id, target_chat_id),
        )
        return

    preview_lines = [
        "👁️ 自动回复预览",
        "",
        "以下为命中后机器人的回复效果预览：",
        "",
        rule.reply_content,
    ]
    await q.edit_message_text(
        "\n".join(preview_lines),
        reply_markup=auto_reply_preview_keyboard(rule.id, target_chat_id),
    )


async def auto_reply_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.edit_message_text("规则不存在")
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("规则不存在")
        return

    field = parts[4]
    state_map = {
        "keywords": ConversationStateType.auto_reply_edit_keywords.value,
        "content": ConversationStateType.auto_reply_edit_content.value,
        "cover": ConversationStateType.auto_reply_edit_cover.value,
        "buttons": ConversationStateType.auto_reply_edit_buttons.value,
    }
    state_type = state_map.get(field)
    if state_type is None:
        await q.answer("暂不支持该编辑项", show_alert=True)
        return

    prompt_map = {
        "keywords": "💬 自动回复 | 编辑关键词\n\n请输入新的关键词列表，使用英文逗号分隔。\n例如：你好,hi,hello",
        "content": "💬 自动回复 | 编辑回复内容\n\n请输入新的回复内容。",
        "cover": "💬 自动回复 | 编辑封面\n\n请发送图片或视频，发送“清空”可移除封面。",
        "buttons": "💬 自动回复 | 编辑按钮\n\n请输入 JSON 按钮数组，或按“按钮文案|URL”逐行输入。\n发送“清空”可移除按钮。",
    }

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(
            session,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            state_type=state_type,
            state_data={"target_chat_id": target_chat_id, "rule_id": rule_id},
        )
        await session.commit()

    await q.edit_message_text(
        prompt_map[field],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]),
    )


async def auto_reply_rule_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.answer("规则不存在", show_alert=True)
        return
    action = parts[1]
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("规则不存在", show_alert=True)
        return
    field = parts[4]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule(session, rule_id)
        if rule is None or rule.chat_id != target_chat_id:
            await session.commit()
            await q.answer("规则不存在", show_alert=True)
            return

        if action == "togglecfg":
            if field == "case":
                await update_auto_reply_rule(session, rule_id, case_sensitive=not bool(rule.case_sensitive))
            elif field == "source":
                await update_auto_reply_rule(session, rule_id, delete_source=not bool(rule.delete_source))
            else:
                await session.commit()
                await q.answer("无效配置项", show_alert=True)
                return
        elif action == "cycle":
            if field == "match":
                ordered = [
                    AutoReplyMatchType.exact.value,
                    AutoReplyMatchType.contains.value,
                    AutoReplyMatchType.starts_with.value,
                    AutoReplyMatchType.ends_with.value,
                    AutoReplyMatchType.regex.value,
                ]
                current = getattr(rule, "match_type", AutoReplyMatchType.contains.value)
                next_index = (ordered.index(current) + 1) % len(ordered) if current in ordered else 0
                await update_auto_reply_rule(session, rule_id, match_type=ordered[next_index])
            elif field == "delay":
                values = [0, 30, 60, 300, 600]
                current_delay = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0)
                next_index = (values.index(current_delay) + 1) % len(values) if current_delay in values else 0
                await update_auto_reply_rule(session, rule_id, delete_reply_delay_seconds=values[next_index])
            else:
                await session.commit()
                await q.answer("无效配置项", show_alert=True)
                return
        await session.commit()

    await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)


async def auto_reply_move_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.answer("移动失败", show_alert=True)
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.answer("移动失败", show_alert=True)
        return
    direction = parts[4]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        moved = await move_auto_reply_rule(
            session,
            chat_id=target_chat_id,
            rule_id=rule_id,
            direction=direction,
        )
        await session.commit()

    if not moved:
        await q.answer("已经不能再移动了", show_alert=True)
        return

    await q.answer("顺序已更新")
    await auto_reply_list_callback(update, context)


async def auto_reply_delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.edit_message_text("删除失败")
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("删除失败")
        return

    from bot.keyboards.content.auto_reply import auto_reply_delete_confirm_keyboard

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        rule = await get_auto_reply_rule(session, rule_id)
        await session.commit()

    if rule is None or rule.chat_id != target_chat_id:
        await q.edit_message_text("规则不存在")
        return

    text = "\n".join([
        "⚠️ 确认删除自动回复规则？",
        "",
        f"规则 #{rule.sort_order} [{rule.id}]",
        f"关键词: {', '.join(rule.keywords)}",
        "",
        "删除后将不再参与匹配。",
    ])
    await q.edit_message_text(
        text,
        reply_markup=auto_reply_delete_confirm_keyboard(rule.id, target_chat_id),
    )


async def auto_reply_delete_do_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_auto_reply_target_chat_id(update, context)
    if target_chat_id is None:
        return

    parts = (q.data or "").split(":")
    if len(parts) < 5:
        await q.edit_message_text("删除失败")
        return
    try:
        rule_id = int(parts[3])
    except ValueError:
        await q.edit_message_text("删除失败")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_auto_reply_rule(session, rule_id)
        await session.commit()

    if not success:
        await q.answer("删除失败", show_alert=True)
        return

    await q.answer("规则已删除")
    await auto_reply_list_callback(update, context)


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
    """切换自动回复规则状态回调（兼容新旧格式）"""
    if not _ensure_callback_update(update):
        return
    q = update.callback_query
    await q.answer()

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
            success = await toggle_auto_reply_rule(session, rule_id)
            await session.commit()

        if not success:
            await q.answer("规则不存在", show_alert=True)
            return

        await q.answer("状态已切换")
        await _show_auto_reply_rule_detail(update, context, chat_id=target_chat_id, rule_id=rule_id)
        return

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
    # 强制日志 - 必须在最开始输出
    log.warning(
        "=== AUTO_REPLY_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
    )

    try:
        if not _ensure_message_update(update, require_user=True):
            return

        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 获取用户状态 - 私聊中使用 chat.id 查询状态（与设置状态时一致）
            state_chat_id = chat.id  # 统一使用 chat.id
            state = await get_user_state(session, chat_id=state_chat_id, user_id=user.id)

            log.info(
                "auto_reply_config_state_check",
                chat_id=chat.id,
                user_id=user.id,
                state_chat_id=state_chat_id,
                state_found=state is not None,
                state_type=state.state_type if state else None,
                expected_state=ConversationStateType.auto_reply_create.value,
            )

            # 静默忽略非自动回复创建状态，避免干扰其他功能
            supported_states = {
                ConversationStateType.auto_reply_create.value,
                ConversationStateType.auto_reply_edit_keywords.value,
                ConversationStateType.auto_reply_edit_content.value,
                ConversationStateType.auto_reply_edit_cover.value,
                ConversationStateType.auto_reply_edit_buttons.value,
            }

            if state is None or state.state_type not in supported_states:
                log.info("auto_reply_state_not_match", state_type=state.state_type if state else None)
                await session.commit()
                # 不 return，让函数自然结束，允许后续 handlers 执行
            else:
                if state.state_type == ConversationStateType.auto_reply_create.value:
                    step = state.state_data.get("step")
                    log.info("auto_reply_step", step=step)

                    if step == "config":
                        if not text:
                            await session.commit()
                            return
                        log.info("auto_reply_calling_parse")
                        await _parse_auto_reply_config(update, session, state, text)
                        log.info("auto_reply_parse_done")
                    else:
                        await session.commit()
                else:
                    await _handle_auto_reply_edit_input(update, context, session, state, text)
                # 注意：各子处理器内部已经 commit 了会话，不需要再次 commit

            log.info("auto_reply_handler_done")
    except Exception as e:
        # 确保异常被记录但不会阻止后续处理器
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
        delete_source = False
        delete_reply_delay_seconds = 0

        # 解析匹配类型和附加配置
        for i in range(1, min(6, len(lines))):
            line = lines[i].strip()
            if line.startswith("匹配类型:"):
                match_type = line.split(":", 1)[1].strip()
            elif line.startswith("区分大小写:"):
                case_sensitive_str = line.split(":", 1)[1].strip().lower()
                case_sensitive = case_sensitive_str in ["true", "1", "yes"]
            elif line.startswith("删除来源:"):
                delete_source_str = line.split(":", 1)[1].strip().lower()
                delete_source = delete_source_str in ["true", "1", "yes"]
            elif line.startswith("延迟删除:"):
                delay_text = line.split(":", 1)[1].strip().rstrip("秒sS")
                delete_reply_delay_seconds = int(delay_text or "0")

        # 解析回复内容
        reply_start = False
        reply_lines = []
        for i in range(1, len(lines)):
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
            delete_source=delete_source,
            delete_reply_delay_seconds=delete_reply_delay_seconds,
        )

        if not result.success:
            error_messages = {
                "invalid_keywords": "关键词格式无效",
                "invalid_reply": "回复内容无效",
                "invalid_match_type": "匹配类型无效",
                "invalid_delete_delay": "延迟删除必须是大于等于 0 的整数",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态（使用与保存/获取状态相同的 chat_id）
        state_chat_id = update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id
        await clear_user_state(session, chat_id=state_chat_id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        reply_text = f"✅ 自动回复规则创建成功！\n\n"
        reply_text += f"🔑 关键词: {', '.join(keywords)}\n"
        reply_text += f"🔢 顺序: #{result.entity.sort_order}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"🔤 区分大小写: {'是' if case_sensitive else '否'}\n"
        reply_text += f"🧹 删除来源: {'是' if delete_source else '否'}\n"
        reply_text += (
            f"⏱️ 延迟删除: {delete_reply_delay_seconds} 秒\n"
            if delete_reply_delay_seconds else
            "⏱️ 延迟删除: 不删除\n"
        )
        reply_text += f"💬 回复: {reply_content[:50]}{'...' if len(reply_content) > 50 else ''}\n"
        reply_text += f"\n规则ID: {result.entity.id}\n\n可继续进入详情页补充封面和按钮。"

        # 显示多级返回按钮：返回自动回复管理 / 返回主菜单
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{result.entity.id}")],
            [InlineKeyboardButton("🔙 返回自动回复管理", callback_data=f"adm:menu:autoreply:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def _handle_auto_reply_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    state_type = state.state_type
    state_data = state.state_data or {}
    target_chat_id = state_data.get("target_chat_id")
    rule_id = state_data.get("rule_id")
    if not target_chat_id or not rule_id:
        await update.effective_message.reply_text("❌ 自动回复状态异常，请重新进入规则详情页。")
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()
        return

    if state_type == ConversationStateType.auto_reply_edit_keywords.value:
        keywords = [item.strip() for item in text.split(",") if item.strip()]
        await update_auto_reply_rule(session, rule_id, keywords=keywords)
    elif state_type == ConversationStateType.auto_reply_edit_content.value:
        await update_auto_reply_rule(session, rule_id, reply_content=text.strip())
    elif state_type == ConversationStateType.auto_reply_edit_cover.value:
        message = update.effective_message
        if text.strip() == "清空":
            await update_auto_reply_rule(session, rule_id, cover_media_type=None, cover_media_file_id=None)
        elif message.photo:
            await update_auto_reply_rule(session, rule_id, cover_media_type="photo", cover_media_file_id=message.photo[-1].file_id)
        elif message.video:
            await update_auto_reply_rule(session, rule_id, cover_media_type="video", cover_media_file_id=message.video.file_id)
        else:
            await update.effective_message.reply_text("❌ 请发送图片、视频，或发送“清空”。")
            await session.commit()
            return
    elif state_type == ConversationStateType.auto_reply_edit_buttons.value:
        if text.strip() == "清空":
            await update_auto_reply_rule(session, rule_id, buttons=[])
        else:
            buttons = _parse_auto_reply_buttons_input(text)
            await update_auto_reply_rule(session, rule_id, buttons=buttons)

    await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(
        "✅ 自动回复规则已更新。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回规则详情", callback_data=f"auto_reply:detail:{target_chat_id}:{rule_id}")]]),
    )


async def auto_reply_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理群组消息，触发自动回复"""
    if not _ensure_message_update(update, require_user=False):
        return

    chat = update.effective_chat
    message_text = update.effective_message.text or ""

    if chat.type == "private" or not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    if result.success and result.reply_content and result.rule is not None:
        try:
            sent = await _send_auto_reply_payload(
                context,
                chat_id=chat.id,
                text=result.reply_content,
                rule=result.rule,
                reply_to_message_id=update.effective_message.message_id,
            )
            if getattr(result.rule, "delete_source", False):
                try:
                    await update.effective_message.delete()
                except Exception as exc:
                    log.debug("auto_reply_delete_source_failed", error=str(exc))
            delete_after = getattr(result.rule, "delete_reply_delay_seconds", 0) or 0
            if delete_after > 0:
                async def _delete_later():
                    await asyncio.sleep(delete_after)
                    try:
                        await sent.delete()
                    except Exception:
                        return

                asyncio.create_task(_delete_later())
        except Exception as e:
            log.debug("auto_reply_send_failed", error=str(e))  # 静默失败，避免循环


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


# ==================== 取消回调处理器 ====================

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消自动回复配置，返回自动回复菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 解析参数：autoreply:cancel:{chat_id}
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
        state_chat_id = chat.id
        await clear_user_state(session, state_chat_id, user.id)
        await session.commit()

    # 返回管理面板
    # 不调用菜单回调（因为它会从状态中获取 target_chat_id，但状态已被清除）
    # 直接调用管理面板，传递 target_chat_id
    from bot.handlers.admin_handler import _show_private_admin_menu

    await _show_private_admin_menu(update, context, target_chat_id)
