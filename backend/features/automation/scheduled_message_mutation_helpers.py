from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import resolve_state_chat_id
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message import (
    sm_day_period_end_keyboard,
    sm_day_period_start_keyboard,
    sm_edit_buttons_keyboard,
    sm_edit_media_keyboard,
    sm_edit_text_keyboard,
    sm_repeat_keyboard,
    sm_time_range_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.time_ui import build_back_keyboard, build_datetime_prompt_text, next_top_of_hour
from backend.shared.time_helper import format_timestamp

log = structlog.get_logger(__name__)


def _task_has_sendable_content(task) -> bool:
    return ScheduledMessageService.has_sendable_content(task)


def _build_task_buttons(buttons: list | None) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    try:
        normalized_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
    except ValidationError:
        normalized_buttons = []
    rows: list[list[InlineKeyboardButton]] = []
    for button_row in normalized_buttons:
        row: list[InlineKeyboardButton] = []
        for button in button_row:
            if isinstance(button, dict):
                row.append(InlineKeyboardButton(text=button.get("text", ""), url=button.get("url", "")))
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None


def _module_identity(update: Update, target_chat_id: int) -> dict:
    user = update.effective_user
    return {
        "chat_id": target_chat_id,
        "chat_type": "supergroup" if target_chat_id < 0 else "private",
        "title": update.effective_chat.title if update.effective_chat else None,
        "user_id": user.id if user else None,
        "username": user.username if user else None,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "language_code": user.language_code if user else None,
    }


async def _create_scheduled_task(session, update: Update, target_chat_id: int):
    await ModuleSettingsService.ensure(session, **_module_identity(update, target_chat_id))
    creator_user_id = update.effective_user.id if update.effective_user else 0
    return await ScheduledMessageService.create_task(
        session,
        chat_id=target_chat_id,
        created_by_user_id=creator_user_id,
        title="定时消息",
        enabled=False,
    )


@dataclass(frozen=True, slots=True)
class SetFieldRequest:
    owner: Any
    update: Update
    context: ContextTypes.DEFAULT_TYPE
    session: Any
    target_chat_id: int
    task_id: str
    field: str
    value: str


async def _set_enabled(request: SetFieldRequest, task) -> bool:
    enabled = request.value == "1"
    if enabled and not _task_has_sendable_content(task):
        await answer_callback_query_safely(request.update, "请先设置文本或封面", show_alert=True)
        await request.owner.show_detail(
            request.update,
            request.context,
            request.target_chat_id,
            request.task_id,
            toast="❌ 启用失败：请先设置文本或封面。下面可直接补齐后再预览、启用。",
        )
        return False
    await ScheduledMessageService.toggle_task_enabled(request.session, request.task_id, enabled)
    return True


async def _set_toggle(request: SetFieldRequest) -> bool:
    await ScheduledMessageService.update_task_toggle_option(
        request.session,
        request.task_id,
        request.field,
        value=request.value == "1",
    )
    return True


async def _set_repeat(request: SetFieldRequest) -> bool:
    await ScheduledMessageService.update_task_repeat(
        request.session,
        request.task_id,
        int(request.value),
    )
    return True


def _request_user_id(request: SetFieldRequest) -> int:
    return request.update.effective_user.id if request.update.effective_user else 0


async def _set_day_start(request: SetFieldRequest) -> bool:
    state_chat_id = resolve_state_chat_id(request.update, request.target_chat_id)
    start_hour = int(request.value)
    await ConversationStateService.start(
        request.session,
        state_chat_id,
        _request_user_id(request),
        state_type=ConversationStateType.sm_edit_day_start.value,
        state_data={
            "task_id": request.task_id,
            "start_hour": start_hour,
            "target_chat_id": request.target_chat_id,
        },
    )
    await request.session.commit()
    await request.owner.message_helper.safe_edit(
        request.update,
        text="请选择时段结束时间",
        reply_markup=sm_day_period_end_keyboard(
            request.target_chat_id,
            request.task_id,
            start_hour,
        ),
    )
    return False


async def _set_day_end(request: SetFieldRequest) -> bool:
    state_chat_id = resolve_state_chat_id(request.update, request.target_chat_id)
    user_id = _request_user_id(request)
    state = await ConversationStateService.get(request.session, state_chat_id, user_id)
    if not state or "start_hour" not in state.state_data:
        raise ValidationError("状态错误，请重新开始")
    await ScheduledMessageService.update_task_day_period(
        request.session,
        request.task_id,
        state.state_data["start_hour"],
        day_end_hour=int(request.value),
    )
    await ConversationStateService.clear(request.session, state_chat_id, user_id)
    return True


async def _apply_task_field(request: SetFieldRequest, task) -> bool:
    if request.field == "enabled":
        return await _set_enabled(request, task)
    if request.field in {"delete_previous", "pin_message"}:
        return await _set_toggle(request)
    if request.field == "repeat":
        return await _set_repeat(request)
    if request.field == "day_start":
        return await _set_day_start(request)
    if request.field == "day_end":
        return await _set_day_end(request)
    raise ValidationError(f"未知字段: {request.field}")


async def _clear_failed_edit_state(db: Database, request: SetFieldRequest) -> None:
    state_chat_id = resolve_state_chat_id(request.update, request.target_chat_id)
    async with db.session_factory() as cleanup_session:
        await ConversationStateService.clear(
            cleanup_session,
            state_chat_id,
            _request_user_id(request),
        )
        await cleanup_session.commit()


BUTTONS_EDIT_PROMPT = (
    "🔗 编辑按钮\n\n"
    "请输入按钮配置，支持逐行格式或 JSON。\n\n"
    "逐行格式示例:\n"
    "官网|example.com\n"
    "帮助|https://help.example.com\n\n"
    "同一行多个按钮可用分号分隔:\n"
    "官网|example.com ; 帮助|help.example.com\n\n"
    "JSON 示例:\n"
    "[\n"
    "  [{\"text\":\"按钮1\",\"url\":\"https://...\"}],\n"
    "  [{\"text\":\"按钮2\",\"url\":\"https://...\"}]\n"
    "]\n\n"
    "或输入 /clear 清空按钮"
)


@dataclass(frozen=True, slots=True)
class EditFieldSpec:
    state_type: str
    text: str
    keyboard: InlineKeyboardMarkup
    parse_mode: str | None = None


def _static_edit_spec(field: str, target_chat_id: int, task_id: str) -> EditFieldSpec | None:
    definitions = {
        "title": (
            ConversationStateType.sm_edit_title.value,
            "📮 编辑标题备注\n\n请输入新的标题备注，或输入 /clear 清空标题备注",
            sm_edit_text_keyboard,
        ),
        "text": (
            ConversationStateType.sm_edit_text.value,
            "✏️ 编辑文本\n\n请输入新的文本内容，或输入 /clear 清空文本",
            sm_edit_text_keyboard,
        ),
        "media": (
            ConversationStateType.sm_edit_media.value,
            "🎬 编辑媒体\n\n请发送图片/视频/文档/贴纸/动画",
            sm_edit_media_keyboard,
        ),
        "buttons": (
            ConversationStateType.sm_edit_buttons.value,
            BUTTONS_EDIT_PROMPT,
            sm_edit_buttons_keyboard,
        ),
        "day_period": (
            ConversationStateType.sm_edit_day_start.value,
            "🕐 选择时段开始时间",
            sm_day_period_start_keyboard,
        ),
    }
    definition = definitions.get(field)
    if definition is None:
        return None
    state_type, text, keyboard_builder = definition
    return EditFieldSpec(state_type, text, keyboard_builder(target_chat_id, task_id))


def _datetime_edit_spec(field: str, target_chat_id: int, task_id: str) -> EditFieldSpec | None:
    definitions = {
        "start_at": (
            ConversationStateType.sm_edit_start_at.value,
            "⏰ 定时消息 | 编辑开始时间",
            0,
            "👉🏻 现在输入定时开始时间:",
            "发送 /clear 可清空开始时间",
        ),
        "end_at": (
            ConversationStateType.sm_edit_end_at.value,
            "⏰ 定时消息 | 编辑结束时间",
            1,
            "👉🏻 现在输入定时结束时间:",
            "发送 /clear 可清空结束时间",
        ),
    }
    definition = definitions.get(field)
    if definition is None:
        return None
    state_type, title, days_offset, input_hint, clear_tip = definition
    sample_dt = next_top_of_hour(days_offset=days_offset)
    sample_unix = int(sample_dt.timestamp())
    text = build_datetime_prompt_text(
        title=title,
        sample_time_text=format_timestamp(sample_unix),
        sample_time_unix=sample_unix,
        show_copy_hint=False,
        input_hint=input_hint,
        extra_tips=[clear_tip],
    )
    keyboard = build_back_keyboard(f"sm:edit:{target_chat_id}:{task_id}:time_range")
    return EditFieldSpec(state_type, text, keyboard, "HTML")


def _edit_field_spec(field: str, target_chat_id: int, task_id: str) -> EditFieldSpec:
    spec = _static_edit_spec(field, target_chat_id, task_id)
    if spec is None:
        spec = _datetime_edit_spec(field, target_chat_id, task_id)
    if spec is None:
        raise ValidationError(f"未知字段: {field}")
    return spec


async def _show_repeat_editor(
    owner,
    update: Update,
    *,
    task,
    target_chat_id: int,
    task_id: str,
) -> None:
    keyboard = sm_repeat_keyboard(target_chat_id, task_id, task.repeat_interval_min)
    await owner.message_helper.safe_edit(update, text="请选择轮播间隔", reply_markup=keyboard)


async def _show_time_range_editor(
    owner,
    update: Update,
    *,
    task,
    target_chat_id: int,
    task_id: str,
) -> None:
    start_text = format_timestamp(task.start_at) if task.start_at else "【等待设置】"
    end_text = format_timestamp(task.end_at) if task.end_at else "【等待设置】"
    text = (
        "⏰ 定时消息 | 时间范围\n\n"
        f"开始时间：{start_text}\n"
        f"结束时间：{end_text}\n\n"
        "未设置开始时间时，从启用后的下一个调度点开始。"
    )
    await owner.message_helper.safe_edit(
        update,
        text=text,
        reply_markup=sm_time_range_keyboard(target_chat_id, task_id),
    )


async def _send_task_preview(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    task,
    reply_markup,
) -> None:
    parse_mode = task.parse_mode if task.parse_mode != "none" else None
    media = task.media_file_id
    if not media:
        await context.bot.send_message(chat_id, task.text, parse_mode=parse_mode, reply_markup=reply_markup)
        return
    if task.media_type == "sticker":
        await context.bot.send_sticker(chat_id, media)
        return
    senders = {
        "photo": context.bot.send_photo,
        "video": context.bot.send_video,
        "document": context.bot.send_document,
        "animation": context.bot.send_animation,
    }
    sender = senders.get(task.media_type)
    if sender is None:
        raise ValidationError(f"不支持的预览媒体类型: {task.media_type}")
    await sender(
        chat_id,
        media,
        caption=task.text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


@dataclass(frozen=True, slots=True)
class EditFieldRequest:
    owner: Any
    update: Update
    session: Any
    task: Any
    target_chat_id: int
    task_id: str
    field: str


async def _prepare_edit_field(request: EditFieldRequest) -> EditFieldSpec | None:
    if request.field == "repeat":
        await _show_repeat_editor(
            request.owner,
            request.update,
            task=request.task,
            target_chat_id=request.target_chat_id,
            task_id=request.task_id,
        )
        return None
    if request.field == "time_range":
        await _show_time_range_editor(
            request.owner,
            request.update,
            task=request.task,
            target_chat_id=request.target_chat_id,
            task_id=request.task_id,
        )
        return None
    spec = _edit_field_spec(request.field, request.target_chat_id, request.task_id)
    state_chat_id = resolve_state_chat_id(request.update, request.target_chat_id)
    user_id = request.update.effective_user.id if request.update.effective_user else 0
    await ConversationStateService.start(
        request.session,
        state_chat_id,
        user_id,
        state_type=spec.state_type,
        state_data={
            "task_id": request.task_id,
            "target_chat_id": request.target_chat_id,
        },
    )
    return spec


async def _render_edit_spec(owner, update: Update, spec: EditFieldSpec) -> None:
    kwargs = {
        "text": spec.text,
        "reply_markup": spec.keyboard,
    }
    if spec.parse_mode is not None:
        kwargs["parse_mode"] = spec.parse_mode
    await owner.message_helper.safe_edit(update, **kwargs)
