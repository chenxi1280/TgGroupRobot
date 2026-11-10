import asyncio
import datetime as dt
import os
import secrets
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete
from telegram.error import Forbidden

from backend.app.web import create_web_app
from backend.features.activity.game_panels import show_blackjack_panel, show_k3_panel
from backend.features.activity.services import game_blackjack, game_k3
from backend.features.activity.services.game_base import get_or_create_setting
from backend.features.points.services.points_service import change_points, get_balance
from backend.platform.config.core.settings import Settings
from backend.platform.db.runtime.session import create_database
from backend.platform.db.schema.models.core import TgChat, TgUser
from backend.platform.db.schema.models.expansion import GameRound
from backend.platform.db.schema.models.room_games import GameNotice
from backend.platform.scheduler.tasks.game_notice_task import GameNoticeTask
from backend.platform.scheduler.tasks.game_task import GameTask
from test_mini_app_auth import TOKEN, signed_data

URL = os.environ.get("TGR_REPAIR_TEST_DATABASE_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Requires isolated PostgreSQL")]


@pytest_asyncio.fixture
async def games():
    db = create_database(URL)
    user = 8_000_000_000 + secrets.randbelow(1_000_000_000)
    chat, points = -user, -(user + 1)
    settings = Settings(_env_file=None, BOT_TOKEN=TOKEN, MINI_APP_ENABLED=True, ADMIN_WEB_ENABLED=False)
    bot = SimpleNamespace(
        username="isolated_games_bot", get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=7)), edit_message_text=AsyncMock(),
    )
    app = SimpleNamespace(bot=bot, bot_data={"db": db, "settings": settings})
    try:
        async with db.session_factory() as s:
            s.add_all([TgChat(id=chat, type="supergroup", title="游戏验收群"),
                       TgChat(id=points, type="supergroup", title="积分主群"), TgUser(id=user), TgUser(id=user + 1)])
            await s.flush()
            setting = await get_or_create_setting(s, chat)
            setting.k3_enabled = setting.blackjack_enabled = True
            setting.points_source_chat_id = points
            for member in (user, user + 1):
                await change_points(s, points, member, amount=100, txn_type="reward")
            await change_points(s, chat, user, amount=22, txn_type="reward")
            await s.commit()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_web_app(app, settings)),
                                     base_url="http://game-test") as client:
            yield SimpleNamespace(db=db, app=app, bot=bot, chat=chat, points=points, user=user, client=client)
    finally:
        async with db.session_factory() as s:
            await s.execute(delete(GameNotice).where(GameNotice.chat_id == chat))
            await s.execute(delete(TgChat).where(TgChat.id.in_([chat, points])))
            await s.execute(delete(TgUser).where(TgUser.id.in_([user, user + 1])))
            await s.commit()
        await db.engine.dispose()


def auth(games, *, user=None, scene=None):
    data = signed_data(user_id=user or games.user, issued_at=int(time.time()), scene=scene or f"game_blackjack_{-games.chat}")
    return {"Authorization": "tma " + data}


@pytest.mark.parametrize(("show_panel", "game"), [(show_k3_panel, "k3"), (show_blackjack_panel, "blackjack")])
async def test_group_panel_keeps_table_and_adds_room_lobby_on_publish_and_refresh(games, show_panel, game):
    await show_panel(games.app, games.db, games.chat)
    await show_panel(games.app, games.db, games.chat)
    for send in (games.bot.send_message, games.bot.edit_message_text):
        rows = send.await_args.kwargs["reply_markup"].inline_keyboard
        assert rows[0][0].url.endswith(f"?startapp=game_{game}_{-games.chat}")
        assert rows[1][0].text == "打开游戏房间"
        assert rows[1][0].url.endswith(f"?startapp=rooms_{-games.chat}")


async def test_blackjack_group_link_signed_member_and_points_lifecycle(games, monkeypatch):
    await show_blackjack_panel(games.app, games.db, games.chat)
    link = games.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url
    assert link == f"https://t.me/isolated_games_bot?startapp=game_blackjack_{-games.chat}"
    games.bot.send_message.reset_mock()
    monkeypatch.setattr(game_blackjack, "build_blackjack_deck", lambda: [10, 2, 6, 10, 9, 7])
    url = "/miniapp/api/games/blackjack"
    headers = auth(games)
    initial = await games.client.get(url, headers=headers)
    assert initial.json()["balance"] == 100 and "积分主群" in initial.json()["balance_label"]
    opened = await games.client.post(url, headers=headers, json={"action": "start", "round_id": 0, "bet": 10})
    active = opened.json()
    assert opened.status_code == 200 and active["balance"] == 90
    assert active["round"]["dealer"] == [10, None] and "deck" not in active["round"]
    assert "黑杰克开局" in games.bot.send_message.await_args.kwargs["text"]
    round_id = active["round"]["id"]
    repeated = await games.client.post(url, headers=headers, json={"action": "start", "round_id": 0, "bet": 10})
    assert repeated.status_code == 409
    stranger = await games.client.get(url, headers=auth(games, user=games.user + 1))
    assert stranger.json()["round"] is None
    hit = {"action": "hit", "round_id": round_id, "card_count": 2}
    hits = await asyncio.gather(*(games.client.post(url, headers=headers, json=hit) for _ in range(2)))
    assert sorted(response.status_code for response in hits) == [200, 409]
    response = next(response for response in hits if response.status_code == 200)
    assert response.json()["round"]["player_total"] == 18
    games.bot.send_message.side_effect = Forbidden("simulated group delivery failure")
    done = await games.client.post(url, headers=headers, json={**hit, "action": "stand", "card_count": 3})
    assert done.json()["round"]["dealer"] == [10, 6, 10]
    assert done.json()["round"]["payout"] == 20 and done.json()["balance"] == 110
    assert "本局获胜" in games.bot.send_message.await_args.kwargs["text"]
    reload = await games.client.get(url, headers=headers)
    assert reload.json()["round"]["status"] == "finished"
    async with games.db.session_factory() as s:
        assert await get_balance(s, games.chat, games.user) == 22


