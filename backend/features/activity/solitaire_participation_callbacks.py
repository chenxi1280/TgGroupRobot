from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.services.solitaire_service import (
    format_solitaire_message,
    get_chat_solitaires,
    get_solitaire,
    join_solitaire,
    leave_solitaire,
    update_entry,
)
from backend.features.activity.ui.solitaire import get_join_solitaire_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import Solitaire, SolitaireEntry
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.shared.services.command_config_service import is_group_text_command_enabled
from sqlalchemy import select
from sqlalchemy.orm import selectinload

log = structlog.get_logger(__name__)

_JOIN_FAILURE_MESSAGES = {
    "full": "❌ 接龙已满员",
    "closed": "❌ 接龙已关闭",
    "expired": "❌ 接龙已过期",
    "insufficient_points": "❌ 积分不足",
    "already_joined": "❌ 你已经参与过这个接龙",
}


async def _callback_solitaire_id(query, prefix: str) -> int | None:
    data = query.data or ""
    if not data.startswith(prefix):
        return None
    try:
        return int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        await query.answer("无效的接龙")
        return None


def _user_mention(user) -> str:
    if user.username:
        return user.username
    first_name = user.first_name or "用户"
    return f'<a href="tg://user?id={user.id}">@{first_name}</a>'


async def _send_join_error(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await update.callback_query.answer()
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="HTML")


async def _load_joinable_solitaire(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    solitaire_id: int,
):
    solitaire = await get_solitaire(session, solitaire_id)
    if solitaire is None:
        await _send_join_error(update, context, "❌ 接龙不存在")
        return None
    if not await is_group_text_command_enabled(session, solitaire.chat_id, "solitaire"):
        await update.callback_query.answer("接龙入口已关闭。", show_alert=True)
        return None
    if solitaire.status != SolitaireStatus.active.value:
        await _send_join_error(update, context, "❌ 接龙已关闭")
        return None
    if solitaire.max_participants and len(solitaire.entries_rel) >= solitaire.max_participants:
        await _send_join_error(update, context, "❌ 接龙已满员")
        return None
    return solitaire


async def _has_required_points(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, solitaire, user) -> bool:
    if not solitaire.points_required or solitaire.points_required <= 0:
        return True
    from backend.features.points.services.points_service import get_balance

    points = await get_balance(session, solitaire.chat_id, user.id)
    if points >= solitaire.points_required:
        return True
    text = (
        f"{_user_mention(user)} ❌ 积分不足\n"
        f"参与接龙需要 {solitaire.points_required} 积分，你当前有 {points} 积分"
    )
    await _send_join_error(update, context, text)
    return False


async def _has_existing_entry(session, solitaire_id: int, user_id: int) -> bool:
    result = await session.execute(
        select(SolitaireEntry).where(
            SolitaireEntry.solitaire_id == solitaire_id,
            SolitaireEntry.user_id == user_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _reject_existing_join(update: Update, context: ContextTypes.DEFAULT_TYPE, user) -> None:
    text = f"{_user_mention(user)} ❌ 你已经参与过这个接龙\n如需修改内容，请回复接龙消息发送新内容。"
    await _send_join_error(update, context, text)


async def _refresh_solitaire_message(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    solitaire_id: int,
    *,
    user_id: int,
) -> None:
    async with db.session_factory() as session:
        stmt = select(Solitaire).options(selectinload(Solitaire.entries_rel)).where(Solitaire.id == solitaire_id)
        solitaire = (await session.execute(stmt)).scalar_one_or_none()
        if solitaire is None or not solitaire.message_id:
            return
        try:
            await context.bot.edit_message_text(
                chat_id=solitaire.chat_id,
                message_id=solitaire.message_id,
                text=format_solitaire_message(solitaire),
                reply_markup=get_join_solitaire_keyboard(solitaire_id),
            )
        except Exception as exc:
            if "Message is not modified" in str(exc):
                return
            log.warning(
                "solitaire_join_message_refresh_failed",
                chat_id=solitaire.chat_id,
                solitaire_id=solitaire_id,
                message_id=solitaire.message_id,
                user_id=user_id,
                error=str(exc),
            )


async def _reply_join_result(update: Update, context: ContextTypes.DEFAULT_TYPE, result, *, db: Database, solitaire_id: int) -> None:
    query = update.callback_query
    user = update.effective_user
    if not result.success:
        await query.answer()
        failure = _JOIN_FAILURE_MESSAGES.get(result.reason, "❌ 参与失败")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"{_user_mention(user)} {failure}",
            parse_mode="HTML",
        )
        return
    await _refresh_solitaire_message(context, db, solitaire_id, user_id=user.id)
    await query.answer("参与成功！")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"{_user_mention(user)} ✅ 已参与接龙\n如需填写具体内容，请回复接龙消息发送内容；再次回复可更新。",
        parse_mode="HTML",
        reply_to_message_id=getattr(query.message, "message_id", None),
        allow_sending_without_reply=True,
    )


