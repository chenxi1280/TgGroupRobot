from __future__ import annotations

from dataclasses import dataclass

import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.user_service import ensure_user
from backend.features.moderation.services.anti_flood_service import (
    get_tracker,
)
from backend.features.moderation.services.anti_flood_punishment import execute_flood_punishment
from backend.features.moderation.services.garbage_guard_rules import (
    get_rule_config,
    has_explicit_garbage_config,
    is_global_whitelisted,
)
from backend.features.moderation.services.garbage_guard_service import (
    apply_garbage_punishment,
    handle_garbage_result_fallback,
)
from backend.features.moderation.services.moderation_service import (
    build_moderation_action_label,
    build_moderation_notice,
    normalize_moderation_actor_id,
    record_violation,
    resolve_effective_action,
    should_exempt_admin,
    send_temporary_notice,
)
log = structlog.get_logger(__name__)

DEFAULT_MUTE_SECONDS = 60
CLEANUP_MAX_AGE_SECONDS = 300


@dataclass(frozen=True)
class FloodRuntime:
    chat: object
    user: object | None
    message: object
    sender_chat: object | None
    actor_id: int
    settings: object
    flood_config: dict
    tracker: object
    result: object | None


@dataclass(frozen=True)
class PreparedFlood:
    db: object
    runtime: FloodRuntime
    explicit_garbage: bool


