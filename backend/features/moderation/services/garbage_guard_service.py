from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import structlog
from telegram import Message
from telegram.ext import ContextTypes

from backend.features.moderation.services.garbage_guard_detection import (
    detect_garbage_violation as detect_garbage_violation,
)
from backend.features.moderation.services.garbage_guard_rules import (
    RULE_DEFINITIONS,
    get_rule_config,
)
from backend.features.moderation.services.garbage_guard_types import (
    GarbagePunishmentResult as GarbagePunishmentResult,
    GarbageViolation as GarbageViolation,
)
from backend.features.moderation.services.moderation_service import (
    build_moderation_notice,
    record_violation,
    resolve_effective_action,
    send_temporary_notice,
)
from backend.features.moderation.services.moderation_warning_service import WarningResult, add_warning
from backend.platform.db.schema.models.core import ChatSettings
from backend.shared.services.action_executor import ActionExecutionResult, ActionExecutor


GARBAGE_ACTION_FAILURE_NOTIFY_SECONDS = 300
log = structlog.get_logger(__name__)


def _action_part_label(action: str) -> str:
    labels = {
        "delete": "删除消息",
        "warn": "警告成员",
        "mute": "禁言成员",
        "ban": "封禁成员",
        "kick": "踢出成员",
        "notice": "提示消息",
        "none": "未执行处罚",
    }
    return labels.get(action, action)


def format_garbage_action_label(action_parts: list[str]) -> str:
    if not action_parts:
        return _action_part_label("none")
    return " + ".join(_action_part_label(part) for part in action_parts)


async def notify_garbage_action_failure(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    rule_id: str,
    *, detail: str,
) -> None:
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    cache_key = (chat_id, rule_id)
    now = dt.datetime.now(dt.UTC)
    if isinstance(bot_data, dict):
        cache = bot_data.setdefault("_garbage_action_failure_notified_at", {})
        last_notified = cache.get(cache_key)
        if isinstance(last_notified, dt.datetime):
            elapsed = (now - last_notified).total_seconds()
            if elapsed < GARBAGE_ACTION_FAILURE_NOTIFY_SECONDS:
                return
        cache[cache_key] = now

    text = (
        "⚠️ 垃圾防护已命中，但处罚动作没有成功执行。\n"
        "请检查机器人是否仍是管理员，并拥有删除消息/禁言权限；也请重启机器人加载最新代码。"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        log.warning(
            "garbage_action_failure_notify_failed",
            chat_id=chat_id,
            rule_id=rule_id,
            detail=detail,
            error=str(exc),
        )


async def delete_garbage_message_fallback(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message: Message,
    *, rule_id: str,
    detail: str,
) -> bool:
    try:
        await message.delete()
        log.warning(
            "garbage_delete_fallback_succeeded",
            chat_id=chat_id,
            rule_id=rule_id,
            message_id=getattr(message, "message_id", None),
            detail=detail,
        )
        return True
    except Exception as exc:
        log.warning(
            "garbage_delete_fallback_failed",
            chat_id=chat_id,
            rule_id=rule_id,
            message_id=getattr(message, "message_id", None),
            detail=detail,
            error=str(exc),
        )
        await notify_garbage_action_failure(context, chat_id, rule_id, detail=detail)
        return False


def _garbage_fallback_needed(result, delete_message_enabled: bool) -> bool:
    delete_failed = bool(getattr(result, "delete_requested", False)) and not bool(
        getattr(result, "delete_applied", False)
    )
    return delete_message_enabled and (delete_failed or not bool(getattr(result, "applied", False)))


def _garbage_result_unresolved(result, *, fallback_succeeded: bool) -> bool:
    escalation_failed = bool(getattr(result, "escalation_requested", False)) and not bool(
        getattr(result, "escalation_applied", False)
    )
    delete_only_recovered = fallback_succeeded and not escalation_failed
    return escalation_failed or (not bool(getattr(result, "applied", False)) and not delete_only_recovered)


async def handle_garbage_result_fallback(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message: Message,
    rule_id: str,
    detail: str,
    result,
    delete_message_enabled: bool,
) -> None:
    applied = bool(getattr(result, "applied", False))
    fallback_needed = _garbage_fallback_needed(result, delete_message_enabled)
    fallback_succeeded = False
    if fallback_needed:
        fallback_succeeded = await delete_garbage_message_fallback(
            context,
            chat_id,
            message,
            rule_id=rule_id,
            detail=detail,
        )
    if not applied and not fallback_needed:
        await notify_garbage_action_failure(context, chat_id, rule_id, detail=detail)
        return
    fallback_failed = fallback_needed and not fallback_succeeded
    if _garbage_result_unresolved(result, fallback_succeeded=fallback_succeeded) and not fallback_failed:
        await notify_garbage_action_failure(context, chat_id, rule_id, detail=detail)


async def execute_garbage_action_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    chat_id: int,
    user_id: int,
    rule_id: str,
    detail: str,
    actor_user_id: int | None = None,
    message_id: int | None = None,
    mute_seconds: int | None = None,
    sender_chat_id: int | None = None,
) -> ActionExecutionResult:
    try:
        return await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            message_id=message_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=detail or rule_id,
        )
    except Exception as exc:
        log.warning(
            "garbage_action_execute_failed",
            chat_id=chat_id,
            user_id=user_id,
            rule_id=rule_id,
            action=action,
            detail=detail,
            error=str(exc),
        )
        return ActionExecutionResult(action=action, applied=False, detail=str(exc))


