from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.platform.telegram.group_pipeline import GroupMessageHandler


EXPECTED_BUSINESS_HANDLER_ORDER = [
    "auction",
    "engagement",
    "game",
    "guess",
    "verification",
    "lottery",
    "solitaire",
    "moderation",
    "points",
]


def _update_context():
    return (
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(id=-1001),
        SimpleNamespace(id=42),
    )


def _recording_handler(name: str, calls: list[str], *, result: bool = False):
    async def handler(update, context):
        del update, context
        calls.append(name)
        return result

    return handler


@pytest.mark.asyncio
async def test_group_message_handler_runs_business_handlers_in_expected_order() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls, result=False)
    handler._business_handlers = [
        (name, _recording_handler(name, calls))
        for name in EXPECTED_BUSINESS_HANDLER_ORDER
    ]
    update, context, chat, user = _update_context()

    handled = await handler.handle(update, context, chat, user, "hello")

    assert handled is False
    assert calls == ["core", *EXPECTED_BUSINESS_HANDLER_ORDER]


@pytest.mark.asyncio
async def test_group_message_handler_short_circuits_after_core_handler() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls, result=True)

    async def forbidden_handler(update, context):
        del update, context
        raise AssertionError("business handlers must not run after core short-circuit")

    handler._business_handlers = [("auction", forbidden_handler)]
    update, context, chat, user = _update_context()

    handled = await handler.handle(update, context, chat, user, "blocked")

    assert handled is True
    assert calls == ["core"]


@pytest.mark.asyncio
async def test_group_message_handler_continues_after_business_handler_error() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls, result=False)

    async def broken_handler(update, context):
        del update, context
        calls.append("auction")
        raise RuntimeError("boom")

    handler._business_handlers = [
        ("auction", broken_handler),
        ("engagement", _recording_handler("engagement", calls)),
    ]
    update, context, chat, user = _update_context()

    handled = await handler.handle(update, context, chat, user, "still runs")

    assert handled is False
    assert calls == ["core", "auction", "engagement"]
