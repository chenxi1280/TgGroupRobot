from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.admin.garage.input_runtime import (
    admin_handler_instance,
    clear_admin_input_state,
    require_garage_manage,
    target_chat_id_from_state,
)
from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import is_clear_button_input


async def handle_garage_forward_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    from backend.features.garage.services.garage_forward_service import GarageForwardService

    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = target_chat_id_from_state(state)
    if not await require_garage_manage(update, context, target_chat_id):
        return

    if state.state_type not in {
        "garage_forward_source_input",
        "garage_forward_keyword_input",
        "garage_forward_buttons_input",
    }:
        await update.effective_message.reply_text("频道同步状态异常，请重新进入页面。")
        return

    if state.state_type == "garage_forward_keyword_input":
        await _handle_keyword_input(update, context, session, target_chat_id, message_text)
        return

    if state.state_type == "garage_forward_buttons_input":
        await _handle_buttons_input(update, context, session, target_chat_id, message_text)
        return

    await _handle_source_input(update, context, session, target_chat_id, message_text)


async def _handle_keyword_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    message_text: str,
) -> None:
    from backend.features.garage.services.garage_forward_service import GarageForwardService

    if update.effective_user is None or update.effective_message is None:
        return

    keywords = [
        item.strip()
        for chunk in message_text.replace("，", ",").splitlines()
        for item in chunk.replace(",", " ").split()
        if item.strip()
    ]
    normalized_keywords: list[str] = []
    for item in keywords:
        if item not in normalized_keywords:
            normalized_keywords.append(item[:64])

    await GarageForwardService.update_setting(
        session,
        target_chat_id,
        keyword_rules=normalized_keywords,
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text(
        f"已更新关键词规则，共 {len(normalized_keywords)} 条。"
        if normalized_keywords
        else "已清空关键词规则。"
    )
    await admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)


async def _handle_buttons_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    message_text: str,
) -> None:
    from backend.features.automation.scheduled_message_handler import _parse_buttons_text
    from backend.features.garage.services.garage_forward_service import GarageForwardService

    if update.effective_user is None or update.effective_message is None:
        return

    raw_value = (message_text or "").strip()
    if is_clear_button_input(raw_value):
        await GarageForwardService.update_setting(
            session,
            target_chat_id,
            button_template=[],
            button_template_enabled=False,
        )
        await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("已清空按钮模板并关闭自动按钮。")
        await admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)
        return

    try:
        buttons = _parse_buttons_text(raw_value)
    except ValidationError as exc:
        await update.effective_message.reply_text(str(exc))
        return

    await GarageForwardService.update_setting(
        session,
        target_chat_id,
        button_template=buttons,
        button_template_enabled=bool(buttons),
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("已更新按钮模板，并自动启用。")
    await admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)


async def _handle_source_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    target_chat_id: int,
    message_text: str,
) -> None:
    from backend.features.garage.services.garage_forward_service import GarageForwardService

    if update.effective_user is None or update.effective_message is None:
        return

    raw_value = message_text.strip()
    if not raw_value:
        await update.effective_message.reply_text("来源频道不能为空。")
        return

    source_channel_id: int | None = None
    source_name: str | None = None
    remote_chat = None
    if raw_value.lstrip("-").isdigit():
        source_channel_id = int(raw_value)
        try:
            remote_chat = await context.bot.get_chat(source_channel_id)
        except Exception:
            remote_chat = None
    else:
        try:
            remote_chat = await context.bot.get_chat(raw_value)
        except Exception:
            remote_chat = None
        if remote_chat is not None:
            source_channel_id = int(remote_chat.id)
            source_name = remote_chat.title or remote_chat.username

    if source_channel_id is None:
        await update.effective_message.reply_text("无法识别该频道，请输入频道 ID、用户名或可解析链接。")
        return
    if remote_chat is None or remote_chat.type != "channel":
        await update.effective_message.reply_text("来源必须是频道，群组或私聊不能作为车库转发来源。")
        return

    source_name = source_name or remote_chat.title or remote_chat.username

    await GarageForwardService.add_source(
        session,
        chat_id=target_chat_id,
        source_channel_id=source_channel_id,
        source_name=source_name,
    )
    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    await update.effective_message.reply_text("已添加来源频道。")
    await admin_handler_instance()._show_garage_forward_prompt(update, context, target_chat_id)
