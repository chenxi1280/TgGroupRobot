"""Generic private reminders and owned points-level label reconciliation."""
import datetime as dt
from backend.features.admin.services.effect_runtime import run_pending
from backend.features.automation.services.ad_expiry import plan_reminders
from backend.platform.scheduler.core.core import ScheduledTask


class AdminAutomationTask(ScheduledTask):
    def __init__(self):
        super().__init__(name='admin_automation', interval=60, enabled=True, max_consecutive_failures=10,
                         auto_pause_on_failure=False)

    async def execute(self, app):
        from backend.features.points.services.level_tags import reconcile_tags
        now = dt.datetime.now(dt.UTC)
        failures = []
        try:
            await plan_reminders(app.bot_data['db'], now=now)
            await run_pending(app, now=now, kinds={'ad_expiry','lock_notice','notice_delete','delivery_action',
                                                'alliance_punish','alliance_release'})
        except Exception as exc:
            failures.append(exc)
        try:
            await reconcile_tags(app, now=now)
        except Exception as exc:
            failures.append(exc)
        if failures:
            raise RuntimeError('generic administrative automation has failures; inspect durable records') from failures[0]
