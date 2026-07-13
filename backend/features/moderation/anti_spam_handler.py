from __future__ import annotations

from dataclasses import dataclass

import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from backend.features.moderation.services.anti_spam_service import detect_spam_violation
from backend.features.moderation.services.garbage_guard_rules import (
    any_garbage_rule_enabled,
    get_rule_config,
    is_global_whitelisted,
)
from backend.features.moderation.services.garbage_guard_service import (
    apply_garbage_punishment,
    delete_garbage_message_fallback,
    detect_garbage_violation,
    execute_garbage_action_safely,
    handle_garbage_result_fallback,
    notify_garbage_action_failure,
)
from backend.features.moderation.services.moderation_service import (
    build_moderation_action_label,
    build_moderation_notice,
    normalize_moderation_actor_id,
    record_violation,
    resolve_effective_action,
    send_temporary_notice,
    should_exempt_admin,
)
from backend.features.moderation.services.quick_reply_actions import (
    apply_quick_reply_action,
    match_quick_reply_action,
)
from backend.platform.db.runtime.session import Database
from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.user_service import ensure_user

log = structlog.get_logger(__name__)
_DEFAULT_NOTICE_SECONDS = 10
_DEFAULT_MUTE_SECONDS = 600


@dataclass(frozen=True)
class ModerationRequest:
    chat: object
    user: object | None
    message: object
    sender_chat: object | None
    actor_id: int
    real_user: object | None


def _user_label(user) -> str:
    if user is None:
        return "频道身份发言"
    return user.mention_html()


def _is_manual_warning_text(text: str) -> bool:
    return text.strip().lower() in {"warn", "警告"}


def _build_moderation_request(update: Update) -> ModerationRequest | None:
    chat = update.effective_chat
    message = update.effective_message
    if chat is None or message is None or chat.type == "private":
        return None
    user = update.effective_user
    sender_chat = message.sender_chat
    if user is not None and user.is_bot and sender_chat is None:
        return None
    actor_id = normalize_moderation_actor_id(
        user.id if user is not None else None,
        sender_chat.id if sender_chat is not None else None,
    )
    return ModerationRequest(
        chat=chat, user=user, message=message, sender_chat=sender_chat,
        actor_id=actor_id, real_user=user if sender_chat is None else None,
    )


async def _ensure_moderation_user(session, *, request: ModerationRequest, user) -> None:
    await ensure_chat(
        session, chat_id=request.chat.id, chat_type=request.chat.type,
        title=request.chat.title,
    )
    await ensure_user(
        session, user_id=user.id, username=user.username,
        first_name=user.first_name, last_name=user.last_name,
        language_code=user.language_code,
    )


async def _process_quick_reply_action(
    context: ContextTypes.DEFAULT_TYPE, session, *, settings, chat, user, message
) -> bool:
    reply_to_message = getattr(message, "reply_to_message", None)
    if user is None or reply_to_message is None:
        return False
    action = match_quick_reply_action(settings, message.text or "")
    if action is None:
        return False
    if not await should_exempt_admin(context, chat.id, user.id, exempt_admin=True):
        return False
    target = getattr(reply_to_message, "from_user", None)
    if target is None or target.id <= 0 or is_global_whitelisted(settings, target.id):
        return False
    if await should_exempt_admin(context, chat.id, target.id, exempt_admin=True):
        return False
    await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
    await ensure_user(
        session, user_id=target.id, username=target.username,
        first_name=target.first_name, last_name=target.last_name,
        language_code=target.language_code,
    )
    await apply_quick_reply_action(
        context, session, settings=settings, chat_id=chat.id,
        target_user_id=target.id, target_label=_user_label(target), action=action,
        actor_user_id=user.id, command_message=message,
        target_message_id=getattr(reply_to_message, "message_id", None),
    )
    return True


