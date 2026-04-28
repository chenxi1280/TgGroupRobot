from __future__ import annotations

import pytest

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.automation.ui.scheduled_message_edit import sm_repeat_keyboard
from backend.shared.services.base import ValidationError
from backend.shared.time_ui import (
    build_back_keyboard,
    build_copy_time_keyboard,
    build_datetime_prompt_text,
    build_interval_keyboard,
    next_top_of_hour,
)


def test_next_top_of_hour_rounds_up_in_local_timezone() -> None:
    import datetime as dt

    now = dt.datetime(2026, 4, 14, 1, 26, tzinfo=dt.UTC)
    rounded = next_top_of_hour(now)

    assert rounded == dt.datetime(2026, 4, 14, 2, 0, tzinfo=dt.UTC)


def test_build_datetime_prompt_text_supports_tg_time_without_copy_hint() -> None:
    text = build_datetime_prompt_text(
        title="🎠 轮播消息 | 编辑开始时间",
        sample_time_text="2026-04-14 10:00",
        sample_time_unix=1_776_124_800,
        show_copy_hint=False,
        input_hint="👉🏻 现在输入定时开始时间:",
        extra_tips=["发送 /clear 可清空开始时间"],
    )

    assert "最近整点示例" in text
    assert '<tg-time unix="1776124800" format="wDT">2026-04-14 10:00</tg-time>' in text
    assert "点击下方蓝色按钮可直接复制" not in text
    assert "发送 /clear 可清空开始时间" in text


def test_build_back_keyboard_only_contains_return_button() -> None:
    keyboard = build_back_keyboard("sm:open:-1001:abcd")

    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].text == "🔙 返回"
    assert keyboard.inline_keyboard[0][0].callback_data == "sm:open:-1001:abcd"


def test_build_copy_time_keyboard_uses_copy_text_payload() -> None:
    keyboard = build_copy_time_keyboard("sm:open:-1001:abcd", "2026-04-14 10:00")

    assert keyboard.inline_keyboard[0][0].to_dict()["copy_text"]["text"] == "2026-04-14 10:00"


def test_build_interval_keyboard_highlights_current_value() -> None:
    keyboard = build_interval_keyboard(
        current_minutes=120,
        option_rows=[[10, 15, 20, 30], [60, 120, 180, 240]],
        callback_factory=lambda value: f"test:{value}",
        back_callback="back",
    )

    assert keyboard.inline_keyboard[1][1].text == "✅ 2小时"


def test_scheduled_message_repeat_keyboard_matches_unified_time_style() -> None:
    keyboard = sm_repeat_keyboard(-1001, "abcd1234", 120)

    assert keyboard.inline_keyboard[0][0].text == "10分钟"
    assert keyboard.inline_keyboard[1][1].text == "✅ 2小时"
    assert keyboard.inline_keyboard[-1][0].text == "🔙 返回"


def test_scheduled_message_end_at_must_be_future() -> None:
    import datetime as dt

    future_end_at = int(dt.datetime(2099, 1, 1, tzinfo=dt.UTC).timestamp())
    ScheduledMessageService.validate_future_end_at(future_end_at)

    past_end_at = int(dt.datetime(2000, 1, 1, tzinfo=dt.UTC).timestamp())
    with pytest.raises(ValidationError):
        ScheduledMessageService.validate_future_end_at(past_end_at)
