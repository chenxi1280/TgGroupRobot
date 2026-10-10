from types import SimpleNamespace
from backend.platform.scheduler.core.core import ScheduledTask
from backend.features.points.services.mall_notifications import dispatch_notifications


class MallNotificationTask(ScheduledTask):
    def __init__(self):
        super().__init__(name="mall_notification", interval=30)

    async def execute(self, app):
        await dispatch_notifications(app.bot_data["db"], SimpleNamespace(bot=app.bot, application=app))
