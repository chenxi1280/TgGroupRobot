"""游戏自动启停任务"""

from __future__ import annotations

import datetime as dt

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.services.game_service import apply_auto_schedule, settle_due_k3_rounds


class GameTask(ScheduledTask):
    def __init__(self) -> None:
        config = TASK_CONFIG["game"]
        super().__init__(
            name="game",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        now_local = dt.datetime.now()
        async with db.session_factory() as session:
            await apply_auto_schedule(session, now_local)
            due_rounds = await settle_due_k3_rounds(session)
            await session.commit()
        for summary in due_rounds:
            round_obj = summary["round"]
            data = round_obj.result_data or {}
            dice = data.get("dice") or []
            winners = summary["winners"]
            lines = [
                "🎲 快3开奖",
                f"🎯 点数：{dice}（{data.get('label', '未知')}）",
            ]
            if winners:
                lines.append("🏆 中奖名单：")
                for winner in winners:
                    lines.append(f"• 用户 {winner['user_id']} | 竞猜 {winner['guess']} | 奖励 {winner['payout']}")
            else:
                lines.append("😶 本局无人中奖")
            await app.bot.send_message(chat_id=round_obj.chat_id, text="\n".join(lines))
