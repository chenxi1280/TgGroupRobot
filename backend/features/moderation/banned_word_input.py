from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.moderation.banned_word_common import (
    get_action_label,
    get_compact_match_type_label,
    get_match_type_label,
    normalize_action_input,
    normalize_bool_input,
    normalize_match_type_input,
)
from backend.features.moderation.services.banned_word_service import create_banned_word
from backend.platform.db.schema.models.enums import BannedWordMatchType
from backend.platform.state.state_service import clear_user_state
from backend.features.moderation.banned_word_runtime import (
    banned_word_check_handler_impl,
    banned_word_config_handler_impl,
)
_PARSE_BANNED_WORD_CONFIG_THRESHOLD_2 = 2


async def banned_word_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_config_handler_impl(update, context)


async def _parse_banned_word_config(update: Update, session, state: object, *, text: str) -> None:
    """解析违禁词配置"""
    try:
        lines = text.strip().split("\n")
        if len(lines) < _PARSE_BANNED_WORD_CONFIG_THRESHOLD_2:
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
                match_type = normalize_match_type_input(line.split(":", 1)[1])
            elif line.startswith("惩罚动作:"):
                action = normalize_action_input(line.split(":", 1)[1])
            elif line.startswith("禁言时长:"):
                duration_str = line.split(":", 1)[1].strip()
                if duration_str:  # 只有非空时才解析
                    try:
                        mute_duration = int(duration_str)
                    except ValueError:
                        raise ValueError("禁言时长必须是数字")
                # 否则使用默认值（对于 delete 和 ban 动作，默认值不会被使用）
            elif line.startswith("删除提醒:"):
                notify = normalize_bool_input(line.split(":", 1)[1])
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
                "invalid_match_type": "❌ 匹配类型无效\n\n有效选项：精确、包含、正则",
                "invalid_action": "❌ 惩罚动作无效\n\n有效选项：删除、禁言、封禁\n\n注意：包含/模糊匹配是匹配类型，不是处罚动作",
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
            [InlineKeyboardButton("🔙 返回违禁词管理", callback_data=f"adm:menu:keywords:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(reply_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置错误: {e}\n\n请重新发送配置，或使用 /cancel 取消。")
        await session.commit()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ 解析失败: {e}\n\n请检查格式后重新发送。")
        await session.commit()


async def banned_word_check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await banned_word_check_handler_impl(update, context)


def _get_match_type_label(match_type: str) -> str:
    return get_compact_match_type_label(match_type)


def _get_action_label(action: str) -> str:
    return get_action_label(action)
