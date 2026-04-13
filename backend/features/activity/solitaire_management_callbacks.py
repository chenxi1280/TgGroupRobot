from __future__ import annotations

import datetime as dt

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from backend.features.activity.services.solitaire_service import (
    close_solitaire,
    delete_solitaire,
    format_solitaire_message,
    get_solitaire_in_chat,
)
from backend.features.activity.ui.solitaire import solitaire_detail_keyboard, solitaire_menu_keyboard
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext


async def solitaire_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire_in_chat(session, target_chat_id, solitaire_id)
        if not solitaire:
            await session.commit()
            await q.edit_message_text("接龙不存在", reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None))
            return

        if solitaire.deadline and solitaire.status == SolitaireStatus.active.value and dt.datetime.now(dt.timezone.utc) > solitaire.deadline:
            close_result = await close_solitaire(session, solitaire_id, chat_id=target_chat_id)
            if close_result.success:
                solitaire = close_result.entity
                try:
                    await context.bot.send_message(
                        chat_id=solitaire.chat_id,
                        text=f"⏰ 接龙已截止\n\n{solitaire.title}\n参与人数: {len(solitaire.entries_rel)} 人",
                    )
                except Exception:
                    pass

        text = format_solitaire_message(solitaire, show_closed=False)
        is_active = solitaire.status == SolitaireStatus.active.value
        await session.commit()

    try:
        await q.edit_message_text(
            text,
            reply_markup=solitaire_detail_keyboard(solitaire_id, is_active, target_chat_id if chat.type == "private" else None),
        )
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def solitaire_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await close_solitaire(session, solitaire_id, chat_id=target_chat_id)
        if result.success:
            entries_count = len(result.entity.entries_rel)
            await session.commit()

            try:
                await context.bot.send_message(
                    chat_id=result.entity.chat_id,
                    text=f"🔴 接龙已结束\n\n{result.entity.title}\n参与人数: {entries_count} 人",
                )
            except Exception:
                pass

            if result.entity.message_id:
                try:
                    await context.bot.edit_message_text(
                        chat_id=result.entity.chat_id,
                        message_id=result.entity.message_id,
                        text=format_solitaire_message(result.entity, show_closed=False),
                    )
                except Exception:
                    pass

            try:
                await context.bot.send_message(chat_id=user.id, text=format_solitaire_message(result.entity, show_closed=False))
            except Exception:
                pass

            await q.edit_message_text(
                format_solitaire_message(result.entity, show_closed=False),
                reply_markup=solitaire_detail_keyboard(solitaire_id, False, target_chat_id if chat.type == "private" else None),
            )
        else:
            reason_text = {
                "not_found": "接龙不存在",
                "already_closed": "接龙已结束",
                "error": "结束失败",
            }.get(result.reason, "未知错误")
            await q.edit_message_text(
                f"❌ {reason_text}",
                reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None),
            )


async def solitaire_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    if cb.length() < 3:
        return
    solitaire_id = cb.get_int(2)
    if solitaire_id == 0:
        return

    chat = update.effective_chat
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_solitaire(session, solitaire_id, chat_id=target_chat_id)
        await session.commit()

    await q.edit_message_text(
        "✅ 接龙已删除" if success else "❌ 接龙不存在",
        reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None),
    )
