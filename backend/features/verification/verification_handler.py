from __future__ import annotations

from sqlalchemy import select
from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from backend.features.invite.services.invite_service import track_and_award_invite
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

        sent_doc_welcome = await WelcomeService.send_for_mode(context, session, chat_id=chat.id, mode="on_join", members=new_members)
        if not sent_doc_welcome and settings.welcome_enabled:
            for u in new_members:
                mention = u.mention_html()
                welcome_text = settings.welcome_message.format(user=mention, chat=chat.title or "本群") if settings.welcome_message else t(settings.language, "welcome.default", user=mention, chat=chat.title or "本群")
                try:
                    await context.bot.send_message(chat_id=chat.id, text=welcome_text, parse_mode="HTML")
                except Exception:
                    pass

        if await _handle_join_burst_guard(context, session, chat, new_members, settings):
            await session.commit()
            return

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
                    except Exception:
                        pass
            await session.commit()
            return

        for u in new_members:
            if await _handle_join_spam_guard(context, chat, u, settings):
                continue

            invite_hint = _pop_invite_join_hint(context, chat_id=chat.id, user_id=u.id)
            if invite_hint is None and context.user_data:
                invite_link_id = context.user_data.get("pending_invite_link_id")
                if invite_link_id:
                    invite_hint = {"invite_link_id": invite_link_id}

            link = None
            if invite_hint:
                if invite_hint.get("invite_link"):
                    link_result = await session.execute(select(InviteLink).where(InviteLink.chat_id == chat.id, InviteLink.invite_link == invite_hint["invite_link"]))
                    link = link_result.scalar_one_or_none()
                elif invite_hint.get("invite_link_id"):
                    link_result = await session.execute(select(InviteLink).where(InviteLink.id == invite_hint["invite_link_id"]))
                    link = link_result.scalar_one_or_none()

            if link and link.chat_id == chat.id and link.created_by_user_id:
                is_new, awarded, _ = await track_and_award_invite(
                    session,
                    chat_id=chat.id,
                    inviter_user_id=link.created_by_user_id,
                    invited_user_id=u.id,
                    invite_link_id=link.id,
                )
                if is_new:
                    link.member_count += 1
                    if awarded and settings.invite_link_notify:
                        try:
                            await context.bot.send_message(chat_id=link.created_by_user_id, text=f"🎉 恭喜！您邀请的 {u.first_name or u.username or '用户'} 加入了群组 {chat.title}")
                        except Exception:
                            pass

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
            try:
                await context.bot.restrict_chat_member(chat_id=chat.id, user_id=u.id, permissions=perms)
            except Exception:
                pass

            mention = u.mention_html()
            prompt_sent = True
            try:
                if settings.verification_mode == "button":
                    from backend.shared.ui.common.verification import verification_keyboard

                    await context.bot.send_message(
                        chat_id=chat.id,
                        text=t(settings.language, "verify.prompt", user=mention, seconds=settings.verification_timeout_seconds),
                        reply_markup=verification_keyboard(ch.token),
                        parse_mode="HTML",
                    )
                elif settings.verification_mode == "math":
                    await context.bot.send_message(chat_id=chat.id, text=f"🔢 {mention} 请回答以下数学题以完成验证：\n\n<b>{ch.question}</b>\n\n⏱️ {settings.verification_timeout_seconds} 秒内完成", parse_mode="HTML")
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
            except Exception:
                prompt_sent = False

            if not prompt_sent:
                ch.solved = True
                ch.timeout_handled = True
                await session.flush()
                await _unrestrict_and_notify(context, chat.id, u.id, settings.language)
                try:
                    await context.bot.send_message(chat_id=chat.id, text=f"⚠️ {mention} 验证提示发送失败，已临时放行。请管理员检查机器人在本群发言权限。", parse_mode="HTML")
                except Exception:
                    pass

        await session.commit()


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    data = q.data or ""
    token = data.split("vfy:verify:", 1)[-1].strip() if data.startswith("vfy:verify:") else data.split("vfy:", 1)[-1].strip() if data.startswith("vfy:") else ""
    if not token:
        await answer_callback_query_safely(update, "验证参数无效", show_alert=True)
        return
    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        origin = await get_challenge_by_token(session, token)
        if origin is None:
            await session.commit()
            await q.answer()
            mark_callback_query_answered(update)
            await q.edit_message_text("验证已过期")
            return
        if origin.chat_id != chat.id:
            await session.commit()
            await answer_callback_query_safely(update, "该验证按钮不属于当前群", show_alert=True)
            return
        if origin.user_id != update.effective_user.id:
            await session.commit()
            await answer_callback_query_safely(update, "仅新成员本人可点击此按钮验证", show_alert=True)
            return
        ch = await solve_by_token_scoped(session, token, expected_chat_id=chat.id, expected_user_id=update.effective_user.id)
        await session.commit()

    await q.answer()
    mark_callback_query_answered(update)
    if ch is None:
        await q.edit_message_text("验证已过期")
        return
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
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    message_text = update.effective_message.text or ""
    if chat.type == "private" or not message_text:
        return
    if await _try_admin_manual_unmute_impl(
        update,
        context,
        extract_target_user_id=_extract_unmute_target_user_id,
        t=t,
        extract_target_name_token=_extract_unmute_name_token,
    ):
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        if settings.verification_mode == "button":
            existing = await get_challenge(session, chat.id, user.id)
            if existing is None or existing.solved or not is_self_review_question(existing.question):
                await session.commit()
                return
            ch = existing
        else:
            ch = await get_challenge(session, chat.id, user.id)
            if ch is None or ch.solved:
                await session.commit()
                return
        result = await solve_by_answer(session, chat.id, user.id, message_text)
        await session.commit()

        if result and result.solved:
            try:
                await update.effective_message.reply_text("✅ 验证成功！")
            except Exception:
                pass
            if settings.join_self_review_enabled and not is_self_review_question(ch.question):
                async with db.session_factory() as next_session:
                    started = await _start_self_review_if_needed(context, next_session, chat, user, settings)
                    await next_session.commit()
                if started:
                    try:
                        await update.effective_message.reply_text(f"📝 请继续发送：{SELF_REVIEW_EXPECTED_ANSWER}")
                    except Exception:
                        pass
                    return
            await _unrestrict_and_notify(context, chat.id, user.id, settings.language)
            await _send_after_verify_welcome(context, chat.id, user.id)
        else:
            if is_self_review_question(ch.question) and settings.join_self_review_wrong_action == "reject_block":
                try:
                    async with db.session_factory() as next_session:
                        await _mark_challenge_released(next_session, chat.id, user.id)
                        await next_session.commit()
                    await context.bot.ban_chat_member(chat_id=chat.id, user_id=user.id)
                    await update.effective_message.reply_text("❌ 自助审核失败，已拒绝入群。")
                except Exception:
                    pass
                return
            prompt = render_self_review_question(ch.question) if is_self_review_question(ch.question) else ch.question
            try:
                await update.effective_message.reply_text(f"❌ 答案错误，请重试。\n\n{prompt}")
            except Exception:
                pass
