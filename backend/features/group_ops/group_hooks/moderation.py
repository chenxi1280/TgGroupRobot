from __future__ import annotations

import datetime as dt

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
from backend.features.moderation.services.garbage_guard_service import apply_garbage_punishment
from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.user_service import ensure_user

from .common import _schedule_message_delete

log = structlog.get_logger(__name__)

BANNED_WORD_ACTION_FAILURE_NOTIFY_SECONDS = 300


async def _notify_banned_word_action_failure(context: ContextTypes.DEFAULT_TYPE, chat_id: int, detail: str) -> None:
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    cache_key = (chat_id, "banned_word_action_failure")
    now = dt.datetime.now(dt.UTC)
    if isinstance(bot_data, dict):
        cache = bot_data.setdefault("_banned_word_action_failure_notified_at", {})
        last_notified = cache.get(cache_key)
        if isinstance(last_notified, dt.datetime):
            elapsed = (now - last_notified).total_seconds()
            if elapsed < BANNED_WORD_ACTION_FAILURE_NOTIFY_SECONDS:
                return
        cache[cache_key] = now

    text = (
        "⚠️ 违禁词已命中，但处罚动作没有成功执行。\n"
        "请确认机器人仍是管理员，并拥有删除消息/禁言权限；也请重启机器人加载最新代码。"
    )
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        log.warning("banned_word_action_failure_notify_failed", chat_id=chat_id, detail=detail, error=str(exc))


async def _delete_banned_word_message_fallback(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message, detail: str) -> bool:
    try:
        await message.delete()
        log.warning(
            "banned_word_delete_fallback_succeeded",
            chat_id=chat_id,
            message_id=getattr(message, "message_id", None),
            detail=detail,
        )
        return True
    except Exception as exc:
        log.warning(
            "banned_word_delete_fallback_failed",
            chat_id=chat_id,
            message_id=getattr(message, "message_id", None),
            detail=detail,
            error=str(exc),
        )
        await _notify_banned_word_action_failure(context, chat_id, detail)
        return False


