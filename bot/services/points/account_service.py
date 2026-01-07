"""积分账户管理服务 - 处理积分余额和账户操作"""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import PointsAccount


async def get_balance(session: AsyncSession, chat_id: int, user_id: int) -> int:
    """
    获取用户在群组中的积分余额

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        用户积分余额，如果没有账户则返回 0
    """
    res = await session.execute(
        select(PointsAccount.balance).where(
            and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.user_id == user_id
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
    """
    获取或创建积分账户

    Args:
        session: 数据库会话
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        积分账户对象
    """
    res = await session.execute(
        select(PointsAccount).where(
            and_(
                PointsAccount.chat_id == chat_id,
                PointsAccount.user_id == user_id
            )
        )
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
