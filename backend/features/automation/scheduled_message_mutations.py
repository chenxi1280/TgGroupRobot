from __future__ import annotations

import traceback

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import resolve_state_chat_id
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message import (
    sm_confirm_delete_keyboard,
    sm_day_period_end_keyboard,
    sm_day_period_start_keyboard,
    sm_edit_buttons_keyboard,
    sm_edit_media_keyboard,
    sm_edit_text_keyboard,
    sm_repeat_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.time_ui import build_copy_time_keyboard, build_datetime_prompt_text, next_top_of_hour
from backend.shared.time_helper import format_timestamp

log = structlog.get_logger(__name__)


class ScheduledMessageMutationMixin:
    async def create_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                await ModuleSettingsService.ensure(
                    session,
                    chat_id=target_chat_id,
                    chat_type="supergroup" if target_chat_id < 0 else "private",
                    title=update.effective_chat.title if update.effective_chat else None,
                    user_id=update.effective_user.id if update.effective_user else None,
                    username=update.effective_user.username if update.effective_user else None,
                    first_name=update.effective_user.first_name if update.effective_user else None,
                    last_name=update.effective_user.last_name if update.effective_user else None,
                    language_code=update.effective_user.language_code if update.effective_user else None,
                )
                task = await ScheduledMessageService.create_task(
                    session,
                    chat_id=target_chat_id,
                    created_by_user_id=update.effective_user.id if update.effective_user else 0,
                    title="定时消息",
                    enabled=True,
                )
            except Exception as exc:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 创建失败: {build_public_error_text(exc, fallback='请稍后重试')}",
                )
                return
            await session.commit()

        await self.show_detail(update, context, target_chat_id, str(task.task_id))

    async def set_field(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        field: str,
        value: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
                if field == "enabled":
                    task = await ScheduledMessageService.toggle_task_enabled(session, task_id, value == "1")
                elif field == "delete_previous":
                    task = await ScheduledMessageService.update_task_toggle_option(
                        session, task_id, "delete_previous", value == "1"
                    )
                elif field == "pin_message":
                    task = await ScheduledMessageService.update_task_toggle_option(
                        session, task_id, "pin_message", value == "1"
                    )
                elif field == "repeat":
                    task = await ScheduledMessageService.update_task_repeat(session, task_id, int(value))
                elif field == "day_start":
                    state_chat_id = resolve_state_chat_id(update, target_chat_id)
                    await ConversationStateService.start(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                        str(ConversationStateType.sm_edit_day_start),
                        {"task_id": task_id, "start_hour": int(value), "target_chat_id": target_chat_id},
                    )
                    await session.commit()
                    keyboard = sm_day_period_end_keyboard(target_chat_id, task_id, int(value))
                    await self.message_helper.safe_edit(
                        update,
                        text="请选择时段结束时间",
                        reply_markup=keyboard,
                    )
                    return
                elif field == "day_end":
                    state_chat_id = resolve_state_chat_id(update, target_chat_id)
                    state = await ConversationStateService.get(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                    if not state or "start_hour" not in state.state_data:
                        await session.rollback()
                        await self.message_helper.safe_edit(update, text="❌ 状态错误，请重新开始")
                        return

                    task = await ScheduledMessageService.update_task_day_period(
                        session,
                        task_id,
                        state.state_data["start_hour"],
                        int(value),
                    )
                    await ConversationStateService.clear(
                        session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                else:
                    await session.rollback()
                    await self.message_helper.safe_edit(update, text=f"❌ 未知字段: {field}")
                    return
            except Exception as exc:
                await session.rollback()
                log.error(
                    "设置任务字段失败",
                    task_id=task_id,
                    field=field,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 设置失败: {build_public_error_text(exc, fallback='请重新输入')}",
                )
                state_chat_id = resolve_state_chat_id(update, target_chat_id)
                async with db.session_factory() as cleanup_session:
                    await ConversationStateService.clear(
                        cleanup_session,
                        state_chat_id,
                        update.effective_user.id if update.effective_user else 0,
                    )
                    await cleanup_session.commit()
                return

            await session.commit()

        await self.show_detail(update, context, target_chat_id, task_id)

    async def edit_field(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
        field: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
            except Exception as exc:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ {build_public_error_text(exc, fallback='任务不可用')}",
                )
                return

            if field == "text":
                state_type = ConversationStateType.sm_edit_text
                text = "✏️ 编辑文本\n\n请输入新的文本内容，或输入 /clear 清空文本"
                keyboard = sm_edit_text_keyboard(target_chat_id, task_id)
            elif field == "media":
                state_type = ConversationStateType.sm_edit_media
                text = "🎬 编辑媒体\n\n请发送图片/视频/文档/贴纸/动画"
                keyboard = sm_edit_media_keyboard(target_chat_id, task_id)
            elif field == "buttons":
                state_type = ConversationStateType.sm_edit_buttons
                text = (
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
                keyboard = sm_edit_buttons_keyboard(target_chat_id, task_id)
            elif field == "repeat":
                task = await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
                await session.commit()
                keyboard = sm_repeat_keyboard(target_chat_id, task_id, task.repeat_interval_min)
                await self.message_helper.safe_edit(update, text="请选择轮播间隔", reply_markup=keyboard)
                return
            elif field == "day_period":
                state_type = ConversationStateType.sm_edit_day_start
                text = "🕐 选择时段开始时间"
                keyboard = sm_day_period_start_keyboard(target_chat_id, task_id)
            elif field == "start_at":
                state_type = ConversationStateType.sm_edit_start_at
                sample_dt = next_top_of_hour()
                sample_text = format_timestamp(int(sample_dt.timestamp()))
                text = build_datetime_prompt_text(
                    title="⏰ 定时消息 | 编辑开始时间",
                    sample_time_text=sample_text,
                    input_hint="👉🏻 现在输入定时开始时间:",
                    extra_tips=["发送 /clear 可清空开始时间"],
                )
                keyboard = build_copy_time_keyboard(f"sm:open:{target_chat_id}:{task_id}", sample_text)
            elif field == "end_at":
                state_type = ConversationStateType.sm_edit_end_at
                sample_dt = next_top_of_hour(days_offset=1)
                sample_text = format_timestamp(int(sample_dt.timestamp()))
                text = build_datetime_prompt_text(
                    title="⏰ 定时消息 | 编辑结束时间",
                    sample_time_text=sample_text,
                    input_hint="👉🏻 现在输入定时结束时间:",
                    extra_tips=["发送 /clear 可清空结束时间"],
                )
                keyboard = build_copy_time_keyboard(f"sm:open:{target_chat_id}:{task_id}", sample_text)
            else:
                await session.rollback()
                await self.message_helper.safe_edit(update, text=f"❌ 未知字段: {field}")
                return

            state_chat_id = resolve_state_chat_id(update, target_chat_id)
            await ConversationStateService.start(
                session,
                state_chat_id,
                update.effective_user.id if update.effective_user else 0,
                str(state_type),
                {"task_id": task_id, "target_chat_id": target_chat_id},
            )
            await session.commit()

        kwargs = {"text": text, "reply_markup": keyboard}
        if field in {"start_at", "end_at"}:
            kwargs["parse_mode"] = "HTML"
        await self.message_helper.safe_edit(update, **kwargs)

    async def confirm_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        keyboard = sm_confirm_delete_keyboard(target_chat_id, task_id)
        await self.message_helper.safe_edit(
            update,
            text="⚠️ 确认删除任务？\n\n此操作不可撤销",
            reply_markup=keyboard,
        )

    async def delete_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
                await ScheduledMessageService.delete_task(session, task_id)
            except Exception as exc:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ 删除失败: {build_public_error_text(exc, fallback='请稍后重试')}",
                )
                return
            await session.commit()

        await self.show_list(update, context, target_chat_id)

    async def cancel_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str,
    ) -> None:
        await self.show_detail(update, context, target_chat_id, task_id)

    async def cancel_operation(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        task_id: str | None = None,
    ) -> None:
        if update.effective_user:
            db: Database = context.application.bot_data["db"]
            async with db.session_factory() as session:
                state_chat_id = resolve_state_chat_id(update, target_chat_id)
                await ConversationStateService.clear(session, state_chat_id, update.effective_user.id)
                await session.commit()

        if task_id:
            await self.show_detail(update, context, target_chat_id, task_id)
        else:
            await self.show_list(update, context, target_chat_id)
