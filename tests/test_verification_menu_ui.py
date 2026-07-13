from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.features.admin import admin_handler
from backend.features.admin.moderation import (
    verification_home_actions,
    verification_timeout_operations,
    verification_views,
)
from backend.shared.callback_parser import CallbackParser


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDb:
    def __init__(self, session):
        self._session = session

    def session_factory(self):
        return _FakeSessionContext(self._session)


@pytest.mark.asyncio
async def test_verification_menu_shows_timeout_operations_entry(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_set_current_chat(*args, **kwargs):
        return None

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            verification_enabled=True,
            verification_mode="math",
            join_spam_guard_enabled=False,
            join_self_review_enabled=True,
            join_burst_enabled=False,
        )

    async def fake_get_chat_title(db, chat_id: int):
        return "测试群"

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler._admin_handler, "_set_current_chat", fake_set_current_chat)
    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(verification_views, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_get_chat_title", fake_get_chat_title)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_verification_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["🤖 进群验证"],
        ["👻 垃圾拦截"],
        ["🛡️ 进群自助审核"],
        ["🚧 禁止批量进群"],
        ["⚠️ 超时失败任务"],
        ["🔙 返回"],
    ]
    assert "进群验证 - 新人未通过验证则进行限制" in rendered["text"]
    assert "进群验证：简单加减法" in rendered["text"]
    assert "进群自助审核：启动" in rendered["text"]


@pytest.mark.asyncio
async def test_verification_timeout_page_lists_retry_cancel_and_replay_actions(monkeypatch):
    rendered: dict[str, object] = {}
    show = getattr(admin_handler._admin_handler, "_show_verification_timeout_tasks", None)

    assert show is not None

    async def fake_list(session, filters):
        return (
            SimpleNamespace(
                id=7,
                user_id=99,
                status="permanent_failed",
                action="mute",
                attempts=2,
                last_error="telegram_forbidden",
            ),
            SimpleNamespace(
                id=8,
                user_id=100,
                status="uncertain",
                action="kick",
                attempts=1,
                last_error="network",
            ),
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(verification_timeout_operations, "list_timeout_tasks", fake_list)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    await show(update, context, chat_id=-1001)

    callback_rows = [[button.callback_data for button in row] for row in rendered["keyboard"]]
    assert ["adm:vfy_home:-1001:timeouts:retry:7", "adm:vfy_home:-1001:timeouts:cancel:7"] in callback_rows
    assert ["adm:vfy_home:-1001:timeouts:replay:8", "adm:vfy_home:-1001:timeouts:cancel:8"] in callback_rows
    assert "telegram_forbidden" in rendered["text"]


@pytest.mark.asyncio
async def test_verification_rules_menu_uses_three_mutually_exclusive_rules(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            verification_enabled=True,
            verification_mode="math",
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(verification_views, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._show_verification_rules_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["❌ 📄 简单接受条约"],
        ["✅ 🔢 简单加减法"],
        ["❌ 🤐 直接禁言新人"],
        ["🔙 返回"],
    ]
    assert "简单接受条约 - 用户需要点击同意按钮" in rendered["text"]
    assert "只能启用一个验证" in rendered["text"]
    assert "当前启用：简单加减法" in rendered["text"]


@pytest.mark.asyncio
async def test_verification_rule_action_enables_one_rule_without_disabling_self_review(monkeypatch):
    settings = SimpleNamespace(
        verification_enabled=True,
        verification_mode="button",
        join_self_review_enabled=True,
    )

    async def fake_get_chat_settings(session, chat_id: int):
        return settings

    shown: list[tuple[int, str]] = []

    async def fake_show_detail(update, context, chat_id: int, mode: str):
        shown.append((chat_id, mode))

    monkeypatch.setattr(verification_home_actions, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler, "_show_verification_rule_detail", fake_show_detail)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))
    callback_data = CallbackParser.parse("adm:vfy_home:-1001:rule:mute:toggle")

    await admin_handler._admin_handler._handle_verification_home(update, context, -1001, callback_data=callback_data)

    assert settings.verification_enabled is True
    assert settings.verification_mode == "mute"
    assert settings.join_self_review_enabled is True
    assert shown == [(-1001, "mute")]


@pytest.mark.asyncio
async def test_verification_spam_guard_page_shows_live_controls(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            join_spam_guard_enabled=True,
            join_spam_detect_rules_count=3,
            join_spam_send_invalid_msg_enabled=False,
            join_spam_mute_member_enabled=True,
            join_spam_kick_member_enabled=False,
            join_spam_tip_delete_after_seconds=120,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(admin_handler, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    class _FakeDb:
        def session_factory(self):
            return _FakeSessionContext(_FakeSession())

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb()}))

    await admin_handler._admin_handler._show_join_spam_guard_menu(update, context, -1001)

    rows = [[button.text for button in row] for row in rendered["keyboard"]]
    assert rows == [
        ["✅ 状态", "🧪 阈值 3"],
        ["💬 提示 ❌", "🔇 禁言 ✅"],
        ["👢 踢出 ❌", "⏱️ 删除 120s"],
        ["🔙 返回"],
    ]
    assert "📌 状态：✅ 开启" in rendered["text"]


@pytest.mark.asyncio
async def test_self_review_force_subscribe_preview_returns_to_self_review(monkeypatch):
    rendered: dict[str, object] = {}

    async def fake_get_chat_settings(session, chat_id: int):
        return SimpleNamespace(
            force_subscribe_custom_buttons_enabled=False,
            force_subscribe_buttons=[],
            force_subscribe_bound_channel_1="@channel_a",
            force_subscribe_bound_channel_2=None,
        )

    async def fake_safe_edit(update, text, reply_markup):
        rendered["text"] = text
        rendered["keyboard"] = reply_markup.inline_keyboard

    monkeypatch.setattr(verification_home_actions, "get_chat_settings", fake_get_chat_settings)
    monkeypatch.setattr(admin_handler._admin_handler.message_helper, "safe_edit", fake_safe_edit)

    update = SimpleNamespace()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": _FakeDb(_FakeSession())}))

    await admin_handler._admin_handler._handle_join_self_review_action(
        update,
        context,
        -1001,
        action="fs_preview",
        key="",
        db=context.application.bot_data["db"],
    )

    assert "强制关注" in rendered["text"]
    assert rendered["keyboard"][-1][0].callback_data == "adm:vfy_home:-1001:self_review"
