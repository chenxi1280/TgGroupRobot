from __future__ import annotations

import datetime as dt

from backend.features.admin.support import *
from backend.features.garage.forward_delivery_admin_service import (
    ACTION_CANCEL,
    ACTION_REPLAY,
    ACTION_RETRY,
    GarageOperation,
    GarageTaskFilter,
    apply_garage_operation,
    list_garage_tasks,
)
from backend.platform.delivery import DeliveryStatus


VISIBLE_STATUSES = (
    DeliveryStatus.retryable_failed,
    DeliveryStatus.permanent_failed,
    DeliveryStatus.uncertain,
)


class GarageForwardOperationsMixin:
    async def _show_garage_forward_tasks(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        status_code: str = "all",
    ) -> None:
        statuses = _statuses_for_code(status_code)
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            items = await list_garage_tasks(
                session,
                GarageTaskFilter(chat_id=chat_id, statuses=statuses),
            )
        await self.message_helper.safe_edit(
            update,
            _render_tasks(items),
            reply_markup=InlineKeyboardMarkup(_task_buttons(chat_id, items, status_code)),
        )

    async def _handle_garage_operation(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        action: str,
        delivery_id: int,
    ) -> None:
        if action == "replay":
            await self._show_garage_replay_confirmation(
                update,
                chat_id=chat_id,
                delivery_id=delivery_id,
            )
            return
        operation_action = ACTION_REPLAY if action == "replay_confirm" else action
        await self._apply_garage_operation(
            context,
            chat_id=chat_id,
            delivery_id=delivery_id,
            action=operation_action,
            confirmed=action == "replay_confirm",
        )
        await answer_callback_query_safely(update, "操作已保存")
        await self._show_garage_forward_tasks(update, context, chat_id=chat_id)

    async def _show_garage_replay_confirmation(
        self,
        update: Update,
        *,
        chat_id: int,
        delivery_id: int,
    ) -> None:
        text = "⚠️ Telegram 投递结果不确定，重放可能产生重复消息。请先人工核对目标群。"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "确认仍要重放",
                callback_data=f"gfw:ops:{chat_id}:replay_confirm:{delivery_id}",
            )],
            [InlineKeyboardButton("返回", callback_data=f"gfw:tasks:{chat_id}:a")],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _apply_garage_operation(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        delivery_id: int,
        action: str,
        confirmed: bool,
    ) -> None:
        operation = GarageOperation(
            delivery_id=delivery_id,
            chat_id=chat_id,
            action=action,
            now=dt.datetime.now(dt.UTC),
            confirmed=confirmed,
        )
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            await apply_garage_operation(session, operation)
            await session.commit()


def _statuses_for_code(code: str) -> tuple[DeliveryStatus, ...]:
    mapping = {
        "r": (DeliveryStatus.retryable_failed,),
        "p": (DeliveryStatus.permanent_failed,),
        "u": (DeliveryStatus.uncertain,),
        "a": VISIBLE_STATUSES,
        "all": VISIBLE_STATUSES,
    }
    return mapping.get(code, VISIBLE_STATUSES)


def _render_tasks(items) -> str:
    if not items:
        return "⚠️ 车库转发失败任务\n\n当前筛选下没有任务。"
    lines = ["⚠️ 车库转发失败任务", ""]
    for item in items:
        lines.append(
            f"#{item.id} 源 {item.source_channel_id} / 消息 {item.source_message_id}"
            f"\n状态：{item.status}｜尝试：{item.attempts}｜错误：{item.last_error or '-'}"
        )
    return "\n\n".join(lines)


def _task_buttons(chat_id: int, items, status_code: str):
    rows = [_filter_buttons(chat_id, status_code)]
    for item in items:
        action = "replay" if item.status == DeliveryStatus.uncertain.value else ACTION_RETRY
        label = "确认重放" if action == "replay" else "重试"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"gfw:ops:{chat_id}:{action}:{item.id}"),
            InlineKeyboardButton("取消", callback_data=f"gfw:ops:{chat_id}:{ACTION_CANCEL}:{item.id}"),
        ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"gfw:home:{chat_id}")])
    return rows


def _filter_buttons(chat_id: int, selected: str):
    labels = (("a", "全部"), ("r", "待重试"), ("p", "永久失败"), ("u", "不确定"))
    return [
        InlineKeyboardButton(
            ("✅" if selected == code else "") + label,
            callback_data=f"gfw:tasks:{chat_id}:{code}",
        )
        for code, label in labels
    ]
