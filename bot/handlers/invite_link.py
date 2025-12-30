from __future__ import annotations

import datetime as dt
import structlog
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.db.session import Database
from bot.keyboards.invite_link import (
    invite_link_create_keyboard,
    invite_link_detail_keyboard,
    invite_link_list_keyboard,
    invite_link_menu_keyboard,
)
from bot.models.enums import InviteLinkStatus
from bot.services.chat_service import get_chat_settings
from bot.services.invite_link_service import (
    create_invite_link,
    delete_invite_link,
    get_chat_invite_links,
    get_invite_link,
    get_link_stats,
    revoke_invite_link,
    update_invite_link_info,
)
from bot.services.state_service import clear_user_state, get_user_state, set_user_state
from bot.services.telegram_perm import is_user_admin

# 创建流程状态
WAIT_NAME = 1
WAIT_LIMIT = 2
WAIT_EXPIRE = 3

log = structlog.get_logger(__name__)


async def invite_link_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await q.edit_message_text("请在群组中使用此功能")
        return

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    await q.edit_message_text(
        f"🔗 [{chat.title}] 邀请链接管理\n\n管理群组邀请链接",
        reply_markup=invite_link_menu_keyboard(),
    )


async def invite_link_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        links = await get_chat_invite_links(session, chat.id)
        await session.commit()

    if not links:
        await q.edit_message_text(
            "🔗 邀请链接列表\n\n暂无邀请链接，点击「创建邀请链接」开始",
            reply_markup=invite_link_menu_keyboard(),
        )
        return

    text = f"🔗 邀请链接列表\n\n共 {len(links)} 个链接"
    await q.edit_message_text(text, reply_markup=invite_link_list_keyboard(links, page))


async def invite_link_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接统计回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        stats = await get_link_stats(session, chat.id)
        await session.commit()

    text = f"📊 邀请链接统计\n\n"
    text += f"总链接数: {stats['total']}\n"
    text += f"激活中: {stats['active']}\n"
    text += f"已撤销: {stats['revoked']}\n"
    text += f"已过期: {stats['expired']}\n"
    text += f"总成员数: {stats['total_members']}"

    await q.edit_message_text(text, reply_markup=invite_link_menu_keyboard())


async def invite_link_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接详情回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    link_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        link = await get_invite_link(session, link_id)
        if not link:
            await session.commit()
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard())
            return

        status_emoji = {
            InviteLinkStatus.active.value: "🟢 激活",
            InviteLinkStatus.revoked.value: "🔴 已撤销",
            InviteLinkStatus.expired.value: "⚫ 已过期",
        }.get(link.status, link.status)

        text = f"🔗 邀请链接详情\n\n"
        text += f"名称: {link.name or '未命名'}\n"
        text += f"状态: {status_emoji}\n"
        text += f"链接: `{link.invite_link}`\n"
        text += f"成员数: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n"
        if link.expire_date:
            text += f"过期时间: {link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        text += f"需要审批: {'是' if link.creates_join_request else '否'}"

        await session.commit()

    await q.edit_message_text(text, reply_markup=invite_link_detail_keyboard(link_id), parse_mode="Markdown")


async def invite_link_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建邀请链接"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "invite_link_create", {})
        await session.commit()

    await q.edit_message_text(
        "➕ 创建邀请链接\n\n请输入链接名称（可选）\n\n输入 /skip 跳过",
    )
    return WAIT_NAME


async def invite_link_create_name_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理链接名称输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_data = await set_user_state(session, chat.id, user.id, "invite_link_create", {"name": update.effective_message.text})
        await session.commit()

    await update.effective_message.reply_text(
        f"名称: {state_data.state_data.get('name')}\n\n请输入成员数量限制（可选）\n\n输入数字或 /skip 跳过"
    )
    return WAIT_LIMIT


