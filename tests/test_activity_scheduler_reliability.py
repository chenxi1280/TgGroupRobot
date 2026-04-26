from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.platform.scheduler.tasks import auction_task, game_task, guess_task


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Db:
    def __init__(self) -> None:
        self.sessions: list[_Session] = []

    def session_factory(self):
        session = _Session()
        self.sessions.append(session)
        return _SessionContext(session)


@pytest.mark.asyncio
async def test_game_task_rolls_back_round_when_result_announcement_fails(monkeypatch):
    db = _Db()
    settled: list[int] = []
    shown: list[int] = []

    async def fake_list_k3(session):
        return [7]

    async def fake_list_bj(session):
        return []

    async def fake_settle(session, round_id: int):
        settled.append(round_id)
        return {"round": SimpleNamespace(chat_id=-1001, result_data={"dice": [1, 2, 3], "label": "小"}), "winners": []}

    async def fake_schedule(session, now_local):
        return []

    async def fail_send(self, app, summary):
        raise RuntimeError("telegram down")

    async def fake_show(*args, **kwargs):
        shown.append(args[2])

    monkeypatch.setattr(game_task, "apply_auto_schedule", fake_schedule)
    monkeypatch.setattr(game_task, "list_due_k3_round_ids", fake_list_k3)
    monkeypatch.setattr(game_task, "list_due_blackjack_round_ids", fake_list_bj)
    monkeypatch.setattr(game_task, "settle_k3_round", fake_settle)
    monkeypatch.setattr(game_task.GameTask, "_send_k3_summary", fail_send)
    monkeypatch.setattr(game_task, "show_k3_panel", fake_show)

    await game_task.GameTask().execute(SimpleNamespace(bot_data={"db": db}))

    assert settled == [7]
    assert db.sessions[0].commits == 1
    assert db.sessions[1].rollbacks == 1
    assert db.sessions[1].commits == 0
    assert shown == []


@pytest.mark.asyncio
async def test_guess_task_sends_fallback_when_deadline_edit_fails(monkeypatch):
    db = _Db()
    event = SimpleNamespace(
        id=9,
        chat_id=-1001,
        announcement_message_id=55,
        title="竞猜",
        status="pending",
        mode="no_banker",
        public_pool=0,
        deadline_at=SimpleNamespace(astimezone=lambda: SimpleNamespace(strftime=lambda fmt: "2026-04-25 20:00:00")),
        command_keyword="竞猜",
        options_json=[{"key": "A", "label": "主胜"}],
        description=None,
    )

    class _Bot:
        def __init__(self) -> None:
            self.sent_messages: list[dict] = []

        async def edit_message_text(self, **kwargs):
            raise RuntimeError("message deleted")

        async def send_message(self, **kwargs):
            self.sent_messages.append(kwargs)
            return SimpleNamespace(message_id=88)

    async def fake_list(session):
        return [9]

    async def fake_close(session, event_id: int):
        return event

    monkeypatch.setattr(guess_task, "list_due_event_ids", fake_list)
    monkeypatch.setattr(guess_task, "close_due_event", fake_close)

    bot = _Bot()
    await guess_task.GuessTask().execute(SimpleNamespace(bot_data={"db": db}, bot=bot))

    assert event.announcement_message_id == 88
    assert db.sessions[1].commits == 1
    assert db.sessions[1].rollbacks == 0
    assert bot.sent_messages
    assert "已截止下注，请等待群内开奖结果" in bot.sent_messages[0]["text"]
    assert "管理员下一步" not in bot.sent_messages[0]["text"]
    assert "后台" not in bot.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_game_task_k3_summary_uses_mentions_without_admin_hint():
    sent_messages: list[dict] = []

    class _Bot:
        async def send_message(self, **kwargs):
            sent_messages.append(kwargs)
            return SimpleNamespace(message_id=66)

    summary = {
        "round": SimpleNamespace(chat_id=-1001, result_data={"dice": [1, 2, 3], "label": "小"}),
        "winners": [{"user_id": 42, "guess": "小", "bet": 10, "payout": 20, "net": 10}],
    }

    await game_task.GameTask()._send_k3_summary(SimpleNamespace(bot=_Bot()), summary)

    assert sent_messages
    text = sent_messages[0]["text"]
    assert sent_messages[0]["parse_mode"] == "HTML"
    assert '<a href="tg://user?id=42">用户42</a>' in text
    assert "用户 42" not in text
    assert "后台" not in text
    assert "管理员" not in text


@pytest.mark.asyncio
async def test_auction_task_rolls_back_when_result_announcement_fails(monkeypatch):
    db = _Db()
    item = SimpleNamespace(
        id=12,
        chat_id=-1001,
        title="拍卖",
        status="ended",
        start_price=100,
        current_price=188,
        end_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 4, 25, 12, 0, tzinfo=dt.UTC),
        last_announce_message_id=None,
    )

    class _Bot:
        async def send_message(self, **kwargs):
            raise RuntimeError("telegram down")

    async def fake_list(session):
        return [12]

    async def fake_settle(session, item_id: int):
        return SimpleNamespace(item=item, note="成交")

    async def fake_setting(session, chat_id: int):
        return SimpleNamespace(pin_message_enabled=False)

    monkeypatch.setattr(auction_task, "list_due_auction_ids", fake_list)
    monkeypatch.setattr(auction_task, "settle_due_auction", fake_settle)
    monkeypatch.setattr(auction_task, "get_or_create_setting", fake_setting)

    await auction_task.AuctionTask().execute(SimpleNamespace(bot_data={"db": db}, bot=_Bot()))

    assert db.sessions[0].commits == 1
    assert db.sessions[1].rollbacks == 1
    assert db.sessions[1].commits == 0
    assert item.last_announce_message_id is None
