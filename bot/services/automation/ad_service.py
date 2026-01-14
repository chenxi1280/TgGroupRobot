from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import AdCampaign


@dataclass
class CreateAdResult:
    """创建广告结果"""
    success: bool
    reason: Literal["ok", "error"]
    ad: AdCampaign | None = None


@dataclass
class SendAdResult:
    """发送广告结果"""
    success: bool
    reason: Literal["ok", "not_found", "disabled", "error"]
    ad: AdCampaign | None = None


async def create_ad_campaign(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    title: str,
    content: str,
    image_file_id: str | None = None,
    image_url: str | None = None,
    schedule_time: dt.datetime | None = None,
    frequency: str | None = None,
    start_time: dt.datetime | None = None,
    interval_hours: int | None = None,
    max_send_count: int | None = None,
) -> CreateAdResult:
    """创建广告活动

    Args:
        session: 数据库会话
        chat_id: 群组ID
        created_by_user_id: 创建者用户ID
        title: 广告标题
        content: 广告内容
        image_file_id: 图片文件ID
        image_url: 图片URL
        schedule_time: 定时推送时间（旧版，兼容）
        frequency: 推送频次（旧版，兼容）
        start_time: 开始推送时间（新版）
        interval_hours: 推送间隔（小时）（新版）
        max_send_count: 最大推送次数（新版）
    """
    try:
        has_image = bool(image_file_id or image_url)

        ad = AdCampaign(
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            title=title,
            content=content,
            image_file_id=image_file_id,
            image_url=image_url,
            has_image=has_image,
            schedule_time=schedule_time,
            frequency=frequency,
            start_time=start_time,
            interval_hours=interval_hours,
            max_send_count=max_send_count,
            send_count=0,
            enabled=True,
        )
        session.add(ad)
        await session.flush()
        return CreateAdResult(success=True, reason="ok", ad=ad)
    except Exception:
        return CreateAdResult(success=False, reason="error")


async def get_chat_ads(
    session: AsyncSession,
    chat_id: int,
    enabled_only: bool = False,
) -> list[AdCampaign]:
    """获取群组的广告列表"""
    stmt = select(AdCampaign).where(AdCampaign.chat_id == chat_id)
    if enabled_only:
        stmt = stmt.where(AdCampaign.enabled == True)
    stmt = stmt.order_by(AdCampaign.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """获取广告"""
    stmt = select(AdCampaign).where(AdCampaign.id == ad_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def delete_ad(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    """删除广告"""
    ad = await get_ad(session, ad_id)
    if not ad:
        return False
    await session.delete(ad)
    return True


async def toggle_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """切换广告启用状态"""
    ad = await get_ad(session, ad_id)
    if ad:
        ad.enabled = not ad.enabled
    return ad


async def get_due_ads(
    session: AsyncSession,
) -> list[AdCampaign]:
    """获取到期的待发送广告"""
    now = dt.datetime.now(dt.UTC)
    stmt = select(AdCampaign).where(
        AdCampaign.enabled == True,
        AdCampaign.schedule_time <= now,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_ad_sent(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    """标记广告已发送"""
    ad = await get_ad(session, ad_id)
    if not ad:
        return False

    ad.last_sent_at = dt.datetime.now(dt.UTC)
    ad.send_locked = False  # 释放锁

    # 增加发送计数
    if ad.send_count is not None:
        ad.send_count += 1

    # 检查是否达到最大推送次数
    if ad.max_send_count and ad.send_count >= ad.max_send_count:
        ad.enabled = False

    # 如果是一次性广告（旧逻辑），发送后禁用
    if ad.frequency == "once" or ad.frequency is None:
        ad.enabled = False
    return True


async def lock_ad_for_sending(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """锁定广告用于发送（防止重复发送）"""
    ad = await get_ad(session, ad_id)
    if not ad or ad.send_locked:
        return None
    ad.send_locked = True
    return ad


def should_send_ad(ad: AdCampaign) -> bool:
    """检查广告是否应该发送"""
    if not ad.enabled:
        return False

    now = dt.datetime.now(dt.UTC)

    # 优先使用新的推送逻辑（自定义间隔和次数）
    if ad.start_time and ad.interval_hours:
        # 检查开始时间
        if now < ad.start_time:
            return False

        # 检查推送次数
        if ad.max_send_count and ad.send_count >= ad.max_send_count:
            return False

        # 计算下次推送时间
        if ad.last_sent_at:
            next_send_time = ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
            return now >= next_send_time
        return True

    # 兼容旧的频次逻辑（向后兼容）
    # 检查定时时间
    if ad.schedule_time and now < ad.schedule_time:
        return False

    # 检查频次
    if ad.frequency == "once":
        return ad.last_sent_at is None
    elif ad.frequency == "daily":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= 1
        return True
    elif ad.frequency == "weekly":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= 7
        return True
    elif ad.frequency == "monthly":
        if ad.last_sent_at:
            return (now - ad.last_sent_at).days >= 30
        return True

    # 无频次限制，立即发送
    return True


async def get_scheduled_ads(session: AsyncSession) -> list[AdCampaign]:
    """获取所有待调度的广告

    包括：
    - 新逻辑：设置了 start_time 和 interval_hours 的广告
    - 旧逻辑：设置了 schedule_time 的广告（向后兼容）
    """
    from sqlalchemy import or_

    stmt = select(AdCampaign).where(
        AdCampaign.enabled == True,
        or_(
            # 新逻辑：有开始时间和推送间隔
            AdCampaign.start_time.isnot(None),
            # 旧逻辑：有定时时间（向后兼容）
            AdCampaign.schedule_time.isnot(None),
        ),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
