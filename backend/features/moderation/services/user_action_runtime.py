from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from telegram.ext import ContextTypes

from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.permission_service import get_bot_admin_ids

log = structlog.get_logger(__name__)

USER_ACTION_DIAGNOSTIC_SECONDS = 300


@dataclass(frozen=True)
class UserActionResult:
    feature: str
    matched: bool = True
    stopped: bool = True
    delete_requested: bool = False
    delete_applied: bool = False
    punishment_requested: bool = False
    punishment_applied: bool = False
    action: str = "none"
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applied(self) -> bool:
        return self.delete_applied or self.punishment_applied

    @property
    def failed(self) -> bool:
        return bool(self.failures)


def _context_chat_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    chat_data = getattr(context, "chat_data", None)
    if isinstance(chat_data, dict):
        value = chat_data.get("chat_id")
        if isinstance(value, int):
            return value
    return None


def _diagnostic_cache(context: ContextTypes.DEFAULT_TYPE) -> dict:
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    if isinstance(bot_data, dict):
        return bot_data.setdefault("_user_action_diagnostic_notified_at", {})
    return {}


async def _resolve_admin_targets(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> list[int]:
    targets = sorted(get_bot_admin_ids(context))
    if targets:
        return targets[:5]

    bot = getattr(context, "bot", None)
    if bot is None or not hasattr(bot, "get_chat_administrators"):
        return []
    try:
        admins = await bot.get_chat_administrators(chat_id=chat_id)
    except Exception as exc:
        log.warning("user_action_admin_resolve_failed", chat_id=chat_id, error=str(exc))
        return []

    resolved: list[int] = []
    for member in admins:
        user = getattr(member, "user", None)
        user_id = getattr(user, "id", None)
        if isinstance(user_id, int) and user_id not in resolved:
            resolved.append(user_id)
        if len(resolved) >= 5:
            break
    return resolved


async def notify_user_action_failure(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    feature: str,
    detail: str,
    failures: Iterable[str],
) -> None:
    failure_text = "；".join(str(item) for item in failures if str(item).strip())
    if not failure_text:
        return

    cache = _diagnostic_cache(context)
    cache_key = (chat_id, feature, failure_text)
    now = dt.datetime.now(dt.UTC)
    last_notified = cache.get(cache_key)
    if isinstance(last_notified, dt.datetime):
        if (now - last_notified).total_seconds() < USER_ACTION_DIAGNOSTIC_SECONDS:
            return

    text = (
        f"⚠️ {feature}已命中，但用户处置动作没有成功执行。\n"
        f"群组：{chat_id}\n"
        f"原因：{failure_text}\n"
        f"说明：{detail}\n"
        "请检查机器人是否仍是管理员，并拥有删除消息/禁言/封禁权限。"
    )
    targets = await _resolve_admin_targets(context, chat_id)
    if not targets:
        log.warning(
            "user_action_failure_no_admin_target",
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failure_text,
        )
        return

    delivered = 0
    for admin_id in targets:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
            delivered += 1
        except Exception as exc:
            log.warning(
                "user_action_failure_notify_failed",
                chat_id=chat_id,
                admin_id=admin_id,
                feature=feature,
            error=str(exc),
        )
    if delivered:
        cache[cache_key] = now
        log.warning(
            "user_action_failure_notified",
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failure_text,
            delivered=delivered,
        )


async def delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message,
    feature: str,
    detail: str,
) -> UserActionResult:
    message_id = getattr(message, "message_id", None)
    failures: list[str] = []
    delete_applied = False

    if message_id is not None:
        try:
            result = await ActionExecutor.delete_many(context, chat_id=chat_id, message_ids=[int(message_id)])
            delete_applied = bool(result.applied)
            if not delete_applied:
                failures.append(result.detail or "delete_many_not_applied")
        except Exception as exc:
            failures.append(str(exc))
            log.warning(
                "user_action_delete_many_failed",
                chat_id=chat_id,
                message_id=message_id,
                feature=feature,
                error=str(exc),
            )
    else:
        failures.append("missing_message_id")

    if not delete_applied and hasattr(message, "delete"):
        try:
            await message.delete()
            delete_applied = True
            failures.clear()
            log.warning(
                "user_action_delete_fallback_succeeded",
                chat_id=chat_id,
                message_id=message_id,
                feature=feature,
            )
        except Exception as exc:
            failures.append(str(exc))
            log.warning(
                "user_action_delete_fallback_failed",
                chat_id=chat_id,
                message_id=message_id,
                feature=feature,
                error=str(exc),
            )

    if failures:
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    return UserActionResult(
        feature=feature,
        delete_requested=True,
        delete_applied=delete_applied,
        action="delete",
        failures=tuple(failures),
    )


