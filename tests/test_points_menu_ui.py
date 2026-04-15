from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import points_config_handler
from backend.features.admin.ui.points import points_config_keyboard, points_rule_keyboard


class _SessionContext:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self):
        self.commits += 1


class _FakeDb:
    def __init__(self, session: _SessionContext) -> None:
        self._session = session

    def session_factory(self):
        return self._session


def _build_settings():
    return SimpleNamespace(
        sign_enabled=True,
        sign_points=5,
        sign_consecutive_days=7,
        sign_consecutive_bonus=10,
        message_points_enabled=False,
        message_points=2,
        message_points_daily_limit=None,
        message_min_length=6,
        invite_points_enabled=False,
        invite_points=3,
        invite_points_daily_limit=20,
        points_display_rule_enabled=True,
        points_speech_rank_enabled=True,
        points_personal_speech_enabled=True,
        points_alias="积分",
        points_rank_alias="积分排行",
    )


def test_points_home_keyboard_matches_doc_style_layout():
    keyboard = points_config_keyboard(_build_settings(), -1001).inline_keyboard
    rows = [[button.text for button in row] for row in keyboard]

    assert rows == [
        ["状态：", "✅ 启动", "关闭"],
        ["展示规则：", "✅ 开启", "关闭"],
        ["发言总排行", "✅ 开启", "关闭"],
        ["个人发言量", "✅ 开启", "关闭"],
        ["⚙️ 签到规则", "⚙️ 发言规则", "⚙️ 邀请规则"],
        ["⚙️ 转让积分", "⚙️ 积分别名", "⚙️ 排行别名"],
        ["➕ 增加积分", "➖ 扣除积分"],
        ["🎁 积分抽奖", "📝 额外规则"],
        ["🧾 导出操作日志", "🗑 清空积分"],
        ["🔙 返回"],
    ]


def test_points_rule_keyboards_keep_existing_real_actions():
    settings = _build_settings()

    checkin_rows = [[button.text for button in row] for row in points_rule_keyboard("checkin", settings, -1001).inline_keyboard]
    speech_rows = [[button.text for button in row] for row in points_rule_keyboard("speech", settings, -1001).inline_keyboard]
    invite_rows = [[button.text for button in row] for row in points_rule_keyboard("invite", settings, -1001).inline_keyboard]

    assert checkin_rows == [
        ["⚙️ 状态：", "✅ 启动", "关闭"],
        ["🎯 设置获得数量"],
        ["🔥 连续奖励"],
        ["🔙 返回"],
    ]
    assert speech_rows == [
        ["⚙️ 状态：", "启动", "✅ 关闭"],
        ["🎯 设置获得数量"],
        ["📈 每日上限"],
        ["🔡 最小字数长度限制"],
        ["🔙 返回"],
    ]
    assert invite_rows == [
        ["⚙️ 状态：", "启动", "✅ 关闭"],
        ["🎯 设置获得数量"],
        ["📈 设置每日上限"],
        ["🔙 返回"],
    ]


@pytest.mark.asyncio
async def test_toggle_all_enabled_updates_three_existing_switches(monkeypatch):
    captured: dict[str, object] = {}
    settings = _build_settings()
    settings.sign_enabled = False
    session = _SessionContext(settings)
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))
    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="pts:toggle:all_enabled:-1001:1"),
        effective_chat=SimpleNamespace(type="private"),
    )

    async def fake_safe_edit(q, text, reply_markup):
        captured["text"] = text
        captured["keyboard"] = reply_markup.inline_keyboard

    async def fake_get_chat_settings(session, chat_id: int):
        return session.settings

    monkeypatch.setattr(points_config_handler, "_safe_edit_message", fake_safe_edit)
    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    await points_config_handler._points_config_handler._handle_toggle(update, context, -1001, "all_enabled")

    assert settings.sign_enabled is True
    assert settings.message_points_enabled is True
    assert settings.invite_points_enabled is True
    assert "配置已更新" in captured["text"]


