from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops import auto_delete_config_handler, auto_delete_handler
from backend.features.group_ops.auto_delete_handler import should_auto_delete_message
from backend.app import bootstrap
from backend.features.admin.ui.auto_delete import auto_delete_config_keyboard


class _Session:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_update(data: str, chat_type: str = "private", user_id: int = 1001):
    calls: dict[str, list] = {"answers": [], "edits": []}

    class _Q:
        def __init__(self) -> None:
            self.data = data

        async def answer(self, *args, **kwargs):
            calls["answers"].append((args, kwargs))

        async def edit_message_text(self, text, **kwargs):
            calls["edits"].append((text, kwargs))

    update = SimpleNamespace(
        callback_query=_Q(),
        effective_chat=SimpleNamespace(type=chat_type),
        effective_user=SimpleNamespace(
            id=user_id,
            username="alice",
            first_name="Alice",
            last_name=None,
            language_code="zh-CN",
        ),
    )
    return update, calls


@pytest.mark.asyncio
async def test_auto_delete_config_rejects_invalid_chat_id_without_fallback(monkeypatch):
    update, calls = _build_update("autodel:set:join:1:bad")
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": object()}))

    async def fake_require_manage(*args, **kwargs):
        raise AssertionError("permission check should not run for invalid callback id")

    async def fake_ensure(*args, **kwargs):
        raise AssertionError("settings should not be touched for invalid callback id")

    monkeypatch.setattr(auto_delete_config_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(auto_delete_config_handler.ModuleSettingsService, "ensure", fake_ensure)

    await auto_delete_config_handler.auto_delete_config_callback(update, context)

    assert len(calls["answers"]) == 1
    assert calls["edits"] == [("无效的群组ID", {})]


@pytest.mark.asyncio
async def test_auto_delete_config_set_updates_settings_and_rerenders(monkeypatch):
    settings = SimpleNamespace(
        auto_delete_enabled=False,
        auto_delete_join=False,
        auto_delete_left=False,
        auto_delete_pinned=False,
        auto_delete_avatar=False,
        auto_delete_title=False,
        auto_delete_anonymous=False,
    )
    session = _Session()
    update, calls = _build_update("autodel:set:join:1:-100123")
    db = SimpleNamespace(session_factory=_SessionFactory(session))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_ensure(*args, **kwargs):
        return settings

    monkeypatch.setattr(auto_delete_config_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(auto_delete_config_handler.ModuleSettingsService, "ensure", fake_ensure)

    await auto_delete_config_handler.auto_delete_config_callback(update, context)

    assert settings.auto_delete_join is True
    assert settings.auto_delete_enabled is True
    assert session.commits == 1
    assert len(calls["edits"]) == 1
    text, kwargs = calls["edits"][0]
    assert "配置已更新" in text
    keyboard = kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == "autodel:noop:join:-100123"
    assert keyboard.inline_keyboard[0][1].callback_data == "autodel:set:join:1:-100123"
    assert keyboard.inline_keyboard[0][2].callback_data == "autodel:set:join:0:-100123"
    assert keyboard.inline_keyboard[-1][0].callback_data == "adm:menu:main:-100123"


@pytest.mark.asyncio
async def test_auto_delete_handler_uses_module_settings_and_deletes_matching_message(monkeypatch):
    settings = SimpleNamespace(
        auto_delete_enabled=True,
        auto_delete_join=True,
        auto_delete_left=False,
        auto_delete_pinned=False,
        auto_delete_anonymous=False,
        auto_delete_title=False,
        auto_delete_avatar=False,
    )
    session = _Session()
    db = SimpleNamespace(session_factory=_SessionFactory(session))
    deleted: list[int] = []

    async def fake_delete():
        deleted.append(1)

    message = SimpleNamespace(
        message_id=10,
        new_chat_members=[SimpleNamespace(id=2)],
        left_chat_member=None,
        pinned_message=None,
        forum_topic_created=None,
        forum_topic_edited=None,
        forum_topic_closed=None,
        general_forum_topic_hidden=None,
        users_shared=None,
        chat_shared=None,
        is_automatic_forward=False,
        successful_payment=None,
        connected_website=None,
        proximity_alert_triggered=None,
        video_chat_scheduled=None,
        video_chat_ended=None,
        video_chat_participants_invited=None,
        from_user=SimpleNamespace(is_bot=False, username=None, id=1087968824),
        new_chat_title=None,
        new_chat_photo=None,
        delete_chat_photo=None,
        delete=fake_delete,
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="Group"),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))

    async def fake_ensure(*args, **kwargs):
        return settings

    monkeypatch.setattr(auto_delete_handler.ModuleSettingsService, "ensure", fake_ensure)

    await auto_delete_handler.auto_delete_handler(update, context)

    assert deleted == [1]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_auto_delete_handler_records_left_member_even_when_auto_delete_disabled(monkeypatch):
    settings = SimpleNamespace(
        auto_delete_enabled=False,
        auto_delete_join=False,
        auto_delete_left=False,
        auto_delete_pinned=False,
        auto_delete_anonymous=False,
        auto_delete_title=False,
        auto_delete_avatar=False,
    )
    session = _Session()
    db = SimpleNamespace(session_factory=_SessionFactory(session))
    recorded: list[int] = []

    message = SimpleNamespace(
        message_id=10,
        new_chat_members=None,
        left_chat_member=SimpleNamespace(id=2),
    )
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="Group"),
        effective_message=message,
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db}))

    async def fake_ensure(*args, **kwargs):
        return settings

    async def fake_record(session_arg, chat_id: int):
        assert session_arg is session
        recorded.append(chat_id)

    monkeypatch.setattr(auto_delete_handler.ModuleSettingsService, "ensure", fake_ensure)
    monkeypatch.setattr(auto_delete_handler, "record_group_leave_event", fake_record)

    await auto_delete_handler.auto_delete_handler(update, context)

    assert recorded == [-100123]
    assert session.commits == 1


