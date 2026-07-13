from __future__ import annotations

import datetime as dt

from backend.features.admin.support import *
from backend.features.verification.timeout_admin_service import (
    ACTION_CANCEL,
    ACTION_REPLAY,
    ACTION_RETRY,
    TimeoutOperation,
    TimeoutTaskFilter,
    apply_timeout_operation,
    list_timeout_tasks,
)
from backend.platform.delivery import DeliveryStatus


VISIBLE_TIMEOUT_STATUSES = (
    DeliveryStatus.retryable_failed,
    DeliveryStatus.permanent_failed,
    DeliveryStatus.uncertain,
)


class VerificationTimeoutOperationsMixin:
    async def _show_verification_timeout_tasks(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            items = await list_timeout_tasks(
                session,
                TimeoutTaskFilter(chat_id=chat_id, statuses=VISIBLE_TIMEOUT_STATUSES),
            )
        await self.message_helper.safe_edit(
            update,
            _render_timeout_tasks(items),
            reply_markup=InlineKeyboardMarkup(_timeout_task_buttons(chat_id, items)),
        )

    async def _handle_verification_timeout_action(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        action: str,
        challenge_key: str,
    ) -> None:
        if action in {"", "home"}:
            await self._show_verification_timeout_tasks(update, context, chat_id=chat_id)
            return
        challenge_id = _parse_challenge_id(challenge_key)
        if action == "replay":
            await self._show_timeout_replay_confirmation(
                update,
                chat_id=chat_id,
                challenge_id=challenge_id,
            )
            return
        await self._apply_timeout_action(
            context,
            chat_id=chat_id,
            challenge_id=challenge_id,
            action=action,
        )
        await answer_callback_query_safely(update, "操作已保存", show_alert=False)
        await self._show_verification_timeout_tasks(update, context, chat_id=chat_id)

    async def _show_timeout_replay_confirmation(
        self,
        update: Update,
        *,
        chat_id: int,
        challenge_id: int,
    ) -> None:
        text = "⚠️ Telegram 结果不确定，重放可能造成重复处罚。确认已人工核对后再继续。"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "确认重放",
                callback_data=f"adm:vfy_home:{chat_id}:timeouts:{ACTION_REPLAY}:{challenge_id}",
            )],
            [InlineKeyboardButton(
                "返回",
                callback_data=f"adm:vfy_home:{chat_id}:timeouts",
            )],
        ])
        await self.message_helper.safe_edit(update, text, reply_markup=keyboard)

    async def _apply_timeout_action(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        challenge_id: int,
        action: str,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        operation = TimeoutOperation(
            challenge_id=challenge_id,
            chat_id=chat_id,
            action=action,
            now=dt.datetime.now(dt.UTC),
        )
        async with db.session_factory() as session:
            await apply_timeout_operation(session, operation)
            await session.commit()


def _parse_challenge_id(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError("超时任务编号无效") from exc


def _render_timeout_tasks(items) -> str:
    if not items:
        return "⚠️ 超时失败任务\n\n当前没有待处理任务。"
    lines = ["⚠️ 超时失败任务", ""]
    for item in items:
        lines.append(
            f"#{item.id} 用户 {item.user_id} | {item.status} | {item.action or 'none'} "
            f"| 尝试 {item.attempts} 次\n错误：{item.last_error or '-'}"
        )
    return "\n\n".join(lines)


def _timeout_task_buttons(chat_id: int, items) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        primary = "replay" if item.status == DeliveryStatus.uncertain.value else ACTION_RETRY
        label = "确认重放" if primary == "replay" else "重试"
        rows.append([
            InlineKeyboardButton(
                label,
                callback_data=f"adm:vfy_home:{chat_id}:timeouts:{primary}:{item.id}",
            ),
            InlineKeyboardButton(
                "关闭",
                callback_data=f"adm:vfy_home:{chat_id}:timeouts:{ACTION_CANCEL}:{item.id}",
            ),
        ])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:verification:{chat_id}")])
    return rows
