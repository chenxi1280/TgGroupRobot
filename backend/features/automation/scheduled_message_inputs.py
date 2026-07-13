from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import (
    is_clear_command,
    parse_buttons_text,
)
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.services.base import ValidationError

log = structlog.get_logger(__name__)

_TITLE_LENGTH = 128


@dataclass(frozen=True)
class _FsmEdit:
    update: Update
    session: object
    task_id: int
    text: str


async def _edit_title(edit: _FsmEdit) -> None:
    title = "定时消息" if is_clear_command(edit.text) else edit.text.strip()
    if not title:
        raise ValidationError("标题备注不能为空，请重新输入")
    await ScheduledMessageService.update_task(edit.session, edit.task_id, title=title[:_TITLE_LENGTH])


async def _edit_text(edit: _FsmEdit) -> None:
    text = None if is_clear_command(edit.text) else edit.text
    await ScheduledMessageService.update_task_text(edit.session, edit.task_id, text)


async def _edit_buttons(edit: _FsmEdit) -> None:
    if is_clear_command(edit.text):
        await ScheduledMessageService.update_task_buttons(edit.session, edit.task_id, [])
        return
    try:
        buttons = parse_buttons_text(edit.text)
    except Exception as exc:
        log.warning("scheduled_message_button_parse_failed", error=str(exc))
        raise ValidationError("按钮格式错误，请使用 文本|链接 或 JSON 重新输入") from exc
    try:
        await ScheduledMessageService.update_task_buttons(edit.session, edit.task_id, buttons)
    except ValidationError as exc:
        raise ValidationError("按钮配置错误，请重新输入") from exc


async def _edit_start_at(edit: _FsmEdit) -> None:
    value = None if is_clear_command(edit.text) else edit.text.strip()
    result = await ScheduledMessageService.update_task_start_at(edit.session, edit.task_id, value)
    if value is not None and not result:
        raise ValidationError("日期时间格式错误，请重新输入")


async def _edit_end_at(edit: _FsmEdit) -> None:
    value = None if is_clear_command(edit.text) else edit.text.strip()
    result = await ScheduledMessageService.update_task_end_at(edit.session, edit.task_id, value)
    if value is not None and not result:
        raise ValidationError("日期时间格式错误，请重新输入")


_FSM_EDIT_HANDLERS: dict[str, Callable[[_FsmEdit], Awaitable[None]]] = {
    ConversationStateType.sm_edit_title.value: _edit_title,
    ConversationStateType.sm_edit_text.value: _edit_text,
    ConversationStateType.sm_edit_buttons.value: _edit_buttons,
    ConversationStateType.sm_edit_start_at.value: _edit_start_at,
    ConversationStateType.sm_edit_end_at.value: _edit_end_at,
}
_FSM_TOASTS = {
    ConversationStateType.sm_edit_title.value: "✅ 标题备注已保存",
    ConversationStateType.sm_edit_text.value: "✅ 文本已保存",
    ConversationStateType.sm_edit_buttons.value: "✅ 按钮已保存",
    ConversationStateType.sm_edit_start_at.value: "✅ 开始时间已保存",
    ConversationStateType.sm_edit_end_at.value: "✅ 终止时间已保存",
}


async def _load_task_state(session, *, state_chat_id: int, user_id: int):
    state = await ConversationStateService.get(session, state_chat_id, user_id)
    log.info(
        "handle_fsm_input_state_result",
        state_found=state is not None,
        state_type=state.state_type if state else None,
    )
    if state is None:
        log.warning("handle_fsm_input_no_state")
        await session.commit()
        return None, None
    task_id = state.state_data.get("task_id")
    if task_id:
        return state, task_id
    log.warning("handle_fsm_input_no_task_id")
    await ConversationStateService.clear(session, state_chat_id, user_id)
    await session.commit()
    return None, None


