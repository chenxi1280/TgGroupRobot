from __future__ import annotations

from backend.features.moderation.anti_flood_config_handler import _parse_bool as parse_flood_bool
from backend.features.moderation.anti_flood_config_handler import _parse_int as parse_flood_int
from backend.features.moderation.anti_spam_config_handler import _parse_bool as parse_spam_bool
from backend.features.moderation.anti_spam_config_handler import _parse_int as parse_spam_int
from backend.features.moderation.anti_spam_config_messages import _parse_config_text


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


def test_anti_spam_text_config_reports_unknown_and_invalid_values() -> None:
    updates, rules, invalid = _parse_config_text(
        "状态: 也许\n例外用户ID: 1,abc\n未知配置: 开启\n无冒号行",
        {"exception_user_ids": [9]},
    )

    assert updates == {}
    assert rules == {"exception_user_ids": [9]}
    assert invalid == ["状态", "例外用户ID", "未知配置", "无冒号行"]


def test_anti_spam_text_config_applies_only_valid_entries() -> None:
    updates, rules, invalid = _parse_config_text(
        "状态: 开启\n处罚: mute\n例外用户ID: 1,-2",
        {"exception_user_ids": []},
    )

    assert updates == {"anti_spam_enabled": True, "anti_spam_action": "mute"}
    assert rules["exception_user_ids"] == [1, -2]
    assert invalid == []
