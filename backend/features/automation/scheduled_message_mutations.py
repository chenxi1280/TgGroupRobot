from __future__ import annotations

import traceback

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_message_helpers import resolve_state_chat_id
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message import (
    sm_confirm_delete_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text
from backend.shared.services.base import ValidationError


from backend.features.automation.scheduled_message_mutation_helpers import (
    EditFieldRequest,
    SetFieldRequest,
    _apply_task_field,
    _build_task_buttons,
    _clear_failed_edit_state,
    _create_scheduled_task,
    _prepare_edit_field,
    _render_edit_spec,
    _send_task_preview,
    _task_has_sendable_content,
)

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
                task = await _create_scheduled_task(session, update, target_chat_id)
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
        *, task_id: str,
        field: str,
        value: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            request = SetFieldRequest(
                self,
                update,
                context,
                session,
                target_chat_id,
                task_id,
                field,
                value,
            )
            try:
                task = await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
                show_detail = await _apply_task_field(request, task)
                if not show_detail:
                    return
            except ValidationError as exc:
                await session.rollback()
                await self.message_helper.safe_edit(update, text=f"❌ {exc}")
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
                await _clear_failed_edit_state(db, request)
                return

            await session.commit()

        await self.show_detail(update, context, target_chat_id, task_id)

    async def edit_field(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, task_id: str,
        field: str,
    ) -> None:
        if not await self._check_permission(update, context, target_chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
            except Exception as exc:
                await session.rollback()
                await self.message_helper.safe_edit(
                    update,
                    text=f"❌ {build_public_error_text(exc, fallback='任务不可用')}",
                )
                return
            try:
                spec = await _prepare_edit_field(
                    EditFieldRequest(
                        self,
                        update,
                        session,
                        task,
                        target_chat_id,
                        task_id,
                        field,
                    )
                )
            except ValidationError as exc:
                await session.rollback()
                await self.message_helper.safe_edit(update, text=f"❌ {exc}")
                return
            await session.commit()

        if spec is None:
            return
        await _render_edit_spec(self, update, spec)

    async def preview_task(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, task_id: str,
    ) -> None:
        if update.effective_user is None:
            return
        if not await self._check_permission(update, context, target_chat_id):
            await answer_callback_query_safely(update, "❌ 需要管理员权限", show_alert=True)
            return

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                task = await ScheduledMessageService.get_task_in_chat_or_404(session, target_chat_id, task_id)
            except Exception as exc:
                await session.rollback()
                await answer_callback_query_safely(update, build_public_error_text(exc, fallback="任务不可用"), show_alert=True)
                return
            await session.commit()

        if not _task_has_sendable_content(task):
            await answer_callback_query_safely(update, "请先设置文本或封面", show_alert=True)
            await self.show_detail(
                update,
                context,
                target_chat_id,
                task_id,
                toast="❌ 预览失败：请先设置文本或封面。下面可直接补齐后再预览。",
            )
            return

        try:
            await _send_task_preview(
                context,
                update.effective_user.id,
                task=task,
                reply_markup=_build_task_buttons(task.buttons),
            )
        except Exception as exc:
            log.warning("scheduled_message_preview_failed", task_id=task_id, error=str(exc))
            await answer_callback_query_safely(update, "预览发送失败，请检查封面或文本配置", show_alert=True)
            return

        await answer_callback_query_safely(update, "预览已发送到当前私聊", show_alert=False)

    async def confirm_delete(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, task_id: str,
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
        *, task_id: str,
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
        *, task_id: str,
    ) -> None:
        await self.show_detail(update, context, target_chat_id, task_id)

    async def cancel_operation(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        *, task_id: str | None = None,
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
