import asyncio
import datetime as dt
import os

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from backend.features.activity.room_games.fees import SETTINGS_KEY, FeeSettings, RoomFee
from backend.features.activity.room_games.mahjong import RESERVE_UNITS
from backend.features.activity.services import game_k3
from backend.features.points.services.points_service_accounts import change_points, get_balance
from backend.platform.db.schema.models.core import AppSetting, PointsMallSetting, TgUser
from backend.platform.db.schema.models.expansion import GameRound
from backend.platform.db.schema.models.room_games import PlatformGameFee, RoomGame
from backend.platform.scheduler.tasks.game_task import GameTask
from backend.platform.scheduler.tasks.room_game_task import RoomGameTask
from test_mini_app_games_postgres import auth, games  # noqa: F401

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("TGR_REPAIR_TEST_DATABASE_URL"), reason="Requires isolated PostgreSQL"),
]


@pytest_asyncio.fixture
async def paid(games):  # noqa: F811
    settings = FeeSettings(
        sichuan=RoomFee(enabled=True, points=12, hands=1),
        zhajinhua=RoomFee(enabled=True, points=12, hands=2), k3=3,
    )
    users = [games.user + i for i in range(4)]
    async with games.db.session_factory() as s:
        old = await s.get(AppSetting, SETTINGS_KEY)
        old_value = old.value if old else None
        await s.merge(AppSetting(key=SETTINGS_KEY, value=settings.model_dump_json()))
        s.add_all(TgUser(id=user) for user in users[2:])
        await s.flush()
        for user in users:
            await change_points(s, games.chat, user, amount=500, txn_type="reward")
        await s.commit()
    games.users = users
    yield games
    async with games.db.session_factory() as s:
        await s.execute(delete(PlatformGameFee).where(PlatformGameFee.chat_id.in_([games.chat, games.points])))
        await s.execute(delete(RoomGame).where(RoomGame.chat_id == games.chat))
        await s.execute(delete(TgUser).where(TgUser.id.in_(users[2:])))
        if old_value is None:
            await s.execute(delete(AppSetting).where(AppSetting.key == SETTINGS_KEY))
        else:
            (await s.get(AppSetting, SETTINGS_KEY)).value = old_value
        await s.commit()


def headers(paid, user=None):
    return auth(paid, user=user, scene=f"rooms_{-paid.chat}")


async def create(paid, game):
    response = await paid.client.post("/miniapp/api/rooms", headers=headers(paid), json={
        "game": game, "base": 1, "multiplier": 1, "special": True,
    })
    assert response.status_code == 200, response.text
    return response.json()


async def operate(paid, room, operation, *, user=None, action=None, code=200):
    response = await paid.client.post(
        f'/miniapp/api/rooms/{room["id"]}', headers=headers(paid, user),
        json={"operation": operation, "version": room["version"], "action": action or {}},
    )
    assert response.status_code == code, response.text
    return response.json()


async def read(paid, room, user=None):
    return (await paid.client.get(f'/miniapp/api/rooms/{room["id"]}', headers=headers(paid, user))).json()


