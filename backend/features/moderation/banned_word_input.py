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
