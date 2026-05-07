from __future__ import annotations

import asyncio
import datetime as dt
import re

import structlog
from telegram import KeyboardButton, ReplyKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.expansion import BottomButtonLayout, BottomButtonSetting
from backend.shared.services.base import ValidationError
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.async_tasks import spawn_background_task
from backend.features.group_ops.services.bottom_button_events import (
    BOTTOM_BUTTON_EVENT_LABELS,
    BOTTOM_BUTTON_EVENT_OPTIONS,
    get_event_label,
    resolve_event_trigger_text,
)


MAX_BUTTON_COLS = 4
MAX_LAYOUT_ROWS = 6
BOTTOM_BUTTON_ACTION_MODES = {"send", "fill", "event"}
GENERATED_MESSAGE_DELETE_DELAY_SECONDS = 5

log = structlog.get_logger(__name__)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def sanitize_button_text(value: str) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", "", value.strip())
    if not text:
        raise ValidationError("按钮文案不能为空。")
    if len(text) > 16:
        raise ValidationError("按钮文案过长，请控制在 16 个字符以内。")
    return text


def sanitize_payload_text(value: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", value.strip())
    if not text:
        raise ValidationError("按钮内容不能为空。")
    if len(text) > 128:
        raise ValidationError("按钮内容过长，请控制在 128 个字符以内。")
    return text


async def get_or_create_setting(session: AsyncSession, chat_id: int) -> BottomButtonSetting:
    await ModuleSettingsService.ensure(session, chat_id=chat_id)
    setting = await session.get(BottomButtonSetting, chat_id)
    if setting is None:
        setting = BottomButtonSetting(chat_id=chat_id)
        session.add(setting)
        await session.flush()
    return setting


async def update_setting(session: AsyncSession, chat_id: int, **updates) -> BottomButtonSetting:
    setting = await get_or_create_setting(session, chat_id)
    for key, value in updates.items():
        if hasattr(setting, key):
            setattr(setting, key, value)
    setting.updated_at = _now()
    await session.flush()
    return setting


async def list_layouts(session: AsyncSession, chat_id: int) -> list[BottomButtonLayout]:
    stmt = (
        select(BottomButtonLayout)
        .where(BottomButtonLayout.chat_id == chat_id)
        .order_by(BottomButtonLayout.row_no.asc(), BottomButtonLayout.col_no.asc(), BottomButtonLayout.sort_key.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_layout(session: AsyncSession, chat_id: int, layout_id: int) -> BottomButtonLayout | None:
    stmt = select(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat_id, BottomButtonLayout.id == layout_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_enabled_layout_by_button_text(
    session: AsyncSession,
    chat_id: int,
    button_text: str,
) -> BottomButtonLayout | None:
    text = button_text.strip()
    if not text:
        return None
    setting = await session.get(BottomButtonSetting, chat_id)
    if setting is None or not setting.enabled:
        return None
    stmt = (
        select(BottomButtonLayout)
        .where(BottomButtonLayout.chat_id == chat_id, BottomButtonLayout.button_text == text)
        .order_by(BottomButtonLayout.row_no.asc(), BottomButtonLayout.col_no.asc(), BottomButtonLayout.sort_key.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _next_empty_slot(layouts: list[BottomButtonLayout]) -> tuple[int, int]:
    occupied = {(item.row_no, item.col_no) for item in layouts}
    for row_no in range(1, MAX_LAYOUT_ROWS + 1):
        for col_no in range(1, MAX_BUTTON_COLS + 1):
            if (row_no, col_no) not in occupied:
                return row_no, col_no
    raise ValidationError("按钮布局已满，最多支持 6 行，每行 4 个按钮。")


def _validate_layout_position(row_no: int, col_no: int) -> None:
    if row_no < 1 or row_no > MAX_LAYOUT_ROWS:
        raise ValidationError(f"按钮行数无效，最多支持 {MAX_LAYOUT_ROWS} 行。")
    if col_no < 1 or col_no > MAX_BUTTON_COLS:
        raise ValidationError(f"按钮列数无效，每行最多 {MAX_BUTTON_COLS} 个按钮。")


async def add_layout_button(
    session: AsyncSession,
    chat_id: int,
    *,
    row_no: int | None = None,
    col_no: int | None = None,
) -> BottomButtonLayout:
    layouts = await list_layouts(session, chat_id)
    if row_no is None or col_no is None:
        row_no, col_no = _next_empty_slot(layouts)
    else:
        _validate_layout_position(row_no, col_no)
        if any(item.row_no == row_no and item.col_no == col_no for item in layouts):
            raise ValidationError("该位置已经有按钮。")
    layout = BottomButtonLayout(
        chat_id=chat_id,
        row_no=row_no,
        col_no=col_no,
        button_text="按钮",
        payload_text="按钮",
        action_mode="send",
        sort_key=(row_no * 10 + col_no),
    )
    session.add(layout)
    await session.flush()
    return layout


async def clear_layouts(session: AsyncSession, chat_id: int) -> None:
    await session.execute(delete(BottomButtonLayout).where(BottomButtonLayout.chat_id == chat_id))


async def delete_layout_button(session: AsyncSession, chat_id: int, layout_id: int) -> None:
    layout = await get_layout(session, chat_id, layout_id)
    if layout is None:
        raise ValidationError("按钮不存在。")
    await session.delete(layout)
    await session.flush()


async def compact_layouts(session: AsyncSession, chat_id: int) -> list[BottomButtonLayout]:
    layouts = await list_layouts(session, chat_id)
    for index, layout in enumerate(layouts):
        row_no = index // MAX_BUTTON_COLS + 1
        col_no = index % MAX_BUTTON_COLS + 1
        layout.row_no = row_no
        layout.col_no = col_no
        layout.sort_key = row_no * 10 + col_no
    await session.flush()
    return layouts


async def update_layout_button(
    session: AsyncSession,
    *,
    chat_id: int,
    layout_id: int,
    button_text: str | None = None,
    payload_text: str | None = None,
    action_mode: str | None = None,
) -> BottomButtonLayout:
    layout = await get_layout(session, chat_id, layout_id)
    if layout is None:
        raise ValidationError("按钮不存在。")
    if button_text is not None:
        layout.button_text = sanitize_button_text(button_text)
    if payload_text is not None:
        layout.payload_text = sanitize_payload_text(payload_text)
    if action_mode is not None:
        if action_mode not in BOTTOM_BUTTON_ACTION_MODES:
            raise ValidationError("按钮模式无效。")
        layout.action_mode = action_mode
    layout.updated_at = _now()
    await session.flush()
    return layout


def describe_layout_action(layout: BottomButtonLayout) -> str:
    if layout.action_mode == "event":
        return f"事件：{get_event_label(layout.payload_text)}"
    payload = (layout.payload_text or layout.button_text or "").strip()
    return f"自定义触发词：{payload or '未设置'}"


async def resolve_layout_trigger_text(
    session: AsyncSession,
    chat_id: int,
    layout: BottomButtonLayout,
) -> str | None:
    if layout.action_mode != "event":
        return (layout.payload_text or layout.button_text or "").strip() or None

    event_key = (layout.payload_text or "").strip()
    return await resolve_event_trigger_text(session, chat_id, event_key)


def build_management_layout_preview(layouts: list[BottomButtonLayout]) -> str:
    if not layouts:
        return "当前还没有按钮，请先点击下方的“➕ 按钮”开始布局。"
    rows: dict[int, list[str]] = {}
    for layout in layouts:
        rows.setdefault(layout.row_no, [])
        rows[layout.row_no].append(layout.button_text)
    return "\n".join(" | ".join(items) for _, items in sorted(rows.items()))


def build_runtime_markup(chat_id: int, layouts: list[BottomButtonLayout]) -> ReplyKeyboardMarkup:
    rows: dict[int, list[KeyboardButton]] = {}
    for layout in layouts:
        button = KeyboardButton(layout.button_text)
        rows.setdefault(layout.row_no, []).append(button)
    keyboard_rows = [items for _, items in sorted(rows.items())]
    return ReplyKeyboardMarkup(
        keyboard_rows or [[KeyboardButton("暂无按钮")]],
        resize_keyboard=True,
        is_persistent=True,
    )


async def generate_buttons(context: ContextTypes.DEFAULT_TYPE, session: AsyncSession, chat_id: int) -> BottomButtonSetting:
    setting = await get_or_create_setting(session, chat_id)
    layouts = await list_layouts(session, chat_id)
    markup = build_runtime_markup(chat_id, layouts)
    text = setting.header_text

    if setting.generated_message_id:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=setting.generated_message_id,
            )
        except TelegramError as exc:
            log.warning("bottom_button_delete_old_failed", chat_id=chat_id, message_id=setting.generated_message_id, error=str(exc))

    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)

    setting.generated_message_id = sent.message_id
    setting.repeat_generate_enabled = False
    setting.last_generated_at = _now()
    setting.updated_at = _now()
    await session.flush()
    _schedule_generated_message_delete(context, chat_id=chat_id, message_id=sent.message_id)
    return setting


async def list_due_repeat_generate(session: AsyncSession) -> list[BottomButtonSetting]:
    return []


async def _delete_generated_message_later(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, message_id: int) -> None:
    try:
        await asyncio.sleep(GENERATED_MESSAGE_DELETE_DELAY_SECONDS)
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (asyncio.CancelledError,):
        raise
    except Exception as exc:
        log.warning("bottom_button_generated_message_delete_failed", chat_id=chat_id, message_id=message_id, error=str(exc))
        return


def _schedule_generated_message_delete(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int | None,
) -> None:
    if not message_id:
        return
    spawn_background_task(
        context,
        _delete_generated_message_later(context, chat_id=chat_id, message_id=message_id),
        name="bottom_button.delete_generated_message",
    )
