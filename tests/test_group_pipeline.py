from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.platform.runtime.request_scope import bind_request_scope
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
    handler._points_handler = _recording_handler("points", calls)
    update, context, chat, user = _update_context()

    async with bind_request_scope(chat_id=chat.id, user_id=user.id):
        handled = await handler.handle(update, context, chat, user=user, message_text="hello")

    assert handled is False
    assert calls == ["core", *EXPECTED_BUSINESS_HANDLER_ORDER, "points"]


@pytest.mark.asyncio
async def test_group_message_handler_still_awards_points_after_business_consume() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls)
    handler._business_handlers = [
        ("auction", _recording_handler("auction", calls, result=True)),
        ("engagement", _recording_handler("engagement", calls)),
    ]
    handler._points_handler = _recording_handler("points", calls)
    update, context, chat, user = _update_context()

    async with bind_request_scope(chat_id=chat.id, user_id=user.id):
        handled = await handler.handle(update, context, chat, user=user, message_text="拍卖")

    # 业务消费不再阻断积分旁路；handle 本身返回 False（仅 core 拦截返回 True）
    assert handled is False
    assert calls == ["core", "auction", "points"]


@pytest.mark.asyncio
async def test_core_short_circuit_suppresses_points() -> None:
    calls: list[str] = []
    handler = GroupMessageHandler()
    handler._core_handler = _recording_handler("core", calls, result=True)
    handler._business_handlers = [
        ("auction", _recording_handler("auction", calls)),
    ]
    handler._points_handler = _recording_handler("points", calls)
    update, context, chat, user = _update_context()

    async with bind_request_scope(chat_id=chat.id, user_id=user.id):
        handled = await handler.handle(update, context, chat, user=user, message_text="blocked")

    assert handled is True
    assert calls == ["core"]


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
    handler._points_handler = _recording_handler("points", calls)
    update, context, chat, user = _update_context()

    async with bind_request_scope(chat_id=chat.id, user_id=user.id):
        assert await handler.handle(update, context, chat, user=user, message_text="continue") is False
    assert calls == ["core", "auction", "engagement", "points"]
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
    handler._points_handler = _recording_handler("points", calls)
    update, context, chat, user = _update_context()

    with pytest.raises(type(error)):
        async with bind_request_scope(chat_id=chat.id, user_id=user.id):
            await handler.handle(update, context, chat, user=user, message_text="stop")

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
            default_suppress_on_consume=False,
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

    def debug(self, event, **values):
        del event, values
