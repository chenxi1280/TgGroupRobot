from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ModerationWarning


@dataclass(frozen=True)
class WarningResult:
    count: int
    threshold: int
    threshold_reached: bool
    expires_at: dt.datetime


async def add_warning(
    session: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
    rule: str,
    threshold: int,
    ttl_days: int = 7,
) -> WarningResult:
    now = dt.datetime.now(dt.UTC)
    expires_at = now + dt.timedelta(days=max(ttl_days, 1))
    threshold = max(int(threshold or 1), 1)

    item = (
        await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
    ).scalar_one_or_none()

    if item is None:
        item = ModerationWarning(
            chat_id=chat_id,
            user_id=user_id,
            warning_count=0,
            last_rule=rule,
            expires_at=expires_at,
        )
        session.add(item)
    elif item.expires_at <= now:
        item.warning_count = 0

    item.warning_count = int(item.warning_count or 0) + 1
    item.last_rule = rule
    item.expires_at = expires_at
    item.updated_at = now
    await session.flush()

    return WarningResult(
        count=item.warning_count,
        threshold=threshold,
        threshold_reached=item.warning_count >= threshold,
        expires_at=expires_at,
    )


async def clear_warning(
    session: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
) -> bool:
    item = (
        await session.execute(
            select(ModerationWarning).where(
                ModerationWarning.chat_id == chat_id,
                ModerationWarning.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        return False
    await session.delete(item)
    await session.flush()
    return True
