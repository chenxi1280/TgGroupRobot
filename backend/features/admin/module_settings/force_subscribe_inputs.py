from __future__ import annotations

import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.admin.module_settings.input_runtime import (
    admin_handler_instance,
    admin_module,
    clear_admin_input_state,
    require_settings_manage,
    target_chat_id_from_state,
)
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.shared.services.base import ValidationError


def parse_force_subscribe_buttons_input(raw_text: str) -> list[list[dict]]:
    text = (raw_text or "").strip()
    if not text:
        raise ValidationError("按钮配置不能为空。")
    if text.startswith("["):
        return json.loads(text)

    rows: list[list[dict]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            raise ValidationError("文本格式错误：每行必须包含“按钮文案|URL”。")
        button_text, button_url = [part.strip() for part in line.split("|", 1)]
        if not button_text or not button_url:
            raise ValidationError("按钮文案和 URL 不能为空。")
        rows.append([{"text": button_text[:32], "url": button_url}])
    if not rows:
        raise ValidationError("未解析到有效按钮。")
    return rows


def _build_force_subscribe_channel_button_preview(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.startswith("@"):
        return InlineKeyboardButton(normalized, url=f"https://t.me/{normalized[1:]}")
    if normalized.startswith("https://t.me/") or normalized.startswith("http://t.me/"):
        return InlineKeyboardButton(normalized, url=normalized)
    return None


def build_force_subscribe_preview_markup(
    settings,
    chat_id: int,
    *,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if custom_enabled and custom_buttons:
        try:
            normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
            for row in normalized:
                rows.append([InlineKeyboardButton(item["text"], url=item["url"]) for item in row])
        except Exception:
            rows = []
    if not rows:
        fallback_buttons = [
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_2", None)),
        ]
        rows.extend([[button] for button in fallback_buttons if button is not None])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback or f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


async def handle_force_subscribe_channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)

    if state.state_type == "force_subscribe_channel_1_input":
        settings.force_subscribe_bound_channel_1 = _optional_text(message_text)
    elif state.state_type == "force_subscribe_channel_2_input":
        settings.force_subscribe_bound_channel_2 = _optional_text(message_text)
    elif state.state_type == "force_subscribe_text_input":
        value = message_text.strip()
        if not value:
            await update.effective_message.reply_text("文案不能为空。")
            return
        settings.force_subscribe_guide_text = value
    elif state.state_type == "force_subscribe_buttons_input":
        if not await _apply_force_subscribe_buttons(update, settings, message_text):
            return
    elif state.state_type == "force_subscribe_cover_input":
        if not await _apply_force_subscribe_cover(update, settings, message_text):
            return

    await clear_admin_input_state(session, target_chat_id=target_chat_id, user_id=update.effective_user.id)
    await session.commit()
    if isinstance(state.state_data, dict) and state.state_data.get("return_to") == "verification_self_review":
        await admin_handler_instance()._show_join_self_review_menu(update, context, target_chat_id)
        return
    await admin_handler_instance()._show_force_subscribe_menu(update, context, target_chat_id)


def _optional_text(message_text: str) -> str | None:
    value = message_text.strip()
    return None if value in {"", "清空"} else value


async def _apply_force_subscribe_buttons(update: Update, settings, message_text: str) -> bool:
    if update.effective_message is None:
        return False
    if message_text.strip() == "清空":
        settings.force_subscribe_buttons = []
        settings.force_subscribe_custom_buttons_enabled = False
        return True
    try:
        buttons = parse_force_subscribe_buttons_input(message_text)
        settings.force_subscribe_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
        settings.force_subscribe_custom_buttons_enabled = True
        return True
    except (json.JSONDecodeError, ValidationError) as exc:
        await update.effective_message.reply_text(f"按钮格式错误：{exc}")
        return False


async def _apply_force_subscribe_cover(update: Update, settings, message_text: str) -> bool:
    message = update.effective_message
    if message is None:
        return False
    if message_text.strip() == "清空":
        settings.force_subscribe_cover_media_type = None
        settings.force_subscribe_cover_file_id = None
        return True
    if message.photo:
        settings.force_subscribe_cover_media_type = "photo"
        settings.force_subscribe_cover_file_id = message.photo[-1].file_id
        return True
    if message.video:
        settings.force_subscribe_cover_media_type = "video"
        settings.force_subscribe_cover_file_id = message.video.file_id
        return True
    await message.reply_text("请发送图片或视频，或发送“清空”移除封面。")
    return False
