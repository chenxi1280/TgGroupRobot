from __future__ import annotations

import datetime as dt
import secrets

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import VerificationChallenge


def new_token() -> str:
    return secrets.token_urlsafe(24)


async def create_or_replace_challenge(
    session: AsyncSession, chat_id: int, user_id: int, ttl_seconds: int
) -> VerificationChallenge:
    res = await session.execute(
        select(VerificationChallenge).where(and_(VerificationChallenge.chat_id == chat_id, VerificationChallenge.user_id == user_id))
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        await session.delete(existing)
        await session.flush()

    token = new_token()
    ch = VerificationChallenge(
        chat_id=chat_id,
        user_id=user_id,
        token=token,
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ttl_seconds),
        solved=False,
    )
    session.add(ch)
    await session.flush()
    return ch


async def solve_by_token(session: AsyncSession, token: str) -> VerificationChallenge | None:
    res = await session.execute(select(VerificationChallenge).where(VerificationChallenge.token == token))
    ch = res.scalar_one_or_none()
    if ch is None:
        return None
    if ch.solved:
        return ch
    if dt.datetime.now(dt.UTC) > ch.expires_at:
        return ch
    ch.solved = True
    await session.flush()
    return ch



