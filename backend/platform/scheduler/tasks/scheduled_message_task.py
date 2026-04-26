"""定时消息任务执行器

负责定时消息任务的调度和发送。
"""
from __future__ import annotations

from dataclasses import dataclass
import structlog
import datetime as dt
from types import SimpleNamespace

from telegram import InlineKeyboardButton

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.shared.services.publish_service import PublishService
from backend.shared.time_helper import calculate_next_run_time, is_time_in_window

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ScheduledMessageDispatchItem:
    task_id: str
    title: str
    chat_id: int
    delete_previous: bool
    last_sent_message_id: int | None
    pin_message: bool
    text: str | None
    parse_mode: str
    media_type: str
    media_file_id: str | None
    buttons: list


@dataclass
class ScheduledMessageRunStats:
    due: int = 0
    claimed: int = 0
    sent: int = 0
    skipped_expired: int = 0
    skipped_window: int = 0
    skipped_empty: int = 0
    telegram_failures: int = 0
    db_commit_failures: int = 0


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
        started_at = dt.datetime.now(dt.UTC)
        stats = ScheduledMessageRunStats()

        dispatch_items = await self._claim_due_tasks(db, stats=stats)
        for item in dispatch_items:
            await self._dispatch_claimed_task(app, db, item, stats=stats)

        if stats.due or stats.claimed or stats.telegram_failures or stats.db_commit_failures:
            duration = (dt.datetime.now(dt.UTC) - started_at).total_seconds()
            log.info(
                "scheduled_message_tick_finished",
                due=stats.due,
                claimed=stats.claimed,
                sent=stats.sent,
                skipped_expired=stats.skipped_expired,
                skipped_window=stats.skipped_window,
                skipped_empty=stats.skipped_empty,
                telegram_failures=stats.telegram_failures,
                db_commit_failures=stats.db_commit_failures,
                duration=round(duration, 3),
            )

    async def _claim_due_tasks(self, db, *, stats: ScheduledMessageRunStats) -> list[ScheduledMessageDispatchItem]:
        dispatch_items: list[ScheduledMessageDispatchItem] = []
        now = int(dt.datetime.now(dt.UTC).timestamp())

        async with db.session_factory() as session:
            try:
                tasks = await ScheduledMessageService.get_due_tasks(session, limit=100)
                stats.due = len(tasks)
                if not tasks:
                    return []

                log.info("scheduled_messages_due", count=len(tasks))

                for task in tasks:
                    if task.start_at and now < task.start_at:
                        task.next_run_at = task.start_at
                        continue

                    if task.end_at and now > task.end_at:
                        task.enabled = False
                        stats.skipped_expired += 1
                        log.info(
                            "scheduled_message_expired",
                            task_id=str(task.task_id),
                            title=task.title,
                        )
                        continue

                    if not is_time_in_window(now, task.day_start_hour, task.day_end_hour):
                        task.next_run_at = calculate_next_run_time(task, now)
                        stats.skipped_window += 1
                        continue

                    if not ScheduledMessageService.has_sendable_content(task):
                        task.enabled = False
                        stats.skipped_empty += 1
                        log.warning(
                            "scheduled_message_skipped_empty_content",
                            task_id=str(task.task_id),
                            title=task.title,
                            chat_id=task.chat_id,
                        )
                        continue

                    dispatch_items.append(self._snapshot_task(task))
                    task.next_run_at = calculate_next_run_time(task, now)
                    stats.claimed += 1

                await session.commit()
            except Exception as exc:
                stats.db_commit_failures += 1
                await session.rollback()
                log.error("scheduled_message_claim_failed", error=str(exc), exc_info=True)
                return []

        return dispatch_items

    @staticmethod
    def _snapshot_task(task) -> ScheduledMessageDispatchItem:
        return ScheduledMessageDispatchItem(
            task_id=str(task.task_id),
            title=str(task.title or ""),
            chat_id=int(task.chat_id),
            delete_previous=bool(task.delete_previous),
            last_sent_message_id=task.last_sent_message_id,
            pin_message=bool(task.pin_message),
            text=task.text,
            parse_mode=task.parse_mode,
            media_type=task.media_type,
            media_file_id=task.media_file_id,
            buttons=list(task.buttons or []),
        )

    async def _dispatch_claimed_task(
        self,
        app,
        db,
        item: ScheduledMessageDispatchItem,
        *,
        stats: ScheduledMessageRunStats,
    ) -> None:
        if item.delete_previous and item.last_sent_message_id:
            try:
                await PublishService.delete(
                    self._context_for_app(app),
                    chat_id=item.chat_id,
                    message_id=item.last_sent_message_id,
                )
                log.info(
                    "scheduled_message_deleted_previous",
                    task_id=item.task_id,
                    message_id=item.last_sent_message_id,
                )
            except Exception as exc:
                log.warning(
                    "scheduled_message_delete_previous_failed",
                    task_id=item.task_id,
                    message_id=item.last_sent_message_id,
                    error=str(exc),
                )

        message_id = await self._send_message(app, item)
        if not message_id:
            stats.telegram_failures += 1
            log.error("scheduled_message_send_failed", task_id=item.task_id, title=item.title)
            return

        if item.pin_message:
            try:
                await PublishService.pin(
                    self._context_for_app(app),
                    chat_id=item.chat_id,
                    message_id=message_id,
                )
            except Exception as exc:
                log.warning(
                    "scheduled_message_pin_failed",
                    task_id=item.task_id,
                    message_id=message_id,
                    error=str(exc),
                )

        async with db.session_factory() as session:
            try:
                await ScheduledMessageService.mark_task_sent(session, item.task_id, message_id)
                await session.commit()
                stats.sent += 1
                log.info(
                    "scheduled_message_sent",
                    task_id=item.task_id,
                    title=item.title,
                    chat_id=item.chat_id,
                    message_id=message_id,
                )
            except Exception as exc:
                stats.db_commit_failures += 1
                await session.rollback()
                log.error(
                    "scheduled_message_mark_sent_failed",
                    task_id=item.task_id,
                    message_id=message_id,
                    error=str(exc),
                    exc_info=True,
                )

    @staticmethod
    def _context_for_app(app):
        return SimpleNamespace(bot=app.bot, application=app)

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
            if not ScheduledMessageService.has_sendable_content(task):
                log.warning(
                    "scheduled_message_send_skipped_empty_content",
                    task_id=str(task.task_id),
                    title=task.title,
                )
                return None

            # 构建回复键盘（如果有按钮）
            reply_markup = None
            if task.buttons:
                from telegram import InlineKeyboardMarkup
                from backend.shared.services.base import ValidationError
                rows = []
                try:
                    normalized_buttons = ScheduledMessageService.normalize_buttons_config(task.buttons)
                except ValidationError as e:
                    log.warning(
                        "scheduled_message_buttons_invalid",
                        task_id=str(task.task_id),
                        error=str(e),
                    )
                    normalized_buttons = []

                for button_row in normalized_buttons:
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
            context = self._context_for_app(app)
            if task.media_type == "photo" and task.media_file_id:
                result = await PublishService.send_photo(
                    context,
                    chat_id=task.chat_id,
                    photo=task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "video" and task.media_file_id:
                result = await PublishService.send_video(
                    context,
                    chat_id=task.chat_id,
                    video=task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "document" and task.media_file_id:
                result = await PublishService.send_document(
                    context,
                    chat_id=task.chat_id,
                    document=task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif task.media_type == "sticker" and task.media_file_id:
                result = await PublishService.send_sticker(
                    context,
                    chat_id=task.chat_id,
                    sticker=task.media_file_id,
                )
            elif task.media_type == "animation" and task.media_file_id:
                result = await PublishService.send_animation(
                    context,
                    chat_id=task.chat_id,
                    animation=task.media_file_id,
                    caption=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            elif str(task.text or "").strip():
                result = await PublishService.send(
                    context,
                    chat_id=task.chat_id,
                    text=task.text,
                    parse_mode=task.parse_mode if task.parse_mode != "none" else None,
                    reply_markup=reply_markup,
                )
            else:
                return None

            return result.message_id

        except Exception as e:
            log.error(
                "scheduled_message_send_error",
                task_id=str(task.task_id),
                error=str(e),
            )
            return None
