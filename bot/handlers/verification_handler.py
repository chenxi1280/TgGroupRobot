from __future__ import annotations

import datetime as dt
import re

import structlog
from sqlalchemy import func, or_, select, desc
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.chat_resolver import ChatResolver
from bot.i18n.strings import t
from bot.keyboards.common.verification import (
    admin_verify_keyboard,
    verification_keyboard,
    verification_timeout_help_keyboard,
)
from bot.models.core import ChatMember, ConversationState, TgUser
from bot.models.enums import MemberRole
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.permission_service import PermissionPolicyService
from bot.services.core.user_service import ensure_user
from bot.services.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    build_self_review_question,
    create_or_replace_challenge,
    get_challenge_by_token,
    get_challenge,
    is_self_review_question,
    render_self_review_question,
    solve_by_answer,
    solve_by_token_scoped,
)
from bot.services.integration.invite_service import track_and_award_invite
from bot.services.state.conversation_state_service import ConversationStateService
from bot.services.welcome_service import WelcomeService
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely, build_public_error_text, mark_callback_query_answered


log = structlog.get_logger(__name__)

_JOIN_SPAM_KEYWORD_RE = re.compile(
    r"(https?://|t\.me/|广告|推广|博彩|兼职|刷单|加群|拉人|电报|飞机|代发|赚钱)",
    flags=re.IGNORECASE,
)


def _user_mention_html(user_id: int) -> str:
    return f'<a href="tg://user?id={user_id}">{user_id}</a>'


