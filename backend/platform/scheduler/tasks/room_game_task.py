from __future__ import annotations

import structlog
from sqlalchemy import select

from backend.features.activity.room_games.notices import room_notice
from backend.features.activity.room_games.rooms import advance_hand, now, void_hand
from backend.platform.db.schema.models.room_games import RoomGame
from backend.platform.scheduler.core.core import ScheduledTask
from backend.shared.services.base import ValidationError

POLL_SECONDS = 3
BATCH = 25
log = structlog.get_logger(__name__)


class RoomGameTask(ScheduledTask):
    def __init__(self):
        super().__init__("room_games", POLL_SECONDS)

    async def execute(self, app):
        db = app.bot_data["db"]
        async with db.session_factory() as session:
            stmt = select(RoomGame.id).where(RoomGame.deadline <= now()).order_by(RoomGame.deadline)
            ids = list((await session.scalars(stmt.limit(BATCH))).all())
        for room_id in ids:
            await self._advance(app, db, room_id)

    async def _advance(self, app, db, room_id):
        async with db.session_factory() as session:
            room = await session.get(RoomGame, room_id, with_for_update=True)
            if room is None or room.deadline is None or room.deadline > now():
                return
            settled = False
            if room.status == "playing":
                settled = await self._play_timeout(session, room)
            else:
                room.status, room.deadline = "closed", None
                room.version += 1
            await session.commit()
        if settled:
            await room_notice(app.bot, room, "settled")

    async def _play_timeout(self, session, room):
        room_id = room.id
        try:
            async with session.begin_nested():
                return await advance_hand(session, room, seat=None, action={"type": "fold"})
        except (ValidationError, RuntimeError, OSError, TimeoutError):
            log.exception("room_game_voided", room_id=room_id)
            await session.refresh(room)
            await void_hand(session, room)
            return True
