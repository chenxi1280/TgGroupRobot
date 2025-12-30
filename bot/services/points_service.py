from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount, PointsTransaction, SignInLog
from bot.models.enums import PointsTxnType


async def get_balance(session: AsyncSession, chat_id: int, user_id: int) -> int:
    """获取用户在群组中的积分余额"""
    res = await session.execute(
        select(PointsAccount.balance).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
    )
    bal = res.scalar_one_or_none()
    return int(bal or 0)


async def _get_or_create_account(session: AsyncSession, chat_id: int, user_id: int) -> PointsAccount:
    """获取或创建积分账户"""
    res = await session.execute(
        select(PointsAccount).where(and_(PointsAccount.chat_id == chat_id, PointsAccount.user_id == user_id))
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
    """
    修改用户积分

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID
        amount: 积分变动量（正数为增加，负数为减少）
        txn_type: 交易类型
        reason: 变动原因

    Returns:
        (是否成功, 变动后余额)
        失败原因：余额不足时无法扣款
    """
    acc = await _get_or_create_account(session, chat_id, user_id)

    # 检查余额是否足够（扣款时）
    if amount < 0 and acc.balance < -amount:
        balance = acc.balance
        return False, balance

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


async def sign_in(session: AsyncSession, chat_id: int, user_id: int, points: int) -> tuple[bool, int]:
    """签到获取积分"""
    today = dt.datetime.now(dt.UTC).date()
    res = await session.execute(
        select(SignInLog).where(and_(SignInLog.chat_id == chat_id, SignInLog.user_id == user_id, SignInLog.sign_date == today))
    )
    if res.scalar_one_or_none() is not None:
        bal = await get_balance(session, chat_id, user_id)
        return False, bal

    # 先创建签到日志
    sign_log = SignInLog(
        chat_id=chat_id,
        user_id=user_id,
        sign_date=today,
        points_awarded=points,
    )
    session.add(sign_log)
    await session.flush()

    # 然后添加积分
    return await change_points(
        session,
        chat_id=chat_id,
        user_id=user_id,
        amount=points,
        txn_type=PointsTxnType.sign_in.value,
        reason="签到奖励",
    )





