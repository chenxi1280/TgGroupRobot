from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

from backend.features.invite import invite_link_handler
from backend.features.invite import invite_admin_config_callbacks
from backend.features.invite import invite_user_callbacks
from backend.features.invite.invite_router import InviteRouter
from backend.features.invite.invite_shared import _invite_link_handler
from backend.features.invite.ui.invite_link import invite_link_menu_keyboard


def test_invite_link_menu_keyboard_matches_basic_mode_layout():
    rows = [[button.text for button in row] for row in invite_link_menu_keyboard(-1001, enabled=False, remind_enabled=True).inline_keyboard]
    callbacks = {
        button.text: button.callback_data
        for row in invite_link_menu_keyboard(-1001, enabled=False, remind_enabled=True).inline_keyboard
        for button in row
    }

    assert rows == [
        ["状态:", "启动", "❌ 关闭"],
        ["邀请提醒:", "✅ 启动", "关闭"],
        ["模式:", "中转", "✅ 直接"],
        ["设置封面", "设置文本"],
        ["设置按钮", "👀 预览效果"],
        ["🧹 清零统计", "♻️ 清空链接"],
        ["📤 导出数据"],
        ["🔙 返回"],
    ]
    assert callbacks["🔙 返回"] == "adm:menu:main:-1001"


