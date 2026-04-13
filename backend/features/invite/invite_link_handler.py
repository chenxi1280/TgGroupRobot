from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.invite.invite_admin_callbacks import (
    invite_link_buttons_callback,
    invite_link_cover_callback,
    invite_link_delete_callback,
    invite_link_detail_callback,
    invite_link_export_callback,
    invite_link_home_callback,
    invite_link_list_callback,
    invite_link_menu_callback,
    invite_link_mode_callback,
    invite_link_preview_callback,
    invite_link_refresh_callback,
    invite_link_reset_callback,
    invite_link_revoke_callback,
    invite_link_stats_callback,
    invite_link_text_callback,
    invite_link_toggle_callback,
)
from backend.features.invite.invite_shared import (
    WAIT_EXPIRE,
    WAIT_LIMIT,
    WAIT_NAME,
    InviteLinkHandler,
    _invite_link_handler,
    format_invite_preview as _format_invite_preview,
    handle_invite_link_config_input,
    parse_invite_buttons as _parse_invite_buttons,
    show_invite_link_menu_from_message as _show_invite_link_menu_from_message,
)
from backend.features.invite.invite_user_callbacks import (
    link_command,
    show_user_invite_menu as _show_user_invite_menu,
    user_invite_create_callback,
    user_invite_list_callback,
    user_invite_rank_callback,
)
from backend.features.invite.services.invite_service import create_invite_link
from backend.features.invite.ui.invite_link import invite_link_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.callback_parser import CallbackParser
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import is_user_admin


async def invite_link_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        target_chat_id = 0
        data = q.data or ""
        if data.startswith("inv:create:"):
            target_chat_id = CallbackParser.parse(data).get_int(2)
        if target_chat_id == 0:
            db: Database = context.application.bot_data["db"]
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)
            if target_chat_id is None:
                await q.edit_message_text("请先选择一个群组")
                return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "invite_link_create", {"target_chat_id": target_chat_id})
        await session.commit()
    await q.edit_message_text("➕ 创建邀请链接\n\n请输入链接名称（可选）\n\n输入 /skip 跳过")
    return WAIT_NAME


async def invite_link_create_name_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    user = update.effective_user
    chat = update.effective_chat
    raw_name = (update.effective_message.text or "").strip()
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = dict(state.state_data if state else {})
        state_data["name"] = None if raw_name == "/skip" else raw_name
        state_record = await set_user_state(session, chat.id, user.id, "invite_link_create", state_data)
        await session.commit()
    await update.effective_message.reply_text(
        f"名称: {state_record.state_data.get('name') or '未命名'}\n\n请输入成员数量限制（可选）\n\n输入数字或 /skip 跳过"
    )
    return WAIT_LIMIT


async def invite_link_create_limit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
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
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        target_chat_id = int(state_data.get("target_chat_id") or chat.id)
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
        result = await create_invite_link(
            session,
            chat_id=target_chat_id,
            created_by_user_id=user.id,
            bot=context.bot,
            name=state_data.get("name"),
            member_limit=state_data.get("member_limit"),
            expire_date=state_data.get("expire_date"),
        )
        await clear_user_state(session, chat.id, user.id)
        await session.commit()
        if result.success:
            text_msg = (
                "✅ 邀请链接创建成功！\n\n"
                f"链接: `{result.invite_link.invite_link}`\n"
                f"名称: {result.invite_link.name or '未命名'}\n"
                f"成员限制: {result.invite_link.member_limit or '无限制'}\n"
            )
            if result.invite_link.expire_date:
                text_msg += f"过期时间: {result.invite_link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            await update.effective_message.reply_text(text_msg, reply_markup=invite_link_menu_keyboard(target_chat_id), parse_mode="Markdown")
        else:
            reason_text = {"limit_reached": "已达到创建限制", "permission_denied": "权限不足", "error": "创建失败"}.get(result.reason, "未知错误")
            await update.effective_message.reply_text(f"❌ {reason_text}", reply_markup=invite_link_menu_keyboard(target_chat_id))
    return ConversationHandler.END


async def invite_link_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    target_chat_id = chat.id
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        if state is not None:
            target_chat_id = int((state.state_data or {}).get("target_chat_id") or target_chat_id)
        await clear_user_state(session, chat.id, user.id)
        await session.commit()
    await q.edit_message_text("已取消创建", reply_markup=invite_link_menu_keyboard(target_chat_id))
    return ConversationHandler.END
