from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from bot.db.session import Database
from bot.keyboards.auto_delete import auto_delete_config_keyboard
from bot.services.chat_service import get_chat_settings
from bot.services.telegram_perm import is_user_admin

log = structlog.get_logger(__name__)


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息"""
    try:
        await q.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            log.debug("message_not_modified", callback_data=q.data)
        else:
            raise


async def auto_delete_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动删除配置回调处理器"""
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
    try:
        chat_id = int(parts[3])
    except (ValueError, IndexError) as e:
        log.warning("invalid_chat_id", data=q.data, error=str(e))
        await _safe_edit_message(q, "无效的群组ID")
        return

    # 检查管理员权限
    if not await is_user_admin(context, chat_id, update.effective_user.id):
        await _safe_edit_message(q, "你没有该群组的管理权限")
        return

    if action != "toggle":
        return

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)

        if hasattr(settings, field):
            current = bool(getattr(settings, field))
            setattr(settings, field, not current)
            await session.commit()

            # 重新显示键盘
            settings = await get_chat_settings(session, chat_id)
            await session.commit()

    keyboard = auto_delete_config_keyboard(settings, chat_id)

    text = "🧹 自动删除配置\n\n"
    text += "配置已更新"
    await _safe_edit_message(q, text, reply_markup=keyboard)
