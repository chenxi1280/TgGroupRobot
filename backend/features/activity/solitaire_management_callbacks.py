from __future__ import annotations

import datetime as dt

import structlog
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

log = structlog.get_logger(__name__)


def _parse_scoped_solitaire_callback(cb: CallbackParser) -> tuple[int | None, int]:
    """Return (solitaire_id, chat_index), accepting new and legacy orders."""
    if cb.get_int_optional(2) is not None and cb.get_int(2) < 0:
        return cb.get_int_optional(3), 2
    return cb.get_int_optional(2), 3


async def _resolve_solitaire_callback_scope(update, context):
    q = update.callback_query
    await q.answer()
    solitaire_id, chat_index = _parse_scoped_solitaire_callback(CallbackParser.parse(q.data or ""))
    if solitaire_id in (None, 0):
        return None
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
    if target_chat_id is None:
        return None
    return q, solitaire_id, target_chat_id


def _is_expired(solitaire) -> bool:
    return bool(
        solitaire.deadline
        and solitaire.status == SolitaireStatus.active.value
        and dt.datetime.now(dt.timezone.utc) > solitaire.deadline
    )


async def _close_expired_solitaire(context, session, solitaire, *, solitaire_id: int, target_chat_id: int):
    if not _is_expired(solitaire):
        return solitaire
    close_result = await close_solitaire(session, solitaire_id, chat_id=target_chat_id)
    if not close_result.success:
        return solitaire
    closed = close_result.entity
    try:
        await context.bot.send_message(
            chat_id=closed.chat_id,
            text=f"⏰ 接龙已截止\n\n{closed.title}\n参与人数: {len(closed.entries_rel)} 人",
        )
    except Exception as exc:
        log.warning("solitaire_deadline_notice_failed", chat_id=closed.chat_id, solitaire_id=closed.id, error=str(exc))
    return closed


async def _edit_refresh_message(q, text: str, reply_markup) -> None:
    try:
        await q.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def solitaire_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    scope = await _resolve_solitaire_callback_scope(update, context)
    if scope is None:
        return
    q, solitaire_id, target_chat_id = scope

    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solitaire = await get_solitaire_in_chat(session, target_chat_id, solitaire_id)
        if not solitaire:
            await session.commit()
            await q.edit_message_text("接龙不存在", reply_markup=solitaire_menu_keyboard(target_chat_id if chat.type == "private" else None))
            return

        solitaire = await _close_expired_solitaire(
            context,
            session,
            solitaire,
            solitaire_id=solitaire_id,
            target_chat_id=target_chat_id,
        )
        text = format_solitaire_message(solitaire, show_closed=False)
        is_active = solitaire.status == SolitaireStatus.active.value
        await session.commit()

    markup = solitaire_detail_keyboard(solitaire_id, is_active, target_chat_id if chat.type == "private" else None)
    await _edit_refresh_message(q, text, markup)


async def _send_close_group_updates(context, entity, entries_count: int) -> None:
    try:
        await context.bot.send_message(
            chat_id=entity.chat_id,
            text=f"🔴 接龙已结束\n\n{entity.title}\n参与人数: {entries_count} 人",
        )
    except Exception as exc:
        log.warning("solitaire_close_notice_failed", chat_id=entity.chat_id, solitaire_id=entity.id, error=str(exc))
    if not entity.message_id:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=entity.chat_id,
            message_id=entity.message_id,
            text=format_solitaire_message(entity, show_closed=False),
        )
    except Exception as exc:
        log.warning(
            "solitaire_close_message_edit_failed",
            chat_id=entity.chat_id,
            solitaire_id=entity.id,
            message_id=entity.message_id,
            error=str(exc),
        )


async def _send_close_dm(context, user_id: int, entity) -> None:
    try:
        await context.bot.send_message(chat_id=user_id, text=format_solitaire_message(entity, show_closed=False))
    except Exception as exc:
        log.warning("solitaire_dm_summary_failed", user_id=user_id, solitaire_id=entity.id, error=str(exc))


async def _show_close_result(q, result, *, solitaire_id: int, target_chat_id: int, is_private: bool) -> None:
    if not result.success:
        reason_text = {"not_found": "接龙不存在", "already_closed": "接龙已结束", "error": "结束失败"}.get(
            result.reason,
            "未知错误",
        )
        await q.edit_message_text(
            f"❌ {reason_text}",
            reply_markup=solitaire_menu_keyboard(target_chat_id if is_private else None),
        )
        return
    await q.edit_message_text(
        format_solitaire_message(result.entity, show_closed=False),
        reply_markup=solitaire_detail_keyboard(solitaire_id, False, target_chat_id if is_private else None),
    )


async def solitaire_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    scope = await _resolve_solitaire_callback_scope(update, context)
    if scope is None:
        return
    q, solitaire_id, target_chat_id = scope

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await close_solitaire(session, solitaire_id, chat_id=target_chat_id)
        if result.success:
            entries_count = len(result.entity.entries_rel)
            await session.commit()
            await _send_close_group_updates(context, result.entity, entries_count)
            await _send_close_dm(context, user.id, result.entity)
        await _show_close_result(
            q,
            result,
            solitaire_id=solitaire_id,
            target_chat_id=target_chat_id,
            is_private=chat.type == "private",
        )


async def solitaire_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    solitaire_id, chat_index = _parse_scoped_solitaire_callback(cb)
    if solitaire_id in (None, 0):
        return

    chat = update.effective_chat
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
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
