from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import select
from telegram import ChatPermissions

from backend.platform.db.schema.models.core import ChatSettings
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG

log = structlog.get_logger(__name__)


def _is_closed_now(settings: ChatSettings) -> bool:
    if not bool(getattr(settings, 'group_lock_schedule_enabled', False)):
        return False

    open_time = getattr(settings, 'group_lock_open_time', None)
    close_time = getattr(settings, 'group_lock_close_time', None)
    if not open_time or not close_time:
        return False

    try:
        open_hour, open_minute = [int(x) for x in open_time.split(':', 1)]
        close_hour, close_minute = [int(x) for x in close_time.split(':', 1)]
    except Exception:
        return False

    now = dt.datetime.now().time()
    now_min = now.hour * 60 + now.minute
    open_min = open_hour * 60 + open_minute
    close_min = close_hour * 60 + close_minute
    if open_min == close_min:
        return False
    if close_min < open_min:
        return close_min <= now_min < open_min
    return now_min >= close_min or now_min < open_min


class GroupLockTask(ScheduledTask):
    """定时关群权限同步任务。"""

    def __init__(self) -> None:
        config = TASK_CONFIG.get(
            'group_lock',
            {
                'interval': 60,
                'enabled': True,
                'max_consecutive_failures': 10,
            },
        )
        super().__init__(
            name='group_lock',
            interval=config['interval'],
            enabled=config['enabled'],
            max_consecutive_failures=config['max_consecutive_failures'],
        )

    async def execute(self, app) -> None:
        db = app.bot_data['db']
        lock_cache: dict[int, bool] = app.bot_data.setdefault('group_lock_state', {})

        async with db.session_factory() as session:
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.group_lock_schedule_enabled == True)
            )
            settings_list = list(result.scalars().all())

        if not settings_list:
            return

        for settings in settings_list:
            desired_closed = _is_closed_now(settings)
            current_closed = lock_cache.get(settings.chat_id)
            if current_closed is not None and current_closed == desired_closed:
                continue

            try:
                await app.bot.set_chat_permissions(
                    chat_id=settings.chat_id,
                    permissions=ChatPermissions(can_send_messages=not desired_closed),
                )
                lock_cache[settings.chat_id] = desired_closed
                log.info(
                    'group_lock_task_applied',
                    chat_id=settings.chat_id,
                    closed=desired_closed,
                )
            except Exception as exc:
                log.warning(
                    'group_lock_task_apply_failed',
                    chat_id=settings.chat_id,
                    closed=desired_closed,
                    error=str(exc),
                )
