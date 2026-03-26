from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import AdCampaign
from bot.services.base import ServiceBase
from bot.services.shared.result import CreateResult


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
) -> CreateResult:
    """
    创建广告活动

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        created_by_user_id: 创建者用户 ID
        title: 广告标题
        content: 广告内容
        image_file_id: 图片文件 ID
        image_url: 图片 URL
        schedule_time: 定时推送时间（旧版，兼容）
        frequency: 推送频次（旧版，兼容）
        start_time: 开始推送时间（新版）
        interval_hours: 推送间隔（小时）（新版）
        max_send_count: 最大推送次数（新版）

    Returns:
        CreateResult: 创建结果
    """
    try:
        has_image = bool(image_file_id or image_url)
        normalized_start_time = start_time
        normalized_interval_hours = interval_hours

        # 如果设置了循环间隔但未指定开始时间，则默认从当前开始
        if normalized_interval_hours and normalized_interval_hours > 0 and normalized_start_time is None:
            normalized_start_time = dt.datetime.now(dt.UTC)

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
            start_time=normalized_start_time,
            interval_hours=normalized_interval_hours,
            max_send_count=max_send_count,
            send_count=0,
            enabled=True,
        )
        session.add(ad)
        await session.flush()
        return CreateResult(success=True, reason="ok", entity=ad, entity_id=ad.id)
    except Exception:
        return CreateResult(success=False, reason="error")


async def get_chat_ads(
    session: AsyncSession,
    chat_id: int,
    enabled_only: bool = False,
) -> list[AdCampaign]:
    """
    获取群组的广告列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        enabled_only: 是否只返回启用的广告

    Returns:
        广告列表
    """
    return await ServiceBase._get_list(
        session,
        AdCampaign,
        filters={"chat_id": chat_id},
        active_only=enabled_only,
        order_by="created_at",
        descending=True,
    )


async def get_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """
    获取广告

    Args:
        session: 数据库会话
        ad_id: 广告 ID

    Returns:
        AdCampaign: 广告对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_id(session, AdCampaign, ad_id)


async def delete_ad(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    """
    删除广告

    Args:
        session: 数据库会话
        ad_id: 广告 ID

    Returns:
        是否删除成功
    """
    ad = await get_ad(session, ad_id)
    if not ad:
        return False
    await ServiceBase._delete_entity(session, ad)
    return True


async def toggle_ad(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """
    切换广告启用状态

    Args:
        session: 数据库会话
        ad_id: 广告 ID

    Returns:
        AdCampaign: 更新后的广告对象，如果不存在则返回 None
    """
    ad = await get_ad(session, ad_id)
    if ad:
        await ServiceBase._update_entity(
            session,
            ad,
            {"enabled": not ad.enabled},
        )
    return ad


async def get_due_ads(
    session: AsyncSession,
) -> list[AdCampaign]:
    """
    获取到期的待发送广告

    Args:
        session: 数据库会话

    Returns:
        到期的广告列表
    """
    ads = await ServiceBase._get_list(
        session,
        AdCampaign,
        active_only=True,
    )
    # 只返回真正到期且符合发送规则的广告，避免调用方重复实现业务判断
    return [ad for ad in ads if should_send_ad(ad)]


async def mark_ad_sent(
    session: AsyncSession,
    ad_id: int,
) -> bool:
    """
    标记广告已发送

    Args:
        session: 数据库会话
        ad_id: 广告 ID

    Returns:
        是否标记成功
    """
    ad = await get_ad(session, ad_id)
    if not ad:
        return False

    updates: dict[str, object] = {
        "last_sent_at": dt.datetime.now(dt.UTC),
        "send_locked": False,  # 释放锁
    }

    # 增加发送计数
    if ad.send_count is not None:
        updates["send_count"] = ad.send_count + 1

    next_send_count = (ad.send_count or 0) + 1

    # 检查是否达到最大推送次数
    if ad.max_send_count and next_send_count >= ad.max_send_count:
        updates["enabled"] = False

    # 新逻辑：存在 interval_hours 代表周期任务，不在这里按 once 关闭
    if not ad.interval_hours and (ad.frequency == "once" or ad.frequency is None):
        updates["enabled"] = False

    await ServiceBase._update_entity(session, ad, updates)
    return True


async def lock_ad_for_sending(
    session: AsyncSession,
    ad_id: int,
) -> AdCampaign | None:
    """
    锁定广告用于发送（防止重复发送）

    Args:
        session: 数据库会话
        ad_id: 广告 ID

    Returns:
        AdCampaign: 锁定后的广告对象，如果失败则返回 None
    """
    # 行级锁 + SKIP LOCKED，避免多实例并发重复发送
    stmt = (
        select(AdCampaign)
        .where(
            AdCampaign.id == ad_id,
            AdCampaign.enabled == True,
            AdCampaign.send_locked == False,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    ad = result.scalar_one_or_none()
    if not ad:
        return None

    ad.send_locked = True
    await session.flush()
    return ad


def should_send_ad(ad: AdCampaign) -> bool:
    """
    检查广告是否应该发送

    Args:
        ad: 广告对象

    Returns:
        是否应该发送
    """
    if not ad.enabled:
        return False

    now = dt.datetime.now(dt.UTC)

    # 优先使用新的推送逻辑（支持 interval_hours；start_time 可选）
    if ad.interval_hours and ad.interval_hours > 0:
        start_at = ad.start_time or ad.schedule_time or ad.created_at
        if start_at and now < start_at:
            return False

        # 检查推送次数
        send_count = ad.send_count or 0
        if ad.max_send_count and send_count >= ad.max_send_count:
            return False

        # 计算下次推送时间
        if ad.last_sent_at:
            next_send_time = ad.last_sent_at + dt.timedelta(hours=ad.interval_hours)
            return now >= next_send_time
        return True

    # 兼容旧频次逻辑（向后兼容）
    if ad.schedule_time and now < ad.schedule_time:
        return False

    if ad.frequency in (None, "once"):
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

    return ad.last_sent_at is None


async def get_scheduled_ads(session: AsyncSession) -> list[AdCampaign]:
    """
    获取所有待调度的广告

    包括：
    - 新逻辑：设置了 start_time 和 interval_hours 的广告
    - 旧逻辑：设置了 schedule_time 的广告（向后兼容）

    Args:
        session: 数据库会话

    Returns:
        待调度的广告列表
    """
    ads = await ServiceBase._get_list(
        session,
        AdCampaign,
        active_only=True,
    )
    # 过滤出有调度时间的广告
    return [
        ad for ad in ads
        if ad.start_time is not None or ad.schedule_time is not None or ad.interval_hours is not None
    ]