async def execute_user_action(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    feature: str,
    chat_id: int,
    user_id: int,
    action: str = "none",
    detail: str,
    message=None,
    message_id: int | None = None,
    delete_message: bool = False,
    mute_seconds: int | None = None,
    actor_user_id: int | None = None,
    sender_chat_id: int | None = None,
    raise_on_failure: bool = False,
) -> UserActionResult:
    failures: list[str] = []
    delete_requested = bool(delete_message)
    delete_applied = False
    punishment_requested = action not in {"", "none", "noop", "delete"}
    punishment_applied = False

    if delete_message and message is not None:
        delete_result = await delete_message_safely(
            context,
            chat_id=chat_id,
            message=message,
            feature=feature,
            detail=detail,
        )
        delete_applied = delete_result.delete_applied
        failures.extend(delete_result.failures)
    elif delete_message:
        target_message_id = message_id
        try:
            result = await ActionExecutor.delete_many(
                context,
                chat_id=chat_id,
                message_ids=[target_message_id] if target_message_id is not None else [],
            )
            delete_applied = bool(result.applied)
            if not delete_applied:
                failures.append(result.detail or "delete_not_applied")
        except Exception as exc:
            failures.append(str(exc))

    normalized_action = (action or "none").strip().lower()
    if normalized_action == "delete":
        punishment_requested = False
    elif normalized_action not in {"", "none", "noop"}:
        try:
            target_message_id = message_id if message_id is not None else getattr(message, "message_id", None)
            result = await ActionExecutor.execute(
                context,
                action=normalized_action,
                chat_id=chat_id,
                user_id=user_id,
                actor_user_id=actor_user_id,
                message_id=target_message_id,
                mute_seconds=mute_seconds,
                sender_chat_id=sender_chat_id,
                reason=detail,
            )
            punishment_applied = bool(result.applied)
            if not punishment_applied:
                failures.append(result.detail or f"{normalized_action}_not_applied")
        except Exception as exc:
            failures.append(str(exc))
            log.warning(
                "user_action_punishment_failed",
                chat_id=chat_id,
                user_id=user_id,
                action=normalized_action,
                feature=feature,
                error=str(exc),
            )

    if failures:
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    result = UserActionResult(
        feature=feature,
        delete_requested=delete_requested,
        delete_applied=delete_applied,
        punishment_requested=punishment_requested,
        punishment_applied=punishment_applied,
        action=normalized_action or "none",
        failures=tuple(failures),
    )
    if raise_on_failure and result.failed:
        raise RuntimeError("; ".join(result.failures))
    return result


async def restrict_user_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    feature: str,
    chat_id: int,
    user_id: int,
    permissions,
    detail: str,
    until_date=None,
    raise_on_failure: bool = False,
) -> UserActionResult:
    failures: list[str] = []
    try:
        kwargs = {"chat_id": chat_id, "user_id": user_id, "permissions": permissions}
        if until_date is not None:
            kwargs["until_date"] = until_date
        await context.bot.restrict_chat_member(**kwargs)
        punishment_applied = True
    except Exception as exc:
        punishment_applied = False
        failures.append(str(exc))
        log.warning(
            "user_action_restrict_failed",
            chat_id=chat_id,
            user_id=user_id,
            feature=feature,
            error=str(exc),
        )
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    result = UserActionResult(
        feature=feature,
        punishment_requested=True,
        punishment_applied=punishment_applied,
        action="mute",
        failures=tuple(failures),
    )
    if raise_on_failure and result.failed:
        raise RuntimeError("; ".join(result.failures))
    return result


async def execute_group_permission_action(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    permissions,
    feature: str,
    detail: str,
) -> UserActionResult:
    failures: list[str] = []
    try:
        await context.bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)
        applied = True
    except Exception as exc:
        applied = False
        failures.append(str(exc))
        log.warning(
            "group_permission_action_failed",
            chat_id=chat_id,
            feature=feature,
            error=str(exc),
        )
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    return UserActionResult(
        feature=feature,
        punishment_requested=True,
        punishment_applied=applied,
        action="group_permissions",
        failures=tuple(failures),
    )
