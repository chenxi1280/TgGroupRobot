from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.shared.chat_context import PrivateChatContext
from backend.shared.handlers.base import chat_resolver as chat_resolver_module
from backend.shared.handlers.base.chat_resolver import ChatResolver


class _CallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


def _private_update(data: str) -> SimpleNamespace:
    return SimpleNamespace(
        callback_query=_CallbackQuery(data),
        effective_chat=SimpleNamespace(id=42, type="private"),
        effective_user=SimpleNamespace(id=42),
    )


@pytest.mark.asyncio
async def test_chat_resolver_prefers_callback_chat_over_current_chat(monkeypatch) -> None:
    async def fail_current_chat(*args, **kwargs):
        raise AssertionError("explicit callback chat id should not fall back to current chat")

    monkeypatch.setattr(chat_resolver_module, "get_user_current_chat", fail_current_chat)

    update = _private_update("auto_reply:list:-100111:0")
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": object()}))

    assert await ChatResolver.resolve_target_chat(update, context) == -100111


@pytest.mark.asyncio
async def test_private_chat_context_prefers_explicit_callback_chat(monkeypatch) -> None:
    async def fake_is_user_admin(context, chat_id: int, user_id: int):
        return True

    monkeypatch.setattr("backend.shared.chat_context.is_user_admin", fake_is_user_admin)

    update = _private_update("inv:home:-100111")
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": object()}))

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=2,
        allow_fallback_to_current_chat=False,
    )

    assert target_chat_id == -100111


@pytest.mark.asyncio
async def test_private_callback_missing_chat_id_can_disable_current_chat_fallback() -> None:
    update = _private_update("inv:home")
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"db": object()}))

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=2,
        allow_fallback_to_current_chat=False,
        error_message_select_chat="❌ 群组参数无效，请返回重试",
    )

    assert target_chat_id is None
    assert update.callback_query.answers == [("❌ 群组参数无效，请返回重试", True)]