async def test_old_blackjack_link_reopens_exact_result_for_group_member(games, monkeypatch):
    monkeypatch.setattr(game_blackjack, "build_blackjack_deck", lambda: [10, 2, 6, 10, 9, 7])
    path = "/miniapp/api/games/blackjack"
    identity = auth(games)
    first = (await games.client.post(path, headers=identity, json={
        "action": "start", "round_id": 0, "bet": 10,
    })).json()["round"]["id"]
    assert (await games.client.post(path, headers=identity, json={
        "action": "stand", "round_id": first, "card_count": 2,
    })).status_code == 200
    url = games.bot.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0].url
    scene = url.partition("startapp=")[2]
    assert scene == f"game_blackjack_{-games.chat}_{first}"
    newer = (await games.client.post(path, headers=identity, json={
        "action": "start", "round_id": first, "bet": 20,
    })).json()["round"]["id"]
    other = auth(games, user=games.user + 1, scene=scene)
    result = (await games.client.get(path, headers=other)).json()
    assert result["historical"] and not result["own_result"]
    assert result["round"]["id"] == first and result["round"]["bet"] == 10
    assert "deck" not in result["round"]
    assert (await games.client.get(path + "?current=true", headers=auth(games, scene=scene))).json()["round"]["id"] == newer
    assert (await games.client.get(path, headers=auth(games, scene=f"game_blackjack_{-games.chat}_{newer}"))).status_code == 404


async def test_k3_reuses_group_round_and_scheduler_result(games, monkeypatch):
    url = "/miniapp/api/games/k3"
    for user in (games.user, games.user + 1):
        response = await games.client.post(
            url, headers=auth(games, user=user),
            json={"action": "bet", "round_id": 0, "bet": 10, "guess": "small"},
        )
        assert response.status_code == 200 and response.json()["balance"] == 90
    assert response.json()["round"]["players"] == 2
    assert games.bot.send_message.await_count == 1
    round_id = response.json()["round"]["id"]
    async with games.db.session_factory() as s:
        round_obj = await s.get(GameRound, round_id)
        round_obj.settle_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        await s.commit()
    rolls = iter([1, 2, 3])
    monkeypatch.setattr(game_k3.random, "randint", lambda *args: next(rolls))
    await GameTask()._process_k3_round(games.app, games.db, round_id)
    await GameNoticeTask().execute(games.app)
    result = (await games.client.get(url, headers=auth(games))).json()
    assert result["round"] is None and result["draw"]["dice"] == [1, 2, 3]
    assert result["my_k3"]["payout"] == 20 and result["balance"] == 110
    draw = next(call.kwargs for call in games.bot.send_message.await_args_list if "快三开奖" in call.kwargs["text"])
    scene = draw["reply_markup"].inline_keyboard[0][0].url.partition("startapp=")[2]
    assert scene == f"game_k3_{-games.chat}_{round_id}"
    history = (await games.client.get(url, headers=auth(games, user=games.user + 2, scene=scene))).json()
    assert history["historical"] and history["my_k3"] is None and history["draw"]["id"] == round_id

    assert any("快三开奖" in call.kwargs["text"] for call in games.bot.send_message.await_args_list)
    late = await games.client.post(
        url, headers=auth(games),
        json={"action": "bet", "round_id": round_id, "target_round_id": round_id, "bet": 10, "guess": "small"},
    )
    assert late.status_code == 409
    refreshed = (await games.client.get(url, headers=auth(games))).json()
    assert refreshed["balance"] == 110 and refreshed["round"] is None


async def test_game_requires_membership_and_signed_game_scene(games):
    url = "/miniapp/api/games/k3"
    assert (await games.client.get(url)).status_code == 401
    assert (await games.client.get(url, headers=auth(games, scene="verify_test"))).status_code == 403
    games.bot.get_chat_member.return_value = SimpleNamespace(status="left")
    move = {"action": "bet", "round_id": 0, "bet": 10, "guess": "big"}
    assert (await games.client.post(url, headers=auth(games), json=move)).status_code == 403
    games.bot.get_chat_member.return_value = SimpleNamespace(status="member")
    invalid = await games.client.post(url, headers=auth(games), json={**move, "bet": 501})
    assert invalid.status_code == 422
    assert (await games.client.get(url, headers=auth(games))).json()["balance"] == 100
    games.bot.send_message.assert_not_awaited()
