"""积分账户与流水。"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import PointsAccount, PointsTransaction


async def get_balance(session: AsyncSession, chat_id: int, user_id: int) -> int:
    res = await session.execute(
        select(PointsAccount.balance).where(
            and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.user_id == user_id,
            )
        )
    )
    bal = res.scalar_one_or_none()
    return int(bal or 0)


async def _get_or_create_account(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> PointsAccount:
    res = await session.execute(
        select(PointsAccount).where(
            and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.user_id == user_id,
            )
        ).with_for_update()
    )
    acc = res.scalar_one_or_none()
    if acc is None:
        acc = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(acc)
        await session.flush()
    return acc


async def change_points(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
    amount: int,
    txn_type: str,
    reason: str | None = None,
) -> tuple[bool, int]:
    acc = await _get_or_create_account(session, chat_id, user_id)
    if amount < 0 and acc.balance < -amount:
        return False, acc.balance

    acc.balance += amount
    session.add(
        PointsTransaction(
            chat_id=chat_id,
            user_id=user_id,
            txn_type=txn_type,
            amount=amount,
            reason=reason,
        )
    )
    await session.flush()
    return True, acc.balance