async def execute_spam_punishment(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, actor_id: int, *,
    action: str, message_ids: list[int] | None = None,
    mute_seconds: int = _DEFAULT_MUTE_SECONDS,
    sender_chat_id: int | None = None, reason: str | None = None,
) -> bool:
    """兼容旧处罚入口，内部统一走 ActionExecutor。"""
    try:
        if message_ids:
            await ActionExecutor.delete_many(
                context, chat_id=chat_id, message_ids=sorted(set(message_ids))
            )
        if action == "delete":
            return True
        execute_result = await ActionExecutor.execute(
            context, action=action, chat_id=chat_id, user_id=actor_id,
            mute_seconds=mute_seconds, sender_chat_id=sender_chat_id, reason=reason,
        )
        return execute_result.applied
    except Exception as exc:
        log.warning(
            "anti_spam_punishment_failed", chat_id=chat_id,
            actor_id=actor_id, action=action, error=str(exc),
        )
        return False


async def _notify_leave_ban(
    context, *, request: ModerationRequest, member, config, action_label: str
) -> None:
    if not bool(config.get("notice_enabled")):
        return
    notice = build_moderation_notice(
        "🚫 离群封禁已执行", _user_label(member), "用户离开群组",
        action_label=action_label,
    )
    await send_temporary_notice(
        context.bot, chat_id=request.chat.id,
        text=str(config.get("notice_text") or notice),
        delete_after_seconds=int(
            config.get("notice_delete_seconds", _DEFAULT_NOTICE_SECONDS)
            or _DEFAULT_NOTICE_SECONDS
        ),
    )


async def _delete_leave_message(
    context, *, request: ModerationRequest, requested: bool
) -> bool:
    if not requested:
        return False
    result = await ActionExecutor.delete_many(
        context, chat_id=request.chat.id,
        message_ids=[request.message.message_id],
    )
    return bool(result.applied)


async def _handle_leave_ban(
    context, session, *, request: ModerationRequest, settings
) -> bool:
    member = getattr(request.message, "left_chat_member", None)
    config = get_rule_config(settings, "leave_ban")
    if member is None or not bool(config.get("enabled")):
        return False
    if is_global_whitelisted(settings, member.id):
        return False
    if await should_exempt_admin(context, request.chat.id, member.id, exempt_admin=True):
        return False
    await _ensure_moderation_user(session, request=request, user=member)
    delete_requested = bool(config.get("delete_message"))
    delete_applied = await _delete_leave_message(
        context, request=request, requested=delete_requested
    )
    ban_result = await execute_garbage_action_safely(
        context, action="ban", chat_id=request.chat.id, user_id=member.id,
        rule_id="leave_ban", detail="成员离开群组",
        actor_user_id=request.user.id if request.user is not None else None,
        message_id=request.message.message_id,
    )
    action_label = "删除消息 + 封禁成员" if delete_requested else "封禁成员"
    await record_violation(
        session, chat_id=request.chat.id, user_id=member.id,
        message_id=request.message.message_id, rule="leave_ban",
        detail="成员离开群组", action=action_label[:32],
    )
    await session.commit()
    if delete_requested and not delete_applied:
        await delete_garbage_message_fallback(
            context, request.chat.id, request.message,
            rule_id="leave_ban", detail="成员离开群组",
        )
    if not bool(ban_result.applied):
        await notify_garbage_action_failure(
            context, request.chat.id, "leave_ban", detail="成员离开群组"
        )
    await _notify_leave_ban(
        context, request=request, member=member,
        config=config, action_label=action_label,
    )
    return True


def _manual_warning_candidate(request: ModerationRequest, config):
    reply = getattr(request.message, "reply_to_message", None)
    if not bool(config.get("enabled")) or reply is None:
        return None
    if request.user is None or not _is_manual_warning_text(request.message.text or ""):
        return None
    return getattr(reply, "from_user", None)


