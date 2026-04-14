from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from backend.features.invite import invite_link_handler
from backend.features.invite import invite_admin_config_callbacks
from backend.features.invite.ui.invite_link import invite_link_menu_keyboard


def test_invite_link_menu_keyboard_matches_basic_mode_layout():
    rows = [[button.text for button in row] for row in invite_link_menu_keyboard(-1001, enabled=False, remind_enabled=True).inline_keyboard]

    assert rows == [
        ["⚙️ 状态：", "启动", "❌ 关闭"],
        ["🔔 邀请提醒：", "✅ 启动", "关闭"],
        ["➕ 创建邀请链接", "📋 链接列表"],
        ["中转模式", "✅ 直达模式"],
        ["🖼️ 设置封面", "📝 修改文本"],
        ["⌨️ 按钮设置", "👀 预览效果"],
        ["🧹 清零统计", "♻️ 清空链接"],
        ["📤 导出数据"],
        ["📊 统计"],
        ["🔙 返回"],
    ]


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

    async def fake_resolve_target_chat_with_permission_check(update, context, chat_index: int = 2):
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
