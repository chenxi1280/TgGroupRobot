from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.platform.db.schema.models.core import ConversationState
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.platform.state.conversation_state_service import ConversationStateService


class DummySession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = 0

    def add(self, entity: object) -> None:
        self.added.append(entity)

    async def flush(self) -> None:
        self.flushed += 1

    async def delete(self, entity: object) -> None:
        self.deleted.append(entity)


@pytest.mark.asyncio
async def test_module_settings_service_ensure_creates_chat_user_and_settings(monkeypatch):
    session = DummySession()
    calls: list[tuple] = []

    async def fake_get_by_id(*args, **kwargs):
        calls.append(("get_by_id", args[1].__name__, args[2]))
        return None

    async def fake_update(*args, **kwargs):
        calls.append(("update", args[1].__class__.__name__, args[2]))
        return args[1]

    async def fake_get_by_filters(*args, **kwargs):
        calls.append(("get_by_filters", args[1].__name__, args[2]))
        return None

    async def fake_ensure_user(*args, **kwargs):
        calls.append(("ensure_user", kwargs["user_id"]))
        return SimpleNamespace(id=kwargs["user_id"])

    monkeypatch.setattr("backend.shared.services.module_settings_service.ServiceBase._get_by_id", fake_get_by_id)
    monkeypatch.setattr("backend.shared.services.module_settings_service.ServiceBase._update_entity", fake_update)
    monkeypatch.setattr("backend.shared.services.module_settings_service.ServiceBase._get_by_filters", fake_get_by_filters)
    monkeypatch.setattr("backend.shared.services.module_settings_service.ensure_user", fake_ensure_user)

    settings = await ModuleSettingsService.ensure(
        session,
        chat_id=-1001,
        chat_type="supergroup",
        title="Group A",
        user_id=42,
        username="alice",
    )

    assert settings.chat_id == -1001
    assert ("ensure_user", 42) in calls
    assert any(item[0] == "get_by_filters" for item in calls)
    assert any(item.__class__.__name__ == "TgChat" for item in session.added)
    assert any(item.__class__.__name__ == "ChatSettings" for item in session.added)
    assert session.flushed >= 2


@pytest.mark.asyncio
async def test_module_settings_service_ensure_chat_zero_is_compat_only(monkeypatch):
    session = DummySession()

    async def fake_get_by_id(*args, **kwargs):
        raise AssertionError("chat_id=0 should not hit storage")

    async def fake_get_by_filters(*args, **kwargs):
        raise AssertionError("chat_id=0 should not hit storage")

    monkeypatch.setattr("backend.shared.services.module_settings_service.ServiceBase._get_by_id", fake_get_by_id)
    monkeypatch.setattr("backend.shared.services.module_settings_service.ServiceBase._get_by_filters", fake_get_by_filters)

    settings = await ModuleSettingsService.ensure(session, chat_id=0)

    assert settings.chat_id == 0
    assert session.added == []
    assert session.flushed == 0


@pytest.mark.asyncio
async def test_conversation_state_service_start_update_get_clear(monkeypatch):
    session = DummySession()
    lookup = {"state": None}

    async def fake_ensure_user(*args, **kwargs):
        return SimpleNamespace(id=kwargs["user_id"])

    async def fake_module_ensure(*args, **kwargs):
        return SimpleNamespace(chat_id=kwargs["chat_id"])

    async def fake_get(*args, **kwargs):
        return lookup["state"]

    async def fake_update(*args, **kwargs):
        entity = args[1]
        updates = args[2]
        for key, value in updates.items():
            setattr(entity, key, value)
        return entity

    async def fake_delete(*args, **kwargs):
        lookup["state"] = None
        return True

    monkeypatch.setattr("backend.platform.state.conversation_state_service.ensure_user", fake_ensure_user)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ModuleSettingsService.ensure", fake_module_ensure)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ServiceBase._get_by_filters", fake_get)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ServiceBase._update_entity", fake_update)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ServiceBase._delete_entity", fake_delete)

    created = await ConversationStateService.start(session, -1001, 42, "state_a", {"a": 1})
    lookup["state"] = created

    assert created.state_type == "state_a"
    assert created.state_data == {"a": 1}
    assert any(item.__class__.__name__ == "ConversationState" for item in session.added)

    updated = await ConversationStateService.update(session, -1001, 42, state_data={"b": 2})
    assert updated is created
    assert updated.state_data == {"a": 1, "b": 2}

    replaced = await ConversationStateService.update(
        session,
        -1001,
        42,
        state_type="state_b",
        state_data={"c": 3},
        merge=False,
    )
    assert replaced is created
    assert replaced.state_type == "state_b"
    assert replaced.state_data == {"c": 3}

    fetched = await ConversationStateService.get(session, -1001, 42)
    assert fetched is created

    await ConversationStateService.clear(session, -1001, 42)
    assert lookup["state"] is None


@pytest.mark.asyncio
async def test_legacy_state_wrappers_delegate(monkeypatch):
    session = DummySession()
    state = ConversationState(chat_id=-1001, user_id=42, state_type="x", state_data={})

    async def fake_start(*args, **kwargs):
        return state

    async def fake_get(*args, **kwargs):
        return state

    async def fake_clear(*args, **kwargs):
        return None

    monkeypatch.setattr("backend.platform.state.conversation_state_service.ConversationStateService.start", fake_start)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ConversationStateService.get", fake_get)
    monkeypatch.setattr("backend.platform.state.conversation_state_service.ConversationStateService.clear", fake_clear)

    assert await ConversationStateService.start(session, -1001, 42, "x") is state
    assert await ConversationStateService.get(session, -1001, 42) is state
    assert await ConversationStateService.clear(session, -1001, 42) is None