async def invite_link_create_limit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理成员数量限制输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

        member_limit = None
        if text != "/skip":
            try:
                member_limit = int(text)
                if member_limit <= 0:
                    await update.effective_message.reply_text("成员数量必须大于0，请重新输入或 /skip 跳过")
                    return WAIT_LIMIT
            except ValueError:
                await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
                return WAIT_LIMIT

        state_data["member_limit"] = member_limit
        await set_user_state(session, chat.id, user.id, "invite_link_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"成员限制: {member_limit or '无限制'}\n\n请输入过期时间（可选）\n格式: 天数\n输入 /skip 跳过"
    )
    return WAIT_EXPIRE


async def invite_link_create_expire_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理过期时间输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

        expire_date = None
        if text != "/skip":
            try:
                days = int(text)
                if days <= 0:
                    await update.effective_message.reply_text("天数必须大于0，请重新输入或 /skip 跳过")
                    return WAIT_EXPIRE
                expire_date = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
            except ValueError:
                await update.effective_message.reply_text("请输入有效的天数或 /skip 跳过")
                return WAIT_EXPIRE

        state_data["expire_date"] = expire_date

        # 创建链接
        result = await create_invite_link(
            session,
            chat_id=chat.id,
            created_by_user_id=user.id,
            bot=context.bot,
            name=state_data.get("name"),
            member_limit=state_data.get("member_limit"),
            expire_date=state_data.get("expire_date"),
        )

        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        if result.success:
            text = f"✅ 邀请链接创建成功！\n\n"
            text += f"链接: `{result.invite_link.invite_link}`\n"
            text += f"名称: {result.invite_link.name or '未命名'}\n"
            text += f"成员限制: {result.invite_link.member_limit or '无限制'}\n"
            if result.invite_link.expire_date:
                text += f"过期时间: {result.invite_link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

            await update.effective_message.reply_text(text, reply_markup=invite_link_menu_keyboard(), parse_mode="Markdown")
        else:
            reason_text = {
                "limit_reached": "已达到创建限制",
                "permission_denied": "权限不足",
                "error": "创建失败",
            }.get(result.reason, "未知错误")
            await update.effective_message.reply_text(f"❌ {reason_text}", reply_markup=invite_link_menu_keyboard())

    return ConversationHandler.END


async def invite_link_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """取消创建流程"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await clear_user_state(session, chat.id, user.id)
        await session.commit()

    await q.edit_message_text("已取消创建", reply_markup=invite_link_menu_keyboard())
    return ConversationHandler.END


async def invite_link_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """刷新邀请链接信息"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    link_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await update_invite_link_info(session, context.bot, link_id)
        await session.commit()

        if not success:
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard())
            return

        link = await get_invite_link(session, link_id)
        if not link:
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard())
            return

        status_emoji = {
            InviteLinkStatus.active.value: "🟢 激活",
            InviteLinkStatus.revoked.value: "🔴 已撤销",
            InviteLinkStatus.expired.value: "⚫ 已过期",
        }.get(link.status, link.status)

        text = f"🔗 邀请链接详情\n\n"
        text += f"名称: {link.name or '未命名'}\n"
        text += f"状态: {status_emoji}\n"
        text += f"链接: `{link.invite_link}`\n"
        text += f"成员数: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n"
        if link.expire_date:
            text += f"过期时间: {link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        text += f"需要审批: {'是' if link.creates_join_request else '否'}"

    await q.edit_message_text(text, reply_markup=invite_link_detail_keyboard(link_id), parse_mode="Markdown")


async def invite_link_revoke_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """撤销邀请链接"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    link_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await revoke_invite_link(session, context.bot, link_id)
        await session.commit()

        if result.success:
            await q.edit_message_text("✅ 链接已撤销", reply_markup=invite_link_menu_keyboard())
        else:
            reason_text = {
                "not_found": "链接不存在",
                "already_revoked": "链接已被撤销",
                "error": "撤销失败",
            }.get(result.reason, "未知错误")
            await q.edit_message_text(f"❌ {reason_text}", reply_markup=invite_link_menu_keyboard())


async def invite_link_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除邀请链接记录"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    link_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_invite_link(session, link_id)
        await session.commit()

        if success:
            await q.edit_message_text("✅ 链接记录已删除", reply_markup=invite_link_menu_keyboard())
        else:
            await q.edit_message_text("❌ 链接不存在", reply_markup=invite_link_menu_keyboard())
