from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.invite.invite_shared import (
    _invite_link_handler,
    format_invite_preview,
    invite_link_menu_keyboard,
    reset_invite_data,
    show_invite_link_menu_from_message,
    export_invite_csv,
)
from backend.features.invite.services.invite_service import (
    delete_invite_link,
    get_invite_link_in_chat,
    revoke_invite_link,
    update_invite_link_info,
)
from backend.features.invite.ui.invite_link import invite_link_detail_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import InviteLinkStatus
from backend.platform.state.state_service import set_user_state
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.permission_service import is_user_admin


async def invite_link_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        db: Database = context.application.bot_data["db"]
        target_chat_id = await ChatResolver.get_current_chat(db, user.id)
        if target_chat_id is None:
            await _invite_link_handler.message_helper.safe_edit(update, "请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await _invite_link_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
            return
        from backend.features.admin.admin_handler import _show_private_admin_menu

        await _show_private_admin_menu(update, context, target_chat_id)
        return

    if not await is_user_admin(context, chat.id, user.id):
        await _invite_link_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
        return

    await _invite_link_handler.show_menu(update, context, chat.id, chat.title)


async def invite_link_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_list(update, context, target_chat_id, CallbackParser.parse(q.data or "").get_int(2, default=0))


async def invite_link_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context)
    if target_chat_id is None:
        return
    await _invite_link_handler.show_stats(update, context, target_chat_id)


async def invite_link_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    cb = CallbackParser.parse(q.data or "")
    field = cb.get(2)
    value = cb.get_int_optional(4)
    if value not in {0, 1}:
        await answer_callback_query_safely(update, "无效开关值", show_alert=True)
        return

    field_map = {"enabled": "invite_link_enabled", "remind": "invite_link_notify"}
    setting_field = field_map.get(field)
    if setting_field is None:
        await answer_callback_query_safely(update, "无效配置项", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        setattr(settings, setting_field, bool(value))
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    mode = CallbackParser.parse(q.data or "").get(3)
    if mode not in {"relay", "direct"}:
        await answer_callback_query_safely(update, "无效模式", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        settings.invite_link_mode = mode
        await session.commit()
    await q.answer()
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_cover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_cover_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "🖼️ 邀请链接 | 修改封面\n\n请发送图片或视频，发送“清空”可移除封面。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_text_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "📝 邀请链接 | 修改文本\n\n"
        f"当前模板：\n{settings.invite_link_text_template}\n\n"
        "支持变量：{inviter} {invitee} {group}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_buttons_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "⌨️ 邀请链接 | 修改按钮\n\n"
        "每行最多 3 个按钮，同行按钮用 `;` 分隔。\n"
        "格式：按钮文案|https://example.com\n"
        "示例：点击关注|https://t.me/demo; 联系管理|https://t.me/admin",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await session.commit()
    preview_text, keyboard = format_invite_preview(settings, str(target_chat_id))
    if settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "photo":
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    elif settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "video":
        await context.bot.send_video(chat_id=update.effective_chat.id, video=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=preview_text, reply_markup=keyboard)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    reset_type = CallbackParser.parse(q.data or "").get(2)
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        toast, links = await reset_invite_data(session, reset_type=reset_type, chat_id=target_chat_id)
        await session.commit()
    if toast is None:
        await answer_callback_query_safely(update, "无效重置类型", show_alert=True)
        return
    if links:
        for link in links:
            try:
                await context.bot.revoke_chat_invite_link(chat_id=target_chat_id, invite_link=link.invite_link)
            except Exception:
                continue
    await q.answer(toast, show_alert=True)
    mark_callback_query_answered(update)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    await export_invite_csv(context, chat_id=target_chat_id, reply_chat_id=update.effective_chat.id)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    link_id = cb.get_int(2)
    if link_id == 0:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        link = await get_invite_link_in_chat(session, target_chat_id, link_id)
        if not link:
            await session.commit()
            await q.answer()
            mark_callback_query_answered(update)
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))
            return

        status_emoji = {
            InviteLinkStatus.active.value: "🟢 激活",
            InviteLinkStatus.revoked.value: "🔴 已撤销",
            InviteLinkStatus.expired.value: "⚫ 已过期",
        }.get(link.status, link.status)
        text = (
            "🔗 邀请链接详情\n\n"
            f"名称: {link.name or '未命名'}\n"
            f"状态: {status_emoji}\n"
            f"链接: `{link.invite_link}`\n"
            f"成员数: {link.member_count}"
        )
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n"
        if link.expire_date:
            text += f"过期时间: {link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        text += f"需要审批: {'是' if link.creates_join_request else '否'}"
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(text, reply_markup=invite_link_detail_keyboard(link_id, target_chat_id), parse_mode="Markdown")


async def invite_link_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    link_id = cb.get_int(2)
    if link_id == 0:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await update_invite_link_info(session, context.bot, link_id, chat_id=target_chat_id)
        await session.commit()
        if not success:
            await q.answer()
            mark_callback_query_answered(update)
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))
            return

    await invite_link_detail_callback(update, context)


async def invite_link_revoke_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    link_id = cb.get_int(2)
    if link_id == 0:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await revoke_invite_link(session, context.bot, link_id, chat_id=target_chat_id)
        await session.commit()
    await q.answer()
    mark_callback_query_answered(update)
    if result.success:
        await q.edit_message_text("✅ 链接已撤销", reply_markup=invite_link_menu_keyboard(target_chat_id))
    else:
        reason_text = {
            "not_found": "链接不存在",
            "already_revoked": "链接已被撤销",
            "error": "撤销失败",
        }.get(result.reason, "未知错误")
        await q.edit_message_text(f"❌ {reason_text}", reply_markup=invite_link_menu_keyboard(target_chat_id))


async def invite_link_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    link_id = cb.get_int(2)
    if link_id == 0:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_invite_link(session, link_id, chat_id=target_chat_id)
        await session.commit()
    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(
        "✅ 链接记录已删除" if success else "❌ 链接不存在",
        reply_markup=invite_link_menu_keyboard(target_chat_id),
    )