async def _resolve_manual_warning_target(
    context, *, request: ModerationRequest, settings, config
):
    target = _manual_warning_candidate(request, config)
    if target is None:
        return None
    if not await should_exempt_admin(
        context, request.chat.id, request.user.id, exempt_admin=True
    ):
        return None
    if target is None or target.id <= 0 or is_global_whitelisted(settings, target.id):
        return None
    if await should_exempt_admin(context, request.chat.id, target.id, exempt_admin=True):
        return None
    return target


async def _handle_manual_warning(
    context, session, *, request: ModerationRequest, settings
) -> bool:
    config = get_rule_config(settings, "manual_warning")
    target = await _resolve_manual_warning_target(
        context, request=request, settings=settings, config=config
    )
    if target is None:
        return False
    await _ensure_moderation_user(session, request=request, user=target)
    delete_enabled = bool(config.get("delete_message"))
    result = await apply_garbage_punishment(
        context, session, settings=settings, chat_id=request.chat.id,
        target_user_id=target.id, target_label=_user_label(target),
        rule_id="manual_warning", detail="manual warn",
        message_ids=[request.message.message_id] if delete_enabled else [],
        actor_user_id=request.user.id,
        record_message_id=getattr(request.message.reply_to_message, "message_id", None),
    )
    await session.commit()
    await handle_garbage_result_fallback(
        context, chat_id=request.chat.id, message=request.message,
        rule_id="manual_warning", detail="管理员人工警告", result=result,
        delete_message_enabled=delete_enabled,
    )
    return True


async def _skip_automated_moderation(
    context, session, *, request: ModerationRequest, settings
) -> bool:
    if not (settings.anti_spam_enabled or any_garbage_rule_enabled(settings)):
        await session.commit()
        return True
    user_id = request.real_user.id if request.real_user is not None else None
    if await should_exempt_admin(context, request.chat.id, user_id, exempt_admin=True):
        await session.commit()
        log.info("spam_skip_admin_exempt", chat_id=request.chat.id, user_id=user_id)
        return True
    if request.real_user is None or not is_global_whitelisted(settings, user_id):
        return False
    await session.commit()
    log.info("spam_skip_global_whitelist", chat_id=request.chat.id, user_id=user_id)
    return True


def _log_garbage_runtime(request: ModerationRequest, settings, violation) -> None:
    config = get_rule_config(settings, "long_message")
    content = getattr(request.message, "text", None) or getattr(request.message, "caption", None) or ""
    log.info(
        "garbage_guard_runtime_check", chat_id=request.chat.id,
        user_id=request.real_user.id if request.real_user is not None else None,
        sender_chat_id=request.sender_chat.id if request.sender_chat is not None else None,
        text_length=len(content), long_message_enabled=bool(config.get("enabled")),
        long_message_max_length=int(config.get("message_max_length", 0) or 0),
        violation_rule=violation.rule_id if violation is not None else None,
    )


async def _handle_garbage_violation(
    context, session, *, request: ModerationRequest, settings
) -> bool:
    violation = detect_garbage_violation(settings, request.message)
    _log_garbage_runtime(request, settings, violation)
    if violation is None or (request.real_user is None and request.sender_chat is None):
        return False
    await ensure_chat(
        session, chat_id=request.chat.id, chat_type=request.chat.type,
        title=request.chat.title,
    )
    target_user_id = request.real_user.id if request.real_user is not None and request.real_user.id > 0 else 0
    if target_user_id > 0:
        await ensure_user(
            session, user_id=request.real_user.id, username=request.real_user.username,
            first_name=request.real_user.first_name, last_name=request.real_user.last_name,
            language_code=request.real_user.language_code,
        )
    result = await apply_garbage_punishment(
        context, session, settings=settings, chat_id=request.chat.id,
        target_user_id=target_user_id, target_label=_user_label(request.real_user),
        rule_id=violation.rule_id, detail=violation.detail,
        message_ids=violation.message_ids_to_delete,
        sender_chat_id=request.sender_chat.id if request.sender_chat is not None else None,
        record_message_id=request.message.message_id,
    )
    await session.commit()
    delete_enabled = bool(get_rule_config(settings, violation.rule_id).get("delete_message"))
    await handle_garbage_result_fallback(
        context, chat_id=request.chat.id, message=request.message,
        rule_id=violation.rule_id, detail=violation.detail,
        result=result, delete_message_enabled=delete_enabled,
    )
    if result.applied:
        log.info(
            "garbage_guard_blocked", chat_id=request.chat.id,
            user_id=target_user_id or request.actor_id,
            rule=violation.rule, action=result.action_label,
        )
    return True


