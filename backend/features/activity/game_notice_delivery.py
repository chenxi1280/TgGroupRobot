from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy import select, update
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError

from backend.platform.db.schema.models.expansion import GameRound
from backend.platform.db.schema.models.room_games import GameNotice

log = structlog.get_logger(__name__)


def queue_game_notice(
    session, chat_id: int, text: str, *, keyboard=None, parse_mode=None,
    message_id=None, actor_id=None, opening_round_id=None, reply_to_message_id=None,
) -> GameNotice:
    now = dt.datetime.now(dt.UTC)
    notice = GameNotice(
        chat_id=chat_id, actor_id=actor_id, created_at=now, due_at=now,
        payload={
            "text": text, "parse_mode": parse_mode,
            "reply_markup": keyboard.to_dict() if keyboard else None,
            "message_id": message_id, "opening_round_id": opening_round_id,
            "reply_to_message_id": reply_to_message_id,
        },
    )
    session.add(notice)
    return notice


async def _send(session, bot, notice: GameNotice) -> int | None:
    payload = dict(notice.payload)
    message_id = payload.pop("message_id")
    opening_round_id = payload.pop("opening_round_id", None)
    reply_to = payload.pop("reply_to_message_id", None)
    if opening_round_id is not None and payload["reply_markup"] is not None:
        status = await session.scalar(select(GameRound.status).where(GameRound.id == opening_round_id))
        if status != "player_turn":
            return None
    payload["reply_markup"] = InlineKeyboardMarkup.de_json(payload["reply_markup"], bot)
    if message_id is not None:
        try:
            await bot.edit_message_text(chat_id=notice.chat_id, message_id=message_id, **payload)
            return message_id
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return message_id
    if reply_to is not None:
        payload.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
    sent = await bot.send_message(chat_id=notice.chat_id, **payload)
    sent_id = getattr(sent, "message_id", None)
    if not isinstance(sent_id, int):
        return None
    if opening_round_id is not None:
        await session.execute(update(GameRound).where(
            GameRound.id == opening_round_id, GameRound.announcement_message_id.is_(None),
        ).values(announcement_message_id=sent_id))
    return sent_id


def _retry_delay(error: TelegramError, attempts: int) -> float | None:
    if isinstance(error, RetryAfter):
        delay = error.retry_after
        return delay.total_seconds() if isinstance(delay, dt.timedelta) else delay
    if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
        return min(15 * 2 ** min(attempts - 1, 6), 600)
    return None


async def _deliver_one(db, bot, notice_id: int) -> None:
    async with db.session_factory() as session:
        stmt = select(GameNotice).where(
            GameNotice.id == notice_id, GameNotice.due_at <= dt.datetime.now(dt.UTC),
        ).with_for_update(skip_locked=True)
        notice = await session.scalar(stmt)
        if notice is None:
            return
        notice.attempts += 1
        try:
            sent_id = await _send(session, bot, notice)
        except TelegramError as exc:
            delay = _retry_delay(exc, notice.attempts)
            notice.due_at = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay) if delay is not None else None
            notice.error = type(exc).__name__
            log.warning("game_notice_delivery_failed", notice_id=notice_id, error=notice.error, retry=delay)
        else:
            notice.due_at = None
            notice.error = None
            if sent_id is not None:
                notice.payload = {**notice.payload, "delivered_message_id": sent_id}
        await session.commit()


async def deliver_game_notices(db, bot, ids: list[int] | None = None) -> None:
    if ids is None:
        async with db.session_factory() as session:
            due = select(GameNotice.id).where(GameNotice.due_at <= dt.datetime.now(dt.UTC))
            ids = list(await session.scalars(due.order_by(GameNotice.due_at, GameNotice.id).limit(20)))
    for notice_id in ids:
        await _deliver_one(db, bot, notice_id)
