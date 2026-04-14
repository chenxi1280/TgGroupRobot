from __future__ import annotations

import structlog
from sqlalchemy import desc, select
from telegram.ext import ContextTypes

from backend.features.verification.verification_service import (
    SELF_REVIEW_EXPECTED_ANSWER,
    build_self_review_question,
    create_or_replace_challenge,
    get_challenge,
)
from backend.platform.db.schema.models.core import ConversationState
from backend.platform.db.schema.models.enums import VerificationMode
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.handlers.base.chat_resolver import ChatResolver

log = structlog.get_logger(__name__)


async def start_self_review_if_needed(context: ContextTypes.DEFAULT_TYPE, session, chat, user, settings) -> bool:
    if not bool(getattr(settings, "join_self_review_enabled", False)):
        return False
    challenge = await create_or_replace_challenge(
        session,
        chat_id=chat.id,
        user_id=user.id,
        ttl_seconds=int(getattr(settings, "join_self_review_timeout_seconds", 300) or 300),
        verification_type=VerificationMode.captcha.value,
    )
    challenge.question = build_self_review_question()
    challenge.answer = SELF_REVIEW_EXPECTED_ANSWER
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
        challenge.solved = True
        challenge.timeout_handled = True
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
    challenge = await get_challenge(session, chat_id, user_id)
    if challenge is None:
        return
    challenge.solved = True
    challenge.timeout_handled = True
    await session.flush()
