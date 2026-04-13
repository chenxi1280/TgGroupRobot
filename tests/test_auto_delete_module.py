from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.group_ops import auto_delete_config_handler, auto_delete_handler
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