async def join_solitaire_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    solitaire_id = await _callback_solitaire_id(update.callback_query, "join_solitaire:")
    if solitaire_id is None:
        return
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await _load_joinable_solitaire(update, context, session, solitaire_id=solitaire_id)
        if solitaire is None:
            return
        if not await _has_required_points(update, context, session, solitaire=solitaire, user=user):
            return
        if await _has_existing_entry(session, solitaire_id, user.id):
            await _reject_existing_join(update, context, user)
            return
        username = user.username or user.first_name or f"用户{user.id}"
        result = await join_solitaire(session, solitaire_id, user.id, username=username, content="✅ 已参与")
        await session.commit()
    await _reply_join_result(update, context, result, db=db, solitaire_id=solitaire_id)


async def edit_solitaire_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    if not data.startswith("edit_solitaire:"):
        return
    try:
        solitaire_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await q.answer("无效的接龙")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await q.answer("接龙不存在", show_alert=True)
            return

        existing_result = await session.execute(
            select(SolitaireEntry).where(
                SolitaireEntry.solitaire_id == solitaire_id,
                SolitaireEntry.user_id == update.effective_user.id,
            )
        )
        if not existing_result.scalar_one_or_none():
            await q.answer("你还没有参与这个接龙", show_alert=True)
            return

        await leave_solitaire(session, solitaire_id, update.effective_user.id)
        await session.commit()

    await q.answer("原报名已删除，请点击「参与接龙」重新报名", show_alert=True)


def _display_name(user) -> str:
    if user.username:
        return user.username
    if user.first_name:
        return user.first_name + (f" {user.last_name}" if user.last_name else "")
    return f"用户{user.id}"


async def _find_reply_solitaire(session, chat_id: int, reply_message_id: int):
    solitaires = await get_chat_solitaires(session, chat_id, active_only=True)
    return next((item for item in solitaires if item.message_id == reply_message_id), None)


async def _update_existing_join(session, message, *, solitaire_id: int, user_id: int) -> bool:
    if not await _has_existing_entry(session, solitaire_id, user_id):
        return False
    result = await update_entry(session, solitaire_id, user_id, content=message.text)
    await session.commit()
    if not result.success:
        await message.reply_text("❌ 更新失败")
        return True
    solitaire = await get_solitaire(session, solitaire_id)
    if solitaire is not None:
        await message.reply_to_message.edit_text(format_solitaire_message(solitaire))
    await message.reply_text("✅ 已更新你的接龙内容")
    return True


async def _refresh_reply_solitaire(message, db: Database, solitaire_id: int) -> bool:
    async with db.session_factory() as session:
        stmt = select(Solitaire).options(selectinload(Solitaire.entries_rel)).where(Solitaire.id == solitaire_id)
        solitaire = (await session.execute(stmt)).scalar_one_or_none()
        if solitaire is None:
            await message.reply_text("❌ 接龙不存在")
            return False
        await message.reply_to_message.edit_text(format_solitaire_message(solitaire))
        return True


_MESSAGE_JOIN_FAILURES = {
    "not_found": "接龙不存在",
    "already_closed": "接龙已结束",
    "already_joined": "你已经参与了，请回复更新内容",
    "full": "接龙人数已满",
    "expired": "接龙已截止",
    "insufficient_points": "积分不足，无法参与",
    "error": "参与失败",
}


async def _join_from_message(session, message, *, target_solitaire, user, db: Database) -> None:
    result = await join_solitaire(
        session,
        target_solitaire.id,
        user.id,
        username=_display_name(user),
        content=message.text,
    )
    await session.commit()
    if not result.success:
        reason_text = _MESSAGE_JOIN_FAILURES.get(result.reason, "未知错误")
        await message.reply_text(f"❌ {reason_text}")
        return
    if await _refresh_reply_solitaire(message, db, target_solitaire.id):
        await message.reply_text("✅ 接龙成功！")


async def solitaire_join_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None or update.effective_chat is None or update.effective_user is None:
        return
    message = update.effective_message
    if not message.reply_to_message:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        target_solitaire = await _find_reply_solitaire(session, chat.id, message.reply_to_message.message_id)
        if target_solitaire is None:
            return
        if not await is_group_text_command_enabled(session, chat.id, "solitaire"):
            await session.commit()
            await message.reply_text("接龙入口已关闭。")
            return
        if await _update_existing_join(session, message, solitaire_id=target_solitaire.id, user_id=user.id):
            return
        await _join_from_message(session, message, target_solitaire=target_solitaire, user=user, db=db)
