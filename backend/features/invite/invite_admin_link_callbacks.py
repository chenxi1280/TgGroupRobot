from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.invite.invite_shared import invite_link_menu_keyboard
from backend.features.invite.services.invite_service import (
    delete_invite_link,
    get_invite_link_in_chat,
    revoke_invite_link,
    update_invite_link_info,
)
from backend.features.invite.ui.invite_link import invite_link_detail_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import InviteLinkStatus
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext


async def _resolve_invite_link_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int | None:
    return await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=3,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )


async def invite_link_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    link_id = _parse_link_id(cb)
    if link_id is None:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await _resolve_invite_link_target_chat_id(update, context)
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

        text = _format_invite_link_detail(link)
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)
    await q.edit_message_text(text, reply_markup=invite_link_detail_keyboard(link_id, target_chat_id), parse_mode="Markdown")


async def invite_link_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    cb = CallbackParser.parse(q.data or "")
    link_id = _parse_link_id(cb)
    if link_id is None:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await _resolve_invite_link_target_chat_id(update, context)
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
    link_id = _parse_link_id(cb)
    if link_id is None:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await _resolve_invite_link_target_chat_id(update, context)
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
    link_id = _parse_link_id(cb)
    if link_id is None:
        await answer_callback_query_safely(update, "无效的链接ID", show_alert=True)
        return
    target_chat_id = await _resolve_invite_link_target_chat_id(update, context)
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


def _parse_link_id(cb: CallbackParser) -> int | None:
    if cb.length() < 3:
        return None
    link_id = cb.get_int(2)
    return link_id or None


def _format_invite_link_detail(link) -> str:
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
    return text
