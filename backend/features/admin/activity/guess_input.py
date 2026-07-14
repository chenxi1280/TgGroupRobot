from __future__ import annotations

import re
from dataclasses import dataclass

from backend.features.activity.services.guess_service import (
    parse_deadline as parse_guess_deadline,
    parse_options as parse_guess_options,
    parse_ratio as parse_guess_ratio,
    resolve_user_id as resolve_guess_user_id,
    update_setting as update_guess_setting,
)
from backend.features.admin.activity.runtime import (
    admin_handler_instance,
    clear_private_admin_state,
)
from backend.platform.state.state_service import clear_user_state, set_user_state
from backend.shared.services.base import ValidationError


@dataclass(frozen=True)
class _GuessInput:
    update: object
    session: object
    state_type: str
    value: str
    draft: dict
    target_chat_id: int
    user_id: int


async def _finish_guess_setting(flow: _GuessInput, context) -> None:
    await clear_user_state(flow.session, chat_id=flow.user_id, user_id=flow.user_id)
    await flow.session.commit()
    await admin_handler_instance()._show_guess_settings(
        flow.update, context, flow.target_chat_id
    )


async def _handle_guess_setting_input(flow: _GuessInput, context) -> bool:
    if flow.state_type not in {"guess_wait_rake_ratio", "guess_wait_rake_owner"}:
        return False
    try:
        updates: dict[str, str | int | None]
        if flow.state_type == "guess_wait_rake_ratio":
            updates = {"rake_ratio": parse_guess_ratio(flow.value)}
        else:
            owner_id = await resolve_guess_user_id(flow.session, flow.value)
            updates = {"rake_owner_user_id": owner_id}
        await update_guess_setting(flow.session, flow.target_chat_id, **updates)
    except ValidationError as exc:
        await flow.update.effective_message.reply_text(str(exc))
        return True
    await _finish_guess_setting(flow, context)
    return True


async def _guess_title_value(flow: _GuessInput):
    if not flow.value:
        await flow.update.effective_message.reply_text("活动名字不能为空。")
        return None
    return {**flow.draft, "title": flow.value[:128]}


async def _guess_cover_value(flow: _GuessInput):
    message = flow.update.effective_message
    if flow.value == "清空":
        file_id = None
    elif getattr(message, "photo", None):
        file_id = message.photo[-1].file_id
    elif _is_image_document(getattr(message, "document", None)):
        file_id = message.document.file_id
    else:
        await message.reply_text("请发送图片，或发送“清空”。")
        return None
    return {**flow.draft, "cover_file_id": file_id}


async def _guess_banker_value(flow: _GuessInput):
    banker_id = await resolve_guess_user_id(flow.session, flow.value)
    return {
        **flow.draft,
        "banker_user_id": banker_id,
        "mode": "banker" if banker_id else "no_banker",
    }


async def _guess_pool_value(flow: _GuessInput):
    if not re.fullmatch(r"\d+", flow.value):
        await flow.update.effective_message.reply_text("公共奖池必须是非负整数。")
        return None
    return {**flow.draft, "public_pool": int(flow.value)}


async def _guess_command_value(flow: _GuessInput):
    if not flow.value:
        await flow.update.effective_message.reply_text("群内指令不能为空。")
        return None
    return {**flow.draft, "command_keyword": flow.value[:32]}


async def _guess_description_value(flow: _GuessInput):
    return {**flow.draft, "description": flow.value}


async def _guess_options_value(flow: _GuessInput):
    return {**flow.draft, "options": parse_guess_options(flow.value)}


async def _guess_deadline_value(flow: _GuessInput):
    deadline = parse_guess_deadline(flow.value, allow_iso=False).isoformat()
    return {**flow.draft, "deadline_at": deadline}


async def _apply_guess_draft_input(flow: _GuessInput):
    handlers = {
        "guess_wait_title": _guess_title_value,
        "guess_wait_cover": _guess_cover_value,
        "guess_wait_description": _guess_description_value,
        "guess_wait_banker": _guess_banker_value,
        "guess_wait_pool": _guess_pool_value,
        "guess_wait_options": _guess_options_value,
        "guess_wait_command": _guess_command_value,
        "guess_wait_deadline": _guess_deadline_value,
    }
    handler = handlers.get(flow.state_type)
    if handler is None:
        await flow.update.effective_message.reply_text(
            "当前竞猜配置状态不支持该输入，请重新进入配置页面。"
        )
        return None
    try:
        return await handler(flow)
    except ValidationError as exc:
        await flow.update.effective_message.reply_text(str(exc))
        return None


async def _save_guess_draft(flow: _GuessInput, context, draft: dict) -> None:
    await clear_private_admin_state(
        flow.session, target_chat_id=flow.target_chat_id, user_id=flow.user_id
    )
    await set_user_state(
        flow.session,
        chat_id=flow.user_id,
        user_id=flow.user_id,
        state_type="guess_wait_title",
        state_data=draft,
    )
    await flow.session.commit()
    await admin_handler_instance()._show_guess_create_menu(
        flow.update, context, flow.target_chat_id, draft=draft
    )


async def handle_guess_admin_input(
    update,
    context,
    session,
    *,
    state,
    message_text: str,
    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    state_type = str(state.state_type)
    if not state_type.startswith("guess_"):
        return False
    user_id = update.effective_user.id
    flow = _GuessInput(
        update=update,
        session=session,
        state_type=state_type,
        value=message_text.strip(),
        draft=dict(state.state_data or {}),
        target_chat_id=target_chat_id,
        user_id=user_id,
    )
    if await _handle_guess_setting_input(flow, context):
        return True
    draft = await _apply_guess_draft_input(flow)
    if draft is None:
        return True
    await _save_guess_draft(flow, context, draft)
    return True


def _is_image_document(document) -> bool:
    if document is None:
        return False
    mime_type = str(getattr(document, "mime_type", "") or "")
    return mime_type.startswith("image/")
