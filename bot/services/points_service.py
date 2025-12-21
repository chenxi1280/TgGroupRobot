from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, SignInLog
from bot.models.enums import PointsTxnType


async def get_balance(session: AsyncSession, chat_id: int, user_id: int) -> int:
    res = await session.execute(
        select(PointsAccount.balance).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
    )
    bal = res.scalar_one_or_none()
    return int(bal or 0)


async def _get_or_create_account(session: AsyncSession, chat_id: int, user_id: int) -> PointsAccount:
    res = await session.execute(
        select(PointsAccount).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
    )
    acc = res.scalar_one_or_none()
    if acc is None:
        acc = PointsAccount(chat_id=chat_id, user_id=user_id, balance=0)
        session.add(acc)
        await session.flush()
    return acc


async def sign_in(session: AsyncSession, chat_id: int, user_id: int, points: int) -> tuple[bool, int]:
    today = dt.datetime.now(dt.UTC).date()
    res = await session.execute(
        select(SignInLog).where(and_(SignInLog.chat_id == chat_id, SignInLog.user_id == user_id, SignInLog.sign_date == today))
    )
    if res.scalar_one_or_none() is not None:
        bal = await get_balance(session, chat_id, user_id)
        return False, bal

    acc = await _get_or_create_account(session, chat_id, user_id)
    acc.balance += points
    session.add(PointsTransaction(chat_id=chat_id, user_id=user_id, txn_type=PointsTxnType.sign_in.value, amount=points))
    session.add(SignInLog(chat_id=chat_id, user_id=user_id, sign_date=today, points_awarded=points))
    await session.flush()
    return True, acc.balance



