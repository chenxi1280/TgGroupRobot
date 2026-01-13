from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ScheduledMessage
from bot.models.enums import ScheduleType


@dataclass
class CreateResult:
    """创建定时消息结果"""
    success: bool
    reason: Literal[
        "ok",
        "invalid_content",
        "invalid_schedule_type",
        "invalid_interval",
    ]
    message: ScheduledMessage | None = None


@dataclass
class UpdateResult:
    """更新定时消息结果"""
    success: bool
    reason: Literal[
        "ok",
        "not_found",
        "invalid_content",
        "invalid_schedule_type",
    ]


@dataclass
class ToggleResult:
    """切换定时消息状态结果"""
    success: bool
    reason: Literal["ok", "not_found"]


def calculate_next_send_time(
    schedule_type: str,
    interval_minutes: int | None = None,
    base_time: dt.datetime | None = None,
) -> dt.datetime:
    """计算下次发送时间"""
    if base_time is None:
        base_time = dt.datetime.now(dt.UTC)

    match schedule_type:
        case ScheduleType.none.value:
            # 一次性消息，返回指定时间（默认当前时间）
            return base_time
        case ScheduleType.every_minute.value:
            return base_time + dt.timedelta(minutes=1)
        case ScheduleType.every_5_minutes.value:
            return base_time + dt.timedelta(minutes=5)
        case ScheduleType.every_15_minutes.value:
            return base_time + dt.timedelta(minutes=15)
        case ScheduleType.every_30_minutes.value:
            return base_time + dt.timedelta(minutes=30)
        case ScheduleType.every_hour.value:
            return base_time + dt.timedelta(hours=1)
        case ScheduleType.every_6_hours.value:
            return base_time + dt.timedelta(hours=6)
        case ScheduleType.every_12_hours.value:
            return base_time + dt.timedelta(hours=12)
        case ScheduleType.every_day.value:
            return base_time + dt.timedelta(days=1)
        case ScheduleType.custom.value:
            if interval_minutes and interval_minutes > 0:
                return base_time + dt.timedelta(minutes=interval_minutes)
            return base_time
        case _:
            return base_time


async def create_scheduled_message(
    session: AsyncSession,
    chat_id: int,
    created_by_user_id: int,
    content: str,
    schedule_type: str,
    interval_minutes: int | None = None,
    initial_delay_minutes: int = 0,
    repeat_enabled: bool = False,
) -> CreateResult:
    """创建定时消息"""
    # 验证消息内容
    if not content or not content.strip():
        return CreateResult(success=False, reason="invalid_content")

    # 验证定时类型
    valid_types = [e.value for e in ScheduleType]
    if schedule_type not in valid_types:
        return CreateResult(success=False, reason="invalid_schedule_type")

    # 验证自定义间隔
    if schedule_type == ScheduleType.custom.value and (not interval_minutes or interval_minutes <= 0):
        return CreateResult(success=False, reason="invalid_interval")

    # 计算首次发送时间
    base_time = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=initial_delay_minutes)
    next_send_time = calculate_next_send_time(schedule_type, interval_minutes, base_time)

    message = ScheduledMessage(
        chat_id=chat_id,
        created_by_user_id=created_by_user_id,
        content=content,
        schedule_type=schedule_type,
        interval_minutes=interval_minutes,
        is_active=True,
        next_send_time=next_send_time,
        repeat_enabled=repeat_enabled,
    )
    session.add(message)
    await session.flush()
    return CreateResult(success=True, reason="ok", message=message)


async def get_scheduled_message(session: AsyncSession, message_id: int) -> ScheduledMessage | None:
    """获取定时消息"""
    stmt = select(ScheduledMessage).where(ScheduledMessage.id == message_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_chat_scheduled_messages(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[ScheduledMessage]:
    """获取群组的定时消息列表"""
    stmt = select(ScheduledMessage).where(ScheduledMessage.chat_id == chat_id)
    if active_only:
        stmt = stmt.where(ScheduledMessage.is_active == True)
    stmt = stmt.order_by(ScheduledMessage.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_scheduled_message(
    session: AsyncSession,
    message_id: int,
    content: str | None = None,
    schedule_type: str | None = None,
    interval_minutes: int | None = None,
) -> UpdateResult:
    """更新定时消息"""
    message = await get_scheduled_message(session, message_id)
    if not message:
        return UpdateResult(success=False, reason="not_found")

    if content is not None:
        if not content or not content.strip():
            return UpdateResult(success=False, reason="invalid_content")
        message.content = content

    if schedule_type is not None:
        valid_types = [e.value for e in ScheduleType]
        if schedule_type not in valid_types:
            return UpdateResult(success=False, reason="invalid_schedule_type")
        message.schedule_type = schedule_type

    if interval_minutes is not None:
        message.interval_minutes = interval_minutes

    # 重新计算下次发送时间
    message.next_send_time = calculate_next_send_time(
        message.schedule_type,
        message.interval_minutes,
        dt.datetime.now(dt.UTC),
    )

    return UpdateResult(success=True, reason="ok")


async def toggle_scheduled_message(
    session: AsyncSession,
    message_id: int,
) -> ToggleResult:
    """切换定时消息激活状态"""
    message = await get_scheduled_message(session, message_id)
    if not message:
        return ToggleResult(success=False, reason="not_found")

    message.is_active = not message.is_active
    return ToggleResult(success=True, reason="ok")


async def delete_scheduled_message(
    session: AsyncSession,
    message_id: int,
) -> bool:
    """删除定时消息"""
    message = await get_scheduled_message(session, message_id)
    if not message:
        return False
    await session.delete(message)
    return True


async def get_pending_messages(
    session: AsyncSession,
    current_time: dt.datetime,
) -> list[ScheduledMessage]:
    """获取待发送的定时消息"""
    stmt = select(ScheduledMessage).where(
        ScheduledMessage.is_active == True,
        ScheduledMessage.next_send_time <= current_time,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_message_sent(
    session: AsyncSession,
    message: ScheduledMessage,
) -> None:
    """标记消息已发送并更新下次发送时间"""
    message.last_sent_at = dt.datetime.now(dt.UTC)
    message.send_count += 1

    # 根据 repeat_enabled 决定是否重复发送
    if not message.repeat_enabled:
        # 不重复，发送后停用
        message.is_active = False
    elif message.schedule_type != ScheduleType.none.value:
        # 重复发送且不是一次性类型，计算下次发送时间
        message.next_send_time = calculate_next_send_time(
            message.schedule_type,
            message.interval_minutes,
            dt.datetime.now(dt.UTC),
        )
    else:
        # 一次性类型，发送后停用
        message.is_active = False
