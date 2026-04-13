from __future__ import annotations

import asyncio
import datetime as dt
import re

import structlog
from sqlalchemy import desc, func, or_, select
from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    build_self_review_question,
    create_or_replace_challenge,
    get_challenge,
)
from backend.platform.db.schema.models.core import ChatMember, ConversationState, TgUser
from backend.platform.db.schema.models.enums import MemberRole, VerificationMode
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.handlers.base.chat_resolver import ChatResolver

log = structlog.get_logger(__name__)

JOIN_SPAM_KEYWORD_RE = re.compile(
    r"(https?://|t\.me/|广告|推广|博彩|兼职|刷单|加群|拉人|电报|飞机|代发|赚钱)",
    flags=re.IGNORECASE,
)


def cache_invite_join_hint(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, user_id: int, invite_link: str) -> None:
    cache = context.application.bot_data.setdefault("invite_join_hints", {})
    cache[(chat_id, user_id)] = {"invite_link": invite_link}


def pop_invite_join_hint(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, user_id: int) -> dict | None:
    cache = context.application.bot_data.setdefault("invite_join_hints", {})
    return cache.pop((chat_id, user_id), None)


def user_mention_html(user_id: int) -> str:
    return f'<a href="tg://user?id={user_id}">{user_id}</a>'


def extract_unmute_target_user_id(message, message_text: str) -> int | None:
    if getattr(message, "reply_to_message", None) is not None:
        reply_user = getattr(message.reply_to_message, "from_user", None)
        if reply_user is not None:
            return reply_user.id
    for entity in [*(message.entities or [])]:
        entity_type = getattr(entity.type, "value", entity.type)
        if entity_type == "text_mention" and entity.user is not None:
            return entity.user.id
    for pattern in [r"@(-?\d{5,})", r"(?:user_id|uid|用户id)\s*[:： ]\s*(-?\d{5,})"]:
        m = re.search(pattern, message_text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


async def resolve_username_to_user_id(context: ContextTypes.DEFAULT_TYPE, message_text: str) -> int | None:
    username: str | None = None
    m = re.search(r"@([A-Za-z0-9_]{5,})", message_text)
    if m:
        username = m.group(1)
    if username is None:
        m2 = re.search(r"(?:^|\s)(?:解封|/unmute)\s+([A-Za-z][A-Za-z0-9_]{4,})", message_text, flags=re.IGNORECASE)
        if m2:
            username = m2.group(1)
    if not username:
        return None
    try:
        target_chat = await context.bot.get_chat(f"@{username}")
        target_id = getattr(target_chat, "id", None)
        if isinstance(target_id, int) and target_id > 0:
            return target_id
    except Exception:
        return None
    return None


def extract_unmute_name_token(message_text: str) -> str | None:
    m = re.search(r"(?:^|\s)(?:解封|/unmute)\s+([^\s]+)", message_text, flags=re.IGNORECASE)
    if not m:
        return None
    token = m.group(1).strip().lstrip("@").strip()
    return token or None


async def resolve_name_from_db(session, name_token: str) -> int | None:
    if not name_token:
        return None
    token = name_token.lower()
    stmt = (
        select(TgUser.id)
        .where(or_(func.lower(TgUser.username) == token, func.lower(TgUser.first_name) == token))
        .limit(2)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return int(rows[0]) if len(rows) == 1 else None


def resolve_state_chat_id(state: ConversationState, fallback_chat_id: int | None = None) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    if fallback_chat_id and fallback_chat_id != 0:
        return fallback_chat_id
    return None


def collect_join_spam_signals(user) -> list[str]:
    username = (getattr(user, "username", None) or "").strip()
    full_name = " ".join(
        part.strip()
        for part in [getattr(user, "first_name", None) or "", getattr(user, "last_name", None) or ""]
        if part and part.strip()
    ).strip()
    haystack = f"{username} {full_name}".strip()
    signals: list[str] = []
    if not username:
        signals.append("no_username")
    if len(full_name) >= 18:
        signals.append("long_name")
    if sum(char.isdigit() for char in haystack) >= 5:
        signals.append("many_digits")
    if re.search(r"(.)\1{4,}", haystack):
        signals.append("repeated_chars")
    if JOIN_SPAM_KEYWORD_RE.search(haystack):
        signals.append("promo_keyword")
    return signals


async def upsert_chat_member_join(session, chat_id: int, user) -> None:
    result = await session.execute(select(ChatMember).where(ChatMember.chat_id == chat_id, ChatMember.user_id == user.id))
    member = result.scalar_one_or_none()
    now = dt.datetime.now(dt.UTC)
    if member is None:
        session.add(ChatMember(chat_id=chat_id, user_id=user.id, role=MemberRole.member.value, joined_at=now))
        await session.flush()
        return
    member.role = MemberRole.member.value
    member.joined_at = now
    member.updated_at = now
    await session.flush()


async def count_recent_joiners(session, chat_id: int, window_seconds: int) -> int:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=max(window_seconds, 1))
    result = await session.execute(
        select(func.count(ChatMember.id)).where(
            ChatMember.chat_id == chat_id,
            ChatMember.joined_at.is_not(None),
            ChatMember.joined_at >= since,
        )
    )
    return int(result.scalar() or 0)


async def send_temporary_notice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    delete_after_seconds: int | None = None,
) -> None:
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as exc:
        log.warning("send_join_guard_notice_failed", chat_id=chat_id, error=str(exc))
        return
    if delete_after_seconds and delete_after_seconds > 0:
        async def _cleanup() -> None:
            await asyncio.sleep(delete_after_seconds)
            try:
                await msg.delete()
            except Exception:
                return
        asyncio.create_task(_cleanup())


