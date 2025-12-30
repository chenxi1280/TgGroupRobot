from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.models.enums import BannedWordMatchType, ConversationStateType
from bot.services.banned_word_service import (
    create_banned_word,
    delete_banned_word,
    get_chat_banned_words,
    get_trigger_stats,
    match_banned_words,
    toggle_banned_word,
    CreateResult,
)
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.telegram_perm import is_user_admin
from bot.services.user_service import ensure_user


log = structlog.get_logger(__name__)


# ============================================
# 回调处理器
# ============================================

async def banned_word_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """违禁词菜单回调"""
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
        words = await get_chat_banned_words(session, chat.id)
        total_triggers = await get_trigger_stats(session, chat.id)
        await session.commit()

    text = f"🔇 [{chat.title}] 违禁词管理\n\n"
    text += f"违禁词总数: {len(words)}  |  总触发次数: {total_triggers}\n\n"
    if words:
        for w in words[:15]:
            status = "🟢" if w.is_active else "🔴"
            match_type_label = _get_match_type_label(w.match_type)
            action_label = _get_action_label(w.action)
            notify_label = "📢" if w.notify else "🔇"
            text += f"{status} [{w.id}] {w.word[:30]}\n"
            text += f"   匹配: {match_type_label} | 处罚: {action_label} {notify_label}\n\n"
        if len(words) > 15:
            text += f"\n... 还有 {len(words) - 15} 条"
    else:
        text += "暂无违禁词"

    from bot.keyboards.banned_word import banned_word_menu_keyboard

    await q.edit_message_text(text, reply_markup=banned_word_menu_keyboard())


async def banned_word_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始添加违禁词流程"""
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

        # 设置状态
        await set_user_state(
            session,
            chat_id=chat.id,
            user_id=user.id,
            state_type=ConversationStateType.banned_word_add.value,
            state_data={"step": "config"},
        )
        await session.commit()

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

    await q.edit_message_text(text, parse_mode="Markdown")


async def banned_word_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换违禁词状态回调"""
    if update.callback_query is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    if chat.type == "private":
        return

    data = q.data
    if not data.startswith("banned_word_toggle_"):
        return

    try:
        word_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await toggle_banned_word(session, word_id)
        await session.commit()

    if success:
        await q.answer("状态已切换")
        await banned_word_menu_callback(update, context)
    else:
        await q.answer("违禁词不存在", show_alert=True)


async def banned_word_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除违禁词回调"""
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

    data = q.data
    if not data.startswith("banned_word_delete_"):
        return

    try:
        word_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_banned_word(session, word_id)
        await session.commit()

    if success:
        await q.answer("违禁词已删除")
        await banned_word_menu_callback(update, context)
    else:
        await q.answer("删除失败", show_alert=True)


# ============================================
# 消息处理器
# ============================================

async def banned_word_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理违禁词添加流程中的消息"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""

    if chat.type == "private" or not text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat_id=chat.id, user_id=user.id)
        if state is None or state.state_type != ConversationStateType.banned_word_add.value:
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
                try:
                    mute_duration = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise ValueError("禁言时长必须是数字")
            elif line.startswith("删除提醒:"):
                notify_str = line.split(":", 1)[1].strip().lower()
                notify = notify_str in ["true", "1", "yes"]
            elif line.startswith("提醒消息:"):
                # 提取冒号后的内容
                if ":" in line:
                    notify_message = line.split(":", 1)[1].strip()

        # 创建违禁词
        result = await create_banned_word(
            session,
            chat_id=update.effective_chat.id,
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
                "invalid_word": "违禁词格式无效",
                "invalid_match_type": "匹配类型无效",
                "invalid_action": "惩罚动作无效",
                "duplicate": "该违禁词已存在",
            }
            raise ValueError(error_messages.get(result.reason, "创建失败"))

        # 清除状态
        await clear_user_state(session, chat_id=update.effective_chat.id, user_id=update.effective_user.id)
        await session.commit()

        # 返回成功消息
        from bot.keyboards.admin import admin_main_menu

        reply_text = f"✅ 违禁词添加成功！\n\n"
        reply_text += f"🔇 违禁词: {word}\n"
        reply_text += f"📋 匹配类型: {_get_match_type_label(match_type)}\n"
        reply_text += f"⚖️ 惩罚动作: {_get_action_label(action)}\n"
        if action == "mute":
            reply_text += f"⏱️ 禁言时长: {mute_duration} 秒\n"
        reply_text += f"📢 删除提醒: {'是' if notify else '否'}\n"
        if notify_message:
            reply_text += f"💬 提醒消息: {notify_message}\n"
        reply_text += f"\n违禁词ID: {result.word.id}"

        await update.effective_message.reply_text(reply_text, reply_markup=admin_main_menu())

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def banned_word_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """检测消息中的违禁词"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if chat.type == "private":
        return

    # 跳过管理员
    try:
        if await is_user_admin(context, chat.id, user.id):
            return
    except Exception:
        return

    message_text = message.text or message.caption or ""
    if not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)
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
        except Exception:
            pass

        # 发送提醒
        if word.notify:
            notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
            try:
                await context.bot.send_message(chat_id=chat.id, text=notify_msg)
            except Exception:
                pass

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
            except Exception:
                pass
        elif word.action == "ban":
            try:
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
            except Exception:
                pass


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
