"""P0/P1 hardening: request scope, points concurrency helpers, ops summary shapes."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.platform.runtime.request_scope import (
    bind_request_scope,
    current_scope,
    get_or_load_admin,
    mark_suppress_message_points,
    should_award_message_points,
)
from backend.platform.telegram.group_pipeline import GroupMessageHandler, HandlerResult
from backend.platform.telegram.private_config_handler import PrivateConfigHandler
from backend.shared.services.module_config_service import (
    DEFAULT_PROMPT_FAIL_OPEN,
    verification_prompt_fail_open,
)


@pytest.mark.asyncio
async def test_request_scope_reuses_nested_bind() -> None:
    async with bind_request_scope(update_id=1, chat_id=-100, user_id=42) as outer:
        outer.settings = SimpleNamespace(chat_id=-100)
        async with bind_request_scope(update_id=1, chat_id=-100, user_id=42) as inner:
            assert inner is outer
            assert current_scope() is outer
            assert inner.settings.chat_id == -100


@pytest.mark.asyncio
async def test_admin_cache_hits_once() -> None:
    checker = AsyncMock(return_value=True)
    async with bind_request_scope(chat_id=-1, user_id=7):
        first = await get_or_load_admin(object(), -1, 7, checker=checker)
        second = await get_or_load_admin(object(), -1, 7, checker=checker)
    assert first is True
    assert second is True
    assert checker.await_count == 1


def test_message_points_suppression_flag() -> None:
    assert should_award_message_points() is True


@pytest.mark.asyncio
async def test_message_points_suppression_in_scope() -> None:
    async with bind_request_scope():
        assert should_award_message_points() is True
        mark_suppress_message_points(True)
        assert should_award_message_points() is False


def test_handler_result_from_bool() -> None:
    assert HandlerResult.from_raw(True) == HandlerResult(consumed=True, suppress_points=False)
    assert HandlerResult.from_raw(False) == HandlerResult(consumed=False, suppress_points=False)
    custom = HandlerResult(consumed=True, suppress_points=True)
    assert HandlerResult.from_raw(custom) is custom


@pytest.mark.asyncio
async def test_group_pipeline_awards_points_after_business_consume(monkeypatch) -> None:
    handler = GroupMessageHandler()
    calls: list[str] = []

    async def core(_update, _context):
        return False

    async def business(_update, _context):
        calls.append("business")
        return True  # consume, but do not suppress points by default

    async def points(_update, _context):
        calls.append("points")
        return False

    monkeypatch.setattr(handler, "_get_core_handler", lambda: core)
    monkeypatch.setattr(handler, "_get_business_handlers", lambda: [("biz", business)])
    monkeypatch.setattr(handler, "_get_points_handler", lambda: points)

    async with bind_request_scope(chat_id=-100, user_id=1):
        await handler.handle(
            object(),
            object(),
            SimpleNamespace(id=-100),
            user=SimpleNamespace(id=1),
            message_text="hello",
        )

    assert calls == ["business", "points"]


@pytest.mark.asyncio
async def test_group_pipeline_core_short_circuit_skips_points(monkeypatch) -> None:
    handler = GroupMessageHandler()
    calls: list[str] = []

    async def core(_update, _context):
        return True

    async def points(_update, _context):
        calls.append("points")
        return False

    monkeypatch.setattr(handler, "_get_core_handler", lambda: core)
    monkeypatch.setattr(handler, "_get_business_handlers", lambda: [])
    monkeypatch.setattr(handler, "_get_points_handler", lambda: points)

    async with bind_request_scope(chat_id=-100, user_id=1):
        stopped = await handler.handle(
            object(),
            object(),
            SimpleNamespace(id=-100),
            user=SimpleNamespace(id=1),
            message_text="spam",
        )

    assert stopped is True
    assert calls == []


def test_verification_prompt_fail_open_defaults_true() -> None:
    settings = SimpleNamespace(module_config={})
    assert verification_prompt_fail_open(settings) is DEFAULT_PROMPT_FAIL_OPEN
    settings.module_config = {"verification": {"prompt_fail_open": False}}
    assert verification_prompt_fail_open(settings) is False


@pytest.mark.asyncio
async def test_private_config_error_is_sanitized(monkeypatch) -> None:
    handler = PrivateConfigHandler()
    sent: list[str] = []

    async def fake_send(update, message: str) -> None:
        sent.append(message)

    monkeypatch.setattr(handler, "_send_error_message", fake_send)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("DETAIL_SQL_password=secret")

    await handler._execute_handler(
        boom,
        SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=object()),
        object(),
        session=SimpleNamespace(rollback=AsyncMock()),
        state=SimpleNamespace(state_type="x", chat_id=1),
        message_text="hi",
        state_type="x",
    )
    assert sent == ["配置处理失败，请重试或使用 /cancel 退出"]
