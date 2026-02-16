from __future__ import annotations

from types import SimpleNamespace

from bot.services.integration.nearby_profile_service import (
    build_user_display_name,
    format_distance,
    haversine_distance_km,
)


def test_haversine_distance_zero() -> None:
    assert haversine_distance_km(39.9, 116.4, 39.9, 116.4) == 0.0


def test_haversine_distance_beijing_shanghai() -> None:
    # 北京天安门到上海人民广场直线距离大约在 1060km 左右
    distance = haversine_distance_km(39.9087, 116.3975, 31.2304, 121.4737)
    assert 1000 <= distance <= 1150


def test_format_distance_exact() -> None:
    assert format_distance(1.234, fuzzy=False) == "1.2km"


def test_format_distance_fuzzy() -> None:
    assert format_distance(0.53, fuzzy=True) == "约 0.5km"
    assert format_distance(2.24, fuzzy=True) == "约 2km"
    assert format_distance(2.26, fuzzy=True) == "约 2.5km"


def test_build_user_display_name_priority() -> None:
    user = SimpleNamespace(username="alice", first_name="Alice")
    assert build_user_display_name(user, 1) == "@alice"

    user = SimpleNamespace(username=None, first_name="Alice")
    assert build_user_display_name(user, 1) == "Alice"

    user = SimpleNamespace(username=None, first_name=None)
    assert build_user_display_name(user, 42) == "用户42"

