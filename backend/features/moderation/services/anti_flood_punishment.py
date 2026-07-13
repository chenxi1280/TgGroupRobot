from __future__ import annotations

import structlog
from telegram.ext import ContextTypes

from backend.shared.services.action_executor import ActionExecutor

log = structlog.get_logger(__name__)


async def _execute_flood_action(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    actor_id: int,
    *,
    action: str,
    tracker,
    mute_seconds: int,
    sender_chat_id: int | None,
    reason: str | None,
) -> bool:
    if action == "delete":
        return True
    if action == "mute" and await tracker.is_muted(chat_id, actor_id):
        return True
    if action == "mute":
        action_result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=actor_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
    else:
        action_result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=actor_id,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
    if action == "mute" and action_result.applied:
        await tracker.mark_muted(chat_id, actor_id, mute_seconds)
    return action_result.applied


async def execute_flood_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    actor_id: int,
    *,
    action: str,
    tracker,
    message_ids: list[int] | None = None,
    cleanup_messages: bool = False,
    mute_seconds: int = 60,
    sender_chat_id: int | None = None,
    reason: str | None = None,
) -> bool:
    """通过统一动作执行器清理消息并执行刷屏处罚。"""
    try:
        if cleanup_messages or action == "delete":
            await ActionExecutor.delete_many(
                context,
                chat_id=chat_id,
                message_ids=message_ids or [],
            )
        return await _execute_flood_action(
            context,
            chat_id,
            actor_id,
            action=action,
            tracker=tracker,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
    except Exception as exc:
        log.warning(
            "anti_flood_punishment_failed",
            chat_id=chat_id,
            actor_id=actor_id,
            action=action,
            error=str(exc),
        )
        return False
