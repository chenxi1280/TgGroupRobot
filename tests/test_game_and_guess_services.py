from __future__ import annotations

import datetime as dt

import pytest

from backend.shared.services.base import ValidationError
from backend.features.activity.services.game_service import parse_ratio as parse_game_ratio, validate_hhmm, format_game_menu_text
from backend.features.activity.services.guess_service import format_event_preview, parse_deadline, parse_options, parse_ratio as parse_guess_ratio


def test_game_ratio_parsing():
    assert parse_game_ratio("0.1") == "0.1"
    with pytest.raises(ValidationError):
        parse_game_ratio("1.5")


def test_game_time_validation():
    assert validate_hhmm("23:05") == "23:05"
    with pytest.raises(ValidationError):
        validate_hhmm("25:00")


def test_guess_options_parser_accepts_lines():
    options = parse_options("1:红队\n2:蓝队")
    assert options == [{"key": "1", "label": "红队"}, {"key": "2", "label": "蓝队"}]


def test_guess_deadline_parser_accepts_minutes():
    target = parse_deadline("30")
    assert target > dt.datetime.now(dt.UTC)


def test_guess_ratio_parser_rejects_invalid():
    assert parse_guess_ratio("0.2") == "0.2"
    with pytest.raises(ValidationError):
        parse_guess_ratio("-0.1")


def test_formatters_include_icons():
    game_text = format_game_menu_text(
        "测试群",
        k3_enabled=True,
        blackjack_enabled=False,
        rake_ratio="0.1",
        rake_owner="@dealer",
        auto_schedule_enabled=True,
        auto_start_time="08:00",
        auto_stop_time="23:00",
        delete_mode="keep",
    )
    assert "🎮 游戏" in game_text
    guess_preview = format_event_preview(
        {
            "title": "周末竞猜",
            "description": "猜胜负",
            "mode": "no_banker",
            "public_pool": 100,
            "command_keyword": "竞猜",
            "deadline_at": "23:00",
            "allow_repeat_bet": False,
            "options": [{"key": "1", "label": "主胜"}, {"key": "2", "label": "客胜"}],
        }
    )
    assert "⚽ 竞猜" in guess_preview
