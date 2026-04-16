from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.activity import auction_handler
from backend.platform.db.schema.models.enums import ConversationStateType


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, session: _FakeSession | None = None) -> None:
        self._session = session or _FakeSession()

    def session_factory(self):
        return _FakeSessionContext(self._session)


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _FakeDb()}),
        bot=SimpleNamespace(),
    )


def _group_update(*, text: str, reply_to_message_id: int | None):
    replies: list[tuple[str, str | None, object | None]] = []

    async def fake_reply_text(text: str, parse_mode=None, reply_markup=None):
        replies.append((text, parse_mode, reply_markup))

    reply_to_message = None
    if reply_to_message_id is not None:
        reply_to_message = SimpleNamespace(message_id=reply_to_message_id)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(
            text=text,
            caption=None,
            reply_to_message=reply_to_message,
            reply_text=fake_reply_text,
        ),
    )
    return update, replies


@pytest.mark.asyncio
async def test_auction_create_trigger_accepts_money_label(monkeypatch):
    saved_state: list[tuple[str, dict]] = []

    async def fake_get_or_create_setting(session, chat_id: int):
        return SimpleNamespace(enabled=True, create_permission="all", pin_message_enabled=False)

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return None

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved_state.append((state_type, state_data))

    monkeypatch.setattr(auction_handler, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(auction_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(auction_handler, "set_user_state", fake_set_user_state)

    update, replies = _group_update(text="💰 拍卖", reply_to_message_id=99)

    result = await auction_handler.auction_group_message_handler(update, _context())

    assert result is True
    assert saved_state == [
        (
            ConversationStateType.auction_wait_title.value,
            {"source_message_id": 99},
        )
    ]
    assert replies and "请输入拍卖标题" in replies[0][0]


@pytest.mark.asyncio
async def test_auction_create_trigger_without_reply_shows_usage(monkeypatch):
    async def fake_get_or_create_setting(session, chat_id: int):
        return SimpleNamespace(enabled=True, create_permission="all", pin_message_enabled=False)

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return None

    monkeypatch.setattr(auction_handler, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(auction_handler, "get_user_state", fake_get_user_state)

    update, replies = _group_update(text="拍卖", reply_to_message_id=None)

    result = await auction_handler.auction_group_message_handler(update, _context())

    assert result is True
    assert replies and "请先回复要拍卖的消息" in replies[0][0]


@pytest.mark.asyncio
async def test_auction_create_trigger_when_disabled_replies(monkeypatch):
    async def fake_get_or_create_setting(session, chat_id: int):
        return SimpleNamespace(enabled=False, create_permission="all", pin_message_enabled=False)

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return None

    async def forbidden_set_user_state(*args, **kwargs):
        raise AssertionError("disabled auctions must not start the create flow")

    monkeypatch.setattr(auction_handler, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(auction_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(auction_handler, "set_user_state", forbidden_set_user_state)

    update, replies = _group_update(text="拍 卖", reply_to_message_id=99)

    result = await auction_handler.auction_group_message_handler(update, _context())

    assert result is True
    assert replies and "拍卖功能未开启" in replies[0][0]
