from __future__ import annotations

import structlog
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.features.garage.services.alliance_service import AllianceService
from backend.features.moderation.auto_reply_handler import _send_auto_reply_payload
from backend.features.moderation.services.auto_reply_service import match_auto_reply
from backend.features.moderation.services.banned_word_service import match_banned_words
from backend.features.moderation.services.garbage_guard_rules import (
    get_rule_config,
    has_explicit_garbage_config,
    is_global_whitelisted,
)
from backend.features.moderation.services.garbage_guard_service import (
    apply_garbage_punishment,
    handle_garbage_result_fallback,
)
from backend.features.moderation.services.user_action_runtime import execute_user_action
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.user_service import ensure_user

from .common import _schedule_message_delete

log = structlog.get_logger(__name__)


async def _reply_text_safely(message, text: str, *, event: str, **fields) -> None:
    try:
        await message.reply_text(text)
    except Exception as exc:
        log.warning(event, error=str(exc), **fields)


def _user_label(user) -> str:
    if user is None:
        return "频道身份发言"
    if hasattr(user, "mention_html"):
        try:
            return user.mention_html()
        except Exception as exc:
            log.warning("user_mention_html_failed", error=str(exc), user_id=getattr(user, "id", None))
    return getattr(user, "first_name", None) or getattr(user, "username", None) or "频道身份发言"


async def _alliance_member_exists(db: Database, chat_id: int) -> bool:
    async with db.session_factory() as session:
        member = await AllianceService.get_member(session, chat_id)
        await session.commit()
        return member is not None


async def _execute_alliance_reply_ban(context: ContextTypes.DEFAULT_TYPE, chat, user, *, message, target_user) -> bool:
    action_result = await execute_user_action(
        context,
        action="ban",
        feature="联盟封禁",
        chat_id=chat.id,
        user_id=target_user.id,
        actor_user_id=user.id,
        detail="联盟联合封禁",
        message_id=getattr(message.reply_to_message, "message_id", None),
        sender_chat_id=getattr(getattr(message.reply_to_message, "sender_chat", None), "id", None),
    )
    if action_result.punishment_applied:
        return True
    await _reply_text_safely(
        message,
        "联合封禁失败，请检查机器人封禁权限。",
        event="alliance_reply_ban_feedback_failed",
        chat_id=chat.id,
        target_user_id=target_user.id,
    )
    return False


async def _append_alliance_ban(db: Database, chat, user, *, message, target_user) -> bool:
    try:
        async with db.session_factory() as session:
            await AllianceService.add_joint_ban_entry(
                session,
                chat_id=chat.id,
                operator_user_id=user.id,
                target_user_id=target_user.id,
                reason="reply_team_command",
            )
            await session.commit()
        return True
    except Exception as exc:
        log.warning("alliance_ban_pool_append_failed", chat_id=chat.id, target_user_id=target_user.id, error=str(exc))
        await _reply_text_safely(
            message,
            "当前群已封禁目标用户，但加入联盟封禁名单失败。",
            event="alliance_reply_ban_feedback_failed",
            chat_id=chat.id,
            target_user_id=target_user.id,
        )
        return False

async def _process_alliance_reply_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *, user,
    message,
    message_text: str,
) -> bool:
    if message_text.strip().lower() != "team" or message.reply_to_message is None:
        return False

    target_user = getattr(message.reply_to_message, "from_user", None)
    if target_user is None:
        return False
    try:
        if not await _alliance_member_exists(db, chat.id):
            return False
        if not await _execute_alliance_reply_ban(context, chat, user, message=message, target_user=target_user):
            return True
        if not await _append_alliance_ban(db, chat, user, message=message, target_user=target_user):
            return True
        await _reply_text_safely(
            message,
            "已加入联盟联合封禁名单，并在当前群执行封禁。",
            event="alliance_reply_ban_feedback_failed",
            chat_id=chat.id,
            target_user_id=target_user.id,
        )
        return True
    except Exception as exc:
        log.warning("alliance_reply_ban_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        await _reply_text_safely(
            message,
            "联合封禁失败，请确认当前群已加入联盟。",
            event="alliance_reply_ban_feedback_failed",
            chat_id=chat.id,
            user_id=user.id,
        )
        return False


