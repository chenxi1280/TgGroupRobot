from __future__ import annotations

import datetime as dt
import hmac

from fastapi import HTTPException
from sqlalchemy import select

from backend.features.verification.verification_service import is_self_review_question
from backend.platform.db.schema.models.core import TgChat, VerificationChallenge
from backend.shared.services.chat_service import get_chat_settings

BASIC_MODES = {"button", "math", "captcha"}
OPEN_TIMEOUT_STATUSES = {"pending", "retryable_failed"}
STATE_TEXT = {
    "pending": "请完成验证",
    "processing": "验证正在处理，请稍后刷新；如长时间未完成，请联系管理员",
    "verified": "验证成功，可以返回群聊",
    "punished": "已按本群规则处理，请联系管理员",
    "failed": "处理失败，请联系群管理员",
    "uncertain": "处理结果尚未确认，请联系群管理员核实",
    "review": "基础验证已通过，请返回群聊完成口令审核",
}


async def load_challenge(session, token: str, user_id: int, *, lock: bool = False):
    stmt = select(VerificationChallenge).where(VerificationChallenge.token == token)
    if lock:
        stmt = stmt.with_for_update()
    challenge = await session.scalar(stmt)
    if challenge is None:
        raise HTTPException(status_code=410, detail="验证已过期或已被替换，请使用群里的最新入口")
    if challenge.user_id != user_id:
        raise HTTPException(status_code=403, detail="仅限新成员本人验证")
    if challenge.mini_app_status is None:
        raise HTTPException(status_code=409, detail="请按群内现有提示完成验证")
    return challenge


def pending_status(challenge) -> str:
    if challenge.mini_app_status != "pending":
        return challenge.mini_app_status
    if challenge.timeout_status not in OPEN_TIMEOUT_STATUSES:
        return "expired"
    if challenge.solved or challenge.expires_at <= dt.datetime.now(dt.UTC):
        return "expired"
    return "pending"


async def challenge_view(session, challenge) -> dict:
    settings = await get_chat_settings(session, challenge.chat_id)
    chat = await session.get(TgChat, challenge.chat_id)
    status = pending_status(challenge)
    return {
        "status": status, "message": STATE_TEXT.get(status, "验证已过期，请联系管理员"),
        "chat_id": challenge.chat_id, "chat_title": chat.title if chat else str(challenge.chat_id),
        "mode": challenge.verification_type,
        "question": challenge.question if status == "pending" else None,
        "agreement": settings.verification_agreement_text or "请阅读并同意本群规则后再发言。",
        "expires_at": challenge.expires_at.isoformat(),
        "server_time": dt.datetime.now(dt.UTC).isoformat(),
    }


def agreement_action(settings, action: str) -> str:
    if action == "agree":
        return "verify"
    if action == "decline":
        return settings.verification_timeout_action or "mute"
    raise HTTPException(status_code=422, detail="请选择同意或不同意")


def submission_action(challenge, settings, *, action: str, answer: str) -> str:
    if challenge.verification_type not in BASIC_MODES or is_self_review_question(challenge.question):
        raise HTTPException(status_code=409, detail="请返回群聊完成后续审核")
    if challenge.verification_type == "button":
        return agreement_action(settings, action)
    if action != "answer":
        raise HTTPException(status_code=422, detail="请提交验证答案")
    expected = (challenge.answer or "").lower().encode()
    if expected and hmac.compare_digest(expected, answer.lower().strip().encode()):
        return "verify"
    punishment = settings.verification_wrong_action or "none"
    if punishment == "none":
        raise HTTPException(status_code=422, detail="答案错误，请在截止前重试")
    return punishment


async def claim_submission(session, token: str, user_id: int, *, payload):
    challenge = await load_challenge(session, token, user_id, lock=True)
    if pending_status(challenge) != "pending":
        return challenge, None
    settings = await get_chat_settings(session, challenge.chat_id)
    action = submission_action(challenge, settings, action=payload.action, answer=payload.answer)
    challenge.solved = True
    challenge.mini_app_status = "processing"
    await session.commit()
    return challenge, action