@dataclass(frozen=True)
class _EscalationResult:
    requested: bool = False
    applied: bool = False
    action: str | None = None


async def _delete_garbage_messages(context: ContextTypes.DEFAULT_TYPE, *, config: dict, chat_id: int, message_ids: list[int]) -> tuple[bool, bool]:
    requested = bool(config.get("delete_message")) and bool(message_ids)
    if not requested:
        return False, False
    result = await ActionExecutor.delete_many(context, chat_id=chat_id, message_ids=message_ids)
    return True, bool(result.applied)


async def _add_garbage_warning(session, *, config: dict, chat_id: int, user_id: int, rule_id: str) -> tuple[WarningResult | None, bool]:
    if not bool(config.get("warn_enabled")) or user_id <= 0:
        return None, True
    warning = await add_warning(
        session,
        chat_id=chat_id,
        user_id=user_id,
        rule=rule_id,
        threshold=int(config.get("warn_threshold", 3) or 3),
    )
    return warning, warning.threshold_reached


def _requested_escalation(config: dict, threshold_reached: bool) -> str | None:
    should_escalate = threshold_reached or not bool(config.get("warn_enabled"))
    if not should_escalate:
        return None
    if bool(config.get("kick_enabled")):
        return "kick"
    if bool(config.get("mute_enabled")):
        return "mute"
    return None


async def _escalate_garbage_action(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: dict,
    requested_action: str | None,
    chat_id: int,
    user_id: int,
    rule_id: str,
    detail: str,
    actor_user_id: int | None,
    message_id: int | None,
    sender_chat_id: int | None,
) -> _EscalationResult:
    if requested_action is None:
        return _EscalationResult()
    resolution = await resolve_effective_action(
        context,
        chat_id,
        user_id,
        requested_action=requested_action,
        sender_chat_id=sender_chat_id,
    )
    result = await execute_garbage_action_safely(
        context,
        action=resolution.action,
        chat_id=chat_id,
        user_id=user_id,
        rule_id=rule_id,
        detail=detail,
        actor_user_id=actor_user_id,
        message_id=message_id,
        mute_seconds=int(config.get("mute_seconds", 3_600) or 3_600) if requested_action == "mute" else None,
        sender_chat_id=sender_chat_id,
    )
    return _EscalationResult(requested=True, applied=bool(result.applied), action=resolution.action)


async def _record_garbage_violation(
    session,
    *,
    chat_id: int,
    user_id: int,
    message_id: int | None,
    rule_id: str,
    detail: str,
    action_label: str,
) -> None:
    if user_id <= 0:
        return
    await record_violation(
        session,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        rule=rule_id,
        detail=detail,
        action=action_label[:32],
    )


