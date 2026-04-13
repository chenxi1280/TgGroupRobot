from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.publish_service import PublishService


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def delete_message(self, **kwargs):
        self.calls.append(("delete_message", kwargs))

    async def restrict_chat_member(self, **kwargs):
        self.calls.append(("restrict_chat_member", kwargs))

    async def ban_chat_member(self, **kwargs):
        self.calls.append(("ban_chat_member", kwargs))

    async def send_message(self, **kwargs):
        self.calls.append(("send_message", kwargs))
        return SimpleNamespace(message_id=321)

    async def edit_message_text(self, **kwargs):
        self.calls.append(("edit_message_text", kwargs))

    async def pin_chat_message(self, **kwargs):
        self.calls.append(("pin_chat_message", kwargs))

    async def unpin_chat_message(self, **kwargs):
        self.calls.append(("unpin_chat_message", kwargs))

    async def unpin_all_chat_messages(self, **kwargs):
        self.calls.append(("unpin_all_chat_messages", kwargs))


def _context(bot: FakeBot):
    return SimpleNamespace(bot=bot)


@pytest.mark.asyncio
async def test_action_executor_delete() -> None:
    bot = FakeBot()
    result = await ActionExecutor.execute(
        _context(bot),
        action="delete",
        chat_id=-1001,
        user_id=1,
        message_id=99,
    )
    assert result.applied is True
    assert bot.calls[0][0] == "delete_message"


@pytest.mark.asyncio
async def test_action_executor_mute() -> None:
    bot = FakeBot()
    result = await ActionExecutor.execute(
        _context(bot),
        action="mute",
        chat_id=-1001,
        user_id=1,
        mute_seconds=60,
    )
    assert result.applied is True
    assert bot.calls[0][0] == "restrict_chat_member"


@pytest.mark.asyncio
async def test_action_executor_ban() -> None:
    bot = FakeBot()
    result = await ActionExecutor.execute(
        _context(bot),
        action="ban",
        chat_id=-1001,
        user_id=1,
    )
    assert result.applied is True
    assert bot.calls[0][0] == "ban_chat_member"


@pytest.mark.asyncio
async def test_publish_service_send_edit_pin_delete() -> None:
    bot = FakeBot()
    context = _context(bot)

    sent = await PublishService.send(context, chat_id=-1001, text="hello")
    edited = await PublishService.edit(context, chat_id=-1001, message_id=sent.message_id or 0, text="world")
    pinned = await PublishService.pin(context, chat_id=-1001, message_id=sent.message_id or 0)
    deleted = await PublishService.delete(context, chat_id=-1001, message_id=sent.message_id or 0)

    assert sent.message_id == 321
    assert edited.ok is True
    assert pinned.ok is True
    assert deleted.ok is True
    assert [call[0] for call in bot.calls] == [
        "send_message",
        "edit_message_text",
        "pin_chat_message",
        "delete_message",
    ]


@pytest.mark.asyncio
async def test_publish_service_unpin_variants() -> None:
    bot = FakeBot()
    context = _context(bot)

    await PublishService.unpin(context, chat_id=-1001, message_id=12)
    await PublishService.unpin(context, chat_id=-1001, message_id=None)

    assert [call[0] for call in bot.calls] == [
        "unpin_chat_message",
        "unpin_all_chat_messages",
    ]
