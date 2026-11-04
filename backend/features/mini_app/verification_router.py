from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from backend.features.mini_app.auth import MiniAppIdentity, verification_identity
from backend.features.verification.mini_app_actions import resolve_submission
from backend.features.verification.mini_app_service import (
    STATE_TEXT, challenge_view, claim_submission, load_challenge,
)
from backend.features.verification.slider_puzzle import MAX_POSITION

router = APIRouter(prefix="/miniapp/api/verification")


class VerificationSubmission(BaseModel):
    puzzle_id: str = Field(min_length=32, max_length=32)
    position: int = Field(ge=0, le=MAX_POSITION, strict=True)


@router.get("")
async def verification_detail(
    request: Request,
    token: str = Header(alias="X-Verification-Token"),
    actor: MiniAppIdentity = Depends(verification_identity),
):
    async with request.app.state.db.session_factory() as session:
        challenge = await load_challenge(session, token, actor.user.id)
        return await challenge_view(session, challenge)


@router.post("")
async def verification_submit(
    request: Request, payload: VerificationSubmission,
    *,
    token: str = Header(alias="X-Verification-Token"),
    actor: MiniAppIdentity = Depends(verification_identity),
):
    async with request.app.state.db.session_factory() as session:
        challenge, action = await claim_submission(session, token, actor.user.id, payload=payload)
        if action is None:
            return await challenge_view(session, challenge)
    result = await resolve_submission(request.app.state.telegram_app, token, actor.user, action=action)
    result["message"] = STATE_TEXT.get(result["status"], result.get("message", "请联系管理员"))
    return result
