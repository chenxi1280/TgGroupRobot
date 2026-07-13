from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.verification.verification_helpers import mark_challenge_released, start_self_review_if_needed
from backend.features.verification.verification_runtime import (
    apply_verification_punishment,
    send_after_verify_welcome,
    unrestrict_and_notify,
)
from backend.features.verification.verification_service import get_challenge_by_token, solve_by_token_scoped
from backend.platform.db.runtime.session import Database
from backend.platform.telegram.errors import answer_callback_query_safely, mark_callback_query_answered
from backend.shared.i18n.strings import t
from backend.shared.services.chat_service import get_chat_settings

log = structlog.get_logger(__name__)


def _parse_verify_callback_data(data: str) -> tuple[str, str]:
    if not data.startswith("vfy:"):
        return "", "agree"
    payload = data.removeprefix("vfy:")
    if payload.startswith("verify:"):
        payload = payload.removeprefix("verify:")
    parts = payload.split(":")
    token = parts[0].strip() if parts else ""
    action = parts[1].strip() if len(parts) > 1 else "agree"
    if action not in {"agree", "decline"}:
        action = ""
    return token, action


async def _load_verification_state(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    token: str,
):
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat_id)
        origin = await get_challenge_by_token(session, token)
        await session.commit()
    return db, settings, origin


async def _validate_challenge_owner(
    update: Update,
    origin,
    chat_id: int,
    *,
    user_id: int,
) -> bool:
    q = update.callback_query
    if origin is None:
        await q.answer()
        mark_callback_query_answered(update)
        await q.edit_message_text("验证已过期")
        return False
    if origin.chat_id != chat_id:
        await answer_callback_query_safely(update, "该验证按钮不属于当前群", show_alert=True)
        return False
    if origin.user_id != user_id:
        await answer_callback_query_safely(update, "仅新成员本人可点击此按钮验证", show_alert=True)
        return False
    return True


async def _handle_verification_decline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    *,
    settings,
) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try:
        await apply_verification_punishment(context, chat_id, user_id, settings=settings)
    except Exception as exc:
        log.warning(
            "verification_decline_punishment_failed",
            chat_id=chat_id,
            user_id=user_id,
            error=str(exc),
        )
        await answer_callback_query_safely(
            update,
            "处理失败，请检查机器人禁言/踢人权限",
            show_alert=True,
        )
        return
    async with db.session_factory() as session:
        await mark_challenge_released(session, chat_id, user_id)
        await session.commit()
    await update.callback_query.answer()
    mark_callback_query_answered(update)
    await update.callback_query.edit_message_text("❌ 已选择不同意，已按本群配置处理。")


async def _solve_verification_agreement(
    db: Database,
    token: str,
    *,
    chat_id: int,
    user_id: int,
):
    async with db.session_factory() as session:
        challenge = await solve_by_token_scoped(
            session,
            token,
            expected_chat_id=chat_id,
            expected_user_id=user_id,
        )
        await session.commit()
    return challenge


async def _complete_verification_agreement(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    *,
    challenge,
    settings,
) -> None:
    q = update.callback_query
    chat = update.effective_chat
    await q.answer()
    mark_callback_query_answered(update)
    if challenge is None:
        await q.edit_message_text("验证已过期")
        return
    if not challenge.solved:
        await q.edit_message_text(t(settings.language, "verify.expired"))
        return
    if settings.join_self_review_enabled:
        async with db.session_factory() as session:
            started = await start_self_review_if_needed(
                context, session, chat, user=update.effective_user, settings=settings
            )
            await session.commit()
        if started:
            await q.edit_message_text("✅ 初步验证已通过，请继续发送口令完成自助审核。")
            return
    await unrestrict_and_notify(context, chat.id, challenge.user_id, language=settings.language)
    await send_after_verify_welcome(context, chat.id, challenge.user_id)
    await q.edit_message_text(t(settings.language, "verify.ok"))


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    data = q.data or ""
    token, action = _parse_verify_callback_data(data)
    if not token or not action:
        await answer_callback_query_safely(update, "验证参数无效", show_alert=True)
        return
    chat = update.effective_chat
    db, settings, origin = await _load_verification_state(context, chat.id, token)
    if not await _validate_challenge_owner(
        update, origin, chat.id, user_id=update.effective_user.id
    ):
        return
    if action == "decline":
        await _handle_verification_decline(update, context, db, settings=settings)
        return
    challenge = await _solve_verification_agreement(
        db,
        token,
        chat_id=chat.id,
        user_id=update.effective_user.id,
    )
    await _complete_verification_agreement(
        update,
        context,
        db,
        challenge=challenge,
        settings=settings,
    )
