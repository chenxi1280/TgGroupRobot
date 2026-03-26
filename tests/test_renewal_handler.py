from __future__ import annotations

from types import SimpleNamespace

import pytest

import bot.handlers.renewal_handler as renewal_handler
from bot.keyboards.integration.renewal import renewal_entry_keyboard


def test_renewal_keyboard_uses_url_when_contact_username_present() -> None:
    keyboard = renewal_entry_keyboard(
        -100123,
        contact_username="seller_name",
        contact_label="一键联系",
    )
    assert keyboard.inline_keyboard[0][0].url == "https://t.me/seller_name"
    assert keyboard.inline_keyboard[-1][0].callback_data == "renew:back:-100123"


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

    monkeypatch.setattr(renewal_handler.ConversationStateService, "clear", fake_clear)
    monkeypatch.setattr(renewal_handler, "_show_menu", fake_show)

    await renewal_handler.renewal_code_message_handler(update, context, object(), state, "ABC123")

    assert calls == [(-1001, 42)]
    assert shown == [-1001]
    assert replies == [("卡密核销功能尚未接入，本轮已先保留续费入口和联系购买流程。", {})]


def _async_collector(storage: list[tuple[str, dict]] | None = None):
    storage = storage if storage is not None else []

    async def _reply(text, **kwargs):
        storage.append((text, kwargs))

    _reply.calls = storage  # type: ignore[attr-defined]
    return _reply