async def _apply_fsm_edit(edit: _FsmEdit, state_type: str) -> None:
    handler = _FSM_EDIT_HANDLERS.get(state_type)
    if handler is None:
        log.warning("handle_fsm_input_unknown_state", state_type=state_type)
        raise ValidationError("状态无效，请重新进入")
    await handler(edit)


async def _save_fsm_edit(edit: _FsmEdit, *, state_chat_id: int, user_id: int, state_type: str) -> bool:
    try:
        await _apply_fsm_edit(edit, state_type)
        await ConversationStateService.clear(edit.session, state_chat_id, user_id)
        await edit.session.commit()
        log.info("handle_fsm_input_update_success")
        return True
    except ValidationError as exc:
        await edit.session.rollback()
        await edit.update.effective_message.reply_text(f"❌ {exc}")
        return False
    except Exception as exc:
        await edit.session.rollback()
        log.error("handle_fsm_input_exception", error=str(exc), traceback=traceback.format_exc())
        error_text = build_public_error_text(exc, fallback="请稍后重试")
        await edit.update.effective_message.reply_text(f"❌ 操作失败: {error_text}")
        return False


def _extract_media(message) -> tuple[str, str] | None:
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.video:
        return "video", message.video.file_id
    if message.document:
        return "document", message.document.file_id
    if message.sticker:
        return "sticker", message.sticker.file_id
    if message.animation:
        return "animation", message.animation.file_id
    return None


async def _save_media_edit(update: Update, session, *, state_chat_id: int, user_id: int, task_id: int, media) -> bool:
    media_type, file_id = media
    try:
        await ScheduledMessageService.update_task_media(session, task_id, media_type, media_file_id=file_id)
        await ConversationStateService.clear(session, state_chat_id, user_id)
        await session.commit()
        return True
    except Exception as exc:
        await session.rollback()
        log.error("更新任务媒体失败", task_id=task_id, error=str(exc))
        error_text = build_public_error_text(exc, fallback="请稍后重试")
        await update.effective_message.reply_text(f"❌ 操作失败: {error_text}")
        return False


class ScheduledMessageInputMixin:
    async def handle_fsm_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, user_id: int,
        text: str,
    ) -> None:
        log.info(
            "=== handle_fsm_input CALLED ===",
            target_chat_id=target_chat_id,
            user_id=user_id,
            text_preview=text[:50],
        )

        if update.effective_message is None:
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state, task_id = await _load_task_state(
                session,
                state_chat_id=state_chat_id,
                user_id=user_id,
            )
            if state is None or task_id is None:
                return
            state_type = state.state_type or ""
            log.info("handle_fsm_input_updating", task_id=task_id, state_type=state_type)
            edit = _FsmEdit(update=update, session=session, task_id=task_id, text=text)
            saved = await _save_fsm_edit(
                edit,
                state_chat_id=state_chat_id,
                user_id=user_id,
                state_type=state_type,
            )
            if not saved:
                return
        toast_msg = _FSM_TOASTS[state_type]
        log.info("handle_fsm_input_showing_detail", task_id=task_id, toast_msg=toast_msg)
        await self.show_detail(update, context, target_chat_id, task_id, toast=toast_msg)
        log.info("handle_fsm_input_completed")

    async def handle_media_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, user_id: int,
    ) -> None:
        if update.effective_message is None:
            return
        media = _extract_media(update.effective_message)
        if media is None:
            await update.effective_message.reply_text("❌ 不支持的媒体类型")
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state, task_id = await _load_task_state(session, state_chat_id=state_chat_id, user_id=user_id)
            if state is None or task_id is None:
                return
            if state.state_type != ConversationStateType.sm_edit_media.value:
                await session.commit()
                return
            saved = await _save_media_edit(
                update,
                session,
                state_chat_id=state_chat_id,
                user_id=user_id,
                task_id=task_id,
                media=media,
            )
            if not saved:
                return
        await self.show_detail(update, context, target_chat_id, task_id, toast="✅ 媒体已保存")
