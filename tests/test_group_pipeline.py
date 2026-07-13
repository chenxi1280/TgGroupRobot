from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.platform.telegram.group_pipeline import GroupMessageHandler
from backend.shared.errors import BusinessRuleError

EXPECTED_BUSINESS_HANDLER_ORDER = [
    "verification",
    "auction",
    "engagement",
    "game",
    "guess",
    "lottery",
    "solitaire",
    "moderation",
    "points",
]


def _update_context():
    return SimpleNamespace(), SimpleNamespace(), SimpleNamespace(id=-1001), SimpleNamespace(id=42)


def _recording_handler(name: str, calls: list[str], *, result: bool = False):
    async def handler(update, context):
        del update, context
        calls.append(name)
        return result

    return handler


def test_real_group_business_handler_registration_order_matches_contract() -> None:
    names = [name for name, _handler in GroupMessageHandler()._get_business_handlers()]

    assert names == EXPECTED_BUSINESS_HANDLER_ORDER


@pytest.mark.asyncio
async def test_group_message_handler_runs_business_handlers_in_order() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls)
    handler._business_handlers = [
        (name, _recording_handler(name, calls))
        for name in EXPECTED_BUSINESS_HANDLER_ORDER
    ]
    update, context, chat, user = _update_context()

    handled = await handler.handle(update, context, chat, user, "hello")

    assert handled is False
    assert calls == ["core", *EXPECTED_BUSINESS_HANDLER_ORDER]


@pytest.mark.asyncio
async def test_group_message_handler_short_circuits_after_consumed_message() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls)
    handler._business_handlers = [
        ("auction", _recording_handler("auction", calls, result=True)),
        ("engagement", _recording_handler("engagement", calls)),
    ]
    update, context, chat, user = _update_context()

    handled = await handler.handle(update, context, chat, user, "拍卖")

    assert handled is True
    assert calls == ["core", "auction"]


@pytest.mark.asyncio
async def test_business_rule_error_warns_and_continues(monkeypatch) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        "backend.platform.telegram.group_pipeline.log",
        _CaptureLogger(events),
    )
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls)

    async def rejected(update, context):
        del update, context
        calls.append("auction")
        raise BusinessRuleError("未满足业务条件")

    handler._business_handlers = [
        ("auction", rejected),
        ("engagement", _recording_handler("engagement", calls)),
    ]
    update, context, chat, user = _update_context()

    assert await handler.handle(update, context, chat, user, "continue") is False
    assert calls == ["core", "auction", "engagement"]
    assert events[0]["event"] == "group_handler_business_error"
    assert events[0]["error_type"] == "BusinessRuleError"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError("bad"), KeyError("missing"), TypeError("wrong")])
async def test_programming_errors_are_re_raised_and_stop_pipeline(error) -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls)

    async def broken(update, context):
        del update, context
        calls.append("auction")
        raise error

    handler._business_handlers = [
        ("auction", broken),
        ("engagement", _recording_handler("engagement", calls)),
    ]
    update, context, chat, user = _update_context()

    with pytest.raises(type(error)):
        await handler.handle(update, context, chat, user, "stop")

    assert calls == ["core", "auction"]


@pytest.mark.asyncio
async def test_unexpected_error_logs_trace_and_re_raises(monkeypatch) -> None:
    events: list[dict] = []
    monkeypatch.setattr(
        "backend.platform.telegram.group_pipeline.log",
        _CaptureLogger(events),
    )

    async def crash(update, context):
        del update, context
        raise RuntimeError("database connection lost")

    with pytest.raises(RuntimeError, match="database connection lost"):
        await GroupMessageHandler()._safe_execute(
            crash,
            SimpleNamespace(),
            SimpleNamespace(),
            handler_name="db",
        )

    assert events == [{
        "level": "exception",
        "event": "group_handler_failed",
        "handler": "db",
        "error": "database connection lost",
        "error_type": "RuntimeError",
    }]


class _CaptureLogger:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def warning(self, event, **values):
        self._events.append({"level": "warning", "event": event, **values})

    def exception(self, event, **values):
        self._events.append({"level": "exception", "event": event, **values})

    def info(self, event, **values):
        del event, values
