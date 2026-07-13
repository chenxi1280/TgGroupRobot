from __future__ import annotations

import structlog
from dataclasses import dataclass

from telegram import Update
from telegram.error import NetworkError
from telegram.ext import ContextTypes

from backend.features.activity.services.lottery_service_parsing import (
    decode_draw_trigger,
    decode_lottery_type,
    decode_selection_mode,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.command_config_service import is_group_text_command_enabled
from backend.shared.handlers.base.state_helper import StateHelper
_LOTTERY_CANCEL_CALLBACK_IMPL_THRESHOLD_3 = 3


log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _CreateOptions:
    target_chat_id: int | None = None
    lottery_type: str = "common"
    selection_mode: str = "threshold_random"
    draw_trigger: str = "time_deadline"


def _parse_create_options(data: str) -> _CreateOptions:
    if not data.startswith("lot:create:"):
        return _CreateOptions()
    from backend.shared.callback_parser import CallbackParser

    callback = CallbackParser.parse(data)
    selection_mode = decode_selection_mode(callback.get(4, "threshold_random") or "threshold_random")
    draw_trigger = decode_draw_trigger(callback.get(5, "time_deadline") or "time_deadline")
    if selection_mode == "ranking_random" and draw_trigger == "full_participants":
        draw_trigger = "time_deadline"
    return _CreateOptions(
        target_chat_id=callback.get_int(2),
        lottery_type=decode_lottery_type(callback.get(3, "common") or "common"),
        selection_mode=selection_mode,
        draw_trigger=draw_trigger,
    )


async def _report_create_error(update: Update, exc: Exception) -> None:
    log.exception("lottery_create_start_error", error=str(exc))
    if update.callback_query is None:
        return
    try:
        await update.callback_query.edit_message_text(f"发生错误: {exc}")
    except Exception as edit_exc:
        log.warning("lottery_message_error_feedback_failed", error=str(edit_exc))


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

        options = _parse_create_options(q.data or "")
        target_chat_id = options.target_chat_id

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

        await handler.start_create_flow(
            update,
            context,
            target_chat_id,
            lottery_type=options.lottery_type,
            selection_mode=options.selection_mode,
            draw_trigger=options.draw_trigger,
        )
        log.info("lottery_create_start_success")
    except Exception as exc:
        await _report_create_error(update, exc)


async def lottery_message_handler_impl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    parse_config_fn,
) -> None:
    log.info("lottery_message_handler_called")
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    user = update.effective_user
    text = update.effective_message.text or ""
    if not text:
        return
    try:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await _dispatch_lottery_message(
                update,
                context,
                session,
                user_id=user.id,
                text=text,
                parse_config_fn=parse_config_fn,
            )
            log.info("lottery_handler_done")
    except NetworkError as exc:
        log.warning("lottery_message_transport_error", error=str(exc), error_type=type(exc).__name__)
        return
    except Exception as exc:
        log.exception("lottery_message_handler_error", error=str(exc), error_type=type(exc).__name__, traceback=True)
        return


async def _dispatch_lottery_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *,
    user_id: int,
    text: str,
    parse_config_fn,
) -> None:
    state = await StateHelper.get_state_by_chat(session, update.effective_chat, user_id)
    if state is None or state.state_type != ConversationStateType.lottery_create.value:
        log.info("lottery_state_not_match", state_type=state.state_type if state else None)
        return
    await parse_config_fn(update, context, session, state, text)


async def parse_lottery_config_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, session, *, state: object, text: str) -> None:
    from backend.features.activity.lottery_creation import parse_lottery_config_message

    await parse_lottery_config_message(update, context, session, state=state, text=text)


async def join_lottery_callback_impl(update: Update, context: ContextTypes.DEFAULT_TYPE, *, handler) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    chat = update.effective_chat
    if chat.type == "private":
        await q.answer()
        await handler.message_helper.safe_edit(update, "请在群里使用。")
        return
    data = q.data
    if not data.startswith("join_lottery_"):
        return
    try:
        lottery_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await q.answer()
        await handler.message_helper.safe_edit(update, "无效的抽奖。")
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if not await is_group_text_command_enabled(session, chat.id, "lottery"):
            await session.commit()
            await q.answer("抽奖入口已关闭。", show_alert=True)
            return
        await session.commit()
    await q.answer()
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
    if len(parts) < _LOTTERY_CANCEL_CALLBACK_IMPL_THRESHOLD_3:
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
