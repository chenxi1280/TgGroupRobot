"""接龙自动结束任务。"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import structlog
from sqlalchemy import select

from backend.features.activity.services.solitaire_service import (
    close_solitaire,
    format_solitaire_message,
)
from backend.platform.db.schema.models.core import Solitaire
from backend.platform.db.schema.models.enums import SolitaireStatus
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ClosedSolitaire:
    solitaire_id: int
    chat_id: int
    title: str
    participant_count: int
    message_id: int | None
    message_text: str | None


async def _list_due_solitaire_ids(db, now: dt.datetime) -> list[int]:
    async with db.session_factory() as session:
        result = await session.execute(
            select(Solitaire.id).where(
                Solitaire.status == SolitaireStatus.active.value,
                Solitaire.deadline.isnot(None),
                Solitaire.deadline < now,
            )
        )
        due_ids = [int(solitaire_id) for solitaire_id in result.scalars().all()]
        await session.commit()
    return due_ids


async def _close_due_solitaire(db, solitaire_id: int) -> ClosedSolitaire | None:
    async with db.session_factory() as session:
        result = await close_solitaire(session, solitaire_id)
        if not result.success:
            await session.commit()
            return None
        solitaire = result.solitaire
        snapshot = ClosedSolitaire(
            solitaire_id=solitaire.id,
            chat_id=solitaire.chat_id,
            title=solitaire.title,
            participant_count=len(solitaire.entries_rel),
            message_id=solitaire.message_id,
            message_text=(
                format_solitaire_message(solitaire, show_closed=False)
                if solitaire.message_id
                else None
            ),
        )
        await session.commit()
    return snapshot


async def _publish_closed_solitaire(app, snapshot: ClosedSolitaire) -> None:
    context = SimpleNamespace(bot=app.bot, application=app)
    try:
        await PublishService.send(
            context,
            chat_id=snapshot.chat_id,
            text=(
                f"⏰ 接龙已截止\n\n{snapshot.title}\n"
                f"参与人数: {snapshot.participant_count} 人"
            ),
        )
    except Exception as exc:
        log.error(
            "solitaire_expired_notification_failed",
            solitaire_id=snapshot.solitaire_id,
            error=str(exc),
        )
    if snapshot.message_id is None or snapshot.message_text is None:
        return
    try:
        await PublishService.edit(
            context,
            chat_id=snapshot.chat_id,
            message_id=snapshot.message_id,
            text=snapshot.message_text,
        )
    except Exception as exc:
        log.error(
            "solitaire_update_group_message_failed",
            solitaire_id=snapshot.solitaire_id,
            error=str(exc),
        )


class SolitaireTask(ScheduledTask):
    """关闭到期接龙，并在事务提交后更新 Telegram 消息。"""

    def __init__(self) -> None:
        config = TASK_CONFIG["solitaire"]
        super().__init__(
            name="solitaire",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        now = dt.datetime.now(dt.UTC)
        due_ids = await _list_due_solitaire_ids(db, now)
        closed_count = 0
        for solitaire_id in due_ids:
            snapshot = await _close_due_solitaire(db, solitaire_id)
            if snapshot is None:
                continue
            closed_count += 1
            await _publish_closed_solitaire(app, snapshot)
        if closed_count > 0:
            log.info("solitaires_auto_closed", count=closed_count)
