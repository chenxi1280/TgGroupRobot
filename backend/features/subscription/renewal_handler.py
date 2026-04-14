from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.subscription.ui.renewal import renewal_entry_keyboard
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.features.group_ops.services.chat_group_service import get_user_current_chat
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
    mark_callback_query_answered,
)
import structlog

log = structlog.get_logger(__name__)


OPEN_ACCESS_TEXT = "\n".join(
    [
        "🔓 功能开放说明",
        "",
        "当前版本已暂时关闭付费/续费逻辑。",
        "所有群组功能默认开放，无需购买套餐或输入卡密。",
        "",
        "请从主菜单继续配置功能。",
    ]
)


async def _show_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
) -> None:
    if update.effective_user is None:
        return

    keyboard = renewal_entry_keyboard(chat_id)

    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text=OPEN_ACCESS_TEXT, reply_markup=keyboard)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text=OPEN_ACCESS_TEXT, reply_markup=keyboard)


async def show_renewal_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    await _show_menu(update, context, chat_id=chat_id)


async def start_renewal_card_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    if update.effective_user is None:
        return

    db = context.application.bot_data.get("db")
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        await ConversationStateService.clear(session, chat_id, update.effective_user.id)
        await session.commit()

    await _show_menu(update, context, chat_id=chat_id)


async def renew_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None:
        return

    db: Database = context.application.bot_data["db"]

    if update.effective_chat.type == "private":
        target_chat_id = await get_user_current_chat(db, update.effective_user.id)
        if target_chat_id is None:
            if update.effective_message is not None:
                await update.effective_message.reply_text("请先在私聊中选择要管理的群组。")
            return
    else:
        if update.effective_message is not None:
            allowed = await ensure_command_enabled(context, update, command_key="renew")
            if not allowed:
                return
        target_chat_id = update.effective_chat.id

    try:
        await _show_menu(update, context, chat_id=target_chat_id)
    except Exception as exc:
        log.exception("renew_command_failed", chat_id=target_chat_id, error=str(exc))
        if update.effective_message is not None:
            await update.effective_message.reply_text("付费逻辑已关闭，所有功能默认开放。")


async def renew_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    cb = CallbackParser.parse(update.callback_query.data or "")
    action = cb.get(1) or "menu"
    chat_id = cb.get_int_optional(2)
    if chat_id is None or chat_id == 0:
        await answer_callback_query_safely(update, "无效群组", show_alert=True)
        return

    if action == "contact":
        await answer_callback_query_safely(update, "付费逻辑已关闭，所有功能默认开放", show_alert=True)
        return

    if action == "input":
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        await _show_menu(update, context, chat_id=chat_id)
        return

    if action == "back":
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ConversationStateService.clear(session, chat_id, update.effective_user.id)
            await session.commit()
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        from backend.features.admin.admin_handler import _admin_handler

        await _admin_handler._show_main_menu(update, context, chat_id)
        return

    await update.callback_query.answer()
    mark_callback_query_answered(update)
    try:
        await _show_menu(update, context, chat_id=chat_id)
    except Exception as exc:
        log.exception("renew_menu_failed", chat_id=chat_id, error=str(exc))
        await answer_callback_query_safely(update, "付费逻辑已关闭，所有功能默认开放", show_alert=True)


async def handle_renewal_card_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id) if state.state_data else state.chat_id
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    if hasattr(session, "commit"):
        await session.commit()
    await update.effective_message.reply_text("付费逻辑已关闭，所有功能默认开放，无需输入卡密。")
    await _show_menu(update, context, chat_id=target_chat_id)


async def renewal_code_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    await handle_renewal_card_input(update, context, session, state, message_text)
