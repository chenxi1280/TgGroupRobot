"""游戏自动启停任务"""

from __future__ import annotations

import datetime as dt
import html
import structlog
from types import SimpleNamespace

from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.features.activity.game_panels import show_blackjack_panel, show_k3_panel
from backend.features.activity.services.game_service import (
    apply_auto_schedule,
    format_blackjack_round_text,
    get_or_create_setting,
    list_due_blackjack_round_ids,
    list_due_k3_round_ids,
    settle_blackjack_round,
    settle_k3_round,
)
from backend.shared.time_helper import LOCAL_TIMEZONE
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


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
            due_k3_round_ids = await list_due_k3_round_ids(session)
            due_blackjack_round_ids = await list_due_blackjack_round_ids(session)
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
            except Exception as exc:
                log.warning("game_schedule_panel_refresh_failed", chat_id=chat_id, error=str(exc))
        for round_id in due_k3_round_ids:
            async with db.session_factory() as session:
                summary = await settle_k3_round(session, round_id)
                if summary is None:
                    await session.commit()
                    continue
                try:
                    await self._send_k3_summary(app, summary)
                except Exception as exc:
                    await session.rollback()
                    log.error("k3_result_announcement_failed", round_id=round_id, error=str(exc))
                    continue
                chat_id = int(summary["round"].chat_id)
                await session.commit()
            try:
                await show_k3_panel(app, db, chat_id)
            except Exception as exc:
                log.warning("game_k3_panel_refresh_failed", chat_id=chat_id, round_id=round_id, error=str(exc))
        for round_id in due_blackjack_round_ids:
            async with db.session_factory() as session:
                summary = await settle_blackjack_round(session, round_id)
                if summary is None:
                    await session.commit()
                    continue
                try:
                    await self._send_blackjack_summary(app, summary)
                except Exception as exc:
                    await session.rollback()
                    log.error("blackjack_result_announcement_failed", round_id=round_id, error=str(exc))
                    continue
                chat_id = int(summary["round"].chat_id)
                await session.commit()
            try:
                await show_blackjack_panel(app, db, chat_id)
            except Exception as exc:
                log.warning("game_blackjack_panel_refresh_failed", chat_id=chat_id, round_id=round_id, error=str(exc))

    async def _send_k3_summary(self, app, summary: dict) -> None:
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
                user_id = int(winner["user_id"])
                mention = f'<a href="tg://user?id={user_id}">用户{user_id}</a>'
                lines.append(
                    f"• {mention} | 竞猜 {html.escape(str(winner['guess']))} | 下注 {winner.get('bet', '-')}"
                    f" | 返奖 {winner['payout']} | 净结果 {winner.get('net', winner['payout'])}"
                )
        else:
            lines.append("😶 本局无人中奖，下注积分已按规则结算。")
        await PublishService.send(
            SimpleNamespace(bot=app.bot, application=app),
            chat_id=round_obj.chat_id,
            text="\n".join(lines),
            parse_mode="HTML",
        )

    async def _send_blackjack_summary(self, app, summary: dict) -> None:
        round_obj = summary["round"]
        participant = summary["participant"]
        outcome = summary["outcome"]
        text = format_blackjack_round_text(participant, reveal_dealer=True, outcome=outcome)
        context = SimpleNamespace(bot=app.bot, application=app)
        if round_obj.announcement_message_id:
            try:
                await PublishService.edit(
                    context,
                    chat_id=round_obj.chat_id,
                    message_id=round_obj.announcement_message_id,
                    text=text,
                )
            except Exception as exc:
                log.warning(
                    "blackjack_summary_edit_failed",
                    chat_id=round_obj.chat_id,
                    message_id=round_obj.announcement_message_id,
                    error=str(exc),
                )
                await PublishService.send(context, chat_id=round_obj.chat_id, text=text)
        else:
            await PublishService.send(context, chat_id=round_obj.chat_id, text=text)
