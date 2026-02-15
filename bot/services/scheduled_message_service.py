from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.core import TgChat
from bot.models.scheduled_message import ScheduledMessageTask
from bot.services.base import ServiceBase, ValidationError, NotFoundError
from bot.utils.time_helper import (
    calculate_next_run_time,
    datetime_to_timestamp,
    parse_date_time_string,
)


class ScheduledMessageService(ServiceBase):
    """定时消息任务服务"""

    # 允许通过 update_task(..., field=None) 清空的字段
    _NULLABLE_UPDATE_FIELDS = {
        "text",
        "start_at",
        "end_at",
        "media_file_id",
        "created_by_user_id",
        "last_sent_message_id",
        "next_run_at",
    }

    @staticmethod
    def _normalize_button_url(url: str) -> str:
        """规范化按钮 URL，支持常见简写。"""
        normalized = url.strip()
        if not normalized:
            raise ValidationError("按钮 URL 不能为空")

        lowered = normalized.lower()
        blocked_schemes = ("javascript:", "data:", "file:", "vbscript:")
        if lowered.startswith(blocked_schemes):
            raise ValidationError("按钮 URL 协议不安全")

        # 常见输入兼容：@channel / t.me/xxx / www.xxx.com / example.com
        if normalized.startswith("@"):
            normalized = f"https://t.me/{normalized[1:]}"
        elif normalized.startswith("t.me/"):
            normalized = f"https://{normalized}"
        elif normalized.startswith("www."):
            normalized = f"https://{normalized}"
        elif "://" not in normalized and not normalized.startswith("tg://"):
            normalized = f"https://{normalized}"

        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https", "tg"}:
            raise ValidationError("按钮 URL 协议仅支持 http/https/tg")

        if parsed.scheme in {"http", "https"} and not parsed.netloc:
            raise ValidationError("按钮 URL 格式无效")

        if parsed.scheme in {"http", "https"}:
            if not parsed.hostname:
                raise ValidationError("按钮 URL 主机名无效")
            try:
                _ = parsed.port
            except ValueError:
                raise ValidationError("按钮 URL 端口格式无效")

        if parsed.scheme == "tg" and not (parsed.netloc or parsed.path):
            raise ValidationError("按钮 tg:// 链接格式无效")

        return normalized

    @staticmethod
    def normalize_buttons_config(buttons: list) -> list[list[dict[str, str]]]:
        """规范化按钮配置，兼容单层和双层数组。"""
        if not isinstance(buttons, list):
            raise ValidationError("按钮配置必须是 JSON 数组")

        if not buttons:
            return []

        # 兼容单层格式: [{"text":"A","url":"https://..."}]
        if all(isinstance(item, dict) for item in buttons):
            rows = [buttons]
        elif all(isinstance(item, list) for item in buttons):
            rows = buttons
        else:
            raise ValidationError("按钮格式必须是 [{text,url}] 或 [[{text,url}]]")

        normalized_rows: list[list[dict[str, str]]] = []

        for row_index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                raise ValidationError(f"第 {row_index} 行按钮格式错误")

            normalized_row: list[dict[str, str]] = []
            for col_index, button in enumerate(row, start=1):
                if not isinstance(button, dict):
                    raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮必须是对象")

                text = str(button.get("text", "")).strip()
                raw_url = button.get("url", button.get("link", ""))
                url = str(raw_url).strip()

                if not text:
                    raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮 text 不能为空")

                if not url:
                    raise ValidationError(f"第 {row_index} 行第 {col_index} 个按钮 url 不能为空")

                normalized_row.append({
                    "text": text,
                    "url": ScheduledMessageService._normalize_button_url(url),
                })

            if normalized_row:
                normalized_rows.append(normalized_row)

        return normalized_rows

    @staticmethod
    async def create_task(
        session: AsyncSession,
        chat_id: int,
        created_by_user_id: int,
        title: str,
        **kwargs: Any,
    ) -> ScheduledMessageTask:
        """
        创建定时消息任务

        Args:
            session: 数据库会话
            chat_id: 群组 ID
            created_by_user_id: 创建者用户 ID
            title: 任务标题
            **kwargs: 其他字段

        Returns:
            创建的任务对象
        """
        # 验证群组存在
        chat = await session.get(TgChat, chat_id)
        if not chat:
            raise ValidationError(f"群组 {chat_id} 不存在")

        # 验证标题
        if not title or not title.strip():
            raise ValidationError("任务标题不能为空")

        # 验证重复间隔
        repeat_interval_min = kwargs.get("repeat_interval_min", 60)
        valid_intervals = [10, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440]
        if repeat_interval_min not in valid_intervals:
            raise ValidationError(f"无效的重复间隔，必须是以下值之一: {valid_intervals}")

        # 验证时段
        day_start_hour = kwargs.get("day_start_hour", 0)
        day_end_hour = kwargs.get("day_end_hour", 23)
        if not (0 <= day_start_hour <= 23 and 0 <= day_end_hour <= 23):
            raise ValidationError("时段小时必须在 0-23 之间")

        # 验证日期时间
        start_at = kwargs.get("start_at")
        end_at = kwargs.get("end_at")

        if start_at is not None and end_at is not None:
            if start_at >= end_at:
                raise ValidationError("开始时间必须早于终止时间")

        raw_buttons = kwargs.get("buttons", [])
        buttons = ScheduledMessageService.normalize_buttons_config(raw_buttons) if raw_buttons else []

        # 生成唯一的短 ID
        while True:
            short_id = secrets.token_hex(4)  # 8 个字符
            existing_task = await session.execute(
                select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == short_id)
            )
            if not existing_task.scalar_one_or_none():
                break

        # 创建任务
        task = ScheduledMessageTask(
            task_id=uuid.uuid4(),
            short_id=short_id,
            chat_id=chat_id,
            created_by_user_id=created_by_user_id,
            title=title.strip(),
            enabled=kwargs.get("enabled", True),
            repeat_interval_min=repeat_interval_min,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
            start_at=start_at,
            end_at=end_at,
            text=kwargs.get("text"),
            parse_mode=kwargs.get("parse_mode", "HTML"),
            media_type=kwargs.get("media_type", "none"),
            media_file_id=kwargs.get("media_file_id"),
            buttons=buttons,
            delete_previous=kwargs.get("delete_previous", True),
            pin_message=kwargs.get("pin_message", False),
        )

        # 计算首次运行时间
        task.next_run_at = calculate_next_run_time(task)

        session.add(task)
        await session.flush()

        return task

    @staticmethod
    async def get_task_by_id(
        session: AsyncSession,
        task_id: str | uuid.UUID,
    ) -> ScheduledMessageTask | None:
        """
        根据 ID 获取任务

        Args:
            session: 数据库会话
            task_id: 任务 ID（UUID 或短 ID）

        Returns:
            任务对象，不存在返回 None
        """
        task_key = str(task_id)

        # 尝试通过短 ID 查找
        stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == task_key)
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()

        # 如果未找到，尝试通过 UUID 查找（无效 UUID 直接返回 None，避免数据库报错）
        if not task:
            try:
                task_uuid = task_id if isinstance(task_id, uuid.UUID) else uuid.UUID(task_key)
            except (TypeError, ValueError, AttributeError):
                return None

            stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.task_id == task_uuid)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

        return task

    @staticmethod
    async def get_task_by_id_or_404(
        session: AsyncSession,
        task_id: str | uuid.UUID,
    ) -> ScheduledMessageTask:
        """
        根据 ID 获取任务，不存在则抛出异常

        Args:
            session: 数据库会话
            task_id: 任务 ID（UUID 或短 ID）

        Returns:
            任务对象

        Raises:
            NotFoundError: 任务不存在
        """
        task = await ScheduledMessageService.get_task_by_id(session, task_id)
        if not task:
            raise NotFoundError(f"任务 {task_id} 不存在")
        return task

    @staticmethod
    async def list_tasks(
        session,
        chat_id: int,
        enabled_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ScheduledMessageTask]:
        """
        获取任务列表

        Args:
            chat_id: 群组 ID
            enabled_only: 是否只返回启用的任务
            limit: 数量限制
            offset: 偏移量

        Returns:
            任务列表
        """
        stmt = select(ScheduledMessageTask).where(ScheduledMessageTask.chat_id == chat_id)

        if enabled_only:
            stmt = stmt.where(ScheduledMessageTask.enabled == True)

        stmt = stmt.order_by(ScheduledMessageTask.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_task(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        **kwargs: Any,
    ) -> ScheduledMessageTask:
        """
        更新任务

        Args:
            task_id: 任务 ID
            **kwargs: 要更新的字段

        Returns:
            更新后的任务对象

        Raises:
            NotFoundError: 任务不存在
            ValidationError: 数据验证失败
        """
        task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)

        # 更新字段
        for key, value in kwargs.items():
            if not hasattr(task, key):
                continue
            if value is None and key not in ScheduledMessageService._NULLABLE_UPDATE_FIELDS:
                continue
            setattr(task, key, value)

        # 验证时段
        if "day_start_hour" in kwargs or "day_end_hour" in kwargs:
            if not (0 <= task.day_start_hour <= 23 and 0 <= task.day_end_hour <= 23):
                raise ValidationError("时段小时必须在 0-23 之间")

        # 验证日期时间
        if task.start_at is not None and task.end_at is not None:
            if task.start_at >= task.end_at:
                raise ValidationError("开始时间必须早于终止时间")

        # 如果修改了关键调度参数，重新计算下次运行时间
        recalculate_keys = [
            "repeat_interval_min",
            "day_start_hour",
            "day_end_hour",
            "start_at",
        ]
        if any(key in kwargs for key in recalculate_keys):
            now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
            task.next_run_at = calculate_next_run_time(task, now_timestamp)

        await session.flush()
        return task

    @staticmethod
    async def toggle_task_enabled(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        enabled: bool,
    ) -> ScheduledMessageTask:
        """
        切换任务启用状态

        Args:
            task_id: 任务 ID
            enabled: 是否启用

        Returns:
            更新后的任务对象
        """
        task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)
        task.enabled = enabled

        # 如果启用任务，重新计算下次运行时间
        if enabled:
            now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
            task.next_run_at = calculate_next_run_time(task, now_timestamp)

        await session.flush()
        return task

    @staticmethod
    async def delete_task(
        session,
        task_id: str | uuid.UUID,
    ) -> bool:
        """
        删除任务

        Args:
            session: 数据库会话
            task_id: 任务 ID

        Returns:
            True 表示删除成功

        Raises:
            NotFoundError: 任务不存在
        """
        task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)
        await session.delete(task)
        await session.flush()
        return True

    @staticmethod
    async def get_due_tasks(
        session,
        limit: int = 100,
    ) -> list[ScheduledMessageTask]:
        """
        获取到期需要执行的任务

        Args:
            session: 数据库会话
            limit: 数量限制

        Returns:
            任务列表
        """
        now = int(dt.datetime.now(dt.UTC).timestamp())

        stmt = (
            select(ScheduledMessageTask)
            .where(
                ScheduledMessageTask.enabled == True,
                ScheduledMessageTask.next_run_at <= now,
            )
            .order_by(ScheduledMessageTask.next_run_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def mark_task_sent(
        session,
        task_id: str | uuid.UUID,
        message_id: int,
    ) -> ScheduledMessageTask:
        """
        标记任务已发送

        Args:
            task_id: 任务 ID
            message_id: 发送的消息 ID

        Returns:
            更新后的任务对象
        """
        task = await ScheduledMessageService.get_task_by_id_or_404(session, task_id)

        # 更新发送记录
        task.last_sent_message_id = message_id

        # 计算下次运行时间
        now_timestamp = int(dt.datetime.now(dt.UTC).timestamp())
        task.next_run_at = calculate_next_run_time(task, now_timestamp)

        await session.flush()
        return task

    @staticmethod
    async def update_task_text(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        text: str | None,
    ) -> ScheduledMessageTask:
        """
        更新任务文本

        Args:
            task_id: 任务 ID
            text: 新文本，None 表示清空

        Returns:
            更新后的任务对象
        """
        return await ScheduledMessageService.update_task(session, task_id, text=text)

    @staticmethod
    async def update_task_media(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        media_type: str,
        media_file_id: str | None = None,
    ) -> ScheduledMessageTask:
        """
        更新任务媒体

        Args:
            task_id: 任务 ID
            media_type: 媒体类型
            media_file_id: 媒体文件 ID

        Returns:
            更新后的任务对象
        """
        valid_types = ["none", "photo", "video", "sticker", "animation", "document"]
        if media_type not in valid_types:
            raise ValidationError(f"无效的媒体类型，必须是: {valid_types}")

        return await ScheduledMessageService.update_task(session, 
            task_id,
            media_type=media_type,
            media_file_id=media_file_id,
        )

    @staticmethod
    async def update_task_buttons(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        buttons: list,
    ) -> ScheduledMessageTask:
        """
        更新任务按钮

        Args:
            task_id: 任务 ID
            buttons: 按钮配置

        Returns:
            更新后的任务对象
        """
        normalized_buttons = ScheduledMessageService.normalize_buttons_config(buttons)
        return await ScheduledMessageService.update_task(session, task_id, buttons=normalized_buttons)

    @staticmethod
    async def update_task_repeat(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        repeat_interval_min: int,
    ) -> ScheduledMessageTask:
        """
        更新任务重复间隔

        Args:
            task_id: 任务 ID
            repeat_interval_min: 重复间隔（分钟）

        Returns:
            更新后的任务对象
        """
        valid_intervals = [10, 15, 20, 30, 60, 120, 180, 240, 360, 480, 720, 1440]
        if repeat_interval_min not in valid_intervals:
            raise ValidationError(f"无效的重复间隔，必须是: {valid_intervals}")

        return await ScheduledMessageService.update_task(session, task_id, repeat_interval_min=repeat_interval_min)

    @staticmethod
    async def update_task_day_period(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        day_start_hour: int,
        day_end_hour: int,
    ) -> ScheduledMessageTask:
        """
        更新任务时段

        Args:
            task_id: 任务 ID
            day_start_hour: 开始小时（0-23）
            day_end_hour: 结束小时（0-23）

        Returns:
            更新后的任务对象
        """
        if not (0 <= day_start_hour <= 23 and 0 <= day_end_hour <= 23):
            raise ValidationError("时段小时必须在 0-23 之间")

        return await ScheduledMessageService.update_task(session, 
            task_id,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
        )

    @staticmethod
    async def update_task_start_at(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        date_time_str: str | None,
    ) -> ScheduledMessageTask:
        """
        更新任务开始时间

        Args:
            session: 数据库会话
            task_id: 任务 ID
            date_time_str: 日期时间字符串（YYYY-MM-DD HH:MM），None 表示清空

        Returns:
            更新后的任务对象
        """
        if date_time_str is None:
            start_at = None
        else:
            start_at = parse_date_time_string(date_time_str)
            if start_at is None:
                raise ValidationError("无效的日期时间格式，应为: YYYY-MM-DD HH:MM")

        return await ScheduledMessageService.update_task(session, task_id, start_at=start_at)

    @staticmethod
    async def update_task_end_at(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        date_time_str: str | None,
    ) -> ScheduledMessageTask:
        """
        更新任务终止时间

        Args:
            session: 数据库会话
            task_id: 任务 ID
            date_time_str: 日期时间字符串（YYYY-MM-DD HH:MM），None 表示清空

        Returns:
            更新后的任务对象
        """
        if date_time_str is None:
            end_at = None
        else:
            end_at = parse_date_time_string(date_time_str)
            if end_at is None:
                raise ValidationError("无效的日期时间格式，应为: YYYY-MM-DD HH:MM")

        return await ScheduledMessageService.update_task(session, task_id, end_at=end_at)

    @staticmethod
    async def update_task_toggle_option(
        session: AsyncSession,
        task_id: str | uuid.UUID,
        option: str,
        value: bool,
    ) -> ScheduledMessageTask:
        """
        更新任务开关选项

        Args:
            task_id: 任务 ID
            option: 选项名称（enabled/delete_previous/pin_message）
            value: 选项值

        Returns:
            更新后的任务对象
        """
        valid_options = ["enabled", "delete_previous", "pin_message"]
        if option not in valid_options:
            raise ValidationError(f"无效的选项，必须是: {valid_options}")

        return await ScheduledMessageService.update_task(session, task_id, **{option: value})
