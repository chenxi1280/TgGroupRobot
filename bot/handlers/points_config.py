from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

from bot.db.session import Database
from bot.keyboards.points import back_button, points_config_keyboard
from bot.services.chat_service import get_chat_settings
from bot.services.telegram_perm import is_user_admin

log = structlog.get_logger(__name__)

# 对话状态
WAIT_VALUE = 0


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise


async def points_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """积分配置回调处理器"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")

    if len(parts) < 4:
        return

    action = parts[1]
    field = parts[2]
    chat_id = int(parts[3])

    # 检查管理员权限
    if not await is_user_admin(context, chat_id, update.effective_user.id):
        await _safe_edit_message(q, "你没有该群组的管理权限")
        return

    db: Database = context.application.bot_data["db"]

    # 处理开关切换
    if action == "toggle":
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()

            # 重新显示键盘
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        keyboard = points_config_keyboard(settings, chat_id)
        await _safe_edit_message(q, "💰 积分配置\n\n配置已更新", reply_markup=keyboard)
        return

    # 处理数值编辑 - 进入对话状态
    if action == "edit":
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        # 保存编辑状态
        context.user_data["points_edit_field"] = field
        context.user_data["points_edit_chat_id"] = chat_id

        # 根据字段类型显示不同的提示
        prompts = {
            "sign_points": "请输入每次签到获得的积分数：",
            "sign_consecutive": "请输入连续签到奖励（格式：天数,积分，例如 7,10 表示连续7天奖励10积分）：",
            "message_points": "请输入每次发言获得的积分数：",
            "message_daily_limit": "请输入每日发言积分上限（输入 0 表示无限制）：",
            "message_min_length": "请输入最小发言字数（输入 0 表示无限制）：",
            "invite_points": "请输入每次邀请获得的积分数：",
            "invite_daily_limit": "请输入每日邀请积分上限（输入 0 表示无限制）：",
            "points_alias": "请输入积分别名（例如：积分）：",
            "points_rank_alias": "请输入积分排行别名（例如：积分排行）：",
        }

        prompt = prompts.get(field, "请输入新值：")

        keyboard = back_button(chat_id)
        await _safe_edit_message(q, prompt, reply_markup=keyboard)

        return WAIT_VALUE


async def points_config_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """积分配置消息处理器"""
    if update.effective_chat is None or update.effective_message is None:
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        return ConversationHandler.END

    text = update.effective_message.text
    if not text:
        return ConversationHandler.END

    # 检查是否在编辑状态
    field = context.user_data.get("points_edit_field")
    chat_id = context.user_data.get("points_edit_chat_id")

    if not field or chat_id is None:
        return ConversationHandler.END

    db: Database = context.application.bot_data["db"]

    try:
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, chat_id)

            # 处理特殊字段
            if field == "sign_consecutive":
                # 格式：天数,积分
                parts = text.split(",")
                if len(parts) != 2:
                    await update.effective_message.reply_text("格式错误，请输入：天数,积分（例如 7,10）")
                    return WAIT_VALUE

                days = int(parts[0].strip())
                bonus = int(parts[1].strip())

                settings.sign_consecutive_days = days
                settings.sign_consecutive_bonus = bonus

            elif field in ["message_daily_limit", "message_min_length", "invite_daily_limit"]:
                # 0 表示无限制（None）
                value = int(text.strip())
                setattr(settings, field, value if value > 0 else None)

            elif field in ["points_alias", "points_rank_alias"]:
                # 字符串
                setattr(settings, field, text.strip())

            else:
                # 普通整数
                value = int(text.strip())
                setattr(settings, field, value)

            await session.commit()

            # 获取更新后的设置
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

        # 显示更新后的键盘
        from bot.keyboards.points import points_config_keyboard

        keyboard = points_config_keyboard(settings, chat_id)
        await update.effective_message.reply_text("✅ 配置已更新", reply_markup=keyboard)

        # 清除编辑状态
        context.user_data.pop("points_edit_field", None)
        context.user_data.pop("points_edit_chat_id", None)

        return ConversationHandler.END

    except ValueError:
        await update.effective_message.reply_text("输入格式错误，请输入有效的数字")
        return WAIT_VALUE
    except Exception as e:
        log.error("points_config_error", error=str(e))
        await update.effective_message.reply_text(f"配置失败：{str(e)}")
        return ConversationHandler.END


async def points_config_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """取消配置"""
    # 清除编辑状态
    context.user_data.pop("points_edit_field", None)
    context.user_data.pop("points_edit_chat_id", None)

    if update.callback_query:
        field = context.user_data.get("points_edit_field")
        chat_id = context.user_data.get("points_edit_chat_id")

        if chat_id:
            from bot.keyboards.points import points_config_keyboard

            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                await session.commit()

            keyboard = points_config_keyboard(settings, chat_id)
            await update.callback_query.edit_message_text("💰 积分配置", reply_markup=keyboard)

    return ConversationHandler.END
