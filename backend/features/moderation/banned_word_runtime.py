from __future__ import annotations

import datetime as dt

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.moderation.banned_word_common import (
    get_action_label,
    get_match_type_label,
    normalize_action_input,
    normalize_bool_input,
    normalize_match_type_input,
)
from backend.features.moderation.services.banned_word_service import create_banned_word, get_chat_banned_words, match_banned_words
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import BannedWordMatchType, ConversationStateType
from backend.platform.state.state_service import clear_user_state, get_user_state
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import is_user_admin
_PARSE_BANNED_WORD_CONFIG_TEXT_THRESHOLD_2 = 2


log = structlog.get_logger(__name__)


async def banned_word_config_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.warning(
        "=== BANNED_WORD_CONFIG_HANDLER CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or "")[:50] if update.effective_message else "",
    )

    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    text = update.effective_message.text or ""
    if not text:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state, target_chat_id = await _load_banned_word_state(session, db, chat.type, chat_id=chat.id, user_id=user.id)
        if state is None or state.state_type != ConversationStateType.banned_word_add.value:
            await session.commit()
            return

        if state.state_data.get("step") == "config":
            await _parse_banned_word_config(update, session, state, text=text)
        else:
            await session.commit()


async def banned_word_check_handler_impl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    try:
        if await is_user_admin(context, chat.id, user.id):
            log.info("banned_word_check_skipped_admin", chat_id=chat.id, user_id=user.id)
            return
    except Exception as exc:
        log.warning("admin_check_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        return

    message_text = message.text or message.caption or ""
    if not message_text:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)
        words = await get_chat_banned_words(session, chat.id)
        log.info(
            "banned_word_check_result",
            chat_id=chat.id,
            user_id=user.id,
            message_text_preview=message_text[:50],
            total_words_count=len(words),
            active_words_count=sum(1 for word in words if word.is_active),
            matched_count=len(matched_words),
        )
        await session.commit()

    if not matched_words:
        return

    word = matched_words[0]
    try:
        await message.delete()
    except Exception as exc:
        log.warning("delete_message_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if word.notify:
        notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
        try:
            await context.bot.send_message(chat_id=chat.id, text=notify_msg)
        except Exception as exc:
            log.warning("send_notify_failed", chat_id=chat.id, error=str(exc))

    if word.action == "mute":
        try:
            until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=word.mute_duration) if word.mute_duration else None
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions={"can_send_messages": False, "can_send_media_messages": False},
                until_date=until_date,
            )
        except Exception as exc:
            log.warning("mute_user_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    elif word.action == "ban":
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        except Exception as exc:
            log.warning("ban_user_failed", chat_id=chat.id, user_id=user.id, error=str(exc))


async def _load_banned_word_state(session, db: Database, chat_type: str, *, chat_id: int, user_id: int):
    if chat_type != "private":
        return await get_user_state(session, chat_id=chat_id, user_id=user_id), chat_id

    target_chat_id = await ChatResolver.get_current_chat(db, user_id=user_id)
    state = None
    if target_chat_id:
        state = await get_user_state(session, chat_id=target_chat_id, user_id=user_id)
    if state is None:
        state = await get_user_state(session, chat_id=user_id, user_id=user_id)
    return state, target_chat_id


async def _parse_banned_word_config(update: Update, session, state: object, *, text: str) -> None:
    try:
        config = _parse_banned_word_config_text(text)
        target_chat_id = state.state_data.get("target_chat_id") or update.effective_chat.id
        result = await create_banned_word(
            session,
            chat_id=target_chat_id,
            created_by_user_id=update.effective_user.id,
            **config,
        )
        if not result.success:
            raise ValueError(
                {
                    "invalid_word": "❌ 违禁词格式无效\n\n违禁词不能为空",
                    "invalid_match_type": "❌ 匹配类型无效\n\n有效选项：精确、包含、正则",
                    "invalid_action": "❌ 惩罚动作无效\n\n有效选项：删除、禁言、封禁\n\n注意：包含/模糊匹配是匹配类型，不是处罚动作",
                    "duplicate": "❌ 该违禁词已存在",
                }.get(result.reason, "❌ 创建失败")
            )

        await clear_user_state(session, chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔙 返回违禁词管理", callback_data=f"adm:menu:keywords:{target_chat_id}")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
            ]
        )
        await update.effective_message.reply_text(_build_banned_word_success_text(config, result), reply_markup=keyboard)
    except ValueError as exc:
        await update.effective_message.reply_text(f"❌ 配置错误: {exc}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as exc:
        await update.effective_message.reply_text(f"❌ 解析失败: {exc}\n\n请检查格式后重新发送。")
        await session.commit()


def _parse_banned_word_config_text(text: str) -> dict:
    lines = text.strip().split("\n")
    if len(lines) < _PARSE_BANNED_WORD_CONFIG_TEXT_THRESHOLD_2:
        raise ValueError("配置格式不完整")

    word = lines[0].strip()
    if not word:
        raise ValueError("违禁词不能为空")

    config = {
        "word": word,
        "match_type": BannedWordMatchType.contains.value,
        "action": "delete",
        "mute_duration": 60,
        "notify": True,
        "notify_message": None,
    }
    for line in [item.strip() for item in lines[1:]]:
        if line.startswith("匹配类型:"):
            config["match_type"] = normalize_match_type_input(line.split(":", 1)[1])
        elif line.startswith("惩罚动作:"):
            config["action"] = normalize_action_input(line.split(":", 1)[1])
        elif line.startswith("禁言时长:"):
            duration_str = line.split(":", 1)[1].strip()
            if duration_str:
                try:
                    config["mute_duration"] = int(duration_str)
                except ValueError as exc:
                    raise ValueError("禁言时长必须是数字") from exc
        elif line.startswith("删除提醒:"):
            config["notify"] = normalize_bool_input(line.split(":", 1)[1])
        elif line.startswith("提醒消息:"):
            config["notify_message"] = line.split(":", 1)[1].strip() if ":" in line else None
    return config


def _build_banned_word_success_text(config: dict, result) -> str:
    text = (
        "✅ 违禁词添加成功！\n\n"
        f"🔇 违禁词: {config['word']}\n"
        f"📋 匹配类型: {get_match_type_label(config['match_type'])}\n"
        f"⚖️ 惩罚动作: {get_action_label(config['action'])}\n"
    )
    if config["action"] == "mute":
        text += f"⏱️ 禁言时长: {config['mute_duration']} 秒\n"
    text += f"📢 删除提醒: {'是' if config['notify'] else '否'}\n"
    if config["notify_message"]:
        text += f"💬 提醒消息: {config['notify_message']}\n"
    text += f"\n违禁词ID: {result.entity.id}"
    return text