async def test_room_fee_disclosed_once_paid_two_hands_and_settlement_link(paid):
    room = await create(paid, "zhajinhua")
    other = paid.users[1]
    invite = paid.bot.send_message.await_args.kwargs
    assert "场费 12 分" in invite["text"]
    assert f'room_{-paid.chat}_{room["id"]}' in invite["reply_markup"].inline_keyboard[0][0].url
    initial = await read(paid, room, other)
    assert initial["fee"] == 12 and initial["requirement"] == 13 and initial["balance"] == 500
    assert initial["seat"] is None and not initial["fee_charged"]
    room = await operate(paid, room, "join", user=other)
    assert room["balance"] == 500 and not room["fee_charged"]
    assert (await read(paid, room))["balance"] == 522
    start = {"operation": "start", "version": room["version"]}
    replies = await asyncio.gather(*[
        paid.client.post(f'/miniapp/api/rooms/{room["id"]}', headers=headers(paid), json=start) for _ in range(2)
    ])
    assert sorted(reply.status_code for reply in replies) == [200, 409]
    room = next(reply.json() for reply in replies if reply.status_code == 200)
    assert room["balance"] == 509 and room["fee_charged"]
    assert "每人已扣场费 12 分" in paid.bot.send_message.await_args.kwargs["text"]
    assert all(player["cards"] is None for player in room["table"]["players"])
    await operate(paid, room, "move", user=other, action={"type": "look"})
    room = await read(paid, room, other)
    assert len(room["table"]["players"][1]["cards"]) == 3
    assert all(player["cards"] is None for player in (await read(paid, room))["table"]["players"])
    room = await operate(paid, room, "move", user=other, action={"type": "fold"})
    assert room["status"] == "between"
    assert "房主" in (await operate(paid, room, "leave", user=other, code=409))["detail"]
    assert [row["delta"] for row in room["results"][0]["rows"]] == [1, -1]
    assert room["results"][0]["rows"][0]["balance"] is None
    assert "已结算" in paid.bot.send_message.await_args.kwargs["text"]
    assert paid.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url.endswith("_1")
    room = await operate(paid, room, "next")
    assert room["balance"] == 510
    room = await operate(paid, room, "move", action={"type": "fold"})
    assert room["status"] == "closed" and len(room["results"]) == 2
    async with paid.db.session_factory() as s:
        fees = (await s.scalars(select(PlatformGameFee).where(PlatformGameFee.chat_id == paid.chat))).all()
        assert sorted(fee.amount for fee in fees) == [12, 12]
        assert await get_balance(s, paid.chat, paid.user) == 510
        assert await get_balance(s, paid.chat, other) == 488


async def test_room_insufficient_balance_and_mall_fail_without_fee(paid):
    room = await create(paid, "zhajinhua")
    other = paid.users[1]
    room = await operate(paid, room, "join", user=other)
    async with paid.db.session_factory() as s:
        await change_points(s, paid.chat, other, amount=-490, txn_type="penalty")
        await s.commit()
    result = await operate(paid, room, "start", code=409)
    assert "不足" in result["detail"]
    assert (await read(paid, room))["balance"] == 522
    assert (await read(paid, room, other))["balance"] == 10
    async with paid.db.session_factory() as s:
        assert (await s.scalars(select(PlatformGameFee).where(PlatformGameFee.chat_id == paid.chat))).first() is None
        s.add(PointsMallSetting(chat_id=paid.chat, enabled=True))
        await s.commit()
    assert "商城" in (await operate(paid, room, "start", code=409))["detail"]


async def _expire(paid, room_id):
    async with paid.db.session_factory() as s:
        room = await s.get(RoomGame, room_id)
        room.deadline = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await s.commit()


async def test_sichuan_reserve_timeout_and_paid_receipt(paid):
    room = await create(paid, "sichuan")
    for user in paid.users[1:]:
        room = await operate(paid, room, "join", user=user)
    room = await operate(paid, room, "start")
    assert room["requirement"] == RESERVE_UNITS + 12
    assert room["balance"] == 522 - RESERVE_UNITS - 12
    assert room["table"]["phase"] == "exchange"
    assert all(player["hand"] is None for player in room["table"]["players"])
    task = RoomGameTask()
    for phase in ("dingque", "play"):
        await _expire(paid, room["id"])
        await task._advance(paid.app, paid.db, room["id"])
        assert (await read(paid, room))["table"]["phase"] == phase
    async with paid.db.session_factory() as s:
        model = await s.get(RoomGame, room["id"])
        model.hand = {**model.hand, "engine": {**model.hand["engine"], "wall": []}}
        await s.commit()
    for _ in range(8):
        await _expire(paid, room["id"])
        await task._advance(paid.app, paid.db, room["id"])
        result = await read(paid, room)
        if result["status"] == "closed":
            break
    assert result["status"] == "closed"
    assert sum(row["delta"] for row in result["results"][0]["rows"]) == 0
    assert result["balance"] == 510 + result["results"][0]["rows"][0]["delta"]


