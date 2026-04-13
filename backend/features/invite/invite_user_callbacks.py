from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from backend.features.invite.services.invite_service import get_user_links
from backend.features.invite.ui.invite_link import user_invite_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatSettings
from backend.platform.db.schema.models.enums import InviteLinkStatus
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.command_config_service import ensure_command_enabled


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.effective_message.reply_text("请在群组中使用此功能")
        return
    allowed = await ensure_command_enabled(context, update, command_key="link")
    if not allowed:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        await session.commit()
    if not settings.invite_link_enabled:
        await update.effective_message.reply_text("本群未开启邀请链接功能")
        return
    await show_user_invite_menu(update, context, chat.id, user.id)


async def show_user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    from backend.features.invite.services.invite_service import get_user_invite_stats

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings_result = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
        settings = settings_result.scalar_one_or_none()
        stats = await get_user_invite_stats(session, chat_id, user_id)
        await session.commit()

    text = (
        "🔗 邀请链接\n\n"
        f"状态: {'✅ 启用' if settings and settings.invite_link_enabled else '❌ 禁用'}\n"
        f"总邀请人数: {stats.total_invites}\n"
        f"活跃链接: {stats.active_links}\n"
        f"链接过期: {settings.invite_link_expire_days or '无限制'} 天\n"
        f"最大邀请: {settings.invite_link_max_joins or '无限制'} 人\n"
    )
    if stats.link_limit:
        text += f"生成上限: {stats.link_limit} 个\n"
    text += f"已生成: {stats.links_generated} 个"

    keyboard = user_invite_menu_keyboard(chat_id)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def user_invite_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    chat_id = cb.get_int(2)
    if chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组ID", show_alert=True)
        return

    from backend.features.invite.services.invite_service import create_invite_link as user_create_link

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success, link, error = await user_create_link(
            session,
            context.bot,
            chat_id,
            user.id,
            name=f"{user.first_name or user.username or '用户'}的链接",
        )
        await session.commit()

    if success and link:
        await q.answer()
        mark_callback_query_answered(update)
        await show_user_invite_menu(update, context, chat_id, user.id)
        await context.bot.send_message(
            chat_id=user.id,
            text=f"✅ 邀请链接创建成功！\n\n`{link.invite_link}`\n\n点击链接即可邀请好友加入群组",
            parse_mode="Markdown",
        )
    else:
        await q.answer()
        mark_callback_query_answered(update)
        await q.edit_message_text(f"❌ {error or '创建失败'}")
        await show_user_invite_menu(update, context, chat_id, user.id)


async def user_invite_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    chat_id = cb.get_int(2)
    if chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组ID", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        links = await get_user_links(session, chat_id, user.id)
        await session.commit()

    if not links:
        await q.answer()
        mark_callback_query_answered(update)
        await q.edit_message_text(
            "🔗 我的邀请链接\n\n暂无链接，点击「生成链接」创建",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]),
        )
        return

    text = f"🔗 我的邀请链接\n\n共 {len(links)} 个链接\n\n"
    for link in links[:5]:
        status_emoji = "🟢" if link.status == InviteLinkStatus.active.value else "🔴"
        text += f"{status_emoji} {link.name or '未命名'}\n"
        text += f"   成员: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n\n"

    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]),
    )


async def user_invite_rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    chat_id = cb.get_int(2)
    if chat_id == 0:
        await answer_callback_query_safely(update, "无效的群组ID", show_alert=True)
        return

    from backend.features.invite.services.invite_service import get_invite_leaderboard, get_user_rank

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        leaderboard = await get_invite_leaderboard(session, chat_id, limit=10)
        user_rank = await get_user_rank(session, chat_id, user.id)
        await session.commit()

    if not leaderboard:
        await q.answer()
        mark_callback_query_answered(update)
        await q.edit_message_text(
            "🏆 邀请排行榜\n\n暂无邀请数据",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]),
        )
        return

    text = "🏆 邀请排行榜（前10名）\n\n"
    for i, (uid, count, username) in enumerate(leaderboard, 1):
        text += f"{i}. {username or f'用户{uid}'} - {count} 人\n"
    if user_rank:
        text += f"\n你的排名: 第 {user_rank} 名"

    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]),
    )