def _extract_unmute_target_user_id(message, message_text: str) -> int | None:
    """从“解封”消息中提取目标用户ID。

    支持：
    1) 回复用户消息后发送“解封”
    2) 文本提及用户（text_mention）
    3) 文本中直接写 @123456789 或 user_id:123456789
    """
    if getattr(message, "reply_to_message", None) is not None:
        reply_user = getattr(message.reply_to_message, "from_user", None)
        if reply_user is not None:
            return reply_user.id

    for entity in [*(message.entities or [])]:
        entity_type = getattr(entity.type, "value", entity.type)
        if entity_type == "text_mention" and entity.user is not None:
            return entity.user.id

    for pattern in [
        r"@(-?\d{5,})",
        r"(?:user_id|uid|用户id)\s*[:： ]\s*(-?\d{5,})",
    ]:
        m = re.search(pattern, message_text, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


async def _resolve_username_to_user_id(context: ContextTypes.DEFAULT_TYPE, message_text: str) -> int | None:
    """从 @username 尝试解析 user_id（仅公开用户名可解析）。"""
    username: str | None = None

    # 1) 显式 @username
    m = re.search(r"@([A-Za-z0-9_]{5,})", message_text)
    if m:
        username = m.group(1)

    # 2) 兼容“解封 Username”/“/unmute Username”
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


def _extract_unmute_name_token(message_text: str) -> str | None:
    m = re.search(r"(?:^|\s)(?:解封|/unmute)\s+([^\s]+)", message_text, flags=re.IGNORECASE)
    if not m:
        return None
    token = m.group(1).strip()
    token = token.lstrip("@").strip()
    return token or None


async def _resolve_name_from_db(session, name_token: str) -> int | None:
    """按用户名/名字从本地库解析 user_id（仅唯一命中时返回）。"""
    if not name_token:
        return None

    token = name_token.lower()
    stmt = (
        select(TgUser.id)
        .where(
            or_(
                func.lower(TgUser.username) == token,
                func.lower(TgUser.first_name) == token,
            )
        )
        .limit(2)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    if len(rows) == 1:
        return int(rows[0])
    return None


def _resolve_state_chat_id(state: ConversationState, fallback_chat_id: int | None = None) -> int | None:
    target_chat_id = state.state_data.get("target_chat_id") if state.state_data else None
    if isinstance(target_chat_id, int) and target_chat_id != 0:
        return target_chat_id
    if state.chat_id != 0:
        return state.chat_id
    if fallback_chat_id and fallback_chat_id != 0:
        return fallback_chat_id
    return None


def _collect_join_spam_signals(user) -> list[str]:
    username = (getattr(user, "username", None) or "").strip()
    full_name = " ".join(
        part.strip()
        for part in [
            getattr(user, "first_name", None) or "",
            getattr(user, "last_name", None) or "",
        ]
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
    if _JOIN_SPAM_KEYWORD_RE.search(haystack):
        signals.append("promo_keyword")
    return signals


async def _upsert_chat_member_join(session, chat_id: int, user) -> None:
    result = await session.execute(
        select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    now = dt.datetime.now(dt.UTC)
    if member is None:
        session.add(
            ChatMember(
                chat_id=chat_id,
                user_id=user.id,
                role=MemberRole.member.value,
                joined_at=now,
            )
        )
        await session.flush()
        return

    member.role = MemberRole.member.value
    member.joined_at = now
    member.updated_at = now
    await session.flush()


async def _count_recent_joiners(session, chat_id: int, window_seconds: int) -> int:
    since = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=max(window_seconds, 1))
    result = await session.execute(
        select(func.count(ChatMember.id)).where(
            ChatMember.chat_id == chat_id,
            ChatMember.joined_at.is_not(None),
            ChatMember.joined_at >= since,
        )
    )
    return int(result.scalar() or 0)


async def _send_temporary_notice(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    delete_after_seconds: int | None = None,
) -> None:
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
        )
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


async def _apply_join_guard_action(
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


async def _handle_join_spam_guard(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    settings,
) -> bool:
    if not bool(getattr(settings, "join_spam_guard_enabled", False)):
        return False

    signals = _collect_join_spam_signals(user)
    threshold = int(getattr(settings, "join_spam_detect_rules_count", 2) or 2)
    if len(signals) < threshold:
        return False

    try:
        await _apply_join_guard_action(
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
        await _send_temporary_notice(
            context,
            chat.id,
            (
                f"🚯 {mention} 命中进群垃圾拦截，已终止后续验证流程。\n"
                f"命中项：{len(signals)} 条"
            ),
            delete_after_seconds=int(getattr(settings, "join_spam_tip_delete_after_seconds", 60) or 60),
        )
    return True


async def _handle_join_burst_guard(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    members: list,
    settings,
) -> bool:
    if not members or not bool(getattr(settings, "join_burst_enabled", False)):
        return False

    recent_count = await _count_recent_joiners(
        session,
        chat.id,
        int(getattr(settings, "join_burst_window_seconds", 30) or 30),
    )
    threshold = int(getattr(settings, "join_burst_threshold_count", 10) or 10)
    if recent_count < threshold:
        return False

    for user in members:
        try:
            await _apply_join_guard_action(
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
        await _send_temporary_notice(
            context,
            chat.id,
            (
                f"🚪 检测到批量进群，{recent_count} 人在时间窗口内加入。\n"
                f"本批处理：{names}"
            ),
            delete_after_seconds=60,
        )
    return True


async def _start_self_review_if_needed(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    settings,
) -> bool:
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

    mention = user.mention_html()
    try:
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"📝 {mention} 请发送以下口令完成自助审核：\n\n"
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


async def _resolve_verification_config_state(
    session,
    db: Database,
    chat,
    user,
) -> ConversationState | None:
    """尽量使用统一状态服务定位验证配置状态。"""
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
        .where(
            ConversationState.user_id == user.id,
            ConversationState.state_type == "verification_config",
        )
        .order_by(desc(ConversationState.id))
    )
    result = await session.execute(stmt)
    row = result.first()
    state = row[0] if row else None
    if state and state.state_type == "verification_config":
        return state
    return None


async def _mark_challenge_released(session, chat_id: int, user_id: int) -> None:
    ch = await get_challenge(session, chat_id, user_id)
    if ch is None:
        return
    ch.solved = True
    ch.timeout_handled = True
    await session.flush()


async def _try_admin_manual_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """管理员文本解封：支持“解封 + 回复用户消息”或“解封 @用户ID”"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return False

    chat = update.effective_chat
    actor = update.effective_user
    message = update.effective_message
    text = (message.text or "").strip()

    if chat.type == "private" or not text:
        return False

    normalized = text.lower()
    wants_unmute = ("解封" in text) or normalized.startswith("/unmute")
    if not wants_unmute:
        return False

    if not await PermissionPolicyService.can_manage(context, chat.id, actor.id, capability="moderation"):
        return False

    target_user_id = _extract_unmute_target_user_id(message, text)
    if target_user_id is None:
        target_user_id = await _resolve_username_to_user_id(context, text)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if target_user_id is None:
            token = _extract_unmute_name_token(text) or ""
            target_user_id = await _resolve_name_from_db(session, token)

        if target_user_id is None:
            try:
                await message.reply_text("请回复目标用户消息或使用“解封 @用户ID / 解封 @username / 解封 用户名”。")
            except Exception:
                pass
            return True

        settings = await get_chat_settings(session, chat.id)
        await _mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()

    await _unrestrict_and_notify(context, chat.id, target_user_id, settings.language)

    try:
        actor_name = actor.mention_html()
        target_name = _user_mention_html(target_user_id)
        await message.reply_text(
            f"✅ 管理员解封完成\n管理员: {actor_name}\n用户: {target_name}\n方式: 文本解封",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return True


async def new_members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        new_members = list(update.effective_message.new_chat_members or [])

        for u in new_members:
            await ensure_user(
                session,
                user_id=u.id,
                username=u.username,
                first_name=u.first_name,
                last_name=u.last_name,
                language_code=u.language_code,
            )
            await _upsert_chat_member_join(session, chat.id, u)
        await session.flush()

        # 发送欢迎消息（独立于验证功能）
        sent_doc_welcome = await WelcomeService.send_for_mode(
            context,
            session,
            chat_id=chat.id,
            mode="on_join",
            members=new_members,
        )
        if not sent_doc_welcome and settings.welcome_enabled:
            for u in new_members:
                mention = u.mention_html()
                if settings.welcome_message:
                    # 使用自定义欢迎消息
                    welcome_text = settings.welcome_message.format(user=mention, chat=chat.title or "本群")
                else:
                    # 使用默认欢迎消息
                    welcome_text = t(settings.language, "welcome.default", user=mention, chat=chat.title or "本群")
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=welcome_text,
                        parse_mode="HTML",
                    )
                except Exception as e:
                    log.warning("send_welcome_message_failed", chat_id=chat.id, error=str(e))

        if await _handle_join_burst_guard(context, session, chat, new_members, settings):
            await session.commit()
            return

        # 如果未启用验证，则尝试进入自助审核模式；否则直接返回
        if not settings.verification_enabled:
            for u in new_members:
                started = await _start_self_review_if_needed(context, session, chat, u, settings)
                if started:
                    try:
                        await context.bot.restrict_chat_member(
                            chat_id=chat.id,
                            user_id=u.id,
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
                                can_change_info=False,
                                can_invite_users=False,
                                can_pin_messages=False,
                                can_manage_topics=False,
                            ),
                        )
                    except Exception as e:
                        log.warning("restrict_chat_member_for_self_review_failed", chat_id=chat.id, user_id=u.id, error=str(e))
            await session.commit()
            return

        for u in new_members:
            if await _handle_join_spam_guard(context, chat, u, settings):
                continue

            # 追踪邀请并发放积分
            # 注意：由于 Telegram 的 API 限制，new_chat_members 消息不包含使用的邀请链接信息
            # 需要使用 ChatMemberHandler 来获取 via_invite_link 信息
            # 这里先尝试追踪（如果有 invite_link_id 的上下文）
            # TODO: 实现 ChatMemberHandler 来准确追踪邀请链接
            invite_link_id = context.user_data.get("pending_invite_link_id") if context.user_data else None
            if invite_link_id:
                from bot.models.core import InviteLink
                from sqlalchemy import select

                link_result = await session.execute(
                    select(InviteLink).where(InviteLink.id == invite_link_id)
                )
                link = link_result.scalar_one_or_none()
                if link and link.chat_id == chat.id:
                    is_new, awarded, _ = await track_and_award_invite(
                        session,
                        chat_id=chat.id,
                        inviter_user_id=link.created_by_user_id,
                        invited_user_id=u.id,
                        invite_link_id=link.id,
                    )
                    if is_new:
                        # 更新链接的成员计数
                        link.member_count += 1
                        if awarded and settings.invite_link_notify:
                            try:
                                # 通知邀请人
                                await context.bot.send_message(
                                    chat_id=link.created_by_user_id,
                                    text=f"🎉 恭喜！您邀请的 {u.first_name or u.username or '用户'} 加入了群组 {chat.title}"
                                )
                            except Exception as e:
                                log.warning("invite_notification_failed", inviter_id=link.created_by_user_id, error=str(e))

            ch = await create_or_replace_challenge(
                session,
                chat_id=chat.id,
                user_id=u.id,
                ttl_seconds=settings.verification_timeout_seconds,
                verification_type=settings.verification_mode,
            )

            # 先限制发言（最小限制：不能发消息）
            perms = ChatPermissions(
                can_send_messages=settings.verification_restrict_can_send,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False,
            )
            try:
                await context.bot.restrict_chat_member(chat_id=chat.id, user_id=u.id, permissions=perms)
            except Exception as e:
                # 权限不足只能静默失败，记录日志
                log.warning("restrict_chat_member_failed", chat_id=chat.id, user_id=u.id, error=str(e))

            # 根据验证类型发送不同的验证消息
            mention = u.mention_html()
            prompt_sent = True
            try:
                if settings.verification_mode == "button":
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=t(settings.language, "verify.prompt", user=mention, seconds=settings.verification_timeout_seconds),
                        reply_markup=verification_keyboard(ch.token),
                        parse_mode="HTML",
                    )
                elif settings.verification_mode == "math":
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"🔢 {mention} 请回答以下数学题以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成",
                        parse_mode="HTML",
                    )
                elif settings.verification_mode == "captcha":
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"🔢 {mention} 请输入以下验证码以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成",
                        parse_mode="HTML",
                    )
                elif settings.verification_mode == "admin":
                    # 管理员确认模式：发送管理员确认请求
                    # 管理员确认模式没有超时限制（永久等待管理员审核）
                    user_name = u.username or u.first_name or "用户"
                    mention_text = f"@{user_name}" if u.username else mention
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"👋 {mention_text} 申请加入群组，请管理员确认是否通过。",
                        reply_markup=admin_verify_keyboard(u.id, ch.token),
                        parse_mode="HTML",
                    )
            except Exception as e:
                prompt_sent = False
                log.warning("send_verification_prompt_failed", chat_id=chat.id, user_id=u.id, mode=settings.verification_mode, error=str(e))

            # 兜底：验证消息发送失败时，不继续按“未验证超时”惩罚，避免误伤
            if not prompt_sent:
                ch.solved = True
                ch.timeout_handled = True
                await session.flush()

                await _unrestrict_and_notify(context, chat.id, u.id, settings.language)
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"⚠️ {mention} 验证提示发送失败，已临时放行。请管理员检查机器人在本群发言权限。",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        await session.commit()


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    data = q.data or ""
    # 兼容两种格式：
    # 1) vfy:<token>（当前标准）
    # 2) vfy:verify:<token>（历史格式）
    token = ""
    if data.startswith("vfy:verify:"):
        token = data.split("vfy:verify:", 1)[-1].strip()
    elif data.startswith("vfy:"):
        token = data.split("vfy:", 1)[-1].strip()

    if not token:
        await answer_callback_query_safely(update, "验证参数无效", show_alert=True)
        return

    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        # 先检查 token 归属，避免非本人点击把消息误改成“已过期”
        origin = await get_challenge_by_token(session, token)
        if origin is None:
            await session.commit()
            await q.answer()
            mark_callback_query_answered(update)
            await q.edit_message_text(t("zh-CN", "verify.expired"))
            return

        if origin.chat_id != chat.id:
            await session.commit()
            await answer_callback_query_safely(update, "该验证按钮不属于当前群", show_alert=True)
            return

        if origin.user_id != update.effective_user.id:
            await session.commit()
            await answer_callback_query_safely(update, "仅新成员本人可点击此按钮验证", show_alert=True)
            return

        ch = await solve_by_token_scoped(
            session,
            token,
            expected_chat_id=chat.id,
            expected_user_id=update.effective_user.id,
        )
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)

    if ch is None:
        await q.edit_message_text(t("zh-CN", "verify.expired"))
        return

    # 过期：不放行
    if not ch.solved:
        await q.edit_message_text(t(settings.language, "verify.expired"))
        return

    if settings.join_self_review_enabled:
        async with db.session_factory() as session:
            started = await _start_self_review_if_needed(context, session, chat, update.effective_user, settings)
            await session.commit()
        if started:
            await q.edit_message_text("✅ 初步验证已通过，请继续发送口令完成自助审核。")
            return

    await _unrestrict_and_notify(context, chat.id, ch.user_id, settings.language)
    await _send_after_verify_welcome(context, chat.id, ch.user_id)
    await q.edit_message_text(t(settings.language, "verify.ok"))


async def verify_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理验证答案消息（数学题/验证码模式）"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    message_text = update.effective_message.text or ""

    if chat.type == "private" or not message_text:
        return

    # 管理员可在群内用“解封”手动解除验证超时禁言
    if await _try_admin_manual_unmute(update, context):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        # 只处理非按钮模式的验证，或自助审核挑战
        if settings.verification_mode == "button":
            existing = await get_challenge(session, chat.id, user.id)
            if existing is None or existing.solved or not is_self_review_question(existing.question):
                await session.commit()
                return
            ch = existing
        else:
            # 检查用户是否有待验证的挑战
            ch = await get_challenge(session, chat.id, user.id)
            if ch is None or ch.solved:
                await session.commit()
                return

        if ch is None:
            await session.commit()
            return

        # 尝试验证答案
        result = await solve_by_answer(session, chat.id, user.id, message_text)
        await session.commit()

        if result and result.solved:
            # 验证成功
            try:
                await update.effective_message.reply_text("✅ 验证成功！")
            except Exception as e:
                log.warning("verify_success_reply_failed", user_id=user.id, error=str(e))
            if settings.join_self_review_enabled and not is_self_review_question(ch.question):
                async with db.session_factory() as next_session:
                    started = await _start_self_review_if_needed(context, next_session, chat, user, settings)
                    await next_session.commit()
                if started:
                    try:
                        await update.effective_message.reply_text(
                            f"📝 请继续发送：{SELF_REVIEW_EXPECTED_ANSWER}"
                        )
                    except Exception:
                        pass
                    return
            await _unrestrict_and_notify(context, chat.id, user.id, settings.language)
            await _send_after_verify_welcome(context, chat.id, user.id)
        else:
            # 验证失败
            if is_self_review_question(ch.question) and settings.join_self_review_wrong_action == "reject_block":
                try:
                    async with db.session_factory() as next_session:
                        await _mark_challenge_released(next_session, chat.id, user.id)
                        await next_session.commit()
                    await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
                    await update.effective_message.reply_text("❌ 自助审核失败，已拒绝入群。")
                except Exception as e:
                    log.warning("self_review_block_failed", user_id=user.id, chat_id=chat.id, error=str(e))
                return
            prompt = render_self_review_question(ch.question) if is_self_review_question(ch.question) else ch.question
            try:
                await update.effective_message.reply_text(f"❌ 答案错误，请重试。\n\n{prompt}")
            except Exception as e:
                log.warning("verify_failed_reply_failed", user_id=user.id, error=str(e))


async def _unrestrict_and_notify(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, language: str) -> None:
    """解除限制并发送通知"""
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_change_info=False,
                can_invite_users=True,
                can_pin_messages=False,
                can_manage_topics=False,
            ),
        )
    except Exception as e:
        log.warning("edit_admin_verify_message_failed", error=str(e))


async def _send_after_verify_welcome(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await WelcomeService.send_for_mode(
            context,
            session,
            chat_id=chat_id,
            mode="after_verify",
            user_ids=[user_id],
        )
        await session.commit()


async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """管理员确认验证回调

    处理管理员对用户验证的通过/拒绝操作。

    回调数据格式：adm_vfy:<user_id>:<token>:<action>
    - user_id: 待验证用户 ID
    - token: 验证令牌
    - action: approve（通过）或 reject（拒绝）
    """
    if update.callback_query is None:
        return

    q = update.callback_query

    data = q.data or ""
    # 解析回调数据：adm_vfy:<user_id>:<token>:<action>
    parts = CallbackParser.parse(data)
    if parts.action != "adm_vfy" or parts.length() < 4:
        log.warning("invalid_admin_verify_callback", callback_data=data)
        await answer_callback_query_safely(update, "验证回调无效", show_alert=True)
        return

    try:
        user_id = parts.require_int(1, label="user_id")
        token = parts.get(2)
        action = parts.get(3)
    except ValueError as e:
        log.warning("invalid_admin_verify_callback_format", callback_data=data, error=str(e))
        await answer_callback_query_safely(update, "验证参数格式错误", show_alert=True)
        return
    if action not in {"approve", "reject"}:
        log.warning("invalid_admin_verify_action", callback_data=data, action=action)
        await answer_callback_query_safely(update, "验证操作无效", show_alert=True)
        return

    chat = update.effective_chat
    if chat is None:
        return

    # 仅群管理员可执行通过/拒绝
    actor = update.effective_user
    if actor is None:
        return
    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=chat.id,
        user_id=actor.id,
        capability="moderation",
    )
    if not allowed:
        await answer_callback_query_safely(update, reason or "仅群管理员可执行该操作", show_alert=True)
        return

    await q.answer()
    mark_callback_query_answered(update)

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        if action == "approve":
            # 通过验证
            ch = await solve_by_token_scoped(
                session,
                token,
                expected_chat_id=chat.id,
                expected_user_id=user_id,
            )
            await session.commit()

            if ch and ch.solved:
                if settings.join_self_review_enabled:
                    target_user = await context.bot.get_chat_member(chat.id, user_id)
                    started = await _start_self_review_if_needed(context, session, chat, target_user.user, settings)
                    await session.commit()
                    try:
                        if started:
                            await q.edit_message_text(f"✅ 已通过用户 {user_id} 的初步验证，已进入自助审核。")
                        else:
                            await q.edit_message_text(f"✅ 已通过用户 {user_id} 的验证")
                    except Exception as e:
                        log.warning("edit_admin_verify_message_failed", error=str(e))
                    if started:
                        return
                # 解除限制并发送通知
                await _unrestrict_and_notify(context, chat.id, user_id, settings.language)
                await _send_after_verify_welcome(context, chat.id, user_id)
                try:
                    await q.edit_message_text(f"✅ 已通过用户 {user_id} 的验证")
                except Exception as e:
                    log.warning("edit_admin_verify_message_failed", error=str(e))
            else:
                # 验证已过期或不存在
                try:
                    await q.edit_message_text(f"❌ 验证已过期或不存在")
                except Exception as e:
                    log.warning("edit_admin_verify_message_failed", error=str(e))
        else:  # reject
            # 拒绝验证：踢出用户
            try:
                await _mark_challenge_released(session, chat.id, user_id)
                await session.commit()
                await context.bot.ban_chat_member(chat_id=chat.id, user_id=user_id)
                await q.edit_message_text(f"❌ 已拒绝并踢出用户 {user_id}")
            except Exception as e:
                log.warning("kick_user_failed", user_id=user_id, chat_id=chat.id, error=str(e))
                try:
                    await q.edit_message_text(f"⚠️ 操作失败：{build_public_error_text(e)}")
                except Exception as e:
                    log.warning("edit_admin_verify_message_failed", error=str(e))


async def verification_timeout_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """验证超时协助回调

    回调格式：
    - vfy_help:appeal:<user_id>  被禁言用户本人点击，通知管理员处理
    - vfy_help:unmute:<user_id>  管理员点击，立即解除限制
    """
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query

    data = q.data or ""
    parts = CallbackParser.parse(data)
    if parts.action != "vfy_help" or parts.length() < 3:
        await answer_callback_query_safely(update, "操作无效", show_alert=True)
        return

    action = parts.get(1)
    try:
        target_user_id = parts.require_int(2, label="user_id")
    except ValueError:
        await answer_callback_query_safely(update, "用户参数无效", show_alert=True)
        return

    chat = update.effective_chat
    actor = update.effective_user

    if action == "appeal":
        if actor.id != target_user_id:
            await answer_callback_query_safely(update, "仅被禁言用户本人可发起解封申请", show_alert=True)
            return

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"🆘 {actor.mention_html()} 请求管理员协助解封。\n"
                    f"管理员可点击下方按钮直接解封。"
                ),
                parse_mode="HTML",
                reply_markup=verification_timeout_help_keyboard(target_user_id),
            )
            await q.answer("已通知管理员，请等待处理", show_alert=True)
            mark_callback_query_answered(update)
        except Exception as exc:
            log.warning("verification_timeout_help_appeal_failed", chat_id=chat.id, user_id=target_user_id, error=str(exc))
            await answer_callback_query_safely(update, "通知管理员失败，请稍后重试", show_alert=True)
        return

    if action != "unmute":
        return

    allowed, reason = await PermissionPolicyService.require_manage(
        context,
        chat_id=chat.id,
        user_id=actor.id,
        capability="moderation",
    )
    if not allowed:
        await answer_callback_query_safely(update, reason or "仅群管理员可解封", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await _mark_challenge_released(session, chat.id, target_user_id)
        await session.commit()

    await _unrestrict_and_notify(context, chat.id, target_user_id, settings.language)

    try:
        await q.answer()
        mark_callback_query_answered(update)
        await q.edit_message_text(
            (
                f"✅ 管理员 {actor.mention_html()} 已解封用户 "
                f"{_user_mention_html(target_user_id)}\n方式: 按钮解封"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning("verification_timeout_unmute_edit_failed", error=str(e))


# ==================== 验证配置相关 ====================

async def verification_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理验证配置流程中的消息"""
    # 关键日志 - 使用 critical 确保一定输出
    log.critical(
        "=== VERIFICATION_CONFIG_HANDLER CALLED ===",
        has_update=update is not None,
        has_chat=update.effective_chat is not None if update else False,
        has_user=update.effective_user is not None if update else False,
    )

    # 模块级别的日志，确认 handler 被调用
    import traceback
    log.warning(
        "=== VERIFICATION_CONFIG_HANDLER ENTRY ===",
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        traceback=traceback.format_stack()
    )

    try:
        # 基础检查
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            log.info("verification_config_missing_fields", has_chat=update.effective_chat is not None, has_user=update.effective_user is not None, has_message=update.effective_message is not None)
            return

        log.info("verification_config_basic_checks_passed")

        chat = update.effective_chat
        user = update.effective_user
        text = update.effective_message.text or ""

        if not text:
            log.info("verification_config_empty_text")
            return

        log.info("verification_config_getting_db")

        # 获取数据库连接
        db: Database = context.application.bot_data["db"]
        log.info("verification_config_db_obtained", db_instance=str(type(db)))

        async with db.session_factory() as session:
            state = await _resolve_verification_config_state(session, db, chat, user)
            log.info(
                "verification_config_state_check",
                state_found=state is not None,
                state_type=state.state_type if state else None,
            )

            if state is None:
                await session.commit()
                log.info("verification_config_state_not_match_returning")
                return

            target_chat_id = _resolve_state_chat_id(state, chat.id if chat.type != "private" else None)
            if target_chat_id is None:
                await session.commit()
                await update.effective_message.reply_text("❌ 无法获取群组ID，请重新进入配置。")
                return

            allowed, reason = await PermissionPolicyService.require_manage(
                context,
                chat_id=target_chat_id,
                user_id=user.id,
                capability="settings",
            )
            if not allowed:
                await ConversationStateService.clear(session, target_chat_id, user.id)
                await session.commit()
                await update.effective_message.reply_text(f"❌ {reason or '需要管理员权限'}")
                return

            log.info("verification_config_parsing_config")
            await _parse_verification_config(update, session, state, text)

    except Exception as e:
        log.exception(
            "verification_config_handler_error",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )


async def _parse_verification_config(update: Update, session, state: ConversationState, text: str) -> None:
    """解析验证配置"""
    try:
        lines = text.strip().split("\n")

        # 默认值
        enabled = False
        mode = "button"
        timeout_seconds = 180
        timeout_action = "mute"
        mute_duration = 86400
        restrict_can_send = False

        # 解析配置
        for line in lines:
            line = line.strip()
            if line.startswith("状态:"):
                status_str = line.split(":", 1)[1].strip().lower()
                enabled = status_str in ["开启", "open", "true", "1", "yes", "on"]
            elif line.startswith("验证方式:"):
                mode_str = line.split(":", 1)[1].strip()
                mode_map = {
                    "按钮验证": "button",
                    "button": "button",
                    "数学题": "math",
                    "math": "math",
                    "验证码": "captcha",
                    "captcha": "captcha",
                    "管理员确认": "admin",
                    "admin": "admin",
                    "管理员": "admin",
                }
                mode = mode_map.get(mode_str, mode_str)
            elif line.startswith("超时时间:"):
                try:
                    timeout_seconds = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise ValueError("超时时间必须是数字")
            elif line.startswith("超时处理:"):
                action_str = line.split(":", 1)[1].strip()
                if action_str in ["禁言", "mute"]:
                    timeout_action = "mute"
                elif action_str in ["踢出", "踢出群聊", "kick"]:
                    timeout_action = "kick"
            elif line.startswith("禁言时长:"):
                try:
                    mute_duration = int(line.split(":", 1)[1].strip())
                except ValueError:
                    raise ValueError("禁言时长必须是数字")
            elif line.startswith("限制发言:"):
                restrict_str = line.split(":", 1)[1].strip().lower()
                restrict_can_send = restrict_str in ["是", "yes", "true", "1", "开启"]

        # 获取目标群组ID
        target_chat_id = _resolve_state_chat_id(state, update.effective_chat.id if update.effective_chat else None)
        if target_chat_id is None:
            raise ValueError("无法获取群组ID")

        # 更新配置
        await ModuleSettingsService.ensure(
            session,
            chat_id=target_chat_id,
            chat_type="supergroup" if target_chat_id < 0 else "private",
            user_id=update.effective_user.id if update.effective_user else None,
        )
        settings = await get_chat_settings(session, target_chat_id)
        settings.verification_enabled = enabled
        settings.verification_mode = mode
        settings.verification_timeout_seconds = timeout_seconds
        settings.verification_timeout_action = timeout_action
        settings.verification_mute_duration = mute_duration
        settings.verification_restrict_can_send = restrict_can_send

        # 清除状态
        if update.effective_user is not None:
            await ConversationStateService.clear(session, chat_id=target_chat_id, user_id=update.effective_user.id)

        await session.commit()

        # 发送成功消息
        mode_label = {
            "button": "按钮验证",
            "math": "数学题",
            "captcha": "验证码",
            "admin": "管理员确认",
        }.get(mode, mode)

        action_label = "禁言" if timeout_action == "mute" else "踢出"
        status_label = "开启" if enabled else "关闭"

        result_text = f"✅ 验证配置已更新！\n\n"
        result_text += f"📋 配置内容：\n"
        result_text += f"• 状态: {status_label}\n"
        result_text += f"• 验证方式: {mode_label}\n"
        result_text += f"• 超时时间: {timeout_seconds} 秒\n"
        result_text += f"• 超时处理: {action_label}\n"
        if timeout_action == "mute":
            result_text += f"• 禁言时长: {mute_duration} 秒\n"
        result_text += f"• 限制发言: {'是' if restrict_can_send else '否'}\n"

        # 显示多级返回按钮：返回验证菜单 / 返回主菜单
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 返回验证菜单", callback_data=f"adm:menu:verification:{target_chat_id}")],
            [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")]
        ])

        await update.effective_message.reply_text(result_text, reply_markup=keyboard)

    except ValueError as e:
        await update.effective_message.reply_text(f"❌ 配置格式错误: {str(e)}\n\n请重新发送配置或使用 /cancel 取消。")
    except Exception as e:
        log.exception("parse_verification_config_error", error=str(e))
        await update.effective_message.reply_text(f"❌ 配置失败: {str(e)}")


# ==================== 取消回调处理器 ====================

async def verification_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消验证配置，返回验证菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query

    # 解析参数：verification:cancel:{chat_id}
    data = q.data or ""
    parts = CallbackParser.parse(data)
    if parts.action != "verification" or parts.length() < 3:
        await answer_callback_query_safely(update, "无法获取群组信息", show_alert=True)
        return

    try:
        target_chat_id = parts.require_int(2, label="chat_id")
    except ValueError:
        await answer_callback_query_safely(update, "群组ID格式错误", show_alert=True)
        return

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await _resolve_verification_config_state(session, db, chat, user)
        resolved_chat_id = _resolve_state_chat_id(state, target_chat_id) if state is not None else target_chat_id
        allowed, reason = await PermissionPolicyService.require_manage(
            context,
            chat_id=resolved_chat_id,
            user_id=user.id,
            capability="settings",
        )
        if not allowed:
            await session.commit()
            await answer_callback_query_safely(update, reason or "需要管理员权限", show_alert=True)
            return

        # 清除配置状态
        await ConversationStateService.clear(session, resolved_chat_id, user.id)
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)

    # 返回验证菜单
    await admin_verification_menu_callback(update, context, resolved_chat_id)


async def admin_verification_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, target_chat_id: int) -> None:
    """显示验证管理菜单（供取消后返回使用）"""
    from bot.handlers.admin_handler import AdminHandler
    handler = AdminHandler()
    await handler._show_verification_menu(update, context, target_chat_id)
