"""定时消息任务执行器

负责定时消息任务的调度和发送。
"""
from __future__ import annotations

import structlog
import datetime as dt
from telegram import InlineKeyboardButton
from bot.services.automation.scheduler.core import ScheduledTask
from bot.services.automation.scheduler.task_config import TASK_CONFIG
from bot.services.scheduled_message_service import ScheduledMessageService
from bot.utils.time_helper import is_time_in_window, timestamp_to_datetime

log = structlog.get_logger(__name__)


class ScheduledMessageTaskRunner(ScheduledTask):
    """定时消息任务执行器"""

    def __init__(self):
        config = TASK_CONFIG.get("scheduled_message", {
            "interval": 60,  # 每分钟检查一次
            "enabled": True,
            "max_consecutive_failures": 3,
        })
        super().__init__(
            name="scheduled_message",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        """执行定时消息任务"""
        db = app.bot_data["db"]

        async with db.session_factory() as session:
            # 获取到期需要执行的任务
            tasks = await ScheduledMessageService.get_due_tasks(session, limit=100)

            if not tasks:
                return

            log.info("scheduled_messages_due", count=len(tasks))

            for task in tasks:
                try:
                    # 检查是否在有效期内
                    now = int(dt.datetime.now(dt.UTC).timestamp())

                    # 检查开始时间
                    if task.start_at and now < task.start_at:
                        continue

                    # 检查终止时间
                    if task.end_at and now > task.end_at:
                        # 过期任务，禁用
                        await ScheduledMessageService.toggle_task_enabled(session, task.task_id, False)
                        log.info(
                            "scheduled_message_expired",
                            task_id=str(task.task_id),
                            title=task.title,
                        )
                        continue

                    # 检查时段窗口
                    if not is_time_in_window(now, task.day_start_hour, task.day_end_hour):
                        # 不在时段内，跳过
                        continue

                    # 删除上一条消息（如果需要）
                    if task.delete_previous and task.last_sent_message_id:
                        try:
                            await app.bot.delete_message(
                                task.chat_id,
                                task.last_sent_message_id,
                            )
                            log.info(
                                "scheduled_message_deleted_previous",
                                task_id=str(task.task_id),
                                message_id=task.last_sent_message_id,
                            )
                        except Exception as e:
                            # 消息可能已被删除，忽略错误
                            log.warning(
                                "scheduled_message_delete_previous_failed",
                                task_id=str(task.task_id),
                                message_id=task.last_sent_message_id,
                                error=str(e),
                            )

                    # 发送消息
                    message_id = await self._send_message(app, task)

                    if message_id:
                        # 置顶消息（如果需要）
                        if task.pin_message:
                            try:
                                await app.bot.pin_chat_message(task.chat_id, message_id)
                            except Exception as e:
                                log.warning(
                                    "scheduled_message_pin_failed",
                                    task_id=str(task.task_id),
                                    message_id=message_id,
                                    error=str(e),
                                )

                        # 标记任务已发送
                        await ScheduledMessageService.mark_task_sent(session, task.task_id, message_id)
                        await session.commit()

                        log.info(
                            "scheduled_message_sent",
                            task_id=str(task.task_id),
                            title=task.title,
                            chat_id=task.chat_id,
                            message_id=message_id,
                        )
                    else:
                        log.error(
                            "scheduled_message_send_failed",
                            task_id=str(task.task_id),
                            title=task.title,
                        )

                except Exception as e:
                    log.error(
                        "scheduled_message_task_error",
                        task_id=str(task.task_id),
                        title=task.title,
                        error=str(e),
                    )
                    await session.rollback()

    async def _send_message(self, app, task) -> int | None:
        """
        发送消息

        Args:
            app: Telegram 应用实例
            task: 任务对象

        Returns:
            发送的消息 ID，失败返回 None
        """
        try:
            # 构建回复键盘（如果有按钮）
            reply_markup = None
            if task.buttons:
                from telegram import InlineKeyboardMarkup
                rows = []
                for button_row in task.buttons:
                    row = []
                    for button in button_row:
                        if isinstance(button, dict):
                            row.append(
                                InlineKeyboardButton(
                                    text=button.get("text", ""),
                                    url=button.get("url", ""),
                                )
                            )
                    if row:
                        rows.append(row)
                if rows:
                    reply_markup = InlineKeyboardMarkup(rows)

            # 根据媒体类型发送不同类型的消息
            if task.media_type == "photo" and task.media_file_id:
                # 发送图片
                msg = await app.bot.send_photo(
                    task.chat_id,
                    task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "video" and task.media_file_id:
                # 发送视频
                msg = await app.bot.send_video(
                    task.chat_id,
                    task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "document" and task.media_file_id:
                # 发送文档
                msg = await app.bot.send_document(
                    task.chat_id,
                    task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "sticker" and task.media_file_id:
                # 发送贴纸（贴纸不能有 caption）
                msg = await app.bot.send_sticker(
                    task.chat_id,
                    task.media_file_id,
                )
            elif task.media_type == "animation" and task.media_file_id:
                # 发送动画（GIF）
                msg = await app.bot.send_animation(
                    task.chat_id,
                    task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            else:
                # 发送纯文本消息
                msg = await app.bot.send_message(
                    task.chat_id,
                    task.text or "（无内容）",
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )

            return msg.message_id

        except Exception as e:
            log.error(
                "scheduled_message_send_error",
                task_id=str(task.task_id),
                error=str(e),
            )
            return None
