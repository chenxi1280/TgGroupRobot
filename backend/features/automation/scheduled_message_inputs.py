from __future__ import annotations

import traceback

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

        db: Database = context.application.bot_data["db"]
        state = None

        async with db.session_factory() as session:
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state = await ConversationStateService.get(session, state_chat_id, user_id)
            log.info(
                "handle_fsm_input_state_result",
                state_found=state is not None,
                state_type=state.state_type if state else None,
            )

            if not state:
                log.warning("handle_fsm_input_no_state")
                await session.commit()
                return

            task_id = state.state_data.get("task_id")
            if not task_id:
                log.warning("handle_fsm_input_no_task_id")
                await ConversationStateService.clear(session, state_chat_id, user_id)
                await session.commit()
                return

            log.info("handle_fsm_input_updating", task_id=task_id, state_type=state.state_type)
            try:
                state_type_str = state.state_type or ""
                if state_type_str == ConversationStateType.sm_edit_title.value:
                    title = "定时消息" if is_clear_command(text) else text.strip()
                    if not title:
                        await session.rollback()
                        await update.effective_message.reply_text("❌ 标题备注不能为空，请重新输入")
                        return
                    await ScheduledMessageService.update_task(session, task_id, title=title[:128])
                elif state_type_str == ConversationStateType.sm_edit_text.value:
                    await ScheduledMessageService.update_task_text(
                        session,
                        task_id,
                        None if is_clear_command(text) else text,
                    )
                elif state_type_str == ConversationStateType.sm_edit_buttons.value:
                    if is_clear_command(text):
                        await ScheduledMessageService.update_task_buttons(session, task_id, [])
                    else:
                        try:
                            buttons = parse_buttons_text(text)
                        except Exception as exc:
                            log.warning("scheduled_message_button_parse_failed", error=str(exc))
                            await session.rollback()
                            await update.effective_message.reply_text(
                                "❌ 按钮格式错误，请使用 文本|链接 或 JSON 重新输入"
                            )
                            return

                        try:
                            await ScheduledMessageService.update_task_buttons(session, task_id, buttons)
                        except ValidationError:
                            await session.rollback()
                            await update.effective_message.reply_text("❌ 按钮配置错误，请重新输入")
                            return
                elif state_type_str == ConversationStateType.sm_edit_start_at.value:
                    if is_clear_command(text):
                        await ScheduledMessageService.update_task_start_at(session, task_id, None)
                    else:
                        result = await ScheduledMessageService.update_task_start_at(session, task_id, text.strip())
                        if not result:
                            await session.rollback()
                            await update.effective_message.reply_text("❌ 日期时间格式错误，请重新输入")
                            return
                elif state_type_str == ConversationStateType.sm_edit_end_at.value:
                    if is_clear_command(text):
                        await ScheduledMessageService.update_task_end_at(session, task_id, None)
                    else:
                        result = await ScheduledMessageService.update_task_end_at(session, task_id, text.strip())
                        if not result:
                            await session.rollback()
                            await update.effective_message.reply_text("❌ 日期时间格式错误，请重新输入")
                            return
                else:
                    log.warning("handle_fsm_input_unknown_state", state_type=state_type_str)
                    await session.rollback()
                    await update.effective_message.reply_text("❌ 状态无效，请重新进入")
                    return

                await ConversationStateService.clear(session, state_chat_id, user_id)
                await session.commit()
                log.info("handle_fsm_input_update_success")
            except Exception as exc:
                await session.rollback()
                log.error(
                    "handle_fsm_input_exception",
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                await update.effective_message.reply_text(
                    f"❌ 操作失败: {build_public_error_text(exc, fallback='请稍后重试')}"
                )
                return

        toast_msg = None
        if state:
            state_type_str = state.state_type or ""
            if state_type_str == ConversationStateType.sm_edit_title.value:
                toast_msg = "✅ 标题备注已保存"
            elif state_type_str == ConversationStateType.sm_edit_text.value:
                toast_msg = "✅ 文本已保存"
            elif state_type_str == ConversationStateType.sm_edit_buttons.value:
                toast_msg = "✅ 按钮已保存"
            elif state_type_str == ConversationStateType.sm_edit_start_at.value:
                toast_msg = "✅ 开始时间已保存"
            elif state_type_str == ConversationStateType.sm_edit_end_at.value:
                toast_msg = "✅ 终止时间已保存"

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

        media_type = "none"
        file_id = None
        if update.effective_message.photo:
            media_type = "photo"
            file_id = update.effective_message.photo[-1].file_id
        elif update.effective_message.video:
            media_type = "video"
            file_id = update.effective_message.video.file_id
        elif update.effective_message.document:
            media_type = "document"
            file_id = update.effective_message.document.file_id
        elif update.effective_message.sticker:
            media_type = "sticker"
            file_id = update.effective_message.sticker.file_id
        elif update.effective_message.animation:
            media_type = "animation"
            file_id = update.effective_message.animation.file_id
        else:
            await update.effective_message.reply_text("❌ 不支持的媒体类型")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state_chat_id = update.effective_chat.id if update.effective_chat else target_chat_id
            state = await ConversationStateService.get(session, state_chat_id, user_id)
            if not state or state.state_type != ConversationStateType.sm_edit_media.value:
                await session.commit()
                return

            task_id = state.state_data.get("task_id")
            if not task_id:
                await ConversationStateService.clear(session, state_chat_id, user_id)
                await session.commit()
                return

            try:
                await ScheduledMessageService.update_task_media(session, task_id, media_type, media_file_id=file_id)
                await ConversationStateService.clear(session, state_chat_id, user_id)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                log.error("更新任务媒体失败", task_id=task_id, error=str(exc))
                await update.effective_message.reply_text(
                    f"❌ 操作失败: {build_public_error_text(exc, fallback='请稍后重试')}"
                )
                return

        await self.show_detail(update, context, target_chat_id, task_id, toast="✅ 媒体已保存")
