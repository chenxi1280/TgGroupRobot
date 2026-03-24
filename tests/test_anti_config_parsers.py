from __future__ import annotations

from bot.handlers.anti_flood_config_handler import _parse_bool as parse_flood_bool
from bot.handlers.anti_flood_config_handler import _parse_int as parse_flood_int
from bot.handlers.anti_spam_config_handler import _parse_bool as parse_spam_bool
from bot.handlers.anti_spam_config_handler import _parse_int as parse_spam_int


def test_parse_bool_supports_cn_and_en_values() -> None:
    assert parse_flood_bool("开启") is True
    assert parse_flood_bool("true") is True
    assert parse_flood_bool("false") is False

    assert parse_spam_bool("是") is True
    assert parse_spam_bool("off") is False


def test_parse_int_returns_none_for_invalid_input() -> None:
    assert parse_flood_int("abc", 1) is None
    assert parse_spam_int("12x", 1) is None


def test_parse_int_clamps_min_value() -> None:
    assert parse_flood_int("0", 2) == 2
    assert parse_spam_int("-5", 1) == 1
    assert parse_spam_int("30", 1) == 30