def test_auto_delete_keyboard_matches_document_layout():
    settings = SimpleNamespace(
        auto_delete_enabled=False,
        auto_delete_join=True,
        auto_delete_left=False,
        auto_delete_pinned=True,
        auto_delete_avatar=False,
        auto_delete_title=True,
        auto_delete_anonymous=False,
    )

    keyboard = auto_delete_config_keyboard(settings, -100123)

    assert keyboard.inline_keyboard[0][0].text == "进群消息："
    assert keyboard.inline_keyboard[0][0].callback_data == "autodel:noop:join:-100123"
    assert keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert keyboard.inline_keyboard[0][2].text == "关闭"
    assert keyboard.inline_keyboard[2][0].callback_data == "autodel:noop:pinned:-100123"
    assert keyboard.inline_keyboard[-1][0].callback_data == "adm:menu:main:-100123"


def _all_delete_settings(**overrides):
    data = {
        "auto_delete_enabled": True,
        "auto_delete_join": True,
        "auto_delete_left": True,
        "auto_delete_pinned": True,
        "auto_delete_avatar": True,
        "auto_delete_title": True,
        "auto_delete_anonymous": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _group_update(message):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100123, type="supergroup", title="Group"),
        effective_message=message,
    )


@pytest.mark.parametrize(
    ("field", "settings_attr"),
    [
        ("new_chat_members", "auto_delete_join"),
        ("left_chat_member", "auto_delete_left"),
        ("pinned_message", "auto_delete_pinned"),
        ("new_chat_title", "auto_delete_title"),
        ("new_chat_photo", "auto_delete_avatar"),
        ("delete_chat_photo", "auto_delete_avatar"),
    ],
)
def test_auto_delete_each_ui_switch_has_runtime_match(field, settings_attr):
    overrides = {
        "auto_delete_join": False,
        "auto_delete_left": False,
        "auto_delete_pinned": False,
        "auto_delete_avatar": False,
        "auto_delete_title": False,
        "auto_delete_anonymous": False,
    }
    overrides[settings_attr] = True
    settings = _all_delete_settings(**overrides)
    message = SimpleNamespace(**{field: object()})

    assert should_auto_delete_message(settings, _group_update(message), message) is True


def test_auto_delete_anonymous_admin_runtime_match():
    settings = _all_delete_settings(
        auto_delete_join=False,
        auto_delete_left=False,
        auto_delete_pinned=False,
        auto_delete_avatar=False,
        auto_delete_title=False,
        auto_delete_anonymous=True,
    )
    message = SimpleNamespace(from_user=SimpleNamespace(id=1087968824))

    assert should_auto_delete_message(settings, _group_update(message), message) is True


def test_auto_delete_all_switches_cover_extra_system_prompts():
    settings = _all_delete_settings()
    message = SimpleNamespace(forum_topic_created=object())

    assert should_auto_delete_message(settings, _group_update(message), message) is True


def test_auto_delete_partial_switches_do_not_delete_unmapped_system_prompts():
    settings = _all_delete_settings(auto_delete_anonymous=False)
    message = SimpleNamespace(forum_topic_created=object())

    assert should_auto_delete_message(settings, _group_update(message), message) is False


def test_auto_delete_handler_registered_before_moderation_stoppers(monkeypatch):
    registrations: list[tuple[object, int]] = []

    class _App:
        def add_handler(self, handler, group=0):
            registrations.append((handler, group))

    monkeypatch.setattr(bootstrap, "register_feature_routers", lambda app: None)
    bootstrap._register_common_handlers(_App())

    auto_delete_groups = [
        group
        for handler, group in registrations
        if getattr(handler, "callback", None) is auto_delete_handler.auto_delete_handler
    ]
    assert auto_delete_groups == [-4]
