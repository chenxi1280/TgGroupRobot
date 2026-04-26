from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.activity import auction_handler
from backend.features.activity import solitaire_creation_cancel, solitaire_creation_start, solitaire_creation_wizard
from backend.shared.callback_parser import CallbackParser


class _FakeSession:
    async def commit(self):
        return None


class _FakeSessionContext:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def session_factory(self):
        return _FakeSessionContext()


@pytest.mark.asyncio
async def test_guess_deadline_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return None

    async def fake_start_guess_input_state(session, *, user_id: int, chat_id: int, state_type: str, draft: dict):
        started.append((state_type, {"target_chat_id": chat_id, **draft}))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr("backend.features.admin.activity.guess.get_user_state", fake_get_user_state)
    monkeypatch.setattr("backend.features.admin.activity.guess._start_guess_input_state", fake_start_guess_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_guess(
        update,
        context,
        -1001,
        CallbackParser.parse("guess:create:-1001:deadline"),
    )

    assert started and started[0][0] == "guess_wait_deadline"
    assert rendered and rendered[0][2] == "HTML"
    assert "支持两种格式" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "30"


@pytest.mark.asyncio
async def test_guess_step_prompts_use_complete_examples(monkeypatch):
    rendered: list[str] = []
    started: list[tuple[str, dict]] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return None

    async def fake_start_guess_input_state(session, *, user_id: int, chat_id: int, state_type: str, draft: dict):
        started.append((state_type, {"target_chat_id": chat_id, **draft}))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append(text)

    monkeypatch.setattr("backend.features.admin.activity.guess.get_user_state", fake_get_user_state)
    monkeypatch.setattr("backend.features.admin.activity.guess._start_guess_input_state", fake_start_guess_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_guess(
        update,
        context,
        -1001,
        CallbackParser.parse("guess:create:-1001:title"),
    )
    await admin_handler._admin_handler._handle_guess(
        update,
        context,
        -1001,
        CallbackParser.parse("guess:create:-1001:options"),
    )
    await admin_handler._admin_handler._handle_guess(
        update,
        context,
        -1001,
        CallbackParser.parse("guess:settings:-1001:rake_ratio"),
    )

    assert [item[0] for item in started] == ["guess_wait_title", "guess_wait_options", "guess_wait_rake_ratio"]
    assert "本步只输入活动名字" in rendered[0]
    assert "完整示例：世界杯决赛胜负" in rendered[0]
    assert "本步只输入竞猜选项" in rendered[1]
    assert "完整示例：" in rendered[1]
    assert "A:主胜" in rendered[1]
    assert "本步只输入 0 到 1 之间的小数" in rendered[2]
    assert "完整示例：0.1" in rendered[2]


@pytest.mark.asyncio
async def test_new_member_window_prompt_uses_numeric_duration_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, state_type: str, state_data: dict):
        started.append((state_type, state_data))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_new_member_limit(
        update,
        context,
        -1001,
        CallbackParser.parse("adm:nml:-1001:input:window"),
    )

    assert started and started[0][1]["field"] == "window"
    assert rendered and rendered[0][2] == "HTML"
    assert "单位：分钟" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "60"


@pytest.mark.asyncio
async def test_garage_limit_interval_prompt_uses_numeric_duration_ui(monkeypatch):
    rendered: list[tuple[str, object, str | None]] = []
    started: list[tuple[str, dict]] = []

    async def fake_start_text_input_state(context, user_id: int, chat_id: int, state_type: str, state_data: dict):
        started.append((state_type, state_data))

    async def fake_safe_edit(update, text: str, reply_markup=None, parse_mode=None):
        rendered.append((text, reply_markup, parse_mode))

    monkeypatch.setattr(admin_handler._admin_handler, "_start_text_input_state", fake_start_text_input_state)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._handle_garage_auth(
        update,
        context,
        -1001,
        CallbackParser.parse("grg:limit:interval:-1001"),
    )

    assert started and started[0][0] == "garage_limit_interval_input"
    assert rendered and rendered[0][2] == "HTML"
    assert "单位：秒" in rendered[0][0]
    assert rendered[0][1].inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "3600"


@pytest.mark.asyncio
async def test_auction_deadline_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, str, object | None]] = []
    saved_state: list[tuple[str, dict]] = []

    async def fake_get_or_create_setting(session, chat_id: int):
        return SimpleNamespace(enabled=True, create_permission="all", pin_message_enabled=False)

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(state_type="auction_wait_start_price", state_data={"title": "测试拍卖"})

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved_state.append((state_type, state_data))
        return None

    async def fake_reply_text(text: str, parse_mode=None, reply_markup=None):
        rendered.append((text, parse_mode, reply_markup))

    monkeypatch.setattr(auction_handler, "get_or_create_setting", fake_get_or_create_setting)
    monkeypatch.setattr(auction_handler, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(auction_handler, "set_user_state", fake_set_user_state)

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(text="100", caption=None, reply_text=fake_reply_text, reply_to_message=None),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    result = await auction_handler.auction_group_message_handler(update, context)

    assert result is True
    assert saved_state and saved_state[0][0] == "auction_wait_end_at"
    assert rendered and rendered[0][1] == "HTML"
    assert "支持两种格式" in rendered[0][0]
    assert rendered[0][2].inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "30"


@pytest.mark.asyncio
async def test_solitaire_deadline_prompt_uses_unified_copy_ui(monkeypatch):
    rendered: list[tuple[str, str | None, object | None]] = []
    saved_state: list[tuple[str, dict]] = []

    async def fake_get_user_state(session, chat_id: int, user_id: int):
        return SimpleNamespace(state_data={"title": "今晚聚餐"})

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        saved_state.append((state_type, state_data))
        return None

    monkeypatch.setattr(solitaire_creation_wizard, "get_user_state", fake_get_user_state)
    monkeypatch.setattr(solitaire_creation_wizard, "set_user_state", fake_set_user_state)

    async def _reply_text(text: str, parse_mode=None, reply_markup=None):
        rendered.append((text, parse_mode, reply_markup))

    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        effective_message=SimpleNamespace(text="50", reply_text=_reply_text),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    result = await solitaire_creation_wizard.solitaire_create_points_message(update, context)

    assert result == solitaire_creation_wizard.WAIT_DEADLINE
    assert saved_state and saved_state[0][0] == "solitaire_create"
    assert rendered and rendered[0][1] == "HTML"
    assert "本步只输入截止时间" in rendered[0][0]
    assert "完整示例：" in rendered[0][0]
    assert "最近整点示例" in rendered[0][0]
    assert rendered[0][2].inline_keyboard[0][0].to_dict()["copy_text"]["text"]


@pytest.mark.asyncio
async def test_solitaire_batch_config_page_exposes_copyable_deadline(monkeypatch):
    started: list[tuple[int, int, str, dict]] = []

    async def fake_resolve_target_chat_with_permission_check(update, context, chat_index=2, **kwargs):
        return -1005566

    async def fake_set_user_state(session, chat_id: int, user_id: int, state_type: str, state_data: dict):
        started.append((chat_id, user_id, state_type, state_data))
        return None

    monkeypatch.setattr(
        solitaire_creation_start.PrivateChatContext,
        "resolve_target_chat_with_permission_check",
        fake_resolve_target_chat_with_permission_check,
    )
    monkeypatch.setattr(solitaire_creation_start, "set_user_state", fake_set_user_state)

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

    edited: list[tuple[str, str | None, object | None]] = []

    async def _answer():
        return None

    async def _edit_message_text(text, parse_mode=None, reply_markup=None):
        edited.append((text, parse_mode, reply_markup))

    update = SimpleNamespace(
        callback_query=SimpleNamespace(answer=_answer, edit_message_text=_edit_message_text),
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    result = await solitaire_creation_start.solitaire_create_start_callback(update, context)

    assert result == solitaire_creation_start.WAIT_CONFIG
    assert started and started[0][2] == "solitaire_create"
    assert edited and edited[0][1] == "Markdown"
    assert "完整示例：" in edited[0][0]
    assert edited[0][2].inline_keyboard[0][0].to_dict()["copy_text"]["text"]
    button_texts = [button.text for row in edited[0][2].inline_keyboard for button in row]
    callbacks = {
        button.text: button.callback_data
        for row in edited[0][2].inline_keyboard
        for button in row
        if button.callback_data
    }
    assert "🔙 返回上级" in button_texts
    assert "❌ 取消配置" in button_texts
    assert callbacks["🔙 返回上级"] == "adm:menu:solitaire:-1005566"
    assert callbacks["❌ 取消配置"] == "solitaire:cancel:-1005566"


@pytest.mark.asyncio
async def test_solitaire_cancel_returns_to_solitaire_menu_in_private_context(monkeypatch):
    calls: list[tuple[str, int, int | None]] = []
    edited: list[dict[str, object]] = []

    async def fake_clear_user_state(session, chat_id, user_id):
        calls.append(("clear_state", chat_id, user_id))

    monkeypatch.setattr(solitaire_creation_cancel, "clear_user_state", fake_clear_user_state)

    class _Session:
        async def commit(self):
            calls.append(("commit", 0, None))

    class _SessionContext:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Db:
        def session_factory(self):
            return _SessionContext()

    class _Query:
        data = "solitaire:cancel:-1001"

        async def answer(self):
            calls.append(("answer", 0, None))

        async def edit_message_text(self, text, **kwargs):
            edited.append({"text": text, **kwargs})

    update = SimpleNamespace(
        callback_query=_Query(),
        effective_chat=SimpleNamespace(id=9001, type="private"),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _Db()}))

    await solitaire_creation_cancel.solitaire_cancel_callback(update, context)

    assert ("clear_state", 42, 42) in calls
    assert edited and "已返回接龙管理" in edited[-1]["text"]
    callbacks = {
        button.text: button.callback_data
        for row in edited[-1]["reply_markup"].inline_keyboard
        for button in row
    }
    assert callbacks["➕ 创建接龙"] == "sol:create:-1001"
