from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from telegram.error import BadRequest, Forbidden, NetworkError, TelegramError

from backend.features.verification.mini_app_service import load_challenge
from backend.features.verification.verification_runtime import (
    apply_verification_punishment, send_after_verify_welcome, unrestrict_and_notify,
)
from backend.features.verification.verification_state import (
    create_self_review_challenge, send_self_review_prompt,
)
from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.ops_audit_service import record_ops_event


async def start_review(session, context, challenge, *, settings, user):
    next_challenge = await create_self_review_challenge(
        session, chat_id=challenge.chat_id, user_id=user.id, settings=settings,
    )
    await session.commit()
    await send_self_review_prompt(context, next_challenge, user=user, settings=settings)
    return {"status": "review", "message": "基础验证已通过，请返回群聊完成口令审核"}


async def verify_member(context, challenge, *, settings):
    await unrestrict_and_notify(
        context, challenge.chat_id, challenge.user_id, language=settings.language,
    )
    member = await context.bot.get_chat_member(challenge.chat_id, challenge.user_id)
    if member.status == "restricted":
        return "verified" if member.is_member and member.can_send_messages else "failed"
    return "verified" if member.status in {"member", "administrator", "creator"} else "failed"


async def perform_action(context, challenge, *, settings, action: str) -> str:
    if action == "verify":
        return await verify_member(context, challenge, settings=settings)
    await apply_verification_punishment(
        context, challenge.chat_id, challenge.user_id, settings=settings, action=action,
    )
    return "punished"


async def audit_resolution(session, challenge, *, status: str):
    await record_ops_event(
        session, domain="verification", event_type="mini_app_resolution",
        chat_id=challenge.chat_id, user_id=challenge.user_id,
        entity_type="verification_challenge", entity_id=str(challenge.id),
        severity="info" if status == "verified" else "warning", detail={"status": status},
    )


async def resolve_submission(app, token: str, user, *, action: str):
    context = SimpleNamespace(bot=app.bot, application=app)
    async with app.bot_data["db"].session_factory() as session:
        challenge = await load_challenge(session, token, user.id, lock=True)
        settings = await get_chat_settings(session, challenge.chat_id)
        if action == "verify" and settings.join_self_review_enabled:
            return await start_review(session, context, challenge, settings=settings, user=user)
        status = await _apply_and_record(session, context, challenge, settings=settings, action=action)
        return {"status": status, "chat_id": challenge.chat_id}


async def _apply_and_record(session, context, challenge, *, settings, action: str):
    try:
        status = await perform_action(context, challenge, settings=settings, action=action)
    except (BadRequest, Forbidden):
        status = "failed"
    except (NetworkError, TelegramError, RuntimeError):
        status = "uncertain"
    challenge.mini_app_status = status
    challenge.timeout_handled = True
    await audit_resolution(session, challenge, status=status)
    await session.commit()
    if status == "verified":
        await _welcome(context, challenge)
    return status


async def _welcome(context, challenge):
    try:
        await send_after_verify_welcome(context, challenge.chat_id, challenge.user_id)
    except TelegramError:
        async with context.application.bot_data["db"].session_factory() as session:
            await record_ops_event(
                session, domain="verification", event_type="mini_app_welcome_failed",
                chat_id=challenge.chat_id, user_id=challenge.user_id,
                severity="warning", detail={"at": dt.datetime.now(dt.UTC).isoformat()},
            )
            await session.commit()