async def apply_join_guard_action(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    *,
    mute: bool,
    kick: bool,
    mute_seconds: int = 86400,
) -> None:
    if kick:
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        return
    if mute:
        until_date = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=max(mute_seconds, 60))
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=until_date,
        )


async def handle_join_spam_guard(context: ContextTypes.DEFAULT_TYPE, chat, user, settings) -> bool:
    if not bool(getattr(settings, "join_spam_guard_enabled", False)):
        return False
    signals = collect_join_spam_signals(user)
    threshold = int(getattr(settings, "join_spam_detect_rules_count", 2) or 2)
    if len(signals) < threshold:
        return False
    try:
        await apply_join_guard_action(
            context,
            chat.id,
            user.id,
            mute=bool(getattr(settings, "join_spam_mute_member_enabled", False)),
            kick=bool(getattr(settings, "join_spam_kick_member_enabled", False)),
            mute_seconds=int(getattr(settings, "verification_mute_duration", 86400) or 86400),
        )
    except Exception as exc:
        log.warning("join_spam_guard_action_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    if bool(getattr(settings, "join_spam_send_invalid_msg_enabled", False)):
        mention = user.mention_html()
        await send_temporary_notice(
            context,
            chat.id,
            f"🚯 {mention} 命中进群垃圾拦截，已终止后续验证流程。\n命中项：{len(signals)} 条",
            delete_after_seconds=int(getattr(settings, "join_spam_tip_delete_after_seconds", 60) or 60),
        )
    return True


async def handle_join_burst_guard(context: ContextTypes.DEFAULT_TYPE, session, chat, members: list, settings) -> bool:
    if not members or not bool(getattr(settings, "join_burst_enabled", False)):
        return False
    recent_count = await count_recent_joiners(session, chat.id, int(getattr(settings, "join_burst_window_seconds", 30) or 30))
    threshold = int(getattr(settings, "join_burst_threshold_count", 10) or 10)
    if recent_count < threshold:
        return False
    for user in members:
        try:
            await apply_join_guard_action(
                context,
                chat.id,
                user.id,
                mute=bool(getattr(settings, "join_burst_mute_enabled", False)),
                kick=bool(getattr(settings, "join_burst_kick_enabled", False)),
                mute_seconds=int(getattr(settings, "verification_mute_duration", 86400) or 86400),
            )
        except Exception as exc:
            log.warning("join_burst_guard_action_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    if getattr(settings, "join_burst_tip_mode", "tip_and_delete") != "no_tip":
        names = "、".join((member.first_name or member.username or str(member.id)) for member in members[:5])
        await send_temporary_notice(
            context,
            chat.id,
            f"🚪 检测到批量进群，{recent_count} 人在时间窗口内加入。\n本批处理：{names}",
            delete_after_seconds=60,
        )
    return True


async def start_self_review_if_needed(context: ContextTypes.DEFAULT_TYPE, session, chat, user, settings) -> bool:
    if not bool(getattr(settings, "join_self_review_enabled", False)):
        return False
    ch = await create_or_replace_challenge(
        session,
        chat_id=chat.id,
        user_id=user.id,
        ttl_seconds=int(getattr(settings, "join_self_review_timeout_seconds", 300) or 300),
        verification_type=VerificationMode.captcha.value,
    )
    ch.question = build_self_review_question()
    ch.answer = SELF_REVIEW_EXPECTED_ANSWER
    await session.flush()
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"📝 {user.mention_html()} 请发送以下口令完成自助审核：\n\n"
                f"<b>{SELF_REVIEW_EXPECTED_ANSWER}</b>\n\n"
                f"⏱️ {settings.join_self_review_timeout_seconds} 秒内完成"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        log.warning("send_self_review_prompt_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        ch.solved = True
        ch.timeout_handled = True
        await session.flush()
        return False
    return True


async def resolve_verification_config_state(session, db, chat, user) -> ConversationState | None:
    if chat.type != "private":
        state = await ConversationStateService.get(session, chat.id, user.id)
        if state and state.state_type == "verification_config":
            return state
        return None
    target_chat_id = await ChatResolver.get_current_chat(db, user.id)
    if target_chat_id:
        state = await ConversationStateService.get(session, target_chat_id, user.id)
        if state and state.state_type == "verification_config":
            return state
    stmt = (
        select(ConversationState)
        .where(ConversationState.user_id == user.id, ConversationState.state_type == "verification_config")
        .order_by(desc(ConversationState.id))
    )
    result = await session.execute(stmt)
    row = result.first()
    state = row[0] if row else None
    return state if state and state.state_type == "verification_config" else None


async def mark_challenge_released(session, chat_id: int, user_id: int) -> None:
    ch = await get_challenge(session, chat_id, user_id)
    if ch is None:
        return
    ch.solved = True
    ch.timeout_handled = True
    await session.flush()
