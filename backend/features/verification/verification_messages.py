from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_admin import try_admin_manual_unmute
from backend.features.verification.verification_helpers import (
    extract_unmute_name_token,
    extract_unmute_target_user_id,
    mark_challenge_released,
    start_self_review_if_needed,
)
from backend.features.verification.verification_runtime import (
    apply_verification_punishment,
    send_after_verify_welcome,
    unrestrict_and_notify,
)
from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    get_challenge,
    is_self_review_question,
    render_self_review_question,
    solve_by_answer,
)
from backend.platform.db.runtime.session import Database
from backend.shared.i18n.strings import t
from backend.shared.services.chat_service import get_chat_settings
from backend.features.moderation.services.user_action_runtime import execute_user_action


async def verify_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    message_text = update.effective_message.text or ""
    if chat.type == "private" or not message_text:
        return
    if await try_admin_manual_unmute(
        update,
        context,
        extract_target_user_id=extract_unmute_target_user_id,
        t=t,
        extract_target_name_token=extract_unmute_name_token,
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
                    started = await start_self_review_if_needed(context, next_session, chat, user, settings)
                    await next_session.commit()
                if started:
                    try:
                        await update.effective_message.reply_text(f"📝 请继续发送：{SELF_REVIEW_EXPECTED_ANSWER}")
                    except Exception:
                        pass
                    return
            await unrestrict_and_notify(context, chat.id, user.id, settings.language)
            await send_after_verify_welcome(context, chat.id, user.id)
        else:
            if is_self_review_question(ch.question) and settings.join_self_review_wrong_action == "reject_block":
                try:
                    await execute_user_action(
                        context,
                        feature="进群验证",
                        chat_id=chat.id,
                        user_id=user.id,
                        action="ban",
                        detail="自助审核失败，按配置拒绝入群",
                        raise_on_failure=True,
                    )
                    async with db.session_factory() as next_session:
                        await mark_challenge_released(next_session, chat.id, user.id)
                        await next_session.commit()
                    await update.effective_message.reply_text("❌ 自助审核失败，已拒绝入群。")
                except Exception:
                    try:
                        await update.effective_message.reply_text("❌ 处理失败，请检查机器人禁言/踢人权限。")
                    except Exception:
                        pass
                return
            wrong_action = getattr(settings, "verification_wrong_action", "none") or "none"
            if not is_self_review_question(ch.question) and wrong_action != "none":
                try:
                    await apply_verification_punishment(context, chat.id, user.id, settings, action=wrong_action)
                    async with db.session_factory() as next_session:
                        await mark_challenge_released(next_session, chat.id, user.id)
                        await next_session.commit()
                    await update.effective_message.reply_text("❌ 答案错误，已按本群配置处理。")
                except Exception:
                    try:
                        await update.effective_message.reply_text("❌ 处理失败，请检查机器人禁言/踢人权限。")
                    except Exception:
                        pass
                return
            prompt = render_self_review_question(ch.question) if is_self_review_question(ch.question) else ch.question
            try:
                await update.effective_message.reply_text(f"❌ 答案错误，请重试。\n\n{prompt}")
            except Exception:
                pass
