from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.user_service import ensure_user
from backend.features.moderation.services.anti_spam_service import (
    detect_spam_violation,
)
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
    should_exempt_admin,
    send_temporary_notice,
)
from backend.shared.services.action_executor import ActionExecutor


log = structlog.get_logger(__name__)


def _user_label(user) -> str:
    if user is None:
        return "频道身份发言"
    return user.mention_html()


def _is_manual_warning_text(text: str) -> bool:
    return text.strip().lower() in {"warn", "警告"}


async def execute_spam_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    actor_id: int,
    action: str,
    *,
    message_ids: list[int] | None = None,
    mute_seconds: int = 600,
    sender_chat_id: int | None = None,
    reason: str | None = None,
) -> bool:
    """兼容旧处罚入口，内部统一走 ActionExecutor。"""
    try:
        if message_ids:
            await ActionExecutor.delete_many(
                context,
                chat_id=chat_id,
                message_ids=sorted(set(message_ids)),
            )

        if action == "delete":
            return True

        execute_result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=actor_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=reason,
        )
        return execute_result.applied
    except Exception as exc:
        log.warning(
            "anti_spam_punishment_failed",
            chat_id=chat_id,
            actor_id=actor_id,
            action=action,
            error=str(exc),
        )
        return False


async def anti_spam_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    sender_chat = message.sender_chat
    actor_id = normalize_moderation_actor_id(user.id if user is not None else None, sender_chat.id if sender_chat is not None else None)

    if chat.type == "private":
        return

    # 机器人账号不参与反垃圾检测（频道身份消息除外）
    if user is not None and user.is_bot and message.sender_chat is None:
        return

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        leave_member = getattr(message, "left_chat_member", None)
        if leave_member is not None and bool(get_rule_config(settings, "leave_ban").get("enabled")):
            if not is_global_whitelisted(settings, leave_member.id) and not await should_exempt_admin(
                context,
                chat.id,
                leave_member.id,
                True,
            ):
                await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
                await ensure_user(
                    session,
                    user_id=leave_member.id,
                    username=leave_member.username,
                    first_name=leave_member.first_name,
                    last_name=leave_member.last_name,
                    language_code=leave_member.language_code,
                )
                config = get_rule_config(settings, "leave_ban")
                delete_requested = bool(config.get("delete_message"))
                delete_applied = False
                if bool(config.get("delete_message")):
                    delete_result = await ActionExecutor.delete_many(context, chat_id=chat.id, message_ids=[message.message_id])
                    delete_applied = bool(delete_result.applied)
                ban_result = await execute_garbage_action_safely(
                    context,
                    action="ban",
                    chat_id=chat.id,
                    user_id=leave_member.id,
                    rule_id="leave_ban",
                    detail="成员离开群组",
                    actor_user_id=user.id if user is not None else None,
                    message_id=message.message_id,
                )
                action_label = "删除消息 + 封禁成员" if delete_requested else "封禁成员"
                await record_violation(
                    session,
                    chat_id=chat.id,
                    user_id=leave_member.id,
                    message_id=message.message_id,
                    rule="leave_ban",
                    detail="成员离开群组",
                    action=action_label[:32],
                )
                await session.commit()
                if delete_requested and not delete_applied:
                    await delete_garbage_message_fallback(context, chat.id, message, "leave_ban", "成员离开群组")
                if not bool(ban_result.applied):
                    await notify_garbage_action_failure(context, chat.id, "leave_ban", "成员离开群组")
                if bool(config.get("notice_enabled")):
                    notice = build_moderation_notice(
                        "🚫 离群封禁已执行",
                        _user_label(leave_member),
                        "用户离开群组",
                        action_label,
                    )
                    await send_temporary_notice(
                        context.bot,
                        chat_id=chat.id,
                        text=str(config.get("notice_text") or notice),
                        delete_after_seconds=int(config.get("notice_delete_seconds", 10) or 10),
                    )
                raise ApplicationHandlerStop

        manual_config = get_rule_config(settings, "manual_warning")
        if bool(manual_config.get("enabled")) and _is_manual_warning_text(message.text or "") and message.reply_to_message is not None:
            issuer_id = user.id if user is not None else None
            if issuer_id is not None and await should_exempt_admin(context, chat.id, issuer_id, True):
                target = getattr(message.reply_to_message, "from_user", None)
                if (
                    target is not None
                    and target.id > 0
                    and not is_global_whitelisted(settings, target.id)
                    and not await should_exempt_admin(context, chat.id, target.id, True)
                ):
                    await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
                    await ensure_user(
                        session,
                        user_id=target.id,
                        username=target.username,
                        first_name=target.first_name,
                        last_name=target.last_name,
                        language_code=target.language_code,
                    )
                    result = await apply_garbage_punishment(
                        context,
                        session,
                        settings=settings,
                        chat_id=chat.id,
                        target_user_id=target.id,
                        target_label=_user_label(target),
                        rule_id="manual_warning",
                        detail="manual warn",
                        message_ids=[message.message_id] if bool(manual_config.get("delete_message")) else [],
                        actor_user_id=issuer_id,
                        record_message_id=getattr(message.reply_to_message, "message_id", None),
                    )
                    await session.commit()
                    await handle_garbage_result_fallback(
                        context,
                        chat_id=chat.id,
                        message=message,
                        rule_id="manual_warning",
                        detail="管理员人工警告",
                        result=result,
                        delete_message_enabled=bool(manual_config.get("delete_message")),
                    )
                    raise ApplicationHandlerStop

        if not (settings.anti_spam_enabled or any_garbage_rule_enabled(settings)):
            await session.commit()
            return

        # 垃圾防护规则对管理员与总白名单用户无效。
        if await should_exempt_admin(context, chat.id, user.id if user is not None else None, True):
            await session.commit()
            log.info("spam_skip_admin_exempt", chat_id=chat.id, user_id=user.id if user is not None else None)
            return

        if user is not None and is_global_whitelisted(settings, user.id):
            await session.commit()
            log.info("spam_skip_global_whitelist", chat_id=chat.id, user_id=user.id)
            return

        garbage_violation = detect_garbage_violation(settings, message)
        if garbage_violation is not None and user is not None and user.id > 0:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
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
                settings=settings,
                chat_id=chat.id,
                target_user_id=user.id,
                target_label=_user_label(user),
                rule_id=garbage_violation.rule_id,
                detail=garbage_violation.detail,
                message_ids=garbage_violation.message_ids_to_delete,
                sender_chat_id=sender_chat.id if sender_chat is not None else None,
                record_message_id=message.message_id,
            )
            await session.commit()
            delete_message_enabled = bool(get_rule_config(settings, garbage_violation.rule_id).get("delete_message"))
            await handle_garbage_result_fallback(
                context,
                chat_id=chat.id,
                message=message,
                rule_id=garbage_violation.rule_id,
                detail=garbage_violation.detail,
                result=result,
                delete_message_enabled=delete_message_enabled,
            )
            if result.applied:
                log.info(
                    "garbage_guard_blocked",
                    chat_id=chat.id,
                    user_id=user.id,
                    rule=garbage_violation.rule,
                    action=result.action_label,
                )
            raise ApplicationHandlerStop

        violation = await detect_spam_violation(settings, message, chat.id, actor_id)

        if not violation.blocked:
            await session.commit()
            return

        resolution = await resolve_effective_action(
            context,
            chat.id,
            user.id if user is not None else actor_id,
            settings.anti_spam_action,
            sender_chat_id=sender_chat.id if sender_chat is not None else None,
        )
        action = resolution.action
        fallback_reason = resolution.fallback_reason

        # 先落库，便于排查策略命中；审计动作必须记录最终实际动作
        if user is not None and user.id > 0:
            await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
            await ensure_user(
                session,
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code,
            )
            await record_violation(
                session,
                chat_id=chat.id,
                user_id=user.id,
                message_id=message.message_id,
                rule=violation.rule,
                detail=violation.detail,
                action=action,
            )

        await session.commit()

    action = resolution.action
    fallback_reason = resolution.fallback_reason
    message_ids = [message.message_id, *getattr(violation, "message_ids_to_delete", [])]
    success = await execute_spam_punishment(
        context,
        chat.id,
        user.id if user is not None else actor_id,
        action,
        message_ids=message_ids,
        mute_seconds=settings.anti_spam_mute_duration,
        sender_chat_id=sender_chat.id if sender_chat is not None else None,
        reason=violation.rule,
    )

    if not success:
        return

    action_label = build_moderation_action_label(action, settings.anti_spam_mute_duration)
    notice = build_moderation_notice(
        "🚫 反垃圾已拦截消息",
        user.mention_html() if user is not None else "频道身份发言",
        violation.rule,
        action_label,
        fallback_reason=fallback_reason,
    )

    await send_temporary_notice(
        context.bot,
        chat_id=chat.id,
        text=notice,
        delete_after_seconds=settings.anti_spam_delete_notify_seconds if settings.anti_spam_delete_notify else None,
    )

    log.info(
        "anti_spam_blocked",
        chat_id=chat.id,
        user_id=actor_id,
        rule=violation.rule,
        action=action,
    )
    raise ApplicationHandlerStop
