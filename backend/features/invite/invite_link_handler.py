from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from backend.features.invite.invite_admin_config_callbacks import (
    invite_link_buttons_callback,
    invite_link_cover_callback,
    invite_link_export_callback,
    invite_link_preview_callback,
    invite_link_reset_callback,
    invite_link_text_callback,
)
from backend.features.invite.invite_admin_link_callbacks import (
    invite_link_delete_callback,
    invite_link_detail_callback,
    invite_link_refresh_callback,
    invite_link_revoke_callback,
)
from backend.features.invite.invite_admin_menu_callbacks import (
    invite_link_home_callback,
    invite_link_list_callback,
    invite_link_menu_callback,
    invite_link_mode_callback,
    invite_link_stats_callback,
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
    link_stat_command,
    show_user_invite_menu as _show_user_invite_menu,
    user_invite_create_callback,
    user_invite_list_callback,
    user_invite_menu_callback,
    user_invite_rank_callback,
)
from backend.features.invite.services.invite_service import create_invite_link
from backend.features.invite.ui.invite_link import invite_link_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.state.state_service import clear_user_state, get_user_state, set_user_state
from backend.shared.callback_parser import CallbackParser
from backend.shared.services.permission_service import is_user_admin
from backend.shared.time_ui import build_copy_options_keyboard, build_numeric_duration_prompt_text


def _parse_optional_positive_int(text: str | None, unit_label: str) -> tuple[int | None, str | None]:
    if text == "/skip":
        return None, None
    try:
        value = int(text or "")
    except ValueError:
        return None, f"请输入有效的{unit_label}或 /skip 跳过"
    if value <= 0:
        return None, f"{unit_label}必须大于0，请重新输入或 /skip 跳过"
    return value, None


def _build_invite_creation_result_text(result) -> str:
    if not result.success:
        reasons = {
            "limit_reached": "已达到创建限制",
            "permission_denied": "权限不足",
            "error": "创建失败",
        }
        return f"❌ {reasons.get(result.reason, '未知错误')}"
    invite_link = result.invite_link
    text = (
        "✅ 邀请链接创建成功！\n\n"
        f"链接: `{invite_link.invite_link}`\n"
        f"名称: {invite_link.name or '未命名'}\n"
        f"成员限制: {invite_link.member_limit or '无限制'}\n"
    )
    if invite_link.expire_date is not None:
        text += f"过期时间: {invite_link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
    return text


async def _reply_invite_creation_result(message, result, target_chat_id: int) -> None:
    await message.reply_text(
        _build_invite_creation_result_text(result),
        reply_markup=invite_link_menu_keyboard(target_chat_id),
        parse_mode="Markdown" if result.success else None,
    )


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
            await q.answer("❌ 群组参数无效，请返回重试", show_alert=True)
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
        await set_user_state(session, chat.id, user.id, state_type="invite_link_create", state_data={"target_chat_id": target_chat_id})
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
        state_record = await set_user_state(session, chat.id, user.id, state_type="invite_link_create", state_data=state_data)
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
    member_limit, error = _parse_optional_positive_int(update.effective_message.text, "成员数量")
    if error is not None:
        await update.effective_message.reply_text(error)
        return WAIT_LIMIT
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = dict(state.state_data if state else {})
        state_data["member_limit"] = member_limit
        await set_user_state(session, chat.id, user.id, state_type="invite_link_create", state_data=state_data)
        await session.commit()
    await update.effective_message.reply_text(
        build_numeric_duration_prompt_text(
            title="🔗 邀请链接 | 过期时间",
            unit_label="天",
            sample_value_text="7",
            input_hint="👉 请输入过期天数，或输入 /skip 跳过：",
            extra_tips=[
                f"成员限制: {member_limit or '无限制'}",
                "不设置则长期有效。",
            ],
        ),
        parse_mode="HTML",
        reply_markup=build_copy_options_keyboard(
            back_callback=None,
            options=[("📋 复制 1天", "1"), ("📋 复制 7天", "7"), ("📋 复制 30天", "30")],
        ),
    )
    return WAIT_EXPIRE


async def invite_link_create_expire_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END
    user = update.effective_user
    chat = update.effective_chat
    days, error = _parse_optional_positive_int(update.effective_message.text, "天数")
    if error is not None:
        await update.effective_message.reply_text(error)
        return WAIT_EXPIRE
    expire_date = dt.datetime.now(dt.UTC) + dt.timedelta(days=days) if days is not None else None
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = dict(state.state_data if state else {})
        target_chat_id = int(state_data.get("target_chat_id") or chat.id)
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
    await _reply_invite_creation_result(update.effective_message, result, target_chat_id)
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