async def _process_alliance_reply_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    message_text: str,
) -> bool:
    if message_text.strip().lower() != "t" or message.reply_to_message is None:
        return False

    target_user = getattr(message.reply_to_message, "from_user", None)
    if target_user is None:
        return False

    try:
        async with db.session_factory() as session:
            member = await AllianceService.get_member(session, chat.id)
            await session.commit()
        if member is None:
            return False

        await ActionExecutor.execute(
            context,
            action="ban",
            chat_id=chat.id,
            user_id=target_user.id,
            actor_user_id=user.id,
            reason="联盟联合封禁",
            message_id=getattr(message.reply_to_message, "message_id", None),
            sender_chat_id=getattr(getattr(message.reply_to_message, "sender_chat", None), "id", None),
        )
        try:
            async with db.session_factory() as session:
                await AllianceService.add_joint_ban_entry(
                    session,
                    chat_id=chat.id,
                    operator_user_id=user.id,
                    target_user_id=target_user.id,
                    reason="reply_t_command",
                )
                await session.commit()
        except Exception as exc:
            log.warning("alliance_ban_pool_append_failed", chat_id=chat.id, target_user_id=target_user.id, error=str(exc))
            try:
                await message.reply_text("当前群已封禁目标用户，但加入联盟封禁名单失败。")
            except Exception:
                pass
            return True
        try:
            await message.reply_text("已加入联盟联合封禁名单，并在当前群执行封禁。")
        except Exception:
            pass
        return True
    except Exception as exc:
        log.warning("alliance_reply_ban_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        try:
            await message.reply_text("联合封禁失败，请确认当前群已加入联盟。")
        except Exception:
            pass
        return False


async def _process_alliance_joint_ban(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
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
        await ActionExecutor.execute(
            context,
            action="ban",
            chat_id=chat.id,
            user_id=user.id,
            actor_user_id=ban_item.source_operator_user_id,
            reason="联盟联合封禁同步",
            message_id=message.message_id,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
        )
        return True
    except Exception as exc:
        log.warning(
            "alliance_joint_ban_enforce_failed",
            chat_id=chat.id,
            user_id=user.id,
            error=str(exc),
        )
        return False


async def _process_banned_word_check(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
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

    explicit_garbage = settings is not None and has_explicit_garbage_config(settings)
    if explicit_garbage:
        rule_config = get_rule_config(settings, "banned_words")
        if not bool(rule_config.get("enabled")):
            return False
        if is_global_whitelisted(settings, user.id):
            log.info("banned_word_skip_global_whitelist", chat_id=chat.id, user_id=user.id)
            return False

    async with db.session_factory() as session:
        matched_words = await match_banned_words(session, chat.id, message_text)
        if not matched_words:
            await session.commit()
            return False

        if explicit_garbage:
            word = matched_words[0]
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
                target_label=user.mention_html(),
                rule_id="banned_words",
                detail=f"word={word.word}",
                message_ids=[message.message_id],
                record_message_id=message.message_id,
            )
            await session.commit()
            if result.applied:
                return True
            if bool(rule_config.get("delete_message")):
                await _delete_banned_word_message_fallback(context, chat.id, message, f"word={word.word}")
            else:
                await _notify_banned_word_action_failure(context, chat.id, f"word={word.word}")
            return True

    log.info(
        "unified_handler_banned_word_check_result",
        chat_id=chat.id,
        user_id=user.id,
        matched_count=len(matched_words),
    )

    word = matched_words[0]
    log.info(
        "banned_word_detected",
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        word=word.word,
        action=word.action,
    )

    try:
        await message.delete()
    except Exception as exc:
        log.warning("delete_message_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if word.notify:
        notify_msg = word.notify_message or f"🚫 您的消息因包含违禁词「{word.word}」已被删除"
        try:
            await context.bot.send_message(chat_id=chat.id, text=notify_msg)
        except Exception as exc:
            log.warning("send_notify_failed", chat_id=chat.id, error=str(exc))

    if word.action == "mute":
        try:
            until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=word.mute_duration) if word.mute_duration else None
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user.id,
                permissions={"can_send_messages": False, "can_send_media_messages": False},
                until_date=until_date,
            )
        except Exception as exc:
            log.warning("mute_user_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    elif word.action == "ban":
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
        except Exception as exc:
            log.warning("ban_user_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return True


async def _process_auto_reply(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    message,
    message_text: str,
) -> None:
    log.info(
        "unified_handler_auto_reply_start",
        chat_id=chat.id,
        message_text_preview=message_text[:50],
    )

    async with db.session_factory() as session:
        result = await match_auto_reply(session, chat.id, message_text)
        await session.commit()

    log.info(
        "unified_handler_auto_reply_result",
        chat_id=chat.id,
        matched=result.success,
        matched_rule_ids=[rule.id for rule in (result.matched_rules or [])],
        has_reply_content=bool(result.reply_content),
    )

    if not (result.success and result.reply_content and result.rule is not None):
        return

    try:
        matched_rules = result.matched_rules or ([result.rule] if result.rule is not None else [])
        sent_messages = []
        for matched_rule in matched_rules:
            sent_messages.append(
                await _send_auto_reply_payload(
                    context,
                    chat_id=chat.id,
                    text=matched_rule.reply_content,
                    rule=matched_rule,
                    reply_to_message_id=message.message_id,
                    message_thread_id=getattr(message, "message_thread_id", None),
                )
            )
        if any(getattr(rule, "delete_source", False) for rule in matched_rules):
            try:
                await message.delete()
            except Exception as exc:
                log.warning("auto_reply_delete_source_failed", chat_id=chat.id, error=str(exc))
        for matched_rule, sent_message in zip(matched_rules, sent_messages, strict=False):
            delete_after = getattr(matched_rule, "delete_reply_delay_seconds", 0) or 0
            if delete_after > 0:
                _schedule_message_delete(
                    context,
                    sent_message,
                    delete_after,
                    name="group_hooks.auto_reply_warn_delete",
                )
        log.info(
            "unified_handler_auto_reply_sent",
            chat_id=chat.id,
            matched_rule_ids=[rule.id for rule in matched_rules],
            reply_content_preview=result.reply_content[:50],
            delete_source=any(bool(getattr(rule, "delete_source", False)) for rule in matched_rules),
            delete_reply_delay_seconds=max(
                (getattr(rule, "delete_reply_delay_seconds", 0) or 0) for rule in matched_rules
            )
            if matched_rules
            else 0,
        )
    except Exception as exc:
        log.warning("auto_reply_send_failed", chat_id=chat.id, error=str(exc))
