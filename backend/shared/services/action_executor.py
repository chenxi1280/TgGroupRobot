from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

import structlog
from telegram import ChatPermissions
from telegram.ext import ContextTypes

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ActionExecutionResult:
    action: str
    applied: bool
    detail: str


class ActionExecutor:
    """统一处罚执行器，收敛删除/禁言/封禁等常见动作。"""

    @staticmethod
    async def execute(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        action: str,
        chat_id: int,
        user_id: int,
        reason: str | None = None,
        actor_user_id: int | None = None,
        message_id: int | None = None,
        mute_seconds: int | None = None,
        sender_chat_id: int | None = None,
    ) -> ActionExecutionResult:
        normalized = action.strip().lower()
        detail = reason or normalized

        log.info(
            "action_executor_execute",
            action=normalized,
            chat_id=chat_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            message_id=message_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )

        if normalized in {"none", "noop", ""}:
            return ActionExecutionResult(action=normalized or "none", applied=False, detail="skipped")
        if normalized == "delete":
            return await ActionExecutor._delete_message(
                context, chat_id, message_id=message_id, detail=detail
            )
        if sender_chat_id is not None and normalized in {"mute", "ban", "kick"}:
            return await ActionExecutor._delete_sender_chat_message(
                context,
                normalized,
                chat_id=chat_id,
                message_id=message_id,
            )
        return await ActionExecutor._execute_member_action(
            context,
            normalized,
            chat_id=chat_id,
            user_id=user_id,
            mute_seconds=mute_seconds,
            detail=detail,
        )

    @staticmethod
    async def _delete_message(
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        *,
        message_id: int | None,
        detail: str,
    ) -> ActionExecutionResult:
        if message_id is None:
            return ActionExecutionResult(
                action="delete", applied=False, detail="missing_message_id"
            )
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        return ActionExecutionResult(action="delete", applied=True, detail=detail)

    @staticmethod
    async def _delete_sender_chat_message(
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        *,
        chat_id: int,
        message_id: int | None,
    ) -> ActionExecutionResult:
        if message_id is None:
            return ActionExecutionResult(
                action=action,
                applied=False,
                detail="sender_chat_requires_delete_message_id",
            )
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        return ActionExecutionResult(
            action="delete", applied=True, detail="sender_chat_fallback_delete"
        )

    @staticmethod
    async def _execute_member_action(
        context: ContextTypes.DEFAULT_TYPE,
        action: str,
        *,
        chat_id: int,
        user_id: int,
        mute_seconds: int | None,
        detail: str,
    ) -> ActionExecutionResult:
        if action == "mute":
            until_date = None
            if mute_seconds and mute_seconds > 0:
                until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=mute_seconds)
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date,
            )
        elif action in {"kick", "ban"}:
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            if action == "kick":
                await context.bot.unban_chat_member(
                    chat_id=chat_id, user_id=user_id, only_if_banned=True
                )
        else:
            raise ValueError(f"unsupported action: {action}")
        return ActionExecutionResult(action=action, applied=True, detail=detail)

    @staticmethod
    async def delete_many(
        context: ContextTypes.DEFAULT_TYPE,
        *,
        chat_id: int,
        message_ids: Iterable[int],
    ) -> ActionExecutionResult:
        deleted = 0
        failed = 0
        for message_id in message_ids:
            if not message_id:
                continue
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                deleted += 1
            except Exception as exc:
                failed += 1
                log.warning("action_executor_delete_many_failed", chat_id=chat_id, message_id=message_id, error=str(exc))

        return ActionExecutionResult(
            action="delete_many",
            applied=deleted > 0,
            detail=f"deleted={deleted},failed={failed}",
        )
