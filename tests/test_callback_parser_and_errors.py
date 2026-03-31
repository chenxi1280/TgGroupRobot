from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import (
    answer_callback_query_safely,
    build_public_error_text,
    mark_callback_query_answered,
)


def test_callback_parser_optional_int_success() -> None:
    cb = CallbackParser.parse("adm:menu:-100123:back_to_menu")
    assert cb.get_int_optional(2) == -100123
    assert cb.has_int(2) is True


def test_callback_parser_optional_int_invalid() -> None:
    cb = CallbackParser.parse("adm:menu:back_to_menu")
    assert cb.get_int_optional(2) is None
    assert cb.has_int(2) is False


def test_callback_parser_require_int_raises() -> None:
    cb = CallbackParser.parse("adm:menu:back_to_menu")
    with pytest.raises(ValueError):
        cb.require_int(2, label="chat_id")


def test_build_public_error_text_uses_first_line() -> None:
    error = RuntimeError("第一行错误\n第二行堆栈")
    assert build_public_error_text(error) == "第一行错误"


def test_build_public_error_text_falls_back_for_long_message() -> None:
    error = RuntimeError("x" * 500)
    assert build_public_error_text(error) == "操作失败，请重试"


@pytest.mark.asyncio
async def test_answer_callback_query_safely_truncates_to_fallback() -> None:
    calls: list[tuple[str, bool]] = []

    class FakeCallbackQuery:
        id = "cb-truncate"

        async def answer(self, text: str, show_alert: bool = True) -> None:
            calls.append((text, show_alert))

    update = SimpleNamespace(callback_query=FakeCallbackQuery())
    await answer_callback_query_safely(update, "x" * 500, show_alert=True)

    assert calls == [("操作失败，请重试", True)]


@pytest.mark.asyncio
async def test_answer_callback_query_safely_recovers_from_raise() -> None:
    calls: list[tuple[str, bool]] = []

    class FakeCallbackQuery:
        def __init__(self) -> None:
            self.id = "cb-recover"
            self.count = 0

        async def answer(self, text: str, show_alert: bool = True) -> None:
            self.count += 1
            calls.append((text, show_alert))
            if self.count == 1:
                raise RuntimeError("telegram failed")

    update = SimpleNamespace(callback_query=FakeCallbackQuery())
    await answer_callback_query_safely(update, "短提示", show_alert=False)

    assert calls == [("短提示", False), ("操作失败，请重试", False)]


@pytest.mark.asyncio
async def test_mark_callback_query_answered_prevents_duplicate_answer() -> None:
    calls: list[tuple[str, bool]] = []

    class FakeCallbackQuery:
        id = "cb-marked"

        async def answer(self, text: str, show_alert: bool = True) -> None:
            calls.append((text, show_alert))

    update = SimpleNamespace(callback_query=FakeCallbackQuery())
    mark_callback_query_answered(update)
    await answer_callback_query_safely(update, "不会再次发送", show_alert=True)

    assert calls == []
