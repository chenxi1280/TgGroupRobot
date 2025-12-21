from __future__ import annotations

from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.i18n.strings import t
from bot.keyboards.verification import verification_keyboard
from bot.services.chat_service import ensure_chat, get_chat_settings
from bot.services.user_service import ensure_user
from bot.services.verification_service import create_or_replace_challenge, solve_by_token


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
            ch = await create_or_replace_challenge(
                session, chat_id=chat.id, user_id=u.id, ttl_seconds=settings.verification_timeout_seconds
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

            mention = u.mention_html()
            await context.bot.send_message(
                chat_id=chat.id,
                text=t(settings.language, "verify.prompt", user=mention, seconds=settings.verification_timeout_seconds),
                reply_markup=verification_keyboard(ch.token),
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

    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=ch.user_id,
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

    await q.edit_message_text(t(settings.language, "verify.ok"))


