from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from bot.db.session import Database
from bot.keyboards.admin.auto_delete import auto_delete_config_keyboard
from bot.services.core.chat_service import get_chat_settings
from bot.services.core.permission_service import is_user_admin
from bot.utils.callback_parser import CallbackParser

log = structlog.get_logger(__name__)

# 字段名映射：键盘回调数据使用简化名，模型使用完整字段名
FIELD_MAPPING = {
    "enabled": "auto_delete_enabled",
    "join": "auto_delete_join",
    "left": "auto_delete_left",
    "pinned": "auto_delete_pinned",
    "avatar": "auto_delete_avatar",
    "title": "auto_delete_title",
    "anonymous": "auto_delete_anonymous",
}


async def _safe_edit_message(q, text: str, **kwargs) -> None:
    """安全地编辑消息"""
    try:
        await q.edit_message_text(text, **kwargs)
    except TelegramError as e:
        # 捕获所有 Telegram 错误，记录日志但不抛出异常
        log.warning("edit_message_failed", error=str(e), callback_data=q.data)


async def auto_delete_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """自动删除配置回调处理器"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    try:
        await q.answer()
    except TelegramError:
        # 回调查询已过期，忽略错误继续处理
        pass

    if update.effective_chat.type != "private":
        await q.edit_message_text("请在私聊中使用此功能")
        return

    data = q.data or ""
    cb = CallbackParser.parse(data)

    if cb.length() < 4:
        return

    action = cb.get(1)
    field = cb.get(2)
    chat_id = cb.get_int(3)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await _safe_edit_message(q, "无效的群组ID")
        return

    # 检查管理员权限
    if not await is_user_admin(context, chat_id, update.effective_user.id):
        await _safe_edit_message(q, "你没有该群组的管理权限")
        return

    if action != "toggle":
        return

    db: Database = context.application.bot_data["db"]

    # 获取完整字段名
    actual_field = FIELD_MAPPING.get(field, field)

    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)

        if hasattr(settings, actual_field):
            current = bool(getattr(settings, actual_field))
            # 添加调试日志
            log.info(
                "auto_delete_toggle",
                field=actual_field,
                before=current,
                after=not current,
                chat_id=chat_id
            )
            setattr(settings, actual_field, not current)
            await session.commit()

        # 在同一个会话中重新查询获取最新数据
        settings = await get_chat_settings(session, chat_id)

    keyboard = auto_delete_config_keyboard(settings, chat_id)

    text = "🧹 自动删除配置\n\n"
    text += "帮助您自动清理群组中的系统消息\n\n"
    text += "配置已更新"
    await _safe_edit_message(q, text, reply_markup=keyboard)