async def _load_flood_settings(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        await session.commit()
    return db, settings


async def _should_exempt_flood_actor(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: FloodRuntime,
    *,
    explicit_garbage: bool,
) -> bool:
    user_id = runtime.user.id if runtime.user is not None else None
    exempt_admin = True if explicit_garbage else runtime.settings.anti_flood_exempt_admin
    if await should_exempt_admin(context, runtime.chat.id, user_id, exempt_admin=exempt_admin):
        log.info("flood_skip_admin_exempt", chat_id=runtime.chat.id, user_id=user_id)
        return True
    if explicit_garbage and user_id is not None and is_global_whitelisted(runtime.settings, user_id):
        log.info("flood_skip_global_whitelist", chat_id=runtime.chat.id, user_id=user_id)
        return True
    return False


def _flood_thresholds(settings, flood_config: dict, *, explicit_garbage: bool) -> tuple[int, int]:
    if explicit_garbage:
        max_messages = int(flood_config.get("messages", settings.anti_flood_messages))
        window_seconds = int(flood_config.get("seconds", settings.anti_flood_seconds))
        return max_messages, window_seconds
    return int(settings.anti_flood_messages), int(settings.anti_flood_seconds)


async def _collect_flood_message_ids(runtime: FloodRuntime) -> list[int]:
    if hasattr(runtime.tracker, "get_and_clear_messages"):
        return await runtime.tracker.get_and_clear_messages(runtime.chat.id, runtime.actor_id)
    return [runtime.message.message_id]


def _flood_detail(runtime: FloodRuntime) -> str:
    return (
        f"{runtime.result.time_span:.1f} 秒内发送 {runtime.result.message_count} 条消息，"
        "达到刷屏阈值"
    )


async def _record_legacy_flood_violation(db, runtime: FloodRuntime, action: str) -> None:
    if runtime.user is None or runtime.user.id <= 0:
        return
    async with db.session_factory() as session:
        await ensure_chat(
            session,
            chat_id=runtime.chat.id,
            chat_type=runtime.chat.type,
            title=runtime.chat.title,
        )
        await ensure_user(
            session,
            user_id=runtime.user.id,
            username=runtime.user.username,
            first_name=runtime.user.first_name,
            last_name=runtime.user.last_name,
            language_code=runtime.user.language_code,
        )
        await record_violation(
            session,
            chat_id=runtime.chat.id,
            user_id=runtime.user.id,
            message_id=runtime.message.message_id,
            rule="anti_flood",
            detail=f"count={runtime.result.message_count},span={runtime.result.time_span:.3f}",
            action=action,
        )
        await session.commit()


async def _handle_explicit_flood(
    context: ContextTypes.DEFAULT_TYPE,
    db,
    runtime: FloodRuntime,
) -> None:
    message_ids = await _collect_flood_message_ids(runtime)
    detail = _flood_detail(runtime)
    result = await _apply_explicit_flood_punishment(
        context,
        db,
        runtime,
        message_ids=message_ids,
        detail=detail,
    )
    await handle_garbage_result_fallback(
        context,
        chat_id=runtime.chat.id,
        message=runtime.message,
        rule_id="flood",
        detail=detail,
        result=result,
        delete_message_enabled=bool(runtime.flood_config.get("delete_message")),
    )
    if result.applied:
        log.info(
            "flood_garbage_guard_executed",
            chat_id=runtime.chat.id,
            user_id=runtime.actor_id,
            action=result.action_label,
        )
    raise ApplicationHandlerStop


async def _apply_explicit_flood_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    db,
    runtime: FloodRuntime,
    *,
    message_ids: list[int],
    detail: str,
):
    user = runtime.user
    if user is None or user.id <= 0:
        raise ValueError("explicit flood punishment requires a concrete user")
    async with db.session_factory() as session:
        await ensure_chat(
            session,
            chat_id=runtime.chat.id,
            chat_type=runtime.chat.type,
            title=runtime.chat.title,
        )
        await ensure_user(
            session,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        result = await apply_garbage_punishment(
            context,
            session,
            settings=runtime.settings,
            chat_id=runtime.chat.id,
            target_user_id=user.id,
            target_label=user.mention_html(),
            rule_id="flood",
            detail=detail,
            message_ids=message_ids,
            sender_chat_id=runtime.sender_chat.id if runtime.sender_chat is not None else None,
            record_message_id=runtime.message.message_id,
        )
        await session.commit()
    return result


async def _notify_legacy_flood_success(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: FloodRuntime,
    *,
    action: str,
    fallback_reason: str | None,
    mute_duration: int,
) -> None:
    action_text = build_moderation_action_label(action, mute_duration)
    warning_msg = build_moderation_notice(
        "🚫 检测到刷屏行为！",
        runtime.user.mention_html() if runtime.user is not None else "频道身份发言",
        f"{runtime.result.time_span:.1f} 秒内发送了 {runtime.result.message_count} 条消息",
        action_label=action_text,
        fallback_reason=fallback_reason,
    )
    await send_temporary_notice(
        context.bot,
        chat_id=runtime.chat.id,
        text=warning_msg,
        delete_after_seconds=(
            runtime.settings.anti_flood_delete_notify_seconds
            if runtime.settings.anti_flood_delete_notify
            else None
        ),
    )
    log.info(
        "flood_punishment_executed",
        chat_id=runtime.chat.id,
        user_id=runtime.actor_id,
        action=action,
    )
    raise ApplicationHandlerStop


async def _handle_legacy_flood(
    context: ContextTypes.DEFAULT_TYPE,
    db,
    runtime: FloodRuntime,
) -> None:
    sender_chat_id = runtime.sender_chat.id if runtime.sender_chat is not None else None
    resolution = await _resolve_legacy_flood_action(
        context, runtime, sender_chat_id=sender_chat_id
    )
    await _record_legacy_flood_violation(db, runtime, resolution.action)
    success, mute_duration = await _execute_legacy_flood_punishment(
        context,
        runtime,
        action=resolution.action,
        sender_chat_id=sender_chat_id,
    )
    if success:
        await _notify_legacy_flood_success(
            context,
            runtime,
            action=resolution.action,
            fallback_reason=resolution.fallback_reason,
            mute_duration=mute_duration,
        )
        return
    log.warning(
        "flood_punishment_failed",
        chat_id=runtime.chat.id,
        user_id=runtime.actor_id,
        action=resolution.action,
    )


async def _resolve_legacy_flood_action(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: FloodRuntime,
    *,
    sender_chat_id: int | None,
):
    resolution = await resolve_effective_action(
        context,
        runtime.chat.id,
        runtime.actor_id,
        requested_action=runtime.settings.anti_flood_action,
        sender_chat_id=sender_chat_id,
    )
    log.info(
        "flood_detected",
        chat_id=runtime.chat.id,
        user_id=runtime.actor_id,
        username=runtime.user.username if runtime.user is not None else None,
        message_count=runtime.result.message_count,
        time_span=runtime.result.time_span,
        action=resolution.action,
        fallback_reason=resolution.fallback_reason or None,
    )
    return resolution


async def _execute_legacy_flood_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    runtime: FloodRuntime,
    *,
    action: str,
    sender_chat_id: int | None,
) -> tuple[bool, int]:
    message_ids = await _collect_flood_message_ids(runtime)
    mute_duration = (
        runtime.settings.anti_flood_mute_duration
        if action == "mute"
        else DEFAULT_MUTE_SECONDS
    )
    success = await execute_flood_punishment(
        context,
        runtime.chat.id,
        runtime.actor_id,
        action=action,
        tracker=runtime.tracker,
        message_ids=message_ids,
        cleanup_messages=runtime.settings.anti_flood_cleanup_messages,
        mute_seconds=mute_duration,
        sender_chat_id=sender_chat_id,
        reason=f"count={runtime.result.message_count},span={runtime.result.time_span:.3f}",
    )
    return success, mute_duration


