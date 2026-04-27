from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.admin_handler import handle_force_subscribe_channel_input
from backend.shared.callback_parser import CallbackParser


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None

    async def flush(self):
        return None


class _Db:
    def __init__(self):
        self.session_factory = lambda: _Session()


@pytest.mark.asyncio
async def test_force_subscribe_menu_shows_action_row(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        force_subscribe_enabled=True,
        force_subscribe_bound_channel_1="@channel_a",
        force_subscribe_bound_channel_2=None,
        force_subscribe_delete_warn_after_seconds=60,
        force_subscribe_guide_text="请先订阅",
        force_subscribe_cover_file_id=None,
        force_subscribe_custom_buttons_enabled=False,
        force_subscribe_buttons=[],
        force_subscribe_not_subscribed_action="warn_only",
        force_subscribe_check_mode="all",
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._show_force_subscribe_menu(update, context, -100123)

    assert rendered
    text, keyboard = rendered[0]
    assert "🚫 未关注时处理: 仅提示关注" in text
    assert "🎯 关注判定: ✅ 全部目标都关注" in text
    assert "📄 提示文案: 请先订阅" in text
    assert "🧩 按钮来源: 跟随绑定目标按钮" in text
    assert keyboard.inline_keyboard[0][0].text == "⚙️ 状态:"
    assert keyboard.inline_keyboard[0][1].text == "✅ 启动"
    assert keyboard.inline_keyboard[3][0].text == "设置封面"
    assert keyboard.inline_keyboard[3][1].text == "✅ 设置文案"
    assert keyboard.inline_keyboard[4][0].text == "设置按钮"
    assert keyboard.inline_keyboard[5][0].text == "⚙️ 关注判定："
    assert keyboard.inline_keyboard[6][0].text == "⚙️ 未关注时处理："
    assert keyboard.inline_keyboard[6][1].text == "仅提示关注"


@pytest.mark.asyncio
async def test_force_subscribe_menu_resolves_link_target_title(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        force_subscribe_enabled=True,
        force_subscribe_bound_channel_1="https://t.me/group_a",
        force_subscribe_bound_channel_2=None,
        force_subscribe_delete_warn_after_seconds=60,
        force_subscribe_guide_text="请先订阅",
        force_subscribe_cover_file_id=None,
        force_subscribe_custom_buttons_enabled=False,
        force_subscribe_buttons=[],
        force_subscribe_not_subscribed_action="warn_only",
        force_subscribe_check_mode="all",
    )

    async def fake_set_current_chat(db, user_id: int, chat_id: int):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    class _Bot:
        async def get_chat(self, *, chat_id):
            assert chat_id == "@group_a"
            return SimpleNamespace(type="supergroup", title="官方群组")

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=7))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())

    await admin_handler._admin_handler._show_force_subscribe_menu(update, context, -100123)

    text, keyboard = rendered[0]
    assert "📡 绑定频道/群组1: 官方群组" in text
    assert keyboard.inline_keyboard[1][1].text == "官方群组"


@pytest.mark.asyncio
async def test_force_subscribe_cycle_action_updates_setting(monkeypatch):
    settings = SimpleNamespace(
        force_subscribe_not_subscribed_action="delete_and_warn",
        force_subscribe_check_mode="all",
    )
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:cycle_action"),
    )

    assert settings.force_subscribe_not_subscribed_action == "delete_only"
    assert shown == [-100123]


@pytest.mark.asyncio
async def test_force_subscribe_cycle_check_mode_updates_setting(monkeypatch):
    settings = SimpleNamespace(force_subscribe_check_mode="all")
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:cycle_check_mode"),
    )

    assert settings.force_subscribe_check_mode == "any"
    assert shown == [-100123]


@pytest.mark.asyncio
async def test_force_subscribe_preview_uses_resolved_channel_buttons(monkeypatch):
    rendered: list[tuple[str, object]] = []
    settings = SimpleNamespace(
        force_subscribe_custom_buttons_enabled=False,
        force_subscribe_buttons=[],
        force_subscribe_bound_channel_1="@channel_a",
        force_subscribe_bound_channel_2="https://t.me/channel_b",
    )

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    class _Bot:
        async def get_chat(self, *, chat_id):
            titles = {
                "@channel_a": "频道 A",
                "@channel_b": "频道 B",
            }
            return SimpleNamespace(type="channel", title=titles[chat_id], username=str(chat_id).lstrip("@"))

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:preview"),
    )

    assert rendered
    text, keyboard = rendered[0]
    assert "预览效果" in text
    assert keyboard.inline_keyboard[0][0].text == "频道 A"
    assert keyboard.inline_keyboard[1][0].text == "频道 B"
    assert keyboard.inline_keyboard[-1][0].callback_data == "adm:menu:forcesub:-100123"


@pytest.mark.asyncio
async def test_force_subscribe_delete_after_opens_selection(monkeypatch):
    settings = SimpleNamespace(force_subscribe_delete_warn_after_seconds=90)
    rendered: list[tuple[str, object]] = []
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_safe_edit(update, text, reply_markup):
        rendered.append((text, reply_markup))

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:cycle_delete_after"),
    )

    assert settings.force_subscribe_delete_warn_after_seconds == 90
    assert shown == []
    text, keyboard = rendered[0]
    assert "请选择提示消息发送后多久自动删除" in text
    assert [button.text for button in keyboard.inline_keyboard[1]] == ["✅ 90秒", "120秒", "300秒"]
    assert keyboard.inline_keyboard[1][0].callback_data == "adm:fs:-100123:delete_after:90"


