from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import TgUser


async def ensure_user(
    session: AsyncSession,
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    language_code: str | None,
) -> TgUser:
    res = await session.execute(select(TgUser).where(TgUser.id == user_id))
    u = res.scalar_one_or_none()
    if u is None:
        u = TgUser(
            id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
        )
        session.add(u)
        await session.flush()
        return u

    u.username = username
    u.first_name = first_name
    u.last_name = last_name
    u.language_code = language_code
    u.updated_at = dt.datetime.now(dt.UTC)
    return u



