from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import structlog
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
from backend.features.group_ops.group_hooks.control_force_subscribe import (
    _build_force_subscribe_channel_button,
    _build_resolved_force_subscribe_channel_button,
    _normalize_force_subscribe_target,
    _resolve_force_subscribe_target_label,
    diagnose_force_subscribe_targets,
)
from backend.shared.services.base import ValidationError
from backend.shared.ui.button_input import is_clear_button_input, parse_button_rows

log = structlog.get_logger(__name__)


def parse_force_subscribe_buttons_input(raw_text: str) -> list[list[dict]]:
    return parse_button_rows(raw_text, allow_empty=False)


def _build_force_subscribe_channel_button_preview(value: str | None) -> InlineKeyboardButton | None:
    return _build_force_subscribe_channel_button(value)


async def describe_force_subscribe_target(context: ContextTypes.DEFAULT_TYPE, value: str | None) -> str:
    if not value:
        return "未绑定"
    return await _resolve_force_subscribe_target_label(context, value)


async def describe_force_subscribe_target_diagnostics(context: ContextTypes.DEFAULT_TYPE, settings) -> list[str]:
    return await diagnose_force_subscribe_targets(context, settings)


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
        except Exception as exc:
            log.warning("force_subscribe_preview_buttons_normalize_failed", error=str(exc))
            rows = []
    if not rows:
        fallback_buttons = [
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button_preview(getattr(settings, "force_subscribe_bound_channel_2", None)),
        ]
        rows.extend([[button] for button in fallback_buttons if button is not None])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback or f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


async def build_force_subscribe_preview_markup_async(
    settings,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
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
        except Exception as exc:
            log.warning("force_subscribe_preview_buttons_normalize_failed", error=str(exc))
            rows = []
    if not rows:
        for value in (
            getattr(settings, "force_subscribe_bound_channel_1", None),
            getattr(settings, "force_subscribe_bound_channel_2", None),
        ):
            button = await _build_resolved_force_subscribe_channel_button(context, value)
            if button is not None:
                rows.append([button])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback or f"adm:menu:forcesub:{chat_id}")])
    return InlineKeyboardMarkup(rows)


async def handle_force_subscribe_channel_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    *, state,
    message_text: str,
) -> None:
    if update.effective_user is None:
        return
    target_chat_id = target_chat_id_from_state(state)
    if not await require_settings_manage(update, context, target_chat_id):
        return
    settings = await admin_module().get_chat_settings(session, target_chat_id)

    if state.state_type == "force_subscribe_channel_1_input":
        if not await _apply_force_subscribe_target(update, context, settings, attr_name="force_subscribe_bound_channel_1", message_text=message_text):
            return
    elif state.state_type == "force_subscribe_channel_2_input":
        if not await _apply_force_subscribe_target(update, context, settings, attr_name="force_subscribe_bound_channel_2", message_text=message_text):
            return
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


def _is_bot_deep_link(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "www.t.me"}:
        return False
    query = parse_qs(parsed.query)
    return bool({"start", "startgroup", "startchannel"} & set(query))


async def _apply_force_subscribe_target(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    settings,
    *, attr_name: str,
    message_text: str,
) -> bool:
    value = _optional_text(message_text)
    if value is None:
        setattr(settings, attr_name, None)
        return True
    if not await _validate_force_subscribe_target(update, context, value):
        return False
    setattr(settings, attr_name, value.strip())
    return True


async def _validate_force_subscribe_target(update: Update, context: ContextTypes.DEFAULT_TYPE, value: str) -> bool:
    message = update.effective_message
    if message is None:
        return False
    if _is_bot_deep_link(value):
        await message.reply_text("本期不支持机器人目标，请填写公开频道或群组的 @用户名 / t.me 链接。")
        return False

    target = _normalize_force_subscribe_target(value)
    raw = value.strip()
    is_public_input = raw.startswith("@") or raw.startswith("https://t.me/") or raw.startswith("http://t.me/")
    if target is None or not is_public_input or isinstance(target, int):
        await message.reply_text("目标格式错误，请填写公开频道或群组的 @用户名 / t.me 链接，不支持裸用户名、数字 ID 或私密邀请链接。")
        return False

    try:
        target_chat = await context.bot.get_chat(chat_id=target)
    except Exception as exc:
        log.warning("force_subscribe_target_chat_lookup_failed", target=target, error=str(exc))
        await message.reply_text("无法访问该频道/群组，请确认机器人已加入目标并具备管理员权限。")
        return False

    if target_chat.type not in {"channel", "group", "supergroup"}:
        await message.reply_text("本期不支持机器人目标，请绑定频道或群组。")
        return False
    if not str(getattr(target_chat, "username", "") or "").strip():
        await message.reply_text("该频道/群组没有公开用户名，无法生成关注按钮。请绑定公开频道/群组的 @用户名。")
        return False

    bot_id = getattr(context.bot, "id", None)
    if bot_id is not None:
        try:
            bot_member = await context.bot.get_chat_member(chat_id=target, user_id=bot_id)
        except Exception as exc:
            log.warning("force_subscribe_target_bot_member_lookup_failed", target=target, bot_id=bot_id, error=str(exc))
            await message.reply_text("无法确认机器人在目标频道/群组中的权限，请先将机器人加入并设为管理员。")
            return False
        if getattr(bot_member, "status", None) not in {"administrator", "creator"}:
            await message.reply_text("请先将机器人设为目标频道/群组管理员，否则无法稳定校验成员关注状态。")
            return False
    return True


async def _apply_force_subscribe_buttons(update: Update, settings, message_text: str) -> bool:
    if update.effective_message is None:
        return False
    if is_clear_button_input(message_text):
        settings.force_subscribe_buttons = []
        settings.force_subscribe_custom_buttons_enabled = False
        return True
    try:
        buttons = parse_force_subscribe_buttons_input(message_text)
        settings.force_subscribe_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
        settings.force_subscribe_custom_buttons_enabled = True
        return True
    except ValidationError as exc:
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
