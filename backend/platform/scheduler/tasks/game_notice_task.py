from backend.features.activity.game_notice_delivery import deliver_game_notices
from backend.platform.scheduler.core.core import ScheduledTask


class GameNoticeTask(ScheduledTask):
    def __init__(self):
        super().__init__("game_notices", 5, auto_pause_on_failure=False)

    async def execute(self, app):
        await deliver_game_notices(app.bot_data["db"], app.bot)
