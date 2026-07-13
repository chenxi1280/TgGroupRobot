from __future__ import annotations


import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.services.ad_rotation_service import (
    create_rotation_item,
)
from backend.platform.db.runtime.session import Database
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.permission_service import PermissionPolicyService

from backend.features.automation.ads_context import (
    _format_ad_push_text,
)

log = structlog.get_logger(__name__)

async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用 /ad。")
        return
    if not await PermissionPolicyService.can_manage(context, chat.id, update.effective_user.id, capability="automation"):
        await update.effective_message.reply_text("需要管理员权限。")
        return

    payload = _parse_ad_command_payload(update.effective_message.text or "")
    if payload is None:
        await update.effective_message.reply_text(
            "用法：/ad 标题|内容\n示例：/ad 置顶活动|今晚 8 点直播，欢迎参加"
        )
        return
    title, content = payload
    if not content:
        await update.effective_message.reply_text("内容不能为空。")
        return
    item = await _create_ad_command_item(update, context, title=title, content=content)
    if item is None:
        return
    await context.bot.send_message(chat_id=chat.id, text=_format_ad_push_text(item))


def _parse_ad_command_payload(text: str) -> tuple[str, str] | None:
    normalized = text.strip()
    parts = normalized.split(maxsplit=1)
    if len(parts) == 1:
        return None
    payload = parts[1]
    title, separator, content = payload.partition("|")
    if not separator:
        title, content = "广告", title
    return title.strip()[:120], content.strip()


async def _create_ad_command_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    title: str,
    content: str,
):
    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        if not settings.ads_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启广告功能（/admin → 群设置 中开启）。")
            return None
        item = await create_rotation_item(
            session,
            chat_id=chat.id,
            created_by_user_id=update.effective_user.id,
            title=title,
            content=content,
        )
        await session.commit()
    return item
