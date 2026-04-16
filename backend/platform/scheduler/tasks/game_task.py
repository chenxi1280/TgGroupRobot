"""游戏自动启停任务"""

from __future__ import annotations

import datetime as dt

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.game_panels import show_blackjack_panel, show_k3_panel
from backend.features.activity.services.game_service import (
    apply_auto_schedule,
    format_blackjack_round_text,
    get_or_create_setting,
    settle_due_blackjack_rounds,
    settle_due_k3_rounds,
)
from backend.shared.time_helper import LOCAL_TIMEZONE


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
        now_local = dt.datetime.now(dt.UTC).astimezone(LOCAL_TIMEZONE)
        async with db.session_factory() as session:
            changed_chat_ids = await apply_auto_schedule(session, now_local)
            due_rounds = await settle_due_k3_rounds(session)
            due_blackjack_rounds = await settle_due_blackjack_rounds(session)
            await session.commit()
        for chat_id in changed_chat_ids:
            async with db.session_factory() as session:
                setting = await get_or_create_setting(session, chat_id)
                create_k3 = bool(setting.k3_enabled)
                create_blackjack = bool(setting.blackjack_enabled)
                await session.commit()
            try:
                await show_k3_panel(app, db, chat_id, create_if_missing=create_k3)
                await show_blackjack_panel(app, db, chat_id, create_if_missing=create_blackjack)
            except Exception:
                pass
        for summary in due_rounds:
            round_obj = summary["round"]
            data = round_obj.result_data or {}
            dice = data.get("dice") or []
            winners = summary["winners"]
            lines = [
                "🎲 快三开奖",
                f"🎯 点数：{dice}（{data.get('label', '未知')}）",
            ]
            if winners:
                lines.append("🏆 中奖名单：")
                for winner in winners:
                    lines.append(f"• 用户 {winner['user_id']} | 竞猜 {winner['guess']} | 奖励 {winner['payout']}")
            else:
                lines.append("😶 本局无人中奖")
            await app.bot.send_message(chat_id=round_obj.chat_id, text="\n".join(lines))
            try:
                await show_k3_panel(app, db, round_obj.chat_id)
            except Exception:
                pass
        for summary in due_blackjack_rounds:
            round_obj = summary["round"]
            participant = summary["participant"]
            outcome = summary["outcome"]
            text = format_blackjack_round_text(participant, reveal_dealer=True, outcome=outcome)
            if round_obj.announcement_message_id:
                try:
                    await app.bot.edit_message_text(
                        chat_id=round_obj.chat_id,
                        message_id=round_obj.announcement_message_id,
                        text=text,
                    )
                except Exception:
                    await app.bot.send_message(chat_id=round_obj.chat_id, text=text)
            else:
                await app.bot.send_message(chat_id=round_obj.chat_id, text=text)
            try:
                await show_blackjack_panel(app, db, round_obj.chat_id)
            except Exception:
                pass
