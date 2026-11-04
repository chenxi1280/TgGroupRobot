from __future__ import annotations

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import select

from backend.features.verification.slider_puzzle import TOLERANCE, new_puzzle, puzzle_id, render_puzzle
from backend.platform.db.schema.models.core import TgChat, VerificationChallenge

OPEN_TIMEOUT_STATUSES = {"pending", "retryable_failed"}
STATE_TEXT = {
    "pending": "拖动滑块，将拼图对齐缺口",
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
    if challenge.verification_type != "web" and challenge.mini_app_status == "pending":
        raise HTTPException(status_code=409, detail="验证入口已更新，请联系管理员重新发起验证")
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
    chat = await session.get(TgChat, challenge.chat_id)
    status = pending_status(challenge)
    return {
        "status": status, "message": STATE_TEXT.get(status, "验证已过期，请联系管理员"),
        "chat_id": challenge.chat_id, "chat_title": chat.title if chat else str(challenge.chat_id),
        "puzzle": render_puzzle(challenge.question, int(challenge.answer)) if status == "pending" else None,
        "expires_at": challenge.expires_at.isoformat(),
        "server_time": dt.datetime.now(dt.UTC).isoformat(),
    }


async def claim_submission(session, token: str, user_id: int, *, payload):
    challenge = await load_challenge(session, token, user_id, lock=True)
    if pending_status(challenge) != "pending":
        return challenge, None
    if puzzle_id(challenge.question) != payload.puzzle_id:
        raise HTTPException(status_code=422, detail="拼图已更新，请重试")
    if abs(int(challenge.answer) - payload.position) > TOLERANCE:
        challenge.question, challenge.answer = new_puzzle()
        await session.commit()
        raise HTTPException(status_code=422, detail="未对齐缺口，已更换拼图，请重试")
    challenge.solved = True
    challenge.mini_app_status = "processing"
    await session.commit()
    return challenge, "verify"
