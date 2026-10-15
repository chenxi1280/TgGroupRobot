"""Persist each current boundary before applying group permissions."""
from backend.features.admin.services.effect_runtime import run_pending
from backend.features.group_ops.services.lock_plans import plan_schedule
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


def _is_closed_now(settings):
    from backend.features.group_ops.group_hooks.control_lock import _is_closed_by_schedule
    return _is_closed_by_schedule(settings)


class GroupLockTask(ScheduledTask):
    def __init__(self):
        config = TASK_CONFIG['group_lock']
        super().__init__(name='group_lock', interval=config['interval'], enabled=config['enabled'],
                         max_consecutive_failures=config['max_consecutive_failures'], auto_pause_on_failure=False)

    async def execute(self, app):
        import datetime as dt
        now = dt.datetime.now(dt.UTC)
        await plan_schedule(app.bot_data['db'], now=now)
        await run_pending(app, now=now, kinds={'group_lock','lock_notice','notice_delete'})