async def _prepare_spam_punishment(
    context, session, *, request: ModerationRequest, settings
):
    violation = await detect_spam_violation(
        settings, request.message, request.chat.id, request.actor_id
    )
    if not violation.blocked:
        await session.commit()
        return None
    resolution = await resolve_effective_action(
        context, request.chat.id,
        request.user.id if request.user is not None else request.actor_id,
        requested_action=settings.anti_spam_action,
        sender_chat_id=request.sender_chat.id if request.sender_chat is not None else None,
    )
    if request.user is not None and request.user.id > 0:
        await _ensure_moderation_user(session, request=request, user=request.user)
        await record_violation(
            session, chat_id=request.chat.id, user_id=request.user.id,
            message_id=request.message.message_id, rule=violation.rule,
            detail=violation.detail, action=resolution.action,
        )
    await session.commit()
    return violation, resolution


async def _execute_prepared_spam(
    context, *, request: ModerationRequest, settings, prepared
) -> bool:
    violation, resolution = prepared
    message_ids = [
        request.message.message_id,
        *getattr(violation, "message_ids_to_delete", []),
    ]
    success = await execute_spam_punishment(
        context, request.chat.id,
        request.user.id if request.user is not None else request.actor_id,
        action=resolution.action, message_ids=message_ids,
        mute_seconds=settings.anti_spam_mute_duration,
        sender_chat_id=request.sender_chat.id if request.sender_chat is not None else None,
        reason=violation.rule,
    )
    if not success:
        return False
    action_label = build_moderation_action_label(
        resolution.action, settings.anti_spam_mute_duration
    )
    notice = build_moderation_notice(
        "🚫 反垃圾已拦截消息", _user_label(request.user), violation.rule,
        action_label=action_label, fallback_reason=resolution.fallback_reason,
    )
    delete_after = (
        settings.anti_spam_delete_notify_seconds
        if settings.anti_spam_delete_notify else None
    )
    await send_temporary_notice(
        context.bot, chat_id=request.chat.id, text=notice,
        delete_after_seconds=delete_after,
    )
    log.info(
        "anti_spam_blocked", chat_id=request.chat.id,
        user_id=request.actor_id, rule=violation.rule, action=resolution.action,
    )
    return True


async def anti_spam_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = _build_moderation_request(update)
    if request is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, request.chat.id)
        if await _handle_leave_ban(
            context, session, request=request, settings=settings
        ):
            raise ApplicationHandlerStop
        if await _process_quick_reply_action(
            context, session, settings=settings, chat=request.chat,
            user=request.user, message=request.message,
        ):
            await session.commit()
            raise ApplicationHandlerStop
        if await _handle_manual_warning(
            context, session, request=request, settings=settings
        ):
            raise ApplicationHandlerStop
        if await _skip_automated_moderation(
            context, session, request=request, settings=settings
        ):
            return
        if await _handle_garbage_violation(
            context, session, request=request, settings=settings
        ):
            raise ApplicationHandlerStop
        prepared = await _prepare_spam_punishment(
            context, session, request=request, settings=settings
        )
    if prepared is None:
        return
    if await _execute_prepared_spam(
        context, request=request, settings=settings, prepared=prepared
    ):
        raise ApplicationHandlerStop
