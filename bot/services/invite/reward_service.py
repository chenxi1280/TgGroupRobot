"""邀请奖励服务 - 处理邀请追踪和积分奖励"""

from __future__ import annotations

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, InviteTracking


async def track_and_award_invite(
    session: AsyncSession,
    chat_id: int,
    inviter_user_id: int,
    invited_user_id: int,
    invite_link_id: int | None = None,
) -> tuple[bool, bool, str | None]:
    """
    追踪邀请并发放积分

    Args:
        session: 数据库会话
        chat_id: 群组ID
        inviter_user_id: 邀请人用户ID
        invited_user_id: 被邀请人用户ID
        invite_link_id: 邀请链接ID

    Returns:
        (is_new_invite, points_awarded, error_message)
    """
    # 检查是否已经追踪过这个邀请（防止重复计算）
    existing_result = await session.execute(
        select(InviteTracking).where(
            and_(
                InviteTracking.chat_id == chat_id,
                InviteTracking.invited_user_id == invited_user_id,
            )
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        # 已经被追踪过，不是新邀请
        return False, False, None

    # 创建新的邀请追踪记录
    tracking = InviteTracking(
        chat_id=chat_id,
        inviter_user_id=inviter_user_id,
        invited_user_id=invited_user_id,
        invite_link_id=invite_link_id,
        points_awarded=False,
    )
    session.add(tracking)
    await session.flush()

    # 获取群组设置
    settings_result = await session.execute(
        select(ChatSettings).where(ChatSettings.chat_id == chat_id)
    )
    settings = settings_result.scalar_one_or_none()

    if not settings or not settings.invite_points_enabled or not settings.invite_points or settings.invite_points <= 0:
        # 没有启用邀请积分
        return True, False, None

    # 发放积分
    from bot.services.points.activity_service import add_invite_points

    result = await add_invite_points(
        session,
        chat_id=chat_id,
        inviter_user_id=inviter_user_id,
        points=settings.invite_points,
        daily_limit=settings.invite_points_daily_limit,
    )

    if result.success:
        tracking.points_awarded = True
        return True, True, None
    else:
        # 积分发放失败（可能达到每日上限）
        return True, False, result.reason


async def clear_invite_data(session: AsyncSession, chat_id: int) -> int:
    """
    清空群组的所有邀请数据

    Args:
        session: 数据库会话
        chat_id: 群组ID

    Returns:
        删除的记录数
    """
    # 统计要删除的记录数
    result = await session.execute(
        select(func.count(InviteTracking.id)).where(InviteTracking.chat_id == chat_id)
    )
    count = result.scalar() or 0

    # 执行删除
    await session.execute(
        delete(InviteTracking).where(InviteTracking.chat_id == chat_id)
    )

    return count
