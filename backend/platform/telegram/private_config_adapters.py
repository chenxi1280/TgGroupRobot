"""Private config state adapter functions."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from importlib import import_module
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.ui.button_input import is_clear_button_input

ConfigHandler = Callable[
    [Update, ContextTypes.DEFAULT_TYPE, AsyncSession, Any, str],
    Awaitable[None],
]


@lru_cache(maxsize=None)
def _resolve_attr(module_path: str, attr_name: str):
    return getattr(import_module(module_path), attr_name)


def update_context_handler(module_path: str, func_name: str) -> ConfigHandler:
    async def handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        del session, state, message_text
        func = _resolve_attr(module_path, func_name)
        await func(update, context)

    return handler


def full_args_handler(module_path: str, func_name: str) -> ConfigHandler:
    async def handler(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state: Any,
        message_text: str,
    ) -> None:
        func = _resolve_attr(module_path, func_name)
        await func(update, context, session, state, message_text)

    return handler


async def handle_invite_link_config(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    invite_link_create_name_message = _resolve_attr(
        "backend.features.invite.invite_link_handler",
        "invite_link_create_name_message",
    )
    handle_invite_link_config_input = _resolve_attr(
        "backend.features.invite.invite_link_handler",
        "handle_invite_link_config_input",
    )

    if state.state_type == "invite_link_create":
        await invite_link_create_name_message(update, context)
        return

    await handle_invite_link_config_input(update, context, session, state, message_text)


async def handle_quick_publish_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    parse_buttons_text = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_parse_buttons_text",
    )
    ValidationError = _resolve_attr("backend.shared.services.base", "ValidationError")
    admin_handler = import_module("backend.features.admin.admin_handler")

    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    field = state.state_data.get("field")

    drafts = context.user_data.setdefault("quick_publish_draft", {})
    draft = drafts.setdefault(
        str(target_chat_id),
        {"text": "", "media_type": None, "media_file_id": None, "buttons": []},
    )

    text_value = (message_text or "").strip()

    if field == "text":
        if not text_value:
            await update.effective_message.reply_text("文本不能为空。")
            return
        draft["text"] = text_value
    elif field == "media":
        if is_clear_button_input(text_value):
            draft["media_type"] = None
            draft["media_file_id"] = None
        else:
            msg = update.effective_message
            if msg.photo:
                draft["media_type"] = "photo"
                draft["media_file_id"] = msg.photo[-1].file_id
            elif msg.video:
                draft["media_type"] = "video"
                draft["media_file_id"] = msg.video.file_id
            elif msg.document:
                draft["media_type"] = "document"
                draft["media_file_id"] = msg.document.file_id
            elif msg.animation:
                draft["media_type"] = "animation"
                draft["media_file_id"] = msg.animation.file_id
            else:
                await update.effective_message.reply_text("请发送图片/视频/文件作为媒体内容。")
                return
            if text_value:
                draft["text"] = text_value
    elif field == "buttons":
        if is_clear_button_input(text_value):
            draft["buttons"] = []
        else:
            try:
                buttons = parse_buttons_text(text_value)
            except ValidationError as exc:
                await update.effective_message.reply_text(str(exc))
                return
            draft["buttons"] = buttons
    else:
        await update.effective_message.reply_text("快捷发布状态异常，请重新进入。")
        return

    state_service = import_module("backend.platform.state.state_service")
    await state_service.clear_user_state(session, chat_id=state.chat_id, user_id=update.effective_user.id)
    await state_service.clear_user_state(
        session,
        chat_id=update.effective_user.id,
        user_id=update.effective_user.id,
    )
    await session.commit()
    await admin_handler._admin_handler._show_quick_publish_menu(update, context, target_chat_id)


async def scheduled_message_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del session
    if update.effective_user is None:
        return

    scheduled_message_handler = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_scheduled_message_handler",
    )
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    await scheduled_message_handler.handle_fsm_input(
        update,
        context,
        target_chat_id,
        update.effective_user.id,
        message_text,
    )


async def scheduled_message_media_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del session, message_text
    if update.effective_user is None:
        return

    scheduled_message_handler = _resolve_attr(
        "backend.features.automation.scheduled_message_handler",
        "_scheduled_message_handler",
    )
    target_chat_id = state.state_data.get("target_chat_id", state.chat_id)
    await scheduled_message_handler.handle_media_input(
        update,
        context,
        target_chat_id,
        update.effective_user.id,
    )


async def nearby_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    nearby_handler = _resolve_attr("backend.features.nearby.nearby_handler", "_nearby_handler")
    await nearby_handler.handle_fsm_text_input(update, context, session, state, message_text)


async def nearby_location_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    state: Any,
    message_text: str,
) -> None:
    del message_text
    nearby_handler = _resolve_attr("backend.features.nearby.nearby_handler", "_nearby_handler")
    await nearby_handler.handle_fsm_location_input(update, context, session, state)
