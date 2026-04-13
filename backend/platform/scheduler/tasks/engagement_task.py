"""促活工具任务：定时投放彩蛋线索。"""

from __future__ import annotations

import datetime as dt

from backend.features.activity.services.engagement_service import get_due_clues, mark_clue_published
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG


class EngagementTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["engagement"]
        super().__init__(
            name="engagement",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        current_hhmm = dt.datetime.now().astimezone().strftime("%H:%M")
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            due_clues = await get_due_clues(session, current_hhmm)
            for egg, clue_index in due_clues:
                clue_text = egg.clues[clue_index] if clue_index < len(egg.clues) else ""
                reward_points = egg.clue_rewards[clue_index] if clue_index < len(egg.clue_rewards) else 0
                await app.bot.send_message(
                    chat_id=egg.chat_id,
                    text=(
                        f"🥚 有奖彩蛋【{getattr(egg, 'title', '彩蛋活动')}】| 第 {clue_index + 1} 条线索\n"
                        f"🧩 线索：{clue_text}\n"
                        f"🎁 当前命中奖励：{reward_points} 积分"
                    ),
                )
                await mark_clue_published(session, egg, clue_index)
            await session.commit()