@pytest.mark.asyncio
async def test_invite_link_show_menu_uses_shared_message_panel(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            invite_link_enabled=True,
            invite_link_notify=False,
            invite_link_mode="relay",
            invite_link_cover_file_id="photo-file-id",
            invite_link_cover_media_type="photo",
            invite_link_text_template="🔗 邀请好友加入 {group}",
            invite_link_buttons=[[{"text": "加入频道", "url": "https://t.me/demo"}]],
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    async def fake_get_link_stats(session, chat_id: int):
        return {"total": 2, "active": 2, "revoked": 0, "expired": 0, "total_members": 3, "total_invites": 3}

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    monkeypatch.setattr("backend.features.invite.invite_shared.get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr("backend.features.invite.invite_shared.get_link_stats", fake_get_link_stats)
    monkeypatch.setattr(_invite_link_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await _invite_link_handler.show_menu(update, context, -1001, "测试群")

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert "🔗 邀请链接生成" in rendered["text"]
    assert "自动生成链接：邀请 或 /link" in rendered["text"]
    assert "查询邀请统计：邀请统计 或 /link_stat" in rendered["text"]
    assert "├当前模式:中转" in rendered["text"]
    assert "├总邀请人数:3" in rendered["text"]
    assert "└已生成数量:2" in rendered["text"]
    assert rows[2] == ["模式:", "✅ 中转", "直接"]
    assert rows[3] == ["✅ 设置封面", "✅ 设置文本"]
    assert rows[4] == ["✅ 设置按钮", "👀 预览效果"]


@pytest.mark.asyncio
async def test_invite_link_empty_list_uses_current_settings_for_keyboard(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            invite_link_enabled=False,
            invite_link_notify=False,
            invite_link_mode="relay",
            invite_link_cover_file_id="photo-file-id",
            invite_link_text_template="邀请模板",
            invite_link_buttons=[[{"text": "官网", "url": "https://example.com"}]],
        )

    async def fake_get_chat_invite_links(session, chat_id: int):
        return []

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    monkeypatch.setattr("backend.features.invite.invite_shared.get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr("backend.features.invite.invite_shared.get_chat_invite_links", fake_get_chat_invite_links)
    monkeypatch.setattr(_invite_link_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await _invite_link_handler.show_list(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows[0] == ["状态:", "启动", "❌ 关闭"]
    assert rows[1] == ["邀请提醒:", "启动", "❌ 关闭"]
    assert rows[2] == ["模式:", "✅ 中转", "直接"]
    assert rows[3] == ["✅ 设置封面", "✅ 设置文本"]
    assert rows[4] == ["✅ 设置按钮", "👀 预览效果"]


@pytest.mark.asyncio
async def test_invite_link_stats_uses_current_settings_for_keyboard(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            invite_link_enabled=False,
            invite_link_notify=True,
            invite_link_mode="relay",
            invite_link_cover_file_id=None,
            invite_link_text_template="邀请模板",
            invite_link_buttons=[],
        )

    async def fake_get_link_stats(session, chat_id: int):
        return {"total": 0, "active": 0, "revoked": 0, "expired": 0, "total_members": 0}

    async def fake_get_invite_leaderboard(session, chat_id: int, limit: int):
        return []

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    monkeypatch.setattr("backend.features.invite.invite_shared.get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr("backend.features.invite.invite_shared.get_link_stats", fake_get_link_stats)
    monkeypatch.setattr("backend.features.invite.services.invite_stats.get_invite_leaderboard", fake_get_invite_leaderboard)
    monkeypatch.setattr(_invite_link_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await _invite_link_handler.show_stats(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert "📊 邀请链接统计" in rendered["text"]
    assert rows[0] == ["状态:", "启动", "❌ 关闭"]
    assert rows[2] == ["模式:", "✅ 中转", "直接"]
    assert rows[3] == ["设置封面", "✅ 设置文本"]


def test_parse_invite_buttons_supports_multi_row_layout():
    rows = invite_link_handler._parse_invite_buttons(
        "关注频道|https://t.me/demo; 联系管理|https://t.me/admin\n官网|https://example.com"
    )

    assert rows == [
        [
            {"text": "关注频道", "url": "https://t.me/demo"},
            {"text": "联系管理", "url": "https://t.me/admin"},
        ],
        [{"text": "官网", "url": "https://example.com"}],
    ]


def test_invite_router_registers_group_text_commands_and_user_menu_callback():
    class _App:
        def __init__(self) -> None:
            self.handlers: list[object] = []

        def add_handler(self, handler, *args, **kwargs) -> None:
            self.handlers.append(handler)

    app = _App()
    InviteRouter().register(app)

    commands = {
        command
        for handler in app.handlers
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }
    message_filters = [
        str(handler.filters)
        for handler in app.handlers
        if isinstance(handler, MessageHandler)
    ]
    callback_patterns = [
        handler.pattern.pattern
        for handler in app.handlers
        if isinstance(handler, CallbackQueryHandler) and handler.pattern is not None
    ]

    assert {"link", "link_stat"} <= commands
    assert any("^邀请$" in item for item in message_filters)
    assert any("^邀请统计$" in item for item in message_filters)
    assert r"^inv:user:menu:\-?\d+$" in callback_patterns


@pytest.mark.asyncio
async def test_invite_link_create_name_keeps_target_chat_in_state(monkeypatch):
    saved: dict[str, object] = {}

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(state_data={"target_chat_id": -1005566})

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved.update(state_data)
        return SimpleNamespace(state_data=state_data)

    monkeypatch.setattr(invite_link_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(invite_link_handler, "set_user_state", fake_set_user_state)

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    replies: list[str] = []

    async def _reply_text(text, reply_markup=None, parse_mode=None):
        replies.append(text)

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="/skip", reply_text=_reply_text),
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=9001, type="private"),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    result = await invite_link_handler.invite_link_create_name_message(update, context)

    assert result == invite_link_handler.WAIT_LIMIT
    assert saved == {"target_chat_id": -1005566, "name": None}
    assert replies
    assert "未命名" in replies[0]


@pytest.mark.asyncio
async def test_invite_link_create_limit_prompt_uses_numeric_duration_ui(monkeypatch):
    saved: dict[str, object] = {}
    replies: list[tuple[str, str | None, object | None]] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(state_data={"target_chat_id": -1005566, "name": "测试链接"})

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved.update(state_data)
        return SimpleNamespace(state_data=state_data)

    monkeypatch.setattr(invite_link_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(invite_link_handler, "set_user_state", fake_set_user_state)

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def _reply_text(text, reply_markup=None, parse_mode=None):
        replies.append((text, parse_mode, reply_markup))

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="12", reply_text=_reply_text),
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=9001, type="private"),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    result = await invite_link_handler.invite_link_create_limit_message(update, context)

    assert result == invite_link_handler.WAIT_EXPIRE
    assert saved["member_limit"] == 12
    assert replies and replies[0][1] == "HTML"
    assert "单位：天" in replies[0][0]
    assert replies[0][2].inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "1"


@pytest.mark.asyncio
async def test_invite_link_create_uses_target_chat_id_from_private_state(monkeypatch):
    replies: list[tuple[str, object]] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(
            state_data={
                "target_chat_id": -1005566,
                "name": "测试链接",
                "member_limit": 3,
                "expire_date": None,
            }
        )

    async def fake_create_invite_link(session, **kwargs):
        assert kwargs["chat_id"] == -1005566
        return SimpleNamespace(
            success=True,
            invite_link=SimpleNamespace(
                invite_link="https://t.me/+demo",
                name="测试链接",
                member_limit=3,
                expire_date=None,
            ),
        )

    async def fake_clear_user_state(session, chat_id: int, user_id: int):
        return None

    monkeypatch.setattr(invite_link_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(invite_link_handler, "create_invite_link", fake_create_invite_link)
    monkeypatch.setattr(invite_link_handler, "clear_user_state", fake_clear_user_state)

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def _reply_text(text, reply_markup=None, parse_mode=None):
        replies.append((text, reply_markup))

    update = SimpleNamespace(
        effective_message=SimpleNamespace(text="/skip", reply_text=_reply_text),
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=9001, type="private"),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=SimpleNamespace())

    result = await invite_link_handler.invite_link_create_expire_message(update, context)

    assert result == -1
    assert replies
    assert "邀请链接创建成功" in replies[0][0]


@pytest.mark.asyncio
async def test_invite_link_buttons_callback_opens_shared_editor(monkeypatch):
    opened: list[object] = []

    async def fake_resolve_target_chat_with_permission_check(update, context, chat_index: int = 2, **kwargs):
        return -1005566

    async def fake_show_layout_menu(update, context, editor_ctx, *, session=None):
        opened.append(editor_ctx)

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    monkeypatch.setattr(
        invite_admin_config_callbacks.PrivateChatContext,
        "resolve_target_chat_with_permission_check",
        fake_resolve_target_chat_with_permission_check,
    )
    monkeypatch.setattr(invite_admin_config_callbacks, "show_layout_menu", fake_show_layout_menu)

    async def _answer():
        return None

    update = SimpleNamespace(
        callback_query=SimpleNamespace(answer=_answer),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await invite_admin_config_callbacks.invite_link_buttons_callback(update, context)

    assert opened
    assert opened[0].module_type == "invite"
    assert opened[0].target_chat_id == -1005566


@pytest.mark.asyncio
async def test_link_command_generates_relay_start_link(monkeypatch):
    replies: list[str] = []
    created: list[dict] = []

    async def fake_ensure_command_enabled(*args, **kwargs):
        return True

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(invite_link_enabled=True, invite_link_mode="relay")

    async def fake_create_user_invite_link(session, bot, chat_id: int, user_id: int, name: str):
        created.append({"chat_id": chat_id, "user_id": user_id, "name": name})
        return True, SimpleNamespace(id=88, invite_link="https://t.me/+real", member_count=0), None

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def _reply_text(text, **kwargs):
        replies.append(text)

    monkeypatch.setattr(invite_user_callbacks, "ensure_command_enabled", fake_ensure_command_enabled)
    monkeypatch.setattr(invite_user_callbacks, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(invite_user_callbacks, "ensure_user", fake_ensure_user)
    monkeypatch.setattr(invite_user_callbacks, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(invite_user_callbacks, "create_user_invite_link", fake_create_user_invite_link)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群"),
        effective_user=SimpleNamespace(id=42, username="tester", first_name="Tester", last_name=None, language_code="zh-CN"),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}), bot=SimpleNamespace(username="DemoBot"))

    await invite_user_callbacks.link_command(update, context)

    assert created == [{"chat_id": -1001, "user_id": 42, "name": "Tester的链接"}]
    assert replies
    assert "https://t.me/DemoBot?start=inv_88" in replies[0]
    assert "模式：中转" in replies[0]


@pytest.mark.asyncio
async def test_link_stat_command_replies_personal_stats(monkeypatch):
    replies: list[str] = []

    async def fake_ensure_command_enabled(*args, **kwargs):
        return True

    async def fake_ensure_chat(*args, **kwargs):
        return None

    async def fake_ensure_user(*args, **kwargs):
        return None

    async def fake_get_user_invite_stats(session, chat_id: int, user_id: int):
        return SimpleNamespace(total_invites=5, links_generated=2, active_links=1)

    async def fake_get_user_rank(session, chat_id: int, user_id: int):
        return 3

    class _Session:
        async def commit(self):
            return None

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    async def _reply_text(text, **kwargs):
        replies.append(text)

    monkeypatch.setattr(invite_user_callbacks, "ensure_command_enabled", fake_ensure_command_enabled)
    monkeypatch.setattr(invite_user_callbacks, "ensure_chat", fake_ensure_chat)
    monkeypatch.setattr(invite_user_callbacks, "ensure_user", fake_ensure_user)
    monkeypatch.setattr("backend.features.invite.services.invite_service.get_user_invite_stats", fake_get_user_invite_stats)
    monkeypatch.setattr("backend.features.invite.services.invite_service.get_user_rank", fake_get_user_rank)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup", title="群"),
        effective_user=SimpleNamespace(id=42, username="tester", first_name="Tester", last_name=None, language_code="zh-CN"),
        effective_message=SimpleNamespace(reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await invite_user_callbacks.link_stat_command(update, context)

    assert replies == [
        "📊 邀请统计\n\n"
        "有效邀请人数：5\n"
        "已生成数量：2\n"
        "活跃链接：1\n"
        "当前排名：第 3 名"
    ]


@pytest.mark.asyncio
async def test_user_invite_menu_callback_returns_to_user_invite_menu(monkeypatch):
    calls: list[tuple[int, int]] = []
    answered: list[bool] = []

    async def fake_show_user_invite_menu(update, context, chat_id: int, user_id: int):
        calls.append((chat_id, user_id))

    async def fake_answer():
        answered.append(True)

    monkeypatch.setattr(invite_user_callbacks, "show_user_invite_menu", fake_show_user_invite_menu)

    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="inv:user:menu:-100123", answer=fake_answer),
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace()

    await invite_user_callbacks.user_invite_menu_callback(update, context)

    assert answered == [True]
    assert calls == [(-100123, 42)]
