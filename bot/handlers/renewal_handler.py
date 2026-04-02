from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import get_settings
from bot.db.session import Database
from bot.keyboards.integration.renewal import renewal_entry_keyboard
from bot.models.enums import ConversationStateType
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.integration.chat_group_service import get_user_current_chat
from bot.services.integration.renewal_service import (
    format_renewal_entry_text,
    get_renewal_snapshot,
    mask_card_code,
    redeem_renewal_card,
)
from bot.services.state.conversation_state_service import ConversationStateService
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import (
    answer_callback_query_safely,
    build_public_error_text,
    mark_callback_query_answered,
)

log = structlog.get_logger(__name__)


def _resolve_contact_url(settings) -> str | None:
    direct_url = (getattr(settings, "renewal_contact_url", None) or "").strip()
    if direct_url:
        return direct_url

    username = (getattr(settings, "renew_contact_username", None) or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}"
    return None


def _resolve_contact_label(settings) -> str:
    label = (getattr(settings, "renewal_contact_label", None) or "").strip()
    if label:
        return label
    label = (getattr(settings, "renew_contact_label", None) or "").strip()
    return label or "一键联系"


async def _show_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
) -> None:
    if update.effective_user is None:
        return

    db: Database = context.application.bot_data["db"]
    settings = context.application.bot_data.get("settings") or get_settings()

    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
            session,
            chat_id=chat_id,
            chat_type="supergroup" if chat_id < 0 else "private",
            user_id=update.effective_user.id,
        )
        snapshot = await get_renewal_snapshot(session, chat_id)

    text = format_renewal_entry_text(
        snapshot,
        contact_username=getattr(settings, "renew_contact_username", None),
    )
    keyboard = renewal_entry_keyboard(
        chat_id,
        contact_username=getattr(settings, "renew_contact_username", None),
        contact_url=_resolve_contact_url(settings),
        contact_label=_resolve_contact_label(settings),
    )

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

    db: Database = context.application.bot_data["db"]
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
            chat_id=chat_id,
            user_id=update.effective_user.id,
            state_type=ConversationStateType.renewal_card_input.value,
            state_data={"target_chat_id": chat_id},
        )
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
        target_chat_id = update.effective_chat.id

    try:
        await _show_menu(update, context, chat_id=target_chat_id)
    except Exception as exc:
        log.exception("renew_command_failed", chat_id=target_chat_id, error=str(exc))
        if update.effective_message is not None:
            await update.effective_message.reply_text(f"❌ {build_public_error_text(exc)}")


async def renew_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return

    cb = CallbackParser.parse(update.callback_query.data or "")
    action = cb.get(1) or "menu"
    chat_id = cb.get_int_optional(2)
    if chat_id is None or chat_id == 0:
        await answer_callback_query_safely(update, "无效群组", show_alert=True)
        return

    settings = context.application.bot_data.get("settings") or get_settings()

    if action == "contact":
        if _resolve_contact_url(settings):
            await update.callback_query.answer()
            mark_callback_query_answered(update)
            return
        await answer_callback_query_safely(update, "未配置联系入口", show_alert=True)
        return

    if action == "input":
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        try:
            await start_renewal_card_input(update, context, chat_id)
        except Exception as exc:
            log.exception("renew_input_failed", chat_id=chat_id, error=str(exc))
            await answer_callback_query_safely(update, build_public_error_text(exc), show_alert=True)
        return

    if action == "back":
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await ConversationStateService.clear(session, chat_id, update.effective_user.id)
            await session.commit()
        await update.callback_query.answer()
        mark_callback_query_answered(update)
        from bot.handlers.admin_handler import _admin_handler

        await _admin_handler._show_main_menu(update, context, chat_id)
        return

    await update.callback_query.answer()
    mark_callback_query_answered(update)
    try:
        await _show_menu(update, context, chat_id=chat_id)
    except Exception as exc:
        log.exception("renew_menu_failed", chat_id=chat_id, error=str(exc))
        await answer_callback_query_safely(update, build_public_error_text(exc), show_alert=True)


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

    card_code = (message_text or "").strip()
    if not card_code:
        if hasattr(session, "commit"):
            await session.commit()
        await update.effective_message.reply_text("❌ 卡密不能为空")
        return

    masked = mask_card_code(card_code)
    log.info(
        "renewal_card_received",
        user_id=update.effective_user.id,
        chat_id=target_chat_id,
        masked_card=masked,
    )
    try:
        result = await redeem_renewal_card(
            session,
            chat_id=target_chat_id,
            operator_user_id=update.effective_user.id,
            card_code=card_code,
        )
        if hasattr(session, "commit"):
            await session.commit()
    except Exception as exc:
        if hasattr(session, "rollback"):
            await session.rollback()
        log.exception("renewal_card_redeem_failed", chat_id=target_chat_id, error=str(exc))
        await update.effective_message.reply_text(f"❌ {build_public_error_text(exc)}")
        await _show_menu(update, context, chat_id=target_chat_id)
        return

    prefix = "✅" if result.success else "❌"
    await update.effective_message.reply_text(f"{prefix} {result.message}")
    if not result.success:
        await _show_menu(update, context, chat_id=target_chat_id)
        return
    await ConversationStateService.clear(session, target_chat_id, update.effective_user.id)
    if hasattr(session, "commit"):
        await session.commit()
    await _show_menu(update, context, chat_id=target_chat_id)


async def renewal_code_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    await handle_renewal_card_input(update, context, session, state, message_text)
