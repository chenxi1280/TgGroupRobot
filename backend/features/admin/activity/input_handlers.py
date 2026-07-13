from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.activity.bottom_button_input import handle_bottom_button_admin_input
from backend.features.admin.activity.engagement_input import handle_engagement_admin_input
from backend.features.admin.activity.game_input import handle_game_admin_input
from backend.features.admin.activity.guess_input import handle_guess_admin_input


async def handle_bottom_button_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("底部按钮状态异常，请重新进入页面。")
        return

    if not await handle_bottom_button_admin_input(
        update,
        context,
        session,
        state=state,
        message_text=message_text,
        target_chat_id=target_chat_id,
    ):
        await update.effective_message.reply_text("当前底部按钮配置状态不支持该输入，请重新进入配置页面。")


async def handle_game_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("游戏配置状态异常，请重新进入页面。")
        return

    if not await handle_game_admin_input(
        update,
        context,
        session,
        state=state,
        message_text=message_text,
        target_chat_id=target_chat_id,
    ):
        await update.effective_message.reply_text("当前游戏配置状态不支持该输入，请重新进入配置页面。")


async def handle_guess_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    from backend.platform.state.state_service import clear_user_state, set_user_state

    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("竞猜配置状态异常，请重新进入页面。")
        return

    if not await handle_guess_admin_input(
        update,
        context,
        session,
        state=state,
        message_text=message_text,
        target_chat_id=target_chat_id,
    ):
        await update.effective_message.reply_text("当前竞猜配置状态不支持该输入，请重新进入配置页面。")


async def handle_engagement_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    if not isinstance(target_chat_id, int):
        await update.effective_message.reply_text("促活工具配置状态异常，请重新进入页面。")
        return

    if not await handle_engagement_admin_input(
        update,
        context,
        session,
        state=state,
        message_text=message_text,
        target_chat_id=target_chat_id,
    ):
        await update.effective_message.reply_text("当前促活工具配置状态不支持该输入，请重新进入配置页面。")
