from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.admin import admin_main_menu, toggle_menu
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.telegram_perm import is_user_admin


def _settings_toggle_rows(settings) -> list[tuple[str, str, bool]]:
    return [
        ("签到", "sign_enabled", settings.sign_enabled),
        ("新人验证", "verification_enabled", settings.verification_enabled),
        ("内容审核", "moderation_enabled", settings.moderation_enabled),
        ("屏蔽链接", "moderation_block_links", settings.moderation_block_links),
        ("广告", "ads_enabled", settings.ads_enabled),
        ("商业化", "monetization_enabled", settings.monetization_enabled),
    ]


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(t("zh-CN", "error.need_group"))
        return

    chat = update.effective_chat
    user = update.effective_user
    if not await is_user_admin(context, chat.id, user.id):
        await update.effective_message.reply_text(t("zh-CN", "error.need_admin"))
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    await update.effective_message.reply_text(t(settings.language, "admin.title"), reply_markup=admin_main_menu())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await q.edit_message_text(t("zh-CN", "error.need_group"))
        return
    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text(t("zh-CN", "error.need_admin"))
        return

    data = q.data or ""
    # adm:menu:xxx  /  adm:toggle:field
    parts = data.split(":")
    if len(parts) < 3:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)

        if parts[1] == "menu":
            menu = parts[2]
            if menu == "main":
                await session.commit()
                await q.edit_message_text(t(settings.language, "admin.title"), reply_markup=admin_main_menu())
                return

            if menu == "settings":
                await session.commit()
                await q.edit_message_text(
                    "开关设置：",
                    reply_markup=toggle_menu(_settings_toggle_rows(settings), back_to="main"),
                )
                return

            if menu == "points":
                await session.commit()
                await q.edit_message_text("积分：成员可用 /sign 签到，/points 查询。更多运营玩法可扩展。", reply_markup=admin_main_menu())
                return

            if menu == "verification":
                await session.commit()
                await q.edit_message_text("新人验证：新成员入群会先限制发言，点击按钮放行。", reply_markup=admin_main_menu())
                return

            if menu == "moderation":
                await session.commit()
                await q.edit_message_text("内容审核：默认屏蔽链接，可扩展关键词/白名单/风控策略。", reply_markup=admin_main_menu())
                return

            if menu == "ads":
                await session.commit()
                await q.edit_message_text("广告与订阅：已预留数据模型与开关位，可扩展群级订阅与广告投放。", reply_markup=admin_main_menu())
                return

        if parts[1] == "toggle":
            field = parts[2]
            if hasattr(settings, field):
                current = bool(getattr(settings, field))
                setattr(settings, field, not current)
                await session.commit()
                await q.edit_message_text(
                    "开关设置：",
                    reply_markup=toggle_menu(_settings_toggle_rows(settings), back_to="main"),
                )
                return

        await session.commit()