@pytest.mark.asyncio
async def test_points_config_home_answers_callback_only_once(monkeypatch):
    settings = _build_settings()
    session = _SessionContext(settings)
    answers: list[tuple[str, bool]] = []
    edits: list[tuple[str, dict]] = []
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_answer(text: str = "", show_alert: bool = False):
        answers.append((text, show_alert))

    async def fake_edit_message_text(text, **kwargs):
        edits.append((text, kwargs))

    async def fake_safe_edit(q, text, **kwargs):
        await q.edit_message_text(text, **kwargs)

    async def fake_get_chat_settings(session, chat_id: int):
        return session.settings

    q = SimpleNamespace(answer=fake_answer, edit_message_text=fake_edit_message_text, data="pts:home:-1001")
    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=1),
    )

    monkeypatch.setattr(points_config_handler, "_safe_edit_message", fake_safe_edit)
    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    await points_config_handler._points_config_handler.process(update, context, -1001)

    assert len(answers) == 1
    assert edits
    assert edits[0][0].startswith("💰 主积分")
    assert "群成员签到或发言获得积分" in edits[0][0]


@pytest.mark.asyncio
async def test_points_config_cancel_returns_to_config_page(monkeypatch):
    settings = _build_settings()
    session = _SessionContext(settings)
    callback_query = SimpleNamespace()
    edits: list[tuple[str, object]] = []

    async def fake_edit_message_text(text, reply_markup=None):
        edits.append((text, reply_markup))

    callback_query.edit_message_text = fake_edit_message_text
    context = SimpleNamespace(
        user_data={
            "points_edit_field": "sign_points",
            "points_edit_chat_id": -1001,
        },
        application=SimpleNamespace(bot_data={"db": _FakeDb(session)}),
    )
    update = SimpleNamespace(callback_query=callback_query)

    async def fake_get_chat_settings(session, chat_id: int):
        assert chat_id == -1001
        return session.settings

    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    result = await points_config_handler.points_config_cancel_callback(update, context)

    assert result == points_config_handler.ConversationHandler.END
    assert context.user_data == {}
    assert edits
    assert edits[0][0].startswith("💰 主积分")
    assert "加积分 数字 备注" in edits[0][0]


@pytest.mark.asyncio
async def test_points_view_display_rules_renders_real_page(monkeypatch):
    settings = _build_settings()
    session = _SessionContext(settings)
    edits: list[tuple[str, object]] = []
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}))

    async def fake_edit_message_text(text, **kwargs):
        edits.append((text, kwargs.get("reply_markup")))

    async def fake_get_chat_settings(session, chat_id: int):
        return session.settings

    q = SimpleNamespace(answer=lambda *args, **kwargs: None, edit_message_text=fake_edit_message_text, data="pts:view:display_rules:-1001")
    async def fake_answer(*args, **kwargs):
        return None
    q.answer = fake_answer

    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=1),
    )

    await points_config_handler._points_config_handler.process(update, context, -1001)

    assert edits
    assert "💰 主积分 | 展示规则" in edits[0][0]
    assert "查询指令：积分" in edits[0][0]


@pytest.mark.asyncio
async def test_points_transfer_prompt_uses_real_edit_flow(monkeypatch):
    settings = _build_settings()
    session = _SessionContext(settings)
    edits: list[tuple[str, object]] = []
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(session)}), user_data={})

    async def fake_edit_message_text(text, **kwargs):
        edits.append((text, kwargs.get("reply_markup")))

    async def fake_get_chat_settings(session, chat_id: int):
        return session.settings

    q = SimpleNamespace(answer=lambda *args, **kwargs: None, edit_message_text=fake_edit_message_text, data="pts:edit:transfer:-1001")
    async def fake_answer(*args, **kwargs):
        return None
    q.answer = fake_answer

    monkeypatch.setattr(points_config_handler, "get_chat_settings", fake_get_chat_settings)

    update = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=1),
    )

    result = await points_config_handler._points_config_handler.process(update, context, -1001)

    assert result == points_config_handler.WAIT_VALUE
    assert context.user_data == {"points_edit_field": "transfer", "points_edit_chat_id": -1001}
    assert edits
    assert "请输入转让信息" in edits[0][0]
