from __future__ import annotations

import html

import structlog
from sqlalchemy import select
from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from backend.features.invite.services.invite_service import track_and_award_invite
from backend.features.group_ops.services.group_daily_stats import record_group_join_event
from backend.features.verification.verification_admin import (
    admin_verification_menu_callback,
    admin_verify_callback,
    parse_verification_config as _parse_verification_config,
    try_admin_manual_unmute as _try_admin_manual_unmute_impl,
    verification_cancel_callback,
    verification_config_handler,
    verification_timeout_help_callback,
)
from backend.features.verification.verification_helpers import (
    cache_invite_join_hint as _cache_invite_join_hint,
    collect_join_spam_signals as _collect_join_spam_signals,
    extract_unmute_name_token as _extract_unmute_name_token,
    extract_unmute_target_user_id as _extract_unmute_target_user_id,
    handle_join_burst_guard as _handle_join_burst_guard,
    handle_join_spam_guard as _handle_join_spam_guard,
    mark_challenge_released as _mark_challenge_released,
    pop_invite_join_hint as _pop_invite_join_hint,
    resolve_name_from_db as _resolve_name_from_db,
    resolve_state_chat_id as _resolve_state_chat_id,
    resolve_username_to_user_id as _resolve_username_to_user_id,
    resolve_verification_config_state as _resolve_verification_config_state,
    start_self_review_if_needed as _start_self_review_if_needed,
    upsert_chat_member_join as _upsert_chat_member_join,
    user_mention_html as _user_mention_html,
)
from backend.features.verification.verification_runtime import (
    apply_verification_punishment as _apply_verification_punishment,
    restrict_for_verification as _restrict_for_verification,
    send_after_verify_welcome as _send_after_verify_welcome,
    unrestrict_and_notify as _unrestrict_and_notify,
)
from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    create_or_replace_challenge,
    get_challenge,
    get_challenge_by_token,
    is_self_review_question,
    render_self_review_question,
    solve_by_answer,
    solve_by_token_scoped,
)
from backend.features.verification.welcome_service import WelcomeService
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import InviteLink
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.i18n.strings import t
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.shared.services.user_service import ensure_user

log = structlog.get_logger(__name__)
from backend.features.moderation.services.user_action_runtime import restrict_user_safely
from backend.features.verification.verification_callbacks import verify_callback
from backend.features.verification.verification_messages import verify_message_handler


async def invite_link_join_hint_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member_update = getattr(update, "chat_member", None)
    if member_update is None:
        return
    chat = getattr(member_update, "chat", None)
    invite_link_obj = getattr(member_update, "invite_link", None)
    new_chat_member = getattr(member_update, "new_chat_member", None)
    from_user = getattr(new_chat_member, "user", None)
    invite_link = getattr(invite_link_obj, "invite_link", None)
    if chat is None or from_user is None or not invite_link:
        return
    _cache_invite_join_hint(context, chat_id=chat.id, user_id=from_user.id, invite_link=invite_link)


async def _track_invite_for_member(context: ContextTypes.DEFAULT_TYPE, session, chat, member, settings) -> None:
    invite_hint = _pop_invite_join_hint(context, chat_id=chat.id, user_id=member.id)
    user_data = getattr(context, "user_data", None)
    if invite_hint is None and isinstance(user_data, dict):
        invite_link_id = user_data.pop("pending_invite_link_id", None)
        if invite_link_id:
            invite_hint = {"invite_link_id": invite_link_id}

    link = None
    if invite_hint:
        if invite_hint.get("invite_link"):
            link_result = await session.execute(
                select(InviteLink).where(
                    InviteLink.chat_id == chat.id,
                    InviteLink.invite_link == invite_hint["invite_link"],
                )
            )
            link = link_result.scalar_one_or_none()
        elif invite_hint.get("invite_link_id"):
            link_result = await session.execute(select(InviteLink).where(InviteLink.id == invite_hint["invite_link_id"]))
            link = link_result.scalar_one_or_none()

    if link and link.chat_id == chat.id and link.created_by_user_id:
        is_new, awarded, _ = await track_and_award_invite(
            session,
            chat_id=chat.id,
            inviter_user_id=link.created_by_user_id,
            invited_user_id=member.id,
            invite_link_id=link.id,
        )
        if is_new:
            link.member_count += 1
            if awarded and getattr(settings, "invite_link_notify", True):
                try:
                    await context.bot.send_message(
                        chat_id=link.created_by_user_id,
                        text=f"🎉 恭喜！您邀请的 {member.first_name or member.username or '用户'} 加入了群组 {chat.title}",
                    )
                except Exception as exc:
                    log.warning("invite_award_notify_failed", chat_id=chat.id, member_user_id=member.id, error=str(exc))


