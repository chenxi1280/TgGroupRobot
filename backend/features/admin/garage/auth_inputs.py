from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import admin_handler_instance, clear_admin_input_state
from backend.shared.services.base import ValidationError


@dataclass(frozen=True, slots=True)
class _AuthInput:
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: object
    target_chat_id: int
    text: str


AuthInputHandler = Callable[[_AuthInput], Awaitable[None]]


async def handle_auth_feature_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state_type: str,
    target_chat_id: int,
    text_value: str,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True
    handlers: dict[str, AuthInputHandler] = {
        "garage_badge_input": _handle_badge_input,
        "garage_teacher_input": _handle_teacher_input,
        "garage_whitelist_input": _handle_whitelist_input,
        "garage_limit_interval_input": _handle_interval_input,
        "garage_limit_max_count_input": _handle_max_count_input,
    }
    handler = handlers.get(state_type)
    if handler is None:
        return False
    await handler(_AuthInput(update, context, session, target_chat_id, text_value))
    return True


async def _handle_badge_input(data: _AuthInput) -> None:
    if not data.text:
        await data.update.effective_message.reply_text("认证图标不能为空。")
        return
    service = _garage_auth_service()
    await service.update_settings(data.session, data.target_chat_id, garage_auth_badge=data.text[:16])
    await _finish_auth_input(data.update, data.context, data.session, target_chat_id=data.target_chat_id)


async def _handle_teacher_input(data: _AuthInput) -> None:
    await _handle_member_list_input(data, list_name="teacher")


async def _handle_whitelist_input(data: _AuthInput) -> None:
    await _handle_member_list_input(data, list_name="whitelist")


async def _handle_member_list_input(data: _AuthInput, *, list_name: str) -> None:
    user_id = data.update.effective_user.id
    service = _garage_auth_service()
    try:
        operation = service.add_teacher if list_name == "teacher" else service.add_whitelist
        await operation(data.session, data.target_chat_id, user_id, raw=data.text)
    except ValidationError as exc:
        await data.update.effective_message.reply_text(str(exc))
        return
    await clear_admin_input_state(data.session, target_chat_id=data.target_chat_id, user_id=user_id)
    await data.session.commit()
    admin = admin_handler_instance()
    if list_name == "teacher":
        await admin._show_garage_teacher_list_menu(data.update, data.context, data.target_chat_id, page=0)
        return
    await admin._show_garage_whitelist_menu(data.update, data.context, data.target_chat_id, page=0)


async def _handle_interval_input(data: _AuthInput) -> None:
    await _handle_limit_input(data, field_name="garage_limit_interval_sec")


async def _handle_max_count_input(data: _AuthInput) -> None:
    await _handle_limit_input(data, field_name="garage_limit_max_count")


async def _handle_limit_input(data: _AuthInput, *, field_name: str) -> None:
    if not re.fullmatch(r"\d+", data.text):
        await data.update.effective_message.reply_text("请输入正整数。")
        return
    await _garage_auth_service().update_settings(
        data.session,
        data.target_chat_id,
        **{field_name: int(data.text)},
    )
    await _finish_auth_input(data.update, data.context, data.session, target_chat_id=data.target_chat_id)


def _garage_auth_service():
    from backend.features.garage.services.garage_features_service import GarageAuthService

    return GarageAuthService


async def _finish_auth_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, target_chat_id: int,
) -> None:
    if update.effective_user is None:
        return
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await admin_handler_instance()._show_garage_auth_menu(update, context, target_chat_id)
