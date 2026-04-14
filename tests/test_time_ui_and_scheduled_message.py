from __future__ import annotations

from backend.features.automation.ui.scheduled_message_edit import sm_repeat_keyboard
from backend.shared.time_ui import (
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


def test_build_datetime_prompt_text_contains_copy_hint() -> None:
    text = build_datetime_prompt_text(
        title="🎠 轮播消息 | 编辑开始时间",
        sample_time_text="2026-04-14 10:00",
        input_hint="👉🏻 现在输入定时开始时间:",
        extra_tips=["发送 /clear 可清空开始时间"],
    )

    assert "最近整点示例" in text
    assert "点击下方蓝色按钮可直接复制" in text
    assert "发送 /clear 可清空开始时间" in text


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
