from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.enums import AutoReplyMatchType, ConversationStateType
from bot.services.auto_reply_service import (
    create_auto_reply_rule,
    delete_auto_reply_rule,
    get_chat_auto_reply_rules,
    get_match_count,
    match_auto_reply,
    CreateResult,
)
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.telegram_perm import is_user_admin
from bot.services.user_service import ensure_user


# ============================================
# 回调处理器
# ============================================

async def auto_reply_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动回复菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await q.edit_message_text("请在群里使用。")
        return
    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        rules = await get_chat_auto_reply_rules(session, chat.id)
        total_matches = await get_match_count(session, chat.id)
        await session.commit()

    text = f"💬 [{chat.title}] 自动回复\n\n"
    text += f"规则总数: {len(rules)}  |  总匹配次数: {total_matches}\n\n"
    if rules:
        for rule in rules[:10]:
            status = "🟢" if rule.is_active else "🔴"
            match_type_label = _get_match_type_label(rule.match_type)
            keywords_preview = ", ".join(rule.keywords[:3])
            if len(rule.keywords) > 3:
                keywords_preview += f" ...(+{len(rule.keywords) - 3})"
            reply_preview = rule.reply_content[:30] + "..." if len(rule.reply_content) > 30 else rule.reply_content
            text += f"{status} [{rule.id}] {match_type_label}\n"
            text += f"   关键词: {keywords_preview}\n"
            text += f"   回复: {reply_preview}\n\n"
        if len(rules) > 10:
            text += f"\n... 还有 {len(rules) - 10} 条规则"
    else:
        text += "暂无自动回复规则"

    from bot.keyboards.auto_reply import auto_reply_menu_keyboard

    await q.edit_message_text(text, reply_markup=auto_reply_menu_keyboard())


async def auto_reply_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建自动回复规则流程"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await q.edit_message_text("请在群里使用。")
        return
    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("需要管理员权限。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )

        # 设置状态：等待输入配置
        await set_user_state(
            session,
            chat_id=chat.id,
            user_id=user.id,
            state_type=ConversationStateType.auto_reply_create.value,
            state_data={"step": "config"},
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


async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换自动回复规则状态回调"""
    if update.callback_query is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    if chat.type == "private":
        return

    # 解析规则ID
    data = q.data
    if not data.startswith("auto_reply_toggle_"):
        return

    try:
        rule_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await toggle_auto_reply_rule(session, rule_id)
        await session.commit()

    if success:
        await q.answer("状态已切换")
        await auto_reply_menu_callback(update, context)
    else:
        await q.answer("规则不存在", show_alert=True)


async def auto_reply_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除自动回复规则回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        return

    if not await is_user_admin(context, chat.id, user.id):
        await q.answer("需要管理员权限", show_alert=True)
        return

    # 解析规则ID
    data = q.data
    if not data.startswith("auto_reply_delete_"):
        return

    try:
        rule_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_auto_reply_rule(session, rule_id)
        await session.commit()

    if success:
        await q.answer("规则已删除")
        await auto_reply_menu_callback(update, context)
    else:
        await q.answer("删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================

async def auto_reply_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理自动回复创建流程中的消息"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    if chat.type == "private" or not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 获取用户状态
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
        if state is None or state.state_type != ConversationStateType.auto_reply_create.value:
            await session.commit()
            return

        step = state.state_data.get("step")

        if step == "config":
            await _parse_auto_reply_config(update, session, state, text)
        else:
            await session.commit()


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

        # 创建自动回复规则
        result = await create_auto_reply_rule(
            session,
            chat_id=update.effective_chat.id,
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

        # 清除状态
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from bot.keyboards.admin import admin_main_menu

        reply_text = f"✅ 自动回复规则创建成功！\n\n"
        reply_text += f"🔑 关键词: {', '.join(keywords)}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"🔤 区分大小写: {'是' if case_sensitive else '否'}\n"
        reply_text += f"💬 回复: {reply_content[:50]}{'...' if len(reply_content) > 50 else ''}\n"
        reply_text += f"\n规则ID: {result.rule.id}"

        await update.effective_message.reply_text(reply_text, reply_markup=admin_main_menu())

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
