from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.handlers.renewal_handler as renewal_handler
from bot.keyboards.integration.renewal import renewal_entry_keyboard
from bot.services.integration.renewal_service import calculate_new_expire_at, hash_card_code


def test_renewal_keyboard_uses_url_when_contact_username_present() -> None:
    keyboard = renewal_entry_keyboard(
        -100123,
        contact_username="seller_name",
        contact_label="一键联系",
    )
    assert keyboard.inline_keyboard[0][0].url == "https://t.me/seller_name"
    assert keyboard.inline_keyboard[-1][0].callback_data == "renew:back:-100123"


def test_renewal_keyboard_falls_back_to_contact_callback_when_missing_config() -> None:
    keyboard = renewal_entry_keyboard(
        -100123,
        contact_username=None,
        contact_url=None,
    )

    assert keyboard.inline_keyboard[0][0].text == "📞 未配置联系入口"
    assert keyboard.inline_keyboard[0][0].callback_data == "renew:contact:-100123"


@pytest.mark.asyncio
async def test_renew_command_in_private_requires_selected_chat(monkeypatch) -> None:
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(type="private"),
        effective_user=SimpleNamespace(id=1),
        effective_message=SimpleNamespace(reply_text=_async_collector()),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": object()}))

    async def fake_get_user_current_chat(db, user_id):
        return None

    monkeypatch.setattr(renewal_handler, "get_user_current_chat", fake_get_user_current_chat)

    await renewal_handler.renew_command(update, context)
    assert update.effective_message.reply_text.calls == [("请先在私聊中选择要管理的群组。", {})]


@pytest.mark.asyncio
async def test_renew_callback_contact_without_config_shows_alert(monkeypatch) -> None:
    alerts: list[tuple[str, bool]] = []

    async def fake_answer(update, text, show_alert=False):
        alerts.append((text, show_alert))

    monkeypatch.setattr(renewal_handler, "answer_callback_query_safely", fake_answer)
    monkeypatch.setattr(
        renewal_handler,
        "get_settings",
        lambda: SimpleNamespace(renew_contact_username=None, renew_contact_label=None, renewal_contact_url=None),
    )

    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="renew:contact:-100123"),
        effective_user=SimpleNamespace(id=1),
    )
    context = SimpleNamespace(application=SimpleNamespace(bot_data={}))

    await renewal_handler.renew_callback(update, context)

    assert alerts == [("未配置联系入口", True)]


@pytest.mark.asyncio
async def test_renewal_code_message_handler_clears_state_and_redisplays(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    shown: list[int] = []
    replies: list[tuple[str, dict]] = []

    update = SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=_async_collector(replies)),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace()
    state = SimpleNamespace(chat_id=-1001, state_data={"target_chat_id": -1001})

    async def fake_clear(session, chat_id, user_id):
        calls.append((chat_id, user_id))

    async def fake_show(update, context, *, chat_id):
        shown.append(chat_id)

    async def fake_redeem(session, *, chat_id, operator_user_id, card_code):
        assert chat_id == -1001
        assert operator_user_id == 42
        assert card_code == "ABC123"
        return SimpleNamespace(success=True, message="续费成功，到期时间已更新为：2026-04-25 12:00")

    monkeypatch.setattr(renewal_handler.ConversationStateService, "clear", fake_clear)
    monkeypatch.setattr(renewal_handler, "_show_menu", fake_show)
    monkeypatch.setattr(renewal_handler, "redeem_renewal_card", fake_redeem)

    await renewal_handler.renewal_code_message_handler(update, context, object(), state, "ABC123")

    assert calls == [(-1001, 42)]
    assert shown == [-1001]
    assert replies == [("✅ 续费成功，到期时间已更新为：2026-04-25 12:00", {})]


@pytest.mark.asyncio
async def test_renewal_code_message_handler_reports_failure_reason(monkeypatch) -> None:
    replies: list[tuple[str, dict]] = []
    shown: list[int] = []
    clears: list[tuple[int, int]] = []

    update = SimpleNamespace(
        effective_message=SimpleNamespace(reply_text=_async_collector(replies)),
        effective_user=SimpleNamespace(id=42),
    )
    context = SimpleNamespace()
    state = SimpleNamespace(chat_id=-1001, state_data={"target_chat_id": -1001})

    async def fake_clear(session, chat_id, user_id):
        clears.append((chat_id, user_id))

    async def fake_show(update, context, *, chat_id):
        shown.append(chat_id)

    async def fake_redeem(session, *, chat_id, operator_user_id, card_code):
        return SimpleNamespace(success=False, message="卡密已使用")

    monkeypatch.setattr(renewal_handler.ConversationStateService, "clear", fake_clear)
    monkeypatch.setattr(renewal_handler, "_show_menu", fake_show)
    monkeypatch.setattr(renewal_handler, "redeem_renewal_card", fake_redeem)

    await renewal_handler.renewal_code_message_handler(update, context, object(), state, "ABC123")

    assert clears == []
    assert shown == [-1001]
    assert replies == [("❌ 卡密已使用", {})]


def test_hash_card_code_is_case_insensitive() -> None:
    assert hash_card_code(" abc123 ") == hash_card_code("ABC123")


def test_calculate_new_expire_at_extends_from_future_end_at() -> None:
    import datetime as dt

    now = dt.datetime(2026, 3, 26, 12, 0, tzinfo=dt.UTC)
    current_end_at = dt.datetime(2026, 3, 30, 12, 0, tzinfo=dt.UTC)

    renewed = calculate_new_expire_at(
        current_end_at,
        duration_seconds=86400,
        now=now,
    )

    assert renewed == dt.datetime(2026, 3, 31, 12, 0, tzinfo=dt.UTC)


def _async_collector(storage: list[tuple[str, dict]] | None = None):
    storage = storage if storage is not None else []

    async def _reply(text, **kwargs):
        storage.append((text, kwargs))

    _reply.calls = storage  # type: ignore[attr-defined]
    return _reply
