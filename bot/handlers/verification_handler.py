from __future__ import annotations

from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.common.verification import verification_keyboard
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.user_service import ensure_user
from bot.services.verification_service import (
    create_or_replace_challenge,
    get_challenge,
    solve_by_answer,
    solve_by_token,
)
from bot.services.integration.invite_service import track_and_award_invite


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

        # 发送欢迎消息（独立于验证功能）
        if settings.welcome_enabled:
            for u in update.effective_message.new_chat_members or []:
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
                except Exception:
                    pass

        # 如果未启用验证，直接返回
        if not settings.verification_enabled:
            await session.commit()
            return

        for u in update.effective_message.new_chat_members or []:
            await ensure_user(
                session,
                user_id=u.id,
                username=u.username,
                first_name=u.first_name,
                last_name=u.last_name,
                language_code=u.language_code,
            )

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
                            except Exception:
                                pass

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
            except Exception:
                # 权限不足就只能提示
                pass

            # 根据验证类型发送不同的验证消息
            mention = u.mention_html()
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

        await session.commit()


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    # vfy:<token>
    token = data.split("vfy:", 1)[-1].strip()
    if not token:
        return

    chat = update.effective_chat
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        ch = await solve_by_token(session, token)
        await session.commit()

    if ch is None:
        await q.edit_message_text(t("zh-CN", "verify.expired"))
        return

    # 过期：不放行
    if not ch.solved:
        await q.edit_message_text(t(settings.language, "verify.expired"))
        return

    await _unrestrict_and_notify(context, chat.id, ch.user_id, settings.language)
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

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)

        # 只处理非按钮模式的验证
        if settings.verification_mode == "button":
            await session.commit()
            return

        # 检查用户是否有待验证的挑战
        ch = await get_challenge(session, chat.id, user.id)
        if ch is None or ch.solved:
            await session.commit()
            return

        # 尝试验证答案
        result = await solve_by_answer(session, chat.id, user.id, message_text)
        await session.commit()

        if result and result.solved:
            # 验证成功
            try:
                await update.effective_message.reply_text("✅ 验证成功！")
            except Exception:
                pass
            await _unrestrict_and_notify(context, chat.id, user.id, settings.language)
        else:
            # 验证失败
            try:
                await update.effective_message.reply_text(f"❌ 答案错误，请重试。\n\n{ch.question}")
            except Exception:
                pass


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
    except Exception:
        pass
