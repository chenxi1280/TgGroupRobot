from __future__ import annotations

import asyncio
import datetime as dt
import os
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from telegram.error import Forbidden

from backend.features.activity import game_runtime_actions
from backend.features.activity.services import game_blackjack as blackjack, game_k3 as k3
from backend.features.activity.services.game_base import get_or_create_setting
from backend.features.points.services.points_service import change_points, get_balance
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import PointsTransaction, TgChat, TgUser
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound
from backend.platform.scheduler.tasks import game_task

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL")]


@pytest_asyncio.fixture
async def game_scope():
    db = create_database(URL)
    user_id = 8_000_000_000 + secrets.randbelow(1_000_000_000)
    chat_id = -user_id
    users = [user_id, user_id + 1]
    try:
        async with db.session_factory() as session:
            session.add_all([TgChat(id=chat_id, type="supergroup", title="隔离游戏回归"), *(TgUser(id=u) for u in users)])
            await session.flush()
            await get_or_create_setting(session, chat_id)
            for user in users:
                await change_points(session, chat_id, user, amount=100, txn_type="reward")
            await session.commit()
        yield db, chat_id, user_id
    finally:
        async with db.session_factory() as session:
            await session.execute(delete(TgChat).where(TgChat.id == chat_id))
            await session.execute(delete(TgUser).where(TgUser.id.in_(users)))
            await session.commit()
        await db.engine.dispose()


async def wait_until_blocked(db, pid: int) -> None:
    async with asyncio.timeout(8), db.session_factory() as observer:
        while not await observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pid}):
            await asyncio.sleep(0.05)


async def test_concurrent_k3_first_bets_share_one_round_and_charge_each_user(game_scope):
    db, chat_id, user_id = game_scope
    async with db.session_factory() as first, db.session_factory() as second:
        first_round, _ = await k3.create_or_join_k3_round(first, chat_id, user_id, guess="small", bet_points=10)
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        second_bet = asyncio.create_task(
            k3.create_or_join_k3_round(second, chat_id, user_id + 1, guess="big", bet_points=10)
        )
        try:
            await wait_until_blocked(db, second_pid)
            await first.commit()
            second_round, _ = await second_bet
            await second.commit()
        finally:
            if not second_bet.done():
                second_bet.cancel()
                await asyncio.gather(second_bet, return_exceptions=True)
        assert first_round.id == second_round.id
    async with db.session_factory() as session:
        assert await get_balance(session, chat_id, user_id) == 90
        assert await get_balance(session, chat_id, user_id + 1) == 90


async def start_blackjack(db, chat_id, user_id, *, message_id, deadline=None):
    async with db.session_factory() as session:
        await change_points(session, chat_id, user_id, amount=-10, txn_type="penalty")
        round_obj, _ = await blackjack.start_blackjack_round(session, chat_id, user_id, bet_points=10)
        round_obj.result_data = {**round_obj.result_data, "player_cards": [10, 10], "dealer_cards": [10, 7], "deck": [3]}
        round_obj.announcement_message_id = message_id
        if deadline is not None:
            round_obj.settle_at = deadline
        await session.commit()
        return round_obj.id, round_obj.settle_at


async def test_blackjack_player_and_timeout_cannot_both_pay(game_scope, monkeypatch):
    db, chat_id, user_id = game_scope
    round_id, deadline = await start_blackjack(db, chat_id, user_id, message_id=8)
    async with db.session_factory() as player, db.session_factory() as worker:
        round_obj, participant = await blackjack.get_active_blackjack_round(player, chat_id, user_id, lock=True)
        monkeypatch.setattr(blackjack, "now_utc", lambda: deadline + dt.timedelta(seconds=1))
        worker_pid = await worker.scalar(text("SELECT pg_backend_pid()"))
        settling = asyncio.create_task(blackjack.settle_blackjack_round(worker, round_id))
        try:
            await wait_until_blocked(db, worker_pid)
            await blackjack.blackjack_stand(player, round_obj, participant)
            await player.commit()
            assert await settling is None
            await worker.commit()
        finally:
            if not settling.done():
                settling.cancel()
                await asyncio.gather(settling, return_exceptions=True)
    async with db.session_factory() as session:
        assert await get_balance(session, chat_id, user_id) == 110


async def test_blackjack_old_message_cannot_stop_new_round(game_scope, monkeypatch):
    db, chat_id, user_id = game_scope
    past = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    old_id, _ = await start_blackjack(db, chat_id, user_id, message_id=7, deadline=past)
    new_id, _ = await start_blackjack(db, chat_id, user_id, message_id=8)
    reply = AsyncMock()
    monkeypatch.setattr(game_runtime_actions, "answer_callback_query_safely", reply)
    monkeypatch.setattr(game_runtime_actions, "show_blackjack_panel", AsyncMock())
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}),
                              bot=SimpleNamespace(edit_message_text=AsyncMock()))
    message = SimpleNamespace(message_id=7)
    update = SimpleNamespace(callback_query=SimpleNamespace(data=f"gmrun:bj:stand:{chat_id}", message=message),
                             effective_chat=SimpleNamespace(id=chat_id), effective_user=SimpleNamespace(id=user_id))
    await game_runtime_actions.handle_game_runtime_callback(update, context)
    assert "旧牌局" in reply.await_args.args[1]
    async with db.session_factory() as session:
        assert (await session.get(GameRound, new_id)).status == "player_turn"
        assert await get_balance(session, chat_id, user_id) == 80
    message.message_id = 8
    await game_runtime_actions.handle_game_runtime_callback(update, context)
    async with db.session_factory() as session:
        assert (await session.get(GameRound, old_id)).status == "player_turn"
        assert (await session.get(GameRound, new_id)).status == "finished"
        assert await get_balance(session, chat_id, user_id) == 100


@pytest.mark.parametrize("kind", ["k3", "blackjack"])
async def test_unavailable_notification_keeps_persisted_result_and_payout(game_scope, monkeypatch, kind):
    db, chat_id, user_id = game_scope
    past = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    if kind == "k3":
        async with db.session_factory() as session:
            round_obj, _ = await k3.create_or_join_k3_round(session, chat_id, user_id, guess="small", bet_points=10)
            round_obj.settle_at = past
            await session.commit()
            round_id = round_obj.id
        values = iter([1, 2, 3])
        monkeypatch.setattr(k3.random, "randint", lambda *_: next(values))
    else:
        round_id, _ = await start_blackjack(db, chat_id, user_id, message_id=8, deadline=past)
    fail_send = AsyncMock(side_effect=Forbidden("mock chat cannot receive message"))
    task = game_task.GameTask()
    monkeypatch.setattr(task, f"_send_{kind}_summary", fail_send)
    monkeypatch.setattr(game_task, f"show_{kind}_panel", AsyncMock())
    process = getattr(task, f"_process_{kind}_round")
    await process(None, db, round_id)
    await process(None, db, round_id)
    fail_send.assert_awaited_once()
    async with db.session_factory() as session:
        round_obj = await session.get(GameRound, round_id)
        assert round_obj.status == "finished"
        if kind == "k3":
            assert round_obj.result_data["dice"] == [1, 2, 3]
        assert await get_balance(session, chat_id, user_id) == 110
        payout = await session.scalar(select(GameParticipant.payout_points).where(GameParticipant.round_id == round_id))
        assert payout == 20
        amounts = (await session.scalars(
            select(PointsTransaction.amount).where(PointsTransaction.chat_id == chat_id, PointsTransaction.user_id == user_id)
            .order_by(PointsTransaction.id)
        )).all()
        assert amounts == [100, -10, 20]