async def test_k3_charges_confirmed_fee_once_and_keeps_odds(paid, monkeypatch):
    path = "/miniapp/api/games/k3"
    token = auth(paid, scene=f"game_k3_{-paid.chat}")
    bet = {"action": "bet", "round_id": 0, "bet": 10, "guess": "small"}
    assert (await paid.client.get(path, headers=token)).json()["fee"] == 3
    assert (await paid.client.post(path, headers=token, json=bet)).status_code == 409
    made = await paid.client.post(path, headers=token, json={**bet, "fee": 3})
    assert made.status_code == 200 and made.json()["balance"] == 87
    assert made.json()["my_k3"]["fee"] == 3
    assert "已扣台费 3 分" in paid.bot.send_message.await_args.kwargs["text"]
    repeat = await paid.client.post(path, headers=token, json={**bet, "fee": 3})
    assert repeat.status_code == 409
    round_id = made.json()["round"]["id"]
    async with paid.db.session_factory() as s:
        round_obj = await s.get(GameRound, round_id)
        round_obj.settle_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await s.commit()
    rolls = iter([1, 2, 3])
    monkeypatch.setattr(game_k3.random, "randint", lambda *args: next(rolls))
    await GameTask()._process_k3_round(paid.app, paid.db, round_id)
    assert (await paid.client.get(path, headers=token)).json()["balance"] == 107
    async with paid.db.session_factory() as s:
        rows = (await s.scalars(select(PlatformGameFee).where(PlatformGameFee.chat_id == paid.points))).all()
        assert [(row.game, row.amount) for row in rows] == [("k3", 3)]


async def test_engine_failure_refunds_only_hand_reserve(paid, monkeypatch):
    from backend.features.activity.room_games import rooms

    room = await create(paid, "sichuan")
    for user in paid.users[1:]:
        room = await operate(paid, room, "join", user=user)
    room = await operate(paid, room, "start")

    async def broken_engine(*args, **kwargs):
        raise RuntimeError("simulated engine failure")

    monkeypatch.setattr(rooms, "mahjong", broken_engine)
    await _expire(paid, room["id"])
    await RoomGameTask()._advance(paid.app, paid.db, room["id"])
    result = await read(paid, room)
    assert result["status"] == "closed" and result["results"][0]["void"]
    assert result["balance"] == 510
    assert "游戏投入已退回" in paid.bot.send_message.await_args.kwargs["text"]
    async with paid.db.session_factory() as s:
        fees = (await s.scalars(select(PlatformGameFee).where(PlatformGameFee.chat_id == paid.chat))).all()
        assert sum(fee.amount for fee in fees) == 48


async def test_platform_admin_updates_fees_and_reads_scoped_balance(paid):
    import httpx

    from backend.app.web import create_web_app
    from backend.features.web_admin.auth_service import hash_password
    from backend.platform.db.schema.models.admin_web import AdminAccount, AdminAuditLog

    username = f"room-test-{paid.user}"
    password = "temporary-local-room-test"
    async with paid.db.session_factory() as s:
        admin = AdminAccount(username=username, password_hash=hash_password(password), display_name=username, status="active")
        s.add(admin)
        await s.commit()
        admin_id = admin.id
    settings = paid.app.bot_data["settings"].model_copy(update={"admin_web_enabled": True})
    app = create_web_app(paid.app, settings)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://admin-test") as client:
            url = "/admin/api/game-fees"
            assert (await client.get(url)).status_code == 401
            assert (await client.post("/admin/api/auth/login", json={"username": username, "password": password})).status_code == 200
            changed = {"sichuan": {"enabled": True, "points": 14, "hands": 15},
                       "zhajinhua": {"enabled": True, "points": 13, "hands": 2}, "k3": 5}
            assert (await client.put(url, json=changed)).status_code == 200
            room = await create(paid, "zhajinhua")
            assert room["fee"] == 13
            room = await operate(paid, room, "join", user=paid.users[1])
            await operate(paid, room, "start")
            data = (await client.get(url, params={"chat_id": paid.chat})).json()["data"]
            assert data["settings"] == changed
            assert sorted(row["amount"] for row in data["entries"]) == [13, 13]
            assert {"chat_id": paid.chat, "points": 26} in data["balances"]
    finally:
        async with paid.db.session_factory() as s:
            await s.execute(delete(AdminAuditLog).where(AdminAuditLog.admin_account_id == admin_id))
            await s.execute(delete(AdminAccount).where(AdminAccount.id == admin_id))
            await s.commit()
