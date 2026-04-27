from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.platform.db.schema.models.core import NearbyProfile, TgUser
from backend.features.nearby.services.nearby_profile_service import (
    build_user_display_name,
    format_distance,
    haversine_distance_km,
    list_nearby_entries,
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
    user = SimpleNamespace(id=1, username="alice", first_name="Alice", last_name=None)
    assert build_user_display_name(user, 1) == "@alice"

    user = SimpleNamespace(id=1, username=None, first_name="Alice", last_name=None)
    assert build_user_display_name(user, 1) == "Alice"

    user = SimpleNamespace(id=42, username=None, first_name=None, last_name=None)
    assert build_user_display_name(user, 42) == "用户42"


@pytest.mark.asyncio
async def test_list_nearby_entries_sorts_by_distance_and_preserves_fields() -> None:
    base_profile = NearbyProfile(chat_id=-100, user_id=2, is_visible=True, fuzzy_distance=True)
    base_profile.latitude = 39.905
    base_profile.longitude = 116.391
    base_profile.updated_at = datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc)

    farther_profile = NearbyProfile(chat_id=-100, user_id=3, is_visible=True, fuzzy_distance=False)
    farther_profile.latitude = 31.2304
    farther_profile.longitude = 121.4737
    farther_profile.updated_at = datetime(2026, 3, 25, 9, 0, tzinfo=timezone.utc)

    class FakeResult:
        def all(self):
            return [
                (farther_profile, TgUser(id=3, username="bob", first_name="Bob", last_name=None, language_code=None)),
                (base_profile, TgUser(id=2, username="alice", first_name="Alice", last_name=None, language_code=None)),
            ]

    class FakeSession:
        async def execute(self, stmt):
            return FakeResult()

    entries = await list_nearby_entries(FakeSession(), -100, 1, 39.9, 116.4)

    assert [entry.user_id for entry in entries] == [2, 3]
    assert entries[0].display_name == "@alice"
    assert entries[0].fuzzy_distance is True
    assert entries[1].display_name == "@bob"
    assert entries[1].fuzzy_distance is False
