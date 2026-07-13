from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.activity.solitaire_shared import _solitaire_handler
from backend.platform.db.runtime.session import Database
from backend.shared.callback_parser import CallbackParser
from backend.shared.chat_context import PrivateChatContext
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import is_user_admin


def _parse_scoped_solitaire_callback(cb: CallbackParser) -> tuple[int | None, int]:
    """Return (solitaire_id, chat_index), accepting new and legacy orders."""
    if cb.get_int_optional(2) is not None and cb.get_int(2) < 0:
        return cb.get_int_optional(3), 2
    return cb.get_int_optional(2), 3


async def solitaire_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    cb = CallbackParser.parse(q.data or "")
    legacy_target_chat_id = cb.get_int_optional(2) if cb.get(0) == "solitaire" else None
    if chat.type == "private":
        await _show_private_solitaire_menu(
            update, context, legacy_target_chat_id=legacy_target_chat_id
        )
        return

    if not await is_user_admin(context, chat.id, user.id):
        await _solitaire_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
        return

    await _solitaire_handler.show_menu(update, context, chat.id, chat_title=chat.title)


async def _show_private_solitaire_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    legacy_target_chat_id: int | None,
) -> None:
    db: Database = context.application.bot_data["db"]
    user = update.effective_user
    target_chat_id = legacy_target_chat_id or await ChatResolver.get_current_chat(db, user.id)
    if target_chat_id is None:
        await _solitaire_handler.message_helper.safe_edit(update, "请先选择一个群组")
        return
    if not await is_user_admin(context, target_chat_id, user.id):
        await _solitaire_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
        return
    await _solitaire_handler.show_menu(update, context, target_chat_id)


async def solitaire_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    page = cb.get_int(3, default=0) if update.effective_chat.type == "private" else (cb.get_int(2, default=0) if cb.get(2).isdigit() else 0)
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=2,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
    if target_chat_id is None:
        return
    await _solitaire_handler.show_list(update, context, target_chat_id, page=page)


async def solitaire_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    await update.callback_query.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=2,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
    if target_chat_id is None:
        return
    await _solitaire_handler.show_stats(update, context, target_chat_id)


async def solitaire_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    cb = CallbackParser.parse(q.data or "")
    solitaire_id, chat_index = _parse_scoped_solitaire_callback(cb)
    if solitaire_id in (None, 0):
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=chat_index,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )
    if target_chat_id is None:
        return
    await _solitaire_handler.show_detail(update, context, solitaire_id, target_chat_id)