@pytest.mark.asyncio
async def test_force_subscribe_delete_after_selection_updates_setting(monkeypatch):
    settings = SimpleNamespace(force_subscribe_delete_warn_after_seconds=60)
    shown: list[int] = []

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=1))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await admin_handler._admin_handler._handle_force_subscribe(
        update,
        context,
        -100123,
        CallbackParser.parse("adm:fs:-100123:delete_after:120"),
    )

    assert settings.force_subscribe_delete_warn_after_seconds == 120
    assert shown == [-100123]


@pytest.mark.asyncio
async def test_force_subscribe_buttons_input_accepts_line_format(monkeypatch):
    settings = SimpleNamespace(
        force_subscribe_buttons=[],
        force_subscribe_custom_buttons_enabled=False,
    )
    shown: list[int] = []
    clear_calls: list[tuple[int, int]] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        clear_calls.append((user_id, user_id))

    async def fake_show_force_subscribe_menu(update, context, chat_id: int):
        shown.append(chat_id)

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    from backend.platform.state import state_service
    monkeypatch.setattr(state_service, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(state_service, "clear_private_input_state", fake_clear_private_input_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show_force_subscribe_menu)

    async def _reply_text(*args, **kwargs):
        return None

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=9),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))
    session = _Session()
    state = SimpleNamespace(
        state_type="force_subscribe_buttons_input",
        state_data={"target_chat_id": -100123},
        chat_id=9,
    )

    await handle_force_subscribe_channel_input(
        update,
        context,
        session,
        state,
        "加入频道|https://t.me/channel_a\n联系客服|https://t.me/channel_b",
    )

    assert settings.force_subscribe_custom_buttons_enabled is True
    assert settings.force_subscribe_buttons == [
        [{"text": "加入频道", "url": "https://t.me/channel_a"}],
        [{"text": "联系客服", "url": "https://t.me/channel_b"}],
    ]
    assert shown == [-100123]
    assert clear_calls == [(-100123, 9), (9, 9)]


@pytest.mark.asyncio
async def test_force_subscribe_target_input_validates_accessible_group(monkeypatch):
    settings = SimpleNamespace(force_subscribe_bound_channel_1=None)
    shown: list[int] = []
    clear_calls: list[tuple[int, int]] = []
    bot_calls: list[tuple[str, object]] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_clear_user_state(session, *, chat_id: int, user_id: int):
        clear_calls.append((chat_id, user_id))

    async def fake_clear_private_input_state(session, user_id: int):
        clear_calls.append((user_id, user_id))

    async def fake_show_force_subscribe_menu(update, context, chat_id: int):
        shown.append(chat_id)

    class _Bot:
        id = 777

        async def get_chat(self, *, chat_id):
            bot_calls.append(("get_chat", chat_id))
            return SimpleNamespace(type="supergroup")

        async def get_chat_member(self, *, chat_id, user_id):
            bot_calls.append(("get_chat_member", (chat_id, user_id)))
            return SimpleNamespace(status="administrator")

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    from backend.platform.state import state_service
    monkeypatch.setattr(state_service, "clear_user_state", fake_clear_user_state)
    monkeypatch.setattr(state_service, "clear_private_input_state", fake_clear_private_input_state)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show_force_subscribe_menu)

    async def _reply_text(*args, **kwargs):
        raise AssertionError("valid target should not produce a validation reply")

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=9),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())
    session = _Session()
    state = SimpleNamespace(
        state_type="force_subscribe_channel_1_input",
        state_data={"target_chat_id": -100123},
        chat_id=9,
    )

    await handle_force_subscribe_channel_input(
        update,
        context,
        session,
        state,
        "https://t.me/group_a",
    )

    assert settings.force_subscribe_bound_channel_1 == "https://t.me/group_a"
    assert bot_calls == [
        ("get_chat", "@group_a"),
        ("get_chat_member", ("@group_a", 777)),
    ]
    assert shown == [-100123]
    assert clear_calls == [(-100123, 9), (9, 9)]


@pytest.mark.asyncio
async def test_force_subscribe_target_input_rejects_bot_deep_link(monkeypatch):
    settings = SimpleNamespace(force_subscribe_bound_channel_1="@old_channel")
    replies: list[str] = []
    shown: list[int] = []

    async def fake_require_manage(*args, **kwargs):
        return True, None

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    async def fake_show_force_subscribe_menu(update, context, chat_id: int):
        shown.append(chat_id)

    class _Bot:
        id = 777

        async def get_chat(self, *, chat_id):
            raise AssertionError("bot deep links should be rejected before Telegram lookup")

    monkeypatch.setattr(admin_handler.PermissionPolicyService, "require_manage", fake_require_manage)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_force_subscribe_menu", fake_show_force_subscribe_menu)

    async def _reply_text(text: str, **kwargs):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=9),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=_Bot())
    session = _Session()
    state = SimpleNamespace(
        state_type="force_subscribe_channel_1_input",
        state_data={"target_chat_id": -100123},
        chat_id=9,
    )

    await handle_force_subscribe_channel_input(
        update,
        context,
        session,
        state,
        "https://t.me/demo_bot?start=abc",
    )

    assert settings.force_subscribe_bound_channel_1 == "@old_channel"
    assert replies == ["本期不支持机器人目标，请填写频道或群组的 @用户名、t.me 链接或数字 ID。"]
    assert shown == []
