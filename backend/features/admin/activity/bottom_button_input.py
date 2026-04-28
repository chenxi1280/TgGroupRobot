from __future__ import annotations

from backend.features.admin.activity.runtime import admin_handler_instance, clear_private_admin_state
from backend.features.group_ops.services.bottom_button_service import (
    generate_buttons as generate_bottom_buttons,
    get_or_create_setting as get_bottom_button_setting,
    update_layout_button,
    update_setting as update_bottom_button_setting,
)
from backend.shared.services.base import ValidationError


async def handle_bottom_button_admin_input(
    update,
    context,
    session,
    state,
    message_text: str,
    *,
    target_chat_id: int,
) -> bool:
    if update.effective_user is None or update.effective_message is None:
        return True

    text_value = message_text.strip()
    state_type = str(state.state_type)
    user_id = update.effective_user.id

    if state_type == "bottom_button_text_input":
        if not text_value:
            await update.effective_message.reply_text("文本内容不能为空。")
            return True
        setting = await update_bottom_button_setting(session, target_chat_id, header_text=text_value)
        if setting.enabled:
            await generate_bottom_buttons(context, session, target_chat_id)
        await clear_private_admin_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await admin_handler_instance()._show_bottom_button_menu(update, context, target_chat_id)
        return True

    if state_type not in {"bottom_button_button_text_input", "bottom_button_payload_input"}:
        return False

    layout_id = state.state_data.get("layout_id")
    if not isinstance(layout_id, int):
        await clear_private_admin_state(session, target_chat_id=target_chat_id, user_id=user_id)
        await session.commit()
        await update.effective_message.reply_text("按钮状态异常，请重新进入页面。")
        return True

    try:
        if state_type == "bottom_button_button_text_input":
            await update_layout_button(
                session,
                chat_id=target_chat_id,
                layout_id=layout_id,
                button_text=text_value,
            )
        else:
            await update_layout_button(
                session,
                chat_id=target_chat_id,
                layout_id=layout_id,
                payload_text=text_value,
            )
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return True

    setting = await get_bottom_button_setting(session, target_chat_id)
    if setting.enabled:
        await generate_bottom_buttons(context, session, target_chat_id)
    await clear_private_admin_state(session, target_chat_id=target_chat_id, user_id=user_id)
    await session.commit()
    await admin_handler_instance()._show_bottom_button_detail(update, context, target_chat_id, layout_id)
    return True