def _extract_flood_subject(update: Update) -> tuple[object, object | None, object, object | None] | None:
    if update.effective_chat is None or update.effective_message is None:
        return None
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    if chat.type == "private":
        return None
    if user is not None and user.is_bot and sender_chat is None:
        return None
    return chat, user, message, sender_chat


def _make_flood_runtime(
    subject: tuple[object, object | None, object, object | None],
    actor_id: int,
    settings,
    *,
    flood_config: dict,
    tracker,
    result,
) -> FloodRuntime:
    chat, user, message, sender_chat = subject
    return FloodRuntime(
        chat=chat,
        user=user,
        message=message,
        sender_chat=sender_chat,
        actor_id=actor_id,
        settings=settings,
        flood_config=flood_config,
        tracker=tracker,
        result=result,
    )


async def _prepare_flood(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> PreparedFlood | None:
    subject = _extract_flood_subject(update)
    if subject is None:
        return None
    chat, user, message, sender_chat = subject
    actor_id = normalize_moderation_actor_id(
        user.id if user is not None else None,
        sender_chat.id if sender_chat is not None else None,
    )
    db, settings = await _load_flood_settings(context, chat.id)
    explicit_garbage = has_explicit_garbage_config(settings)
    flood_config = get_rule_config(settings, "flood")
    if not (settings.anti_flood_enabled or bool(flood_config.get("enabled"))):
        return None
    tracker = get_tracker()
    runtime = _make_flood_runtime(
        subject,
        actor_id,
        settings,
        flood_config=flood_config,
        tracker=tracker,
        result=None,
    )
    if await _should_exempt_flood_actor(context, runtime, explicit_garbage=explicit_garbage):
        return None
    await tracker.add_message(chat.id, actor_id, message.message_id)
    max_messages, window_seconds = _flood_thresholds(
        settings, flood_config, explicit_garbage=explicit_garbage
    )
    flood_result = await tracker.check_flood(
        chat.id, actor_id, max_messages, time_window_seconds=window_seconds
    )
    if not flood_result.is_flooding:
        return None
    runtime = _make_flood_runtime(
        subject,
        actor_id,
        settings,
        flood_config=flood_config,
        tracker=tracker,
        result=flood_result,
    )
    return PreparedFlood(db=db, runtime=runtime, explicit_garbage=explicit_garbage)


async def anti_flood_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """反刷屏消息处理器。"""
    prepared = await _prepare_flood(update, context)
    if prepared is None:
        return
    runtime = prepared.runtime
    if prepared.explicit_garbage and runtime.user is not None and runtime.user.id > 0:
        await _handle_explicit_flood(context, prepared.db, runtime)
        return
    await _handle_legacy_flood(context, prepared.db, runtime)


async def anti_flood_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """定期清理旧记录的定时任务"""
    tracker = get_tracker()
    await tracker.cleanup_old_records(max_age_seconds=CLEANUP_MAX_AGE_SECONDS)
    log.debug("anti_flood_cleanup_done")
