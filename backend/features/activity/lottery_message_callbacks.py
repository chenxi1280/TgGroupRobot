from __future__ import annotations

import structlog

from telegram import Update
from telegram.error import NetworkError
from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_service_parsing import (
    decode_draw_trigger,
    decode_lottery_type,
    decode_selection_mode,
)
from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.state_helper import StateHelper

log = structlog.get_logger(__name__)


async def lottery_create_start_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
) -> None:
    try:
        log.info("lottery_create_start_entered")
        if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
            log.warning("lottery_create_start_missing_data")
            return
        q = update.callback_query
        await q.answer()
        chat = update.effective_chat
        user = update.effective_user

        data = q.data or ""
        target_chat_id = None
        lottery_type = "common"
        selection_mode = "threshold_random"
        draw_trigger = "time_deadline"
        if data.startswith("lot:create:"):
            from backend.shared.callback_parser import CallbackParser

            cb = CallbackParser.parse(data)
            target_chat_id = cb.get_int(2)
            lottery_type = decode_lottery_type(cb.get(3, "common") or "common")
            selection_mode = decode_selection_mode(cb.get(4, "threshold_random") or "threshold_random")
            draw_trigger = decode_draw_trigger(cb.get(5, "time_deadline") or "time_deadline")
            if selection_mode == "ranking_random" and draw_trigger == "full_participants":
                draw_trigger = "time_deadline"

        if target_chat_id is None:
            if chat.type == "private":
                await handler.message_helper.safe_edit(update, "请在群里使用。")
                return
            target_chat_id = chat.id

        is_admin = await is_user_admin_fn(context, target_chat_id, user.id)
        if not is_admin:
            await handler.message_helper.safe_edit(
                update,
                f"需要管理员权限。\n\n请确保你是群组 {target_chat_id} 的管理员，且 Bot 已加入该群组。"
            )
            return

        await handler.start_create_flow(update, context, target_chat_id, lottery_type, selection_mode, draw_trigger)
        log.info("lottery_create_start_success")
    except Exception as exc:
        log.exception("lottery_create_start_error", error=str(exc))
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(f"发生错误: {str(exc)}")
            except Exception as edit_exc:
                log.warning("lottery_message_error_feedback_failed", error=str(edit_exc))


async def lottery_message_handler_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    parse_config_fn,
) -> None:
    log.info("lottery_message_handler_called")
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    text = update.effective_message.text or ""
    if not text:
        return
    try:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state = await StateHelper.get_state_by_chat(session, chat, user.id)
            if state is None or state.state_type != __import__("backend.platform.db.schema.models.enums", fromlist=["ConversationStateType"]).ConversationStateType.lottery_create.value:
                log.info("lottery_state_not_match", state_type=state.state_type if state else None)
            else:
                await parse_config_fn(update, context, session, state, text)
            log.info("lottery_handler_done")
    except NetworkError as exc:
        log.warning("lottery_message_transport_error", error=str(exc), error_type=type(exc).__name__)
        return
    except Exception as exc:
        log.exception("lottery_message_handler_error", error=str(exc), error_type=type(exc).__name__, traceback=True)
        return


async def parse_lottery_config_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, session, state: object, text: str) -> None:
    from backend.features.activity.lottery_creation import parse_lottery_config_message

    await parse_lottery_config_message(update, context, session, state, text)


async def join_lottery_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    if chat.type == "private":
        await handler.message_helper.safe_edit(update, "请在群里使用。")
        return
    data = q.data
    if not data.startswith("join_lottery_"):
        return
    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await handler.message_helper.safe_edit(update, "无效的抽奖。")
        return
    await handler.handle_join(update, context, lottery_id)


async def draw_lottery_callback_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    handler,
    is_user_admin_fn,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == "private":
        await handler.message_helper.safe_edit(update, "请在群里使用。")
        return
    if not await is_user_admin_fn(context, chat.id, user.id):
        await handler.message_helper.safe_edit(update, "需要管理员权限。")
        return
    data = q.data
    if not data.startswith("draw_lottery_"):
        return
    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await handler.message_helper.safe_edit(update, "无效的抽奖。")
        return
    await handler.handle_draw(update, context, lottery_id)


async def lottery_cancel_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler, clear_user_state_fn) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    if len(parts) < 3:
        await q.edit_message_text("❌ 无法获取群组信息")
        return
    try:
        target_chat_id = int(parts[2])
    except ValueError:
        await q.edit_message_text("❌ 群组ID格式错误")
        return
    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = user.id if chat.type == "private" else chat.id
        await clear_user_state_fn(session, state_chat_id, user.id)
        await session.commit()
    await handler.show_menu(update, context, target_chat_id)
