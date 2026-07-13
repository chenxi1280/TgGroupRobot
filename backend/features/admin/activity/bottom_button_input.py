from __future__ import annotations

from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.features.group_ops.services.bottom_button_service import (
    generate_buttons as generate_bottom_buttons,
    get_or_create_setting as get_bottom_button_setting,
    update_layout_button,
    update_setting as update_bottom_button_setting,
)
from backend.shared.services.base import ValidationError


async def _refresh_bottom_buttons(context, session, *, target_chat_id: int) -> None:
    setting = await get_bottom_button_setting(session, target_chat_id)
    if setting.enabled:
        await generate_bottom_buttons(context, session, target_chat_id)


async def _finish_bottom_button_input(
    update, context, session, *, target_chat_id: int, user_id: int,
    detail_layout_id: int | None = None,
) -> None:
    await clear_private_admin_state(
        session, target_chat_id=target_chat_id, user_id=user_id
    )
    await session.commit()
    handler = admin_handler_instance()
    if detail_layout_id is None:
        await handler._show_bottom_button_menu(update, context, target_chat_id)
        return
    await handler._show_bottom_button_detail(
        update, context, target_chat_id, layout_id=detail_layout_id
    )


async def _handle_bottom_button_header(
    update, context, session, *, target_chat_id: int, user_id: int, text_value: str
) -> None:
    if not text_value:
        await update.effective_message.reply_text("文本内容不能为空。")
        return
    await update_bottom_button_setting(
        session, target_chat_id, header_text=text_value
    )
    await _refresh_bottom_buttons(context, session, target_chat_id=target_chat_id)
    await _finish_bottom_button_input(
        update, context, session, target_chat_id=target_chat_id, user_id=user_id
    )


async def _handle_bottom_button_layout(
    update, context, session, *, state, target_chat_id: int,
    user_id: int, text_value: str,
) -> None:
    layout_id = state.state_data.get("layout_id")
    if not isinstance(layout_id, int):
        await clear_private_admin_state(
            session, target_chat_id=target_chat_id, user_id=user_id
        )
        await session.commit()
        await update.effective_message.reply_text("按钮状态异常，请重新进入页面。")
        return
    changes = (
        {"button_text": text_value}
        if str(state.state_type) == "bottom_button_button_text_input"
        else {"payload_text": text_value, "action_mode": "send"}
    )
    try:
        await update_layout_button(
            session, chat_id=target_chat_id, layout_id=layout_id, **changes
        )
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await _refresh_bottom_buttons(context, session, target_chat_id=target_chat_id)
    await _finish_bottom_button_input(
        update, context, session, target_chat_id=target_chat_id,
        user_id=user_id, detail_layout_id=layout_id,
    )


async def handle_bottom_button_admin_input(
    update,
    context,
    session,
    *, state,
    message_text: str,

    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    text_value = message_text.strip()
    state_type = str(state.state_type)
    user_id = update.effective_user.id

    if state_type == "bottom_button_text_input":
        await _handle_bottom_button_header(
            update, context, session, target_chat_id=target_chat_id,
            user_id=user_id, text_value=text_value,
        )
        return True

    if state_type not in {"bottom_button_button_text_input", "bottom_button_payload_input"}:
        return False

    await _handle_bottom_button_layout(
        update, context, session, state=state, target_chat_id=target_chat_id,
        user_id=user_id, text_value=text_value,
    )
    return True
