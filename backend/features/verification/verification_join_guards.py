from __future__ import annotations

import asyncio
import datetime as dt
import re

import structlog
from sqlalchemy import func, select
from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.core import ChatMember
from backend.platform.db.schema.models.enums import MemberRole
from backend.shared.async_tasks import spawn_background_task

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
        message = await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as exc:
        log.warning("send_join_guard_notice_failed", chat_id=chat_id, error=str(exc))
        return
    if delete_after_seconds and delete_after_seconds > 0:
        spawn_background_task(
            context,
            _cleanup_notice(message, delete_after_seconds),
            name="verification.cleanup_notice",
        )


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
        await send_temporary_notice(
            context,
            chat.id,
            f"🚯 {user.mention_html()} 命中进群垃圾拦截，已终止后续验证流程。\n命中项：{len(signals)} 条",
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


async def _cleanup_notice(message, delete_after_seconds: int) -> None:
    try:
        await asyncio.sleep(max(delete_after_seconds, 1))
    except asyncio.CancelledError:
        raise
    try:
        await message.delete()
    except Exception:
        return
