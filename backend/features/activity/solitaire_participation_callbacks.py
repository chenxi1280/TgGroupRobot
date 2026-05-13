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


async def join_solitaire_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    data = q.data or ""
    if not data.startswith("join_solitaire:"):
        return
    try:
        solitaire_id = int(data.split(":")[1])
    except (ValueError, IndexError):
        await q.answer("无效的接龙")
        return

    user = update.effective_user
    user_id = user.id
    user_mention = user.username or f"<a href=\"tg://user?id={user_id}\">@{user.first_name or '用户'}</a>"
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        solitaire = await get_solitaire(session, solitaire_id)
        if not solitaire:
            await q.answer()
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 接龙不存在", parse_mode="HTML")
            return
        if not await is_group_text_command_enabled(session, solitaire.chat_id, "solitaire"):
            await q.answer("接龙入口已关闭。", show_alert=True)
            return
        if solitaire.status != SolitaireStatus.active.value:
            await q.answer()
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 接龙已关闭", parse_mode="HTML")
            return
        if solitaire.max_participants and len(solitaire.entries_rel) >= solitaire.max_participants:
            await q.answer()
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 接龙已满员", parse_mode="HTML")
            return

        if solitaire.points_required and solitaire.points_required > 0:
            from backend.features.points.services.points_service import get_balance

            points = await get_balance(session, solitaire.chat_id, user_id)
            if points < solitaire.points_required:
                await q.answer()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{user_mention} ❌ 积分不足\n参与接龙需要 {solitaire.points_required} 积分，你当前有 {points} 积分",
                    parse_mode="HTML",
                )
                return

        existing_result = await session.execute(
            select(SolitaireEntry).where(
                SolitaireEntry.solitaire_id == solitaire_id,
                SolitaireEntry.user_id == user_id,
            )
        )
        if existing_result.scalar_one_or_none():
            await q.answer()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_mention} ❌ 你已经参与过这个接龙\n如需修改内容，请回复接龙消息发送新内容。",
                parse_mode="HTML",
            )
            return

        username = user.username or user.first_name or f"用户{user_id}"
        result = await join_solitaire(session, solitaire_id, user_id, username, content="✅ 已参与")
        await session.commit()

        if result.success:
            async with db.session_factory() as new_session:
                stmt = select(Solitaire).options(selectinload(Solitaire.entries_rel)).where(Solitaire.id == solitaire_id)
                query_result = await new_session.execute(stmt)
                solitaire = query_result.scalar_one_or_none()
                if solitaire is None:
                    await q.answer("❌ 接龙不存在")
                    return
                if solitaire.message_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=solitaire.chat_id,
                            message_id=solitaire.message_id,
                            text=format_solitaire_message(solitaire),
                            reply_markup=get_join_solitaire_keyboard(solitaire_id),
                        )
                    except Exception as exc:
                        if "Message is not modified" not in str(exc):
                            log.warning(
                                "solitaire_join_message_refresh_failed",
                                chat_id=solitaire.chat_id,
                                solitaire_id=solitaire_id,
                                message_id=solitaire.message_id,
                                user_id=user_id,
                                error=str(exc),
                            )
            await q.answer("参与成功！")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_mention} ✅ 已参与接龙\n如需填写具体内容，请回复接龙消息发送内容；再次回复可更新。",
                parse_mode="HTML",
                reply_to_message_id=getattr(q.message, "message_id", None),
                allow_sending_without_reply=True,
            )
        else:
            await q.answer()
            reason_map = {
                "full": "❌ 接龙已满员",
                "closed": "❌ 接龙已关闭",
                "expired": "❌ 接龙已过期",
                "insufficient_points": "❌ 积分不足",
                "already_joined": "❌ 你已经参与过这个接龙",
            }
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_mention} {reason_map.get(result.reason, '❌ 参与失败')}",
                parse_mode="HTML",
            )


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
        solitaires = await get_chat_solitaires(session, chat.id, active_only=True)
        target_solitaire = next((item for item in solitaires if item.message_id == message.reply_to_message.message_id), None)
        if not target_solitaire:
            return
        if not await is_group_text_command_enabled(session, chat.id, "solitaire"):
            await session.commit()
            await message.reply_text("接龙入口已关闭。")
            return

        existing_result = await session.execute(
            select(SolitaireEntry).where(
                SolitaireEntry.solitaire_id == target_solitaire.id,
                SolitaireEntry.user_id == user.id,
            )
        )
        if existing_result.scalar_one_or_none():
            result = await update_entry(session, target_solitaire.id, user.id, message.text)
            if result.success:
                await session.commit()
                solitaire = await get_solitaire(session, target_solitaire.id)
                if solitaire:
                    await message.reply_to_message.edit_text(format_solitaire_message(solitaire))
                await message.reply_text("✅ 已更新你的接龙内容")
            else:
                await session.commit()
                await message.reply_text("❌ 更新失败")
            return

        if user.username:
            display_name = user.username
        elif user.first_name:
            display_name = user.first_name + (f" {user.last_name}" if user.last_name else "")
        else:
            display_name = f"用户{user.id}"

        result = await join_solitaire(session, target_solitaire.id, user.id, display_name, message.text)
        if result.success:
            await session.commit()
            async with db.session_factory() as new_session:
                stmt = select(Solitaire).options(selectinload(Solitaire.entries_rel)).where(Solitaire.id == target_solitaire.id)
                query_result = await new_session.execute(stmt)
                solitaire = query_result.scalar_one_or_none()
                if solitaire is None:
                    await message.reply_text("❌ 接龙不存在")
                    return
                await message.reply_to_message.edit_text(format_solitaire_message(solitaire))
            await message.reply_text("✅ 接龙成功！")
        else:
            await session.commit()
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "already_joined": "你已经参与了，请回复更新内容",
                "full": "接龙人数已满",
                "expired": "接龙已截止",
                "insufficient_points": "积分不足，无法参与",
                "error": "参与失败",
            }.get(result.reason, "未知错误")
            await message.reply_text(f"❌ {reason_text}")
