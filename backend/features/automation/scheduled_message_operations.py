from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.automation.scheduled_occurrence_admin_service import (
    cancel_occurrence,
    list_task_occurrences,
    load_task_for_history,
    replay_uncertain_occurrence,
    retry_occurrence,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.scheduled_message import ScheduledMessageLog, ScheduledMessageTask
from backend.platform.delivery import DeliveryStatus
from backend.platform.telegram.errors import build_public_error_text
from backend.shared.time_helper import format_timestamp

STATUS_LABELS = {
    DeliveryStatus.pending.value: "待执行",
    DeliveryStatus.processing.value: "执行中",
    DeliveryStatus.retryable_failed.value: "等待重试",
    DeliveryStatus.succeeded.value: "成功",
    DeliveryStatus.permanent_failed.value: "永久失败",
    DeliveryStatus.uncertain.value: "结果不确定",
    DeliveryStatus.cancelled.value: "已取消",
}


class ScheduledMessageOperationsMixin:
    async def show_occurrence_history(self, update, context, chat_id: int, *, task_key: str) -> None:
        if not await self._check_permission(update, context, chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            task = await load_task_for_history(session, chat_id, task_key)
            occurrences = await list_task_occurrences(session, task.task_id)
            await session.commit()
        text = _format_history(task, occurrences)
        keyboard = _history_keyboard(chat_id, task.short_id, occurrences)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def operate_occurrence(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        occurrence_id: int,
        action: str,
    ) -> None:
        if not await self._check_permission(update, context, chat_id):
            await self.message_helper.safe_edit(update, text="❌ 需要管理员权限")
            return
        try:
            task_key = await self._apply_operation(context, chat_id, occurrence_id, action=action)
        except Exception as exc:
            await self.message_helper.safe_edit(update, text=f"❌ {build_public_error_text(exc)}")
            return
        await self.show_occurrence_history(update, context, chat_id, task_key=task_key)

    async def confirm_uncertain_replay(self, update, context, *, chat_id: int, occurrence_id: int) -> None:
        text = "⚠️ 该次发送结果未知，重放可能产生重复消息。\n\n确认仍要人工重放吗？"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            "确认重放",
            callback_data=f"sm:occ_replay_do:{chat_id}:{occurrence_id}",
        )], [InlineKeyboardButton("取消", callback_data=f"sm:list:{chat_id}:0")]])
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def _apply_operation(self, context, chat_id: int, occurrence_id: int, *, action: str) -> str:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await _mutate_occurrence(session, occurrence_id, chat_id, action=action)
            occurrence = await _load_occurrence(session, occurrence_id)
            task = await session.get(ScheduledMessageTask, occurrence.task_id)
            if task is None:
                raise RuntimeError("定时消息任务不存在")
            await session.commit()
        return str(task.short_id)


async def _load_occurrence(session, occurrence_id: int):
    occurrence = await session.get(ScheduledMessageLog, occurrence_id)
    if occurrence is None:
        raise RuntimeError("执行记录不存在")
    return occurrence


async def _mutate_occurrence(session, occurrence_id: int, chat_id: int, *, action: str) -> None:
    operations = {
        "retry": retry_occurrence,
        "cancel": cancel_occurrence,
        "replay": replay_uncertain_occurrence,
    }
    operation = operations.get(action)
    if operation is None:
        raise ValueError(f"unknown occurrence operation: {action}")
    await operation(session, occurrence_id, chat_id)


def _occurrence_keyboard_row(chat_id: int, item) -> list[InlineKeyboardButton] | None:
    if item.status in {DeliveryStatus.retryable_failed.value, DeliveryStatus.permanent_failed.value}:
        return [
            InlineKeyboardButton(f"重试 #{item.id}", callback_data=f"sm:occ_retry:{chat_id}:{item.id}"),
            InlineKeyboardButton("取消", callback_data=f"sm:occ_cancel:{chat_id}:{item.id}"),
        ]
    if item.status == DeliveryStatus.uncertain.value:
        return [
            InlineKeyboardButton(f"确认重放 #{item.id}", callback_data=f"sm:occ_replay_confirm:{chat_id}:{item.id}"),
            InlineKeyboardButton("取消", callback_data=f"sm:occ_cancel:{chat_id}:{item.id}"),
        ]
    if item.status == DeliveryStatus.pending.value:
        return [InlineKeyboardButton(f"取消 #{item.id}", callback_data=f"sm:occ_cancel:{chat_id}:{item.id}")]
    return None


def _format_history(task, occurrences) -> str:
    lines = [f"⏱️ 定时消息执行历史\n\n#{task.short_id} {task.title}"]
    for item in occurrences:
        status = STATUS_LABELS.get(item.status, item.status)
        scheduled = format_timestamp(item.scheduled_for)
        detail = item.error_code or item.error_message or "-"
        lines.append(f"\n#{item.id} {status} | 计划 {scheduled}\n尝试 {item.attempt_count} | {detail}")
    if not occurrences:
        lines.append("\n暂无执行记录")
    return "\n".join(lines)


def _history_keyboard(chat_id: int, task_key: str, occurrences) -> InlineKeyboardMarkup:
    rows = []
    for item in occurrences:
        row = _occurrence_keyboard_row(chat_id, item)
        if row is not None:
            rows.append(row)
    rows.append([InlineKeyboardButton("🔙 返回任务", callback_data=f"sm:open:{chat_id}:{task_key}")])
    return InlineKeyboardMarkup(rows)
