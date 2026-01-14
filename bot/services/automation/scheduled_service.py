from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ScheduledMessage
from bot.models.enums import ScheduleType
from bot.services.base import ServiceBase
from bot.services.shared.result import CreateResult, ToggleResult, UpdateResult


def calculate_next_send_time(
    schedule_type: str,
    interval_minutes: int | None = None,
    base_time: dt.datetime | None = None,
) -> dt.datetime:
    """
    计算下次发送时间

    Args:
        schedule_type: 定时类型
        interval_minutes: 自定义间隔（分钟）
        base_time: 基准时间，默认为当前时间

    Returns:
        下次发送时间
    """
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
    """
    创建定时消息

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        created_by_user_id: 创建者用户 ID
        content: 消息内容
        schedule_type: 定时类型
        interval_minutes: 自定义间隔（分钟）
        initial_delay_minutes: 首次延迟（分钟）
        repeat_enabled: 是否重复发送

    Returns:
        CreateResult: 创建结果
    """
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
    return CreateResult(success=True, reason="ok", entity=message, entity_id=message.id)


async def get_scheduled_message(session: AsyncSession, message_id: int) -> ScheduledMessage | None:
    """
    获取定时消息

    Args:
        session: 数据库会话
        message_id: 消息 ID

    Returns:
        ScheduledMessage: 定时消息对象，如果不存在则返回 None
    """
    return await ServiceBase._get_by_id(session, ScheduledMessage, message_id)


async def get_chat_scheduled_messages(
    session: AsyncSession,
    chat_id: int,
    active_only: bool = False,
) -> list[ScheduledMessage]:
    """
    获取群组的定时消息列表

    Args:
        session: 数据库会话
        chat_id: 群组 ID
        active_only: 是否只返回激活的消息

    Returns:
        定时消息列表
    """
    return await ServiceBase._get_list(
        session,
        ScheduledMessage,
        filters={"chat_id": chat_id},
        active_only=active_only,
        order_by="created_at",
        descending=True,
    )


async def update_scheduled_message(
    session: AsyncSession,
    message_id: int,
    content: str | None = None,
    schedule_type: str | None = None,
    interval_minutes: int | None = None,
) -> UpdateResult:
    """
    更新定时消息

    Args:
        session: 数据库会话
        message_id: 消息 ID
        content: 新内容
        schedule_type: 新定时类型
        interval_minutes: 新自定义间隔

    Returns:
        UpdateResult: 更新结果
    """
    message = await get_scheduled_message(session, message_id)
    if not message:
        return UpdateResult(success=False, reason="not_found")

    updates: dict[str, object] = {}

    if content is not None:
        if not content or not content.strip():
            return UpdateResult(success=False, reason="invalid_content")
        updates["content"] = content

    if schedule_type is not None:
        valid_types = [e.value for e in ScheduleType]
        if schedule_type not in valid_types:
            return UpdateResult(success=False, reason="invalid_schedule_type")
        updates["schedule_type"] = schedule_type

    if interval_minutes is not None:
        updates["interval_minutes"] = interval_minutes

    await ServiceBase._update_entity(session, message, updates)

    # 重新计算下次发送时间
    message.next_send_time = calculate_next_send_time(
        message.schedule_type,
        message.interval_minutes,
        dt.datetime.now(dt.UTC),
    )

    return UpdateResult(success=True, reason="ok", entity=message)


async def toggle_scheduled_message(
    session: AsyncSession,
    message_id: int,
) -> ToggleResult:
    """
    切换定时消息激活状态

    Args:
        session: 数据库会话
        message_id: 消息 ID

    Returns:
        ToggleResult: 切换结果
    """
    message = await get_scheduled_message(session, message_id)
    if not message:
        return ToggleResult(success=False, reason="not_found")

    await ServiceBase._update_entity(
        session,
        message,
        {"is_active": not message.is_active},
    )
    return ToggleResult(success=True, reason="ok", entity=message)


async def delete_scheduled_message(
    session: AsyncSession,
    message_id: int,
) -> bool:
    """
    删除定时消息

    Args:
        session: 数据库会话
        message_id: 消息 ID

    Returns:
        是否删除成功
    """
    message = await get_scheduled_message(session, message_id)
    if not message:
        return False
    await ServiceBase._delete_entity(session, message)
    return True


async def get_pending_messages(
    session: AsyncSession,
    current_time: dt.datetime,
) -> list[ScheduledMessage]:
    """
    获取待发送的定时消息

    Args:
        session: 数据库会话
        current_time: 当前时间

    Returns:
        待发送的消息列表
    """
    messages = await ServiceBase._get_list(
        session,
        ScheduledMessage,
        active_only=True,
        order_by="next_send_time",
        descending=False,
    )
    # 过滤出已到发送时间的消息
    return [m for m in messages if m.next_send_time <= current_time]


async def mark_message_sent(
    session: AsyncSession,
    message: ScheduledMessage,
) -> None:
    """
    标记消息已发送并更新下次发送时间

    Args:
        session: 数据库会话
        message: 消息对象
    """
    updates: dict[str, object] = {
        "last_sent_at": dt.datetime.now(dt.UTC),
        "send_count": message.send_count + 1,
    }

    # 根据 repeat_enabled 决定是否重复发送
    if not message.repeat_enabled:
        # 不重复，发送后停用
        updates["is_active"] = False
    elif message.schedule_type != ScheduleType.none.value:
        # 重复发送且不是一次性类型，计算下次发送时间
        updates["next_send_time"] = calculate_next_send_time(
            message.schedule_type,
            message.interval_minutes,
            dt.datetime.now(dt.UTC),
        )
    else:
        # 一次性类型，发送后停用
        updates["is_active"] = False

    await ServiceBase._update_entity(session, message, updates)
