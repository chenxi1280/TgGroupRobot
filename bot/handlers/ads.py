from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.telegram_perm import is_user_admin
from bot.models.core import AdCampaign


async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    管理员发布广告（MVP）：/ad 标题|内容
    """
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用 /ad。")
        return
    if not await is_user_admin(context, chat.id, update.effective_user.id):
        await update.effective_message.reply_text("需要管理员权限。")
        return

    text = (update.effective_message.text or "").strip()
    if text == "/ad" or text.startswith("/ad@") or len(text.split(maxsplit=1)) == 1:
        await update.effective_message.reply_text("用法：/ad 标题|内容\n示例：/ad 置顶活动|今晚 8 点直播，欢迎参加")
        return

    payload = text.split(maxsplit=1)[1]
    if "|" in payload:
        title, content = payload.split("|", 1)
    else:
        title, content = "广告", payload
    title = title.strip()[:120]
    content = content.strip()
    if not content:
        await update.effective_message.reply_text("内容不能为空。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        if not settings.ads_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启广告功能（/admin → 群设置 中开启）。")
            return
        session.add(AdCampaign(chat_id=chat.id, created_by_user_id=update.effective_user.id, title=title, content=content))
        await session.commit()

    await context.bot.send_message(chat_id=chat.id, text=f"【{title}】\n{content}")



