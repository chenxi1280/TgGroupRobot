import datetime as dt

import pytest

from backend.shared.services.base import ValidationError
from backend.shared.ui.datetime_picker import new_picker, picker_view, transition


def callbacks(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


def test_leap_calendar_year_boundary_and_exact_minute():
    picker = new_picker("sm:open:-1:abc", "2028-02-29 08:03")
    picker = transition(picker, "open", "")
    text, markup = picker_view(picker, scope="群 -1")
    assert "UTC+8" in text
    assert any(callback.endswith(":day:2028-02-29") for callback in callbacks(markup))
    assert all(len(callback.encode()) <= 64 for callback in callbacks(markup))
    assert len(markup.inline_keyboard[1]) == 7
    picker = transition(picker, "day", "2028-02-29")
    picker = transition(picker, "hour", "23")
    picker = transition(picker, "minutes", "2")
    picker = transition(picker, "minute", "59")
    assert picker["step"] == "confirm" and picker["value"] == "2028-02-29 23:59"
    _, markup = picker_view(picker, scope="群 -1")
    copied = [b.to_dict()["copy_text"]["text"] for row in markup.inline_keyboard for b in row if "copy_text" in b.to_dict()]
    assert copied == ["2028-02-29 23:59"]
    picker = transition(picker, "back", "day")
    picker = transition(picker, "month", "-12")
    _, markup = picker_view(picker, scope="群 -1")
    assert not any(callback.endswith(":day:2027-02-29") for callback in callbacks(markup))
    picker = transition(picker, "month", "-1")
    picker = transition(picker, "month", "-1")
    assert picker["month"] == "2026-12"


@pytest.mark.parametrize(("action", "value"), [("apply", ""), ("minute", "60"), ("hour", "10"), ("day", "2028-03-01"), ("month", "999")])
def test_invalid_or_out_of_step_selection_is_rejected(action, value):
    picker = transition(new_picker("back", "2028-02-29 08:03"), "open", "")
    with pytest.raises((ValidationError, ValueError)):
        transition(picker, action, value)


def test_minute_pages_cover_all_sixty_values_without_duplicates():
    picker = transition(new_picker("back", "2028-01-01 08:03"), "open", "")
    picker = transition(picker, "day", "2028-01-01")
    picker = transition(picker, "hour", "0")
    minutes = []
    for page in range(3):
        picker = transition(picker, "minutes", str(page))
        _, markup = picker_view(picker, scope="scope")
        minutes.extend(int(cb.rsplit(":", 1)[1]) for cb in callbacks(markup) if ":minute:" in cb)
    assert minutes == list(range(60))
    manual = transition(picker, "manual", "")
    assert manual["step"] == "input"
    assert manual["token"] == picker["token"] and manual["revision"] > picker["revision"]
    assert dt.datetime.strptime(manual["value"], "%Y-%m-%d %H:%M")
