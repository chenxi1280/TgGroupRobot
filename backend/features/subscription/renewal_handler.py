from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.subscription.ui.renewal import renewal_entry_keyboard
from backend.features.subscription.services.renewal_service import (
    format_renewal_entry_text,
    get_renewal_snapshot,
    redeem_renewal_card,
)
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.command_config_service import ensure_command_enabled
from backend.features.group_ops.services.chat_group_service import get_user_current_chat
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.callback_parser import CallbackParser
from backend.platform.config.core.settings import get_settings
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
    mark_callback_query_answered,
)
import structlog

log = structlog.get_logger(__name__)


async def _show_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
) -> None:
    if update.effective_user is None:
        return

    app_settings = context.application.bot_data.get("settings") or get_settings()
    db = context.application.bot_data.get("db")
    if db is None:
        return

    async with db.session_factory() as session:
        snapshot = await get_renewal_snapshot(session, chat_id)
        await session.commit()

    keyboard = renewal_entry_keyboard(
        chat_id,
        contact_username=getattr(app_settings, "renew_contact_username", None),
        contact_url=getattr(app_settings, "renewal_contact_url", None),
        contact_label=getattr(app_settings, "renewal_contact_label", "一键联系"),
    )
    text = format_renewal_entry_text(snapshot, getattr(app_settings, "renew_contact_username", None))

    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text=text, reply_markup=keyboard)


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
        await ConversationStateService.start(
            session,
            chat_id,
            update.effective_user.id,
            ConversationStateType.renewal_card_input.value,
            {"target_chat_id": chat_id},
        )
        await session.commit()

    text = "请发送续费卡密。\n\n发送后系统会立即核销，并绑定当前群组。"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"renew:back:{chat_id}")]])
    if update.callback_query is not None:
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    elif update.effective_message is not None:
        await update.effective_message.reply_text(text=text, reply_markup=keyboard)


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
            await update.effective_message.reply_text("续费入口暂时不可用，请稍后再试。")


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
        await answer_callback_query_safely(update, "请联系服务商获取续费卡密", show_alert=True)
        return

    if action == "input":
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        await start_renewal_card_input(update, context, chat_id)
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
        await answer_callback_query_safely(update, "续费入口暂时不可用，请稍后再试", show_alert=True)


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
    result = await redeem_renewal_card(
        session,
        chat_id=target_chat_id,
        operator_user_id=update.effective_user.id,
        card_code=message_text,
    )
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    if hasattr(session, "commit"):
        await session.commit()
    await update.effective_message.reply_text(result.message)
    await _show_menu(update, context, chat_id=target_chat_id)


async def renewal_code_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    await handle_renewal_card_input(update, context, session, state, message_text)
