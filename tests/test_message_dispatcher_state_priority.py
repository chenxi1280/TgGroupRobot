from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.update_pipeline import MessageDispatcher


@pytest.mark.asyncio
async def test_get_user_state_prefers_private_state_over_target_chat(monkeypatch):
    dispatcher = MessageDispatcher()
    private_state = SimpleNamespace(state_type="sm_edit_text")
    group_state = SimpleNamespace(state_type="verification_config")

    async def fake_get_current_chat(db, user_id: int):
        assert user_id == 42
        return -1005566

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        assert user_id == 42
        if chat_id == 9001:
            return private_state
        if chat_id == -1005566:
            return group_state
        return None

    monkeypatch.setattr(
        "backend.app.update_pipeline.ChatResolver.get_current_chat",
        fake_get_current_chat,
    )
    monkeypatch.setattr(
        "backend.app.update_pipeline.get_user_state",
        fake_get_user_state,
    )

    state = await dispatcher._get_user_state(session=object(), db=object(), user_id=42, chat_id=9001)

    assert state is private_state


@pytest.mark.asyncio
async def test_get_user_state_falls_back_to_target_chat_state(monkeypatch):
    dispatcher = MessageDispatcher()
    group_state = SimpleNamespace(state_type="verification_config")

    async def fake_get_current_chat(db, user_id: int):
        assert user_id == 42
        return -1005566

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        assert user_id == 42
        if chat_id == 9001:
            return None
        if chat_id == -1005566:
            return group_state
        return None

    monkeypatch.setattr(
        "backend.app.update_pipeline.ChatResolver.get_current_chat",
        fake_get_current_chat,
    )
    monkeypatch.setattr(
        "backend.app.update_pipeline.get_user_state",
        fake_get_user_state,
    )

    state = await dispatcher._get_user_state(session=object(), db=object(), user_id=42, chat_id=9001)

    assert state is group_state


@pytest.mark.asyncio
async def test_get_user_state_ignores_selected_chat_placeholder(monkeypatch):
    dispatcher = MessageDispatcher()
    private_state = SimpleNamespace(state_type="selected_chat", state_data={"managed_chat_id": -1005566})
    group_state = SimpleNamespace(state_type="teacher_delegate_target_input")

    async def fake_get_current_chat(db, user_id: int):
        raise AssertionError("selected_chat state_data already contains the target chat")

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        assert user_id == 42
        if chat_id == 9001:
            return private_state
        if chat_id == -1005566:
            return group_state
        return None

    monkeypatch.setattr(
        "backend.app.update_pipeline.ChatResolver.get_current_chat",
        fake_get_current_chat,
    )
    monkeypatch.setattr(
        "backend.app.update_pipeline.get_user_state",
        fake_get_user_state,
    )

    state = await dispatcher._get_user_state(session=object(), db=object(), user_id=42, chat_id=9001)

    assert state is group_state


@pytest.mark.asyncio
async def test_dispatch_routes_sender_chat_group_messages_without_effective_user():
    dispatcher = MessageDispatcher()
    calls: list[tuple[int, str]] = []

    async def fake_handle(update, context, chat, user, message_text):
        calls.append((user.id, message_text))

    dispatcher._group_message_handler.handle = fake_handle
    message = SimpleNamespace(
        text="你好",
        caption=None,
        sender_chat=SimpleNamespace(id=-100777, title="Channel Identity", username="channel_identity"),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="Test Group"),
        effective_user=None,
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

    await dispatcher.dispatch(update, context)

    assert calls == [(-100777, "你好")]


@pytest.mark.asyncio
async def test_private_message_handler_does_not_treat_selected_chat_as_input_state(monkeypatch):
    from backend.features.group_ops import start_handler

    replies: list[tuple[str, object]] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            return None

    class _Db:
        def session_factory(self):
            return _Session()

    async def fake_get_state_by_chat(session, chat, user_id: int):
        return SimpleNamespace(state_type="selected_chat", state_data={"managed_chat_id": -1005566})

    async def fake_get_user_managed_chats(db, user_id: int, bot):
        return [(-1005566, "测试群", True)]

    async def fake_get_user_current_chat(db, user_id: int):
        return -1005566

    async def fake_reply_text(text, reply_markup=None):
        replies.append((text, reply_markup))

    monkeypatch.setattr(start_handler.StateHelper, "get_state_by_chat", fake_get_state_by_chat)
    monkeypatch.setattr(start_handler, "get_user_managed_chats", fake_get_user_managed_chats)
    monkeypatch.setattr(start_handler, "get_user_current_chat", fake_get_user_current_chat)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(reply_text=fake_reply_text),
    )
    context = SimpleNamespace(
        application=SimpleNamespace(bot_data={"db": _Db()}),
        bot=SimpleNamespace(username="bot"),
    )

    await start_handler.private_message_handler(update, context)

    assert len(replies) == 1
    assert "请选择要管理的群组" in replies[0][0]
