from __future__ import annotations

from backend.features.admin.callback_flow import (
    admin_callback_impl,
    group_admin_callback_impl,
    private_admin_callback_impl,
)
from backend.features.admin.command_flow import admin_command_impl, show_private_admin_menu_impl
from backend.features.admin.runtime import admin_runtime
from backend.features.admin.support import *


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_command_impl(update, context)


async def _show_private_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    await show_private_admin_menu_impl(update, context, chat_id)


async def private_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await private_admin_callback_impl(update, context)


async def group_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await group_admin_callback_impl(update, context)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await admin_callback_impl(update, context)
