from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_admin_callbacks import (
    admin_verify_callback_impl,
    verification_timeout_help_callback_impl,
)
from backend.features.verification.verification_admin_config import (
    parse_verification_config_impl,
    verification_cancel_callback_impl,
    verification_config_handler_impl,
)
from backend.features.verification.verification_admin_unmute import try_admin_manual_unmute_impl


async def try_admin_manual_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE, *, extract_target_user_id, t, extract_target_name_token=None) -> bool:
    return await try_admin_manual_unmute_impl(
        update,
        context,
        extract_target_user_id=extract_target_user_id,
        extract_target_name_token=extract_target_name_token,
    )


async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_verify_callback_impl(update, context)


async def verification_timeout_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await verification_timeout_help_callback_impl(update, context)


async def verification_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await verification_config_handler_impl(update, context)


async def parse_verification_config(update: Update, session, state, *, text: str) -> None:
    await parse_verification_config_impl(update, session, state, text=text)


async def verification_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await verification_cancel_callback_impl(update, context, reopen_menu=admin_verification_menu_callback)


async def admin_verification_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
    from backend.features.admin.admin_handler import AdminHandler

    handler = AdminHandler()
    await handler._show_verification_menu(update, context, target_chat_id)