async def _process_alliance_joint_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *, user,
    message,
) -> bool:
    async with db.session_factory() as session:
        hit = await AllianceService.get_joint_ban_hit(
            session,
            chat_id=chat.id,
            target_user_id=user.id,
        )
        if hit is None:
            await session.commit()
            return False
        _, ban_item = hit
        await session.commit()

    try:
        action_result = await execute_user_action(
            context,
            action="ban",
            feature="联盟封禁",
            chat_id=chat.id,
            user_id=user.id,
            actor_user_id=ban_item.source_operator_user_id,
            detail="联盟联合封禁同步",
            message_id=message.message_id,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
        )
        if not action_result.punishment_applied:
            return True
        return True
    except Exception as exc:
        log.warning(
            "alliance_joint_ban_enforce_failed",
            chat_id=chat.id,
            user_id=user.id,
            error=str(exc),
        )
        return False


def _explicit_banned_word_rule(settings, chat, user) -> tuple[bool, dict | None]:
    explicit = settings is not None and has_explicit_garbage_config(settings)
    if not explicit:
        return False, None
    rule_config = get_rule_config(settings, "banned_words")
    if not bool(rule_config.get("enabled")):
        return True, None
    if is_global_whitelisted(settings, user.id):
        log.info("banned_word_skip_global_whitelist", chat_id=chat.id, user_id=user.id)
        return True, None
    return True, rule_config


async def _matched_banned_words(db: Database, chat_id: int, message_text: str):
    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat_id, message_text)
        await session.commit()
        return matched_words


async def _ensure_banned_word_actor(session, chat, user) -> int:
    target_user_id = user.id if getattr(user, "id", 0) > 0 else 0
    await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
    if target_user_id <= 0:
        return target_user_id
    await ensure_user(
        session,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )
    return target_user_id


async def _apply_explicit_banned_word(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *,
    user,
    message,
    settings,
    rule_config: dict,
    word,
) -> bool:
    detail = f"命中违禁词「{word.word}」"
    async with db.session_factory() as session:
        target_user_id = await _ensure_banned_word_actor(session, chat, user)
        result = await apply_garbage_punishment(
            context,
            session,
            settings=settings,
            chat_id=chat.id,
            target_user_id=target_user_id,
            target_label=_user_label(user),
            rule_id="banned_words",
            detail=detail,
            message_ids=[message.message_id],
            record_message_id=message.message_id,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
        )
        await session.commit()
    await handle_garbage_result_fallback(
        context,
        chat_id=chat.id,
        message=message,
        rule_id="banned_words",
        detail=detail,
        result=result,
        delete_message_enabled=bool(rule_config.get("delete_message")),
    )
    return True


async def _send_legacy_banned_notice(context: ContextTypes.DEFAULT_TYPE, chat_id: int, word) -> None:
    if not word.notify:
        return
    notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
    try:
        await context.bot.send_message(chat_id=chat_id, text=notify_msg)
    except Exception as exc:
        log.warning("send_notify_failed", chat_id=chat_id, error=str(exc))


async def _apply_legacy_banned_word(context: ContextTypes.DEFAULT_TYPE, chat, user, *, message, word) -> bool:
    detail = f"命中违禁词「{word.word}」"
    user_id = user.id if getattr(user, "id", 0) > 0 else 0
    await execute_user_action(
        context,
        feature="违禁词",
        chat_id=chat.id,
        user_id=user_id,
        action="none",
        detail=detail,
        message=message,
        delete_message=True,
    )
    await _send_legacy_banned_notice(context, chat.id, word)
    if user_id <= 0 or word.action not in {"mute", "ban"}:
        return True
    await execute_user_action(
        context,
        feature="违禁词",
        chat_id=chat.id,
        user_id=user_id,
        action=word.action,
        detail=detail,
        message=message,
        mute_seconds=int(word.mute_duration or 0) or None,
    )
    return True


