from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.platform.db.schema.models.core import ConversationState
from backend.platform.db.schema.models.enums import ConversationStateType
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.platform.state.conversation_state_service import ConversationStateService, clear_private_input_state


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


def test_state_type_values_fit_db_column() -> None:
    from backend.platform.telegram.private_config_registry import build_private_config_handlers

    max_length = 32
    candidates: dict[str, set[str]] = {}

    def add(source: str, value: str) -> None:
        candidates.setdefault(value, set()).add(source)

    for item in ConversationStateType:
        add(f"ConversationStateType.{item.name}", item.value)

    for state_name in build_private_config_handlers():
        add("private_config_registry", state_name)

    for path in Path("backend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                if (
                    value.endswith("_input")
                    and not value.startswith(("handle_", "parse_"))
                    and "." not in value
                    and "\n" not in value
                ):
                    add(f"{path}:{node.lineno}", value)

    too_long = {
        value: sorted(sources)
        for value, sources in sorted(candidates.items())
        if len(value) > max_length
    }

    assert too_long == {}


def test_teacher_search_attendance_states_registered_for_private_input() -> None:
    from backend.platform.telegram.private_config_registry import build_private_config_handlers

    handlers = build_private_config_handlers()

    assert ConversationStateType.teacher_search_attendance_target_input.value in handlers
    assert ConversationStateType.teacher_search_attendance_open_input.value in handlers
    assert ConversationStateType.teacher_search_attendance_full_input.value in handlers
    assert ConversationStateType.teacher_search_attendance_rest_input.value in handlers


@pytest.mark.asyncio
async def test_clear_private_input_state_preserves_selected_chat(monkeypatch):
    calls: list[tuple] = []
    state = SimpleNamespace(state_type="selected_chat")

    async def fake_get(session, chat_id: int, user_id: int):
        calls.append(("get", chat_id, user_id))
        return state

    async def fake_clear(session, chat_id: int, user_id: int):
        calls.append(("clear", chat_id, user_id))

    monkeypatch.setattr(ConversationStateService, "get", fake_get)
    monkeypatch.setattr(ConversationStateService, "clear", fake_clear)

    await clear_private_input_state(object(), 42)

    assert calls == [("get", 42, 42)]


@pytest.mark.asyncio
async def test_clear_private_input_state_clears_real_input_state(monkeypatch):
    calls: list[tuple] = []
    state = SimpleNamespace(state_type="teacher_delegate_target_input")

    async def fake_get(session, chat_id: int, user_id: int):
        calls.append(("get", chat_id, user_id))
        return state

    async def fake_clear(session, chat_id: int, user_id: int):
        calls.append(("clear", chat_id, user_id))

    monkeypatch.setattr(ConversationStateService, "get", fake_get)
    monkeypatch.setattr(ConversationStateService, "clear", fake_clear)

    await clear_private_input_state(object(), 42)

    assert calls == [("get", 42, 42), ("clear", 42, 42)]


@pytest.mark.asyncio
async def test_start_text_input_state_preserves_private_selected_chat(monkeypatch):
    from backend.features.admin.moderation.state import ModerationStateMixin

    calls: list[tuple] = []

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            calls.append(("commit",))

    class _Db:
        def session_factory(self):
            return _Session()

    class _Handler(ModerationStateMixin):
        pass

    async def fake_clear_user_state(session, chat_id: int, user_id: int):
        calls.append(("clear", chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        calls.append(("clear_private_input", user_id))

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        calls.append(("set", chat_id, user_id, state_type, state_data))

    monkeypatch.setattr("backend.platform.state.state_service.clear_user_state", fake_clear_user_state)
    monkeypatch.setattr("backend.platform.state.state_service.clear_private_input_state", fake_clear_private_input_state)
    monkeypatch.setattr("backend.platform.state.state_service.set_user_state", fake_set_user_state)

    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await _Handler()._start_text_input_state(
        context,
        42,
        -1001,
        "teacher_delegate_target_input",
        {"target_chat_id": -1001},
    )

    assert ("clear", 42, 42) not in calls
    assert calls == [
        ("clear", -1001, 42),
        ("clear_private_input", 42),
        ("set", -1001, 42, "teacher_delegate_target_input", {"target_chat_id": -1001}),
        ("commit",),
    ]


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