async def _send_verification_prompt(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    settings,
    text: str,
    *,
    reply_markup=None,
) -> None:
    media_type = getattr(settings, "verification_cover_media_type", None)
    file_id = getattr(settings, "verification_cover_file_id", None)
    if media_type == "photo" and file_id:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return
    if media_type == "video" and file_id:
        await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


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
        await record_group_join_event(session, chat.id, len(new_members))
        await session.flush()

        if await _handle_join_burst_guard(context, session, chat, new_members, settings):
            await session.commit()
            return

        welcomed_members = []
        for u in new_members:
            if await _handle_join_spam_guard(context, chat, u, settings):
                continue

            welcomed_members.append(u)
            await _track_invite_for_member(context, session, chat, u, settings)

            if not settings.verification_enabled:
                started = await _start_self_review_if_needed(context, session, chat, u, settings)
                if started:
                    try:
                        await _restrict_for_verification(context, chat.id, u.id)
                    except Exception as exc:
                        log.warning("self_review_restrict_failed", chat_id=chat.id, user_id=u.id, error=str(exc))
                continue

            if settings.verification_mode == "mute":
                try:
                    await _apply_verification_punishment(
                        context,
                        chat.id,
                        u.id,
                        settings,
                        action="mute",
                        mute_seconds=int(getattr(settings, "verification_direct_mute_duration", 0) or 0),
                    )
                except Exception as exc:
                    log.warning("verification_direct_punishment_failed", chat_id=chat.id, user_id=u.id, error=str(exc))
                continue

            ch = await create_or_replace_challenge(
                session,
                chat_id=chat.id,
                user_id=u.id,
                ttl_seconds=settings.verification_timeout_seconds,
                verification_type=settings.verification_mode,
            )

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
            restrict_result = await restrict_user_safely(
                context,
                feature="进群验证",
                chat_id=chat.id,
                user_id=u.id,
                permissions=perms,
                detail="新成员验证开始，限制验证期间发言权限",
            )
            if restrict_result.failed:
                ch.solved = True
                ch.timeout_handled = True
                await session.flush()
                continue

            mention = u.mention_html()
            prompt_sent = True
            try:
                if settings.verification_mode == "button":
                    from backend.shared.ui.common.verification import verification_keyboard

                    agreement_text = html.escape(
                        (getattr(settings, "verification_agreement_text", None) or "请阅读并同意本群规则后再发言。").strip()
                    )
                    await _send_verification_prompt(
                        context,
                        chat.id,
                        settings,
                        (
                            f"{mention}\n\n"
                            f"{agreement_text}\n\n"
                            f"⏱️ 请在 {settings.verification_timeout_seconds} 秒内点击按钮。"
                        ),
                        reply_markup=verification_keyboard(ch.token),
                    )
                elif settings.verification_mode == "math":
                    prompt_text = html.escape(
                        (getattr(settings, "verification_math_prompt_text", None) or "请回答下面的简单算术题完成验证。").strip()
                    )
                    await _send_verification_prompt(
                        context,
                        chat.id,
                        settings,
                        f"🔢 {mention}\n\n{prompt_text}\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成",
                    )
                elif settings.verification_mode == "captcha":
                    await context.bot.send_message(chat_id=chat.id, text=f"🔢 {mention} 请输入以下验证码以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成", parse_mode="HTML")
                elif settings.verification_mode == "admin":
                    from backend.shared.ui.common.verification import admin_verify_keyboard

                    user_name = u.username or u.first_name or "用户"
                    mention_text = f"@{user_name}" if u.username else mention
                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=f"👋 {mention_text} 申请加入群组，请管理员确认是否通过。",
                        reply_markup=admin_verify_keyboard(u.id, ch.token),
                        parse_mode="HTML",
                    )
            except Exception as exc:
                log.warning(
                    "verification_prompt_send_failed",
                    chat_id=chat.id,
                    user_id=u.id,
                    mode=settings.verification_mode,
                    error=str(exc),
                )
                prompt_sent = False

            if not prompt_sent:
                ch.solved = True
                ch.timeout_handled = True
                await session.flush()
                await _unrestrict_and_notify(context, chat.id, u.id, settings.language)
                try:
                    await context.bot.send_message(chat_id=chat.id, text=f"⚠️ {mention} 验证提示发送失败，已临时放行。请管理员检查机器人在本群发言权限。", parse_mode="HTML")
                except Exception as exc:
                    log.warning("verification_prompt_failure_notice_failed", chat_id=chat.id, user_id=u.id, error=str(exc))

        if welcomed_members:
            sent_doc_welcome = await WelcomeService.send_for_mode(
                context,
                session,
                chat_id=chat.id,
                mode="on_join",
                members=welcomed_members,
            )
            if not sent_doc_welcome and settings.welcome_enabled:
                for u in welcomed_members:
                    mention = u.mention_html()
                    welcome_text = (
                        settings.welcome_message.format(user=mention, chat=chat.title or "本群")
                        if settings.welcome_message
                        else t(settings.language, "welcome.default", user=mention, chat=chat.title or "本群")
                    )
                    try:
                        await context.bot.send_message(chat_id=chat.id, text=welcome_text, parse_mode="HTML")
                    except Exception as exc:
                        log.warning("welcome_message_send_failed", chat_id=chat.id, user_id=u.id, error=str(exc))

        await session.commit()