def _garbage_notice_text(config: dict, *, rule_id: str, target_label: str, detail: str, action_label: str, warning) -> str:
    configured_text = str(config.get("notice_text") or "").strip()
    if configured_text:
        return configured_text
    warning_text = f"警告次数: {warning.count}/{warning.threshold}" if warning is not None else ""
    rule_label = RULE_DEFINITIONS[rule_id].label if rule_id in RULE_DEFINITIONS else "垃圾防护"
    return build_moderation_notice(
        f"🚫 {rule_label}已处理",
        target_label,
        detail,
        action_label=action_label,
        extra_lines=[warning_text] if warning_text else None,
    )


async def _send_garbage_notice(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: dict,
    chat_id: int,
    rule_id: str,
    target_label: str,
    detail: str,
    action_label: str,
    warning,
) -> None:
    if not bool(config.get("notice_enabled")):
        return
    text = _garbage_notice_text(
        config,
        rule_id=rule_id,
        target_label=target_label,
        detail=detail,
        action_label=action_label,
        warning=warning,
    )
    await send_temporary_notice(
        context.bot,
        chat_id=chat_id,
        text=text,
        delete_after_seconds=int(config.get("notice_delete_seconds", 10) or 10),
    )


def _punishment_result(
    *,
    action_label: str,
    warning: WarningResult | None,
    threshold_reached: bool,
    delete_requested: bool,
    delete_applied: bool,
    escalation: _EscalationResult,
) -> GarbagePunishmentResult:
    return GarbagePunishmentResult(
        applied=delete_applied or warning is not None or escalation.applied,
        action_label=action_label,
        warning=warning,
        threshold_reached=threshold_reached,
        delete_requested=delete_requested,
        delete_applied=delete_applied,
        escalation_requested=escalation.requested,
        escalation_applied=escalation.applied,
    )


async def apply_garbage_punishment(
    context: ContextTypes.DEFAULT_TYPE, session, *, settings: ChatSettings, chat_id: int, target_user_id: int,
    target_label: str, rule_id: str, detail: str, message_ids: list[int] | None = None,
    sender_chat_id: int | None = None, actor_user_id: int | None = None, record_message_id: int | None = None,
) -> GarbagePunishmentResult:
    config = get_rule_config(settings, rule_id)
    normalized_message_ids = sorted(set(message_ids or []))
    delete_requested, delete_applied = await _delete_garbage_messages(
        context, config=config, chat_id=chat_id, message_ids=normalized_message_ids,
    )
    warning_result, threshold_reached = await _add_garbage_warning(
        session,
        config=config,
        chat_id=chat_id,
        user_id=target_user_id,
        rule_id=rule_id,
    )
    message_id = normalized_message_ids[0] if normalized_message_ids else record_message_id
    escalation = await _escalate_garbage_action(
        context,
        config=config,
        requested_action=_requested_escalation(config, threshold_reached),
        chat_id=chat_id,
        user_id=target_user_id,
        rule_id=rule_id,
        detail=detail,
        actor_user_id=actor_user_id,
        message_id=message_id,
        sender_chat_id=sender_chat_id,
    )
    action_parts = [part for part in ("delete" if delete_requested else None, "warn" if warning_result else None, escalation.action) if part]
    action_label = format_garbage_action_label(action_parts)
    await _record_garbage_violation(
        session, chat_id=chat_id, user_id=target_user_id, message_id=record_message_id,
        rule_id=rule_id, detail=detail, action_label=action_label,
    )
    await _send_garbage_notice(
        context, config=config, chat_id=chat_id, rule_id=rule_id, target_label=target_label,
        detail=detail, action_label=action_label, warning=warning_result,
    )
    return _punishment_result(
        action_label=action_label,
        warning=warning_result,
        threshold_reached=threshold_reached,
        delete_requested=delete_requested,
        delete_applied=delete_applied,
        escalation=escalation,
    )
