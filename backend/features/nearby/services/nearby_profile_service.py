from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import NearbyProfile, TgUser
from backend.shared.services.chat_service import ensure_chat
from backend.shared.services.formatters import format_user_display_name
from backend.shared.services.user_service import ensure_user

EARTH_RADIUS_KM = 6371.0088


class UserIdentityLike(Protocol):
    """用户身份最小字段协议，统一 telegram.User 与 ORM TgUser 的读取边界。"""

    id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None


@dataclass
class NearbyEntry:
    user_id: int
    display_name: str
    username: str | None
    distance_km: float
    price_text: str | None
    method_text: str | None
    address_text: str | None
    fuzzy_distance: bool
    updated_at: dt.datetime
    profile: NearbyProfile


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """计算 WGS84 球面距离（公里）。"""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return EARTH_RADIUS_KM * c


def format_distance(distance_km: float, fuzzy: bool = False) -> str:
    """格式化距离文本。"""
    if distance_km < 0:
        distance_km = 0.0

    if not fuzzy:
        return f"{distance_km:.1f}km"

    if distance_km < 1:
        value = round(distance_km, 1)
    elif distance_km < 5:
        value = round(distance_km * 2) / 2
    else:
        value = round(distance_km)
    return f"约 {value:g}km"


def build_user_display_name(user: TgUser, fallback_user_id: int) -> str:
    return format_user_display_name(user, fallback_user_id)


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _infer_chat_type(chat_id: int) -> str:
    return "supergroup" if chat_id < 0 else "private"


async def get_profile(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> NearbyProfile | None:
    stmt = select(NearbyProfile).where(
        NearbyProfile.chat_id == chat_id,
        NearbyProfile.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_profile_with_user(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> tuple[NearbyProfile, TgUser] | None:
    stmt = (
        select(NearbyProfile, TgUser)
        .join(TgUser, TgUser.id == NearbyProfile.user_id)
        .where(
            NearbyProfile.chat_id == chat_id,
            NearbyProfile.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None
    return row[0], row[1]


async def get_or_create_profile(
    session: AsyncSession,
    chat_id: int,
    user: UserIdentityLike,
    chat_type: str | None = None,
    chat_title: str | None = None,
) -> NearbyProfile:
    """获取或创建群内个人资料。"""
    await ensure_chat(
        session,
        chat_id=chat_id,
        chat_type=chat_type or _infer_chat_type(chat_id),
        title=chat_title,
    )
    await ensure_user(
        session,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code,
    )

    profile = await get_profile(session, chat_id, user.id)
    if profile is None:
        profile = NearbyProfile(chat_id=chat_id, user_id=user.id)
        session.add(profile)
        await session.flush()
    return profile


async def update_profile(
    session: AsyncSession,
    chat_id: int,
    user: UserIdentityLike,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    price_text: str | None = None,
    method_text: str | None = None,
    address_text: str | None = None,
    is_visible: bool | None = None,
    fuzzy_distance: bool | None = None,
    chat_type: str | None = None,
    chat_title: str | None = None,
) -> NearbyProfile:
    profile = await get_or_create_profile(
        session, chat_id, user, chat_type=chat_type, chat_title=chat_title
    )

    if latitude is not None:
        profile.latitude = latitude
    if longitude is not None:
        profile.longitude = longitude
    if price_text is not None:
        profile.price_text = price_text
    if method_text is not None:
        profile.method_text = method_text
    if address_text is not None:
        profile.address_text = address_text
    if is_visible is not None:
        profile.is_visible = is_visible
    if fuzzy_distance is not None:
        profile.fuzzy_distance = fuzzy_distance

    if latitude is not None and longitude is not None:
        profile.last_location_at = dt.datetime.now(dt.UTC)

    await session.flush()
    return profile


async def clear_profile(
    session: AsyncSession,
    chat_id: int,
    user_id: int,
) -> bool:
    profile = await get_profile(session, chat_id, user_id)
    if profile is None:
        return False

    profile.latitude = None
    profile.longitude = None
    profile.price_text = None
    profile.method_text = None
    profile.address_text = None
    profile.is_visible = False
    profile.last_location_at = None
    await session.flush()
    return True


async def list_nearby_entries(
    session: AsyncSession,
    chat_id: int,
    requester_user_id: int,
    requester_lat: float,
    requester_lon: float,
) -> list[NearbyEntry]:
    """获取群内可见用户并按距离排序。"""
    stmt = (
        select(NearbyProfile, TgUser)
        .join(TgUser, TgUser.id == NearbyProfile.user_id)
        .where(
            NearbyProfile.chat_id == chat_id,
            NearbyProfile.is_visible == True,
            NearbyProfile.latitude.is_not(None),
            NearbyProfile.longitude.is_not(None),
            NearbyProfile.user_id != requester_user_id,
        )
    )
    result = await session.execute(stmt)
    rows = result.all()

    entries: list[NearbyEntry] = []
    for profile, user in rows:
        lat = _to_float(profile.latitude)
        lon = _to_float(profile.longitude)
        if lat is None or lon is None:
            continue

        distance = haversine_distance_km(requester_lat, requester_lon, lat, lon)
        entries.append(
            NearbyEntry(
                user_id=user.id,
                display_name=build_user_display_name(user, user.id),
                username=user.username,
                distance_km=distance,
                price_text=profile.price_text,
                method_text=profile.method_text,
                address_text=profile.address_text,
                fuzzy_distance=profile.fuzzy_distance,
                updated_at=profile.updated_at,
                profile=profile,
            )
        )

    entries.sort(key=lambda x: (x.distance_km, x.updated_at))
    return entries