async def _process_banned_word_check(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *, user,
    message,
    message_text: str,
    settings=None,
) -> bool:
    log.info(
        "unified_handler_banned_word_check_start",
        chat_id=chat.id,
        user_id=user.id,
        message_text_preview=message_text[:50],
    )
    explicit_garbage, rule_config = _explicit_banned_word_rule(settings, chat, user)
    if explicit_garbage and rule_config is None:
        return False
    matched_words = await _matched_banned_words(db, chat.id, message_text)
    if not matched_words:
        return False
    log.info(
        "unified_handler_banned_word_check_result",
        chat_id=chat.id,
        user_id=user.id,
        matched_count=len(matched_words),
    )

    word = matched_words[0]
    if explicit_garbage:
        return await _apply_explicit_banned_word(
            context, db, chat, user=user, message=message, settings=settings,
            rule_config=rule_config, word=word,
        )
    log.info(
        "banned_word_detected",
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        word=word.word,
        action=word.action,
    )
    return await _apply_legacy_banned_word(context, chat, user, message=message, word=word)


async def _match_group_auto_reply(db: Database, chat_id: int, message_text: str):
    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat_id, message_text)
        await session.commit()
        return result


async def _send_group_auto_replies(context: ContextTypes.DEFAULT_TYPE, chat, *, message, rules: list) -> list:
    return [
        await _send_auto_reply_payload(
            context,
            chat_id=chat.id,
            text=rule.reply_content,
            rule=rule,
            reply_to_message_id=message.message_id,
            message_thread_id=getattr(message, "message_thread_id", None),
        )
        for rule in rules
    ]


async def _delete_auto_reply_source(chat, message, rules: list) -> None:
    if not any(getattr(rule, "delete_source", False) for rule in rules):
        return
    try:
        await message.delete()
    except Exception as exc:
        log.warning("auto_reply_delete_source_failed", chat_id=chat.id, error=str(exc))


def _schedule_auto_reply_deletions(context: ContextTypes.DEFAULT_TYPE, rules: list, sent_messages: list) -> None:
    for rule, sent_message in zip(rules, sent_messages, strict=False):
        delete_after = getattr(rule, "delete_reply_delay_seconds", 0) or 0
        if delete_after <= 0:
            continue
        _schedule_message_delete(
            context,
            sent_message,
            delete_after,
            name="group_hooks.auto_reply_warn_delete",
        )


def _log_auto_reply_sent(chat_id: int, result, rules: list) -> None:
    delays = [getattr(rule, "delete_reply_delay_seconds", 0) or 0 for rule in rules]
    log.info(
        "unified_handler_auto_reply_sent",
        chat_id=chat_id,
        matched_rule_ids=[rule.id for rule in (result.matched_rules or [])],
        reply_content_preview=result.reply_content[:50],
        delete_source=any(bool(getattr(rule, "delete_source", False)) for rule in rules),
        delete_reply_delay_seconds=max(delays) if delays else 0,
    )


async def _process_auto_reply(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *, message,
    message_text: str,
) -> bool:
    log.info("unified_handler_auto_reply_start", chat_id=chat.id, message_text_preview=message_text[:50])
    result = await _match_group_auto_reply(db, chat.id, message_text)
    log.info(
        "unified_handler_auto_reply_result",
        chat_id=chat.id,
        matched=result.success,
        matched_rule_ids=[rule.id for rule in (result.matched_rules or [])],
        has_reply_content=bool(result.reply_content),
    )
    if not (result.success and result.reply_content and result.rule is not None):
        return False
    try:
        matched_rules = result.matched_rules or ([result.rule] if result.rule is not None else [])
        sent_messages = await _send_group_auto_replies(context, chat, message=message, rules=matched_rules)
        await _delete_auto_reply_source(chat, message, matched_rules)
        _schedule_auto_reply_deletions(context, matched_rules, sent_messages)
        _log_auto_reply_sent(chat.id, result, matched_rules)
        return True
    except Exception as exc:
        log.warning("auto_reply_send_failed", chat_id=chat.id, error=str(exc))
        return False
