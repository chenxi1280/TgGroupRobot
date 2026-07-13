from __future__ import annotations

import structlog
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

log = structlog.get_logger(__name__)


async def _reply_verification(message, text: str, *, event: str, chat_id: int, user_id: int) -> bool:
    try:
        await message.reply_text(text)
        return True
    except Exception as exc:
        log.warning(event, chat_id=chat_id, user_id=user_id, error=str(exc))
        return False


async def _release_verification_challenge(db, *, chat_id: int, user_id: int) -> None:
    async with db.session_factory() as session:
        await mark_challenge_released(session, chat_id, user_id)
        await session.commit()


async def _handle_solved_verification(
    update, context, *, db, chat, user, settings, challenge
) -> None:
    await _reply_verification(
        update.effective_message, "✅ 验证成功！",
        event="verification_success_reply_failed", chat_id=chat.id, user_id=user.id,
    )
    needs_review = (
        settings.join_self_review_enabled
        and not is_self_review_question(challenge.question)
    )
    if needs_review:
        async with db.session_factory() as session:
            started = await start_self_review_if_needed(
                context, session, chat, user=user, settings=settings
            )
            await session.commit()
        if started:
            await _reply_verification(
                update.effective_message,
                f"📝 请继续发送：{SELF_REVIEW_EXPECTED_ANSWER}",
                event="verification_self_review_prompt_failed",
                chat_id=chat.id, user_id=user.id,
            )
            return
    await unrestrict_and_notify(
        context, chat.id, user.id, language=settings.language
    )
    await send_after_verify_welcome(context, chat.id, user.id)


async def _reply_action_failure(update, *, event: str, chat_id: int, user_id: int, exc) -> None:
    log.warning(event, chat_id=chat_id, user_id=user_id, error=str(exc))
    await _reply_verification(
        update.effective_message,
        "❌ 处理失败，请检查机器人禁言/踢人权限。",
        event=f"{event}_fallback_reply_failed", chat_id=chat_id, user_id=user_id,
    )


async def _handle_self_review_failure(
    update, context, *, db, chat, user, settings, challenge
) -> bool:
    should_reject = (
        is_self_review_question(challenge.question)
        and settings.join_self_review_wrong_action == "reject_block"
    )
    if not should_reject:
        return False
    try:
        await execute_user_action(
            context, feature="进群验证", chat_id=chat.id, user_id=user.id,
            action="ban", detail="自助审核失败，按配置拒绝入群",
            raise_on_failure=True,
        )
        await _release_verification_challenge(db, chat_id=chat.id, user_id=user.id)
        await update.effective_message.reply_text("❌ 自助审核失败，已拒绝入群。")
    except Exception as exc:
        await _reply_action_failure(
            update, event="verification_self_review_fail_reply_failed",
            chat_id=chat.id, user_id=user.id, exc=exc,
        )
    return True


async def _handle_wrong_answer_action(
    update, context, *, db, chat, user, settings, challenge
) -> bool:
    action = getattr(settings, "verification_wrong_action", "none") or "none"
    if is_self_review_question(challenge.question) or action == "none":
        return False
    try:
        await apply_verification_punishment(
            context, chat.id, user.id, settings=settings, action=action
        )
        await _release_verification_challenge(db, chat_id=chat.id, user_id=user.id)
        await update.effective_message.reply_text("❌ 答案错误，已按本群配置处理。")
    except Exception as exc:
        await _reply_action_failure(
            update, event="verification_wrong_answer_reply_failed",
            chat_id=chat.id, user_id=user.id, exc=exc,
        )
    return True


async def _handle_failed_verification(
    update, context, *, db, chat, user, settings, challenge
) -> None:
    if await _handle_self_review_failure(
        update, context, db=db, chat=chat, user=user,
        settings=settings, challenge=challenge,
    ):
        return
    if await _handle_wrong_answer_action(
        update, context, db=db, chat=chat, user=user,
        settings=settings, challenge=challenge,
    ):
        return
    prompt = (
        render_self_review_question(challenge.question)
        if is_self_review_question(challenge.question) else challenge.question
    )
    await _reply_verification(
        update.effective_message, f"❌ 答案错误，请重试。\n\n{prompt}",
        event="verification_retry_prompt_failed", chat_id=chat.id, user_id=user.id,
    )


async def _resolve_verification_request(update, context):
    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message
    if chat is None or user is None or message is None or chat.type == "private":
        return None
    message_text = message.text or ""
    if not message_text:
        return None
    handled = await try_admin_manual_unmute(
        update, context, extract_target_user_id=extract_unmute_target_user_id,
        t=t, extract_target_name_token=extract_unmute_name_token,
    )
    return None if handled else (chat, user, message_text)


async def _solve_verification(session, *, chat_id: int, user_id: int, answer: str):
    settings = await get_chat_settings(session, chat_id)
    challenge = await get_challenge(session, chat_id, user_id)
    if challenge is None or challenge.solved:
        await session.commit()
        return None
    requires_self_review = settings.verification_mode == "button"
    if requires_self_review and not is_self_review_question(challenge.question):
        await session.commit()
        return None
    result = await solve_by_answer(session, chat_id, user_id, answer=answer)
    await session.commit()
    return settings, challenge, result


async def verify_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    request = await _resolve_verification_request(update, context)
    if request is None:
        return
    chat, user, message_text = request
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        solved = await _solve_verification(
            session, chat_id=chat.id, user_id=user.id, answer=message_text
        )
    if solved is None:
        return
    settings, challenge, result = solved
    handler = _handle_solved_verification if result and result.solved else _handle_failed_verification
    await handler(
        update, context, db=db, chat=chat, user=user,
        settings=settings, challenge=challenge,
    )
