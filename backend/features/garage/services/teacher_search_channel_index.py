from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.teacher_search_settings import TeacherSearchSettingsMixin
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import TeacherProfile


@dataclass(frozen=True)
class ChannelPostTeacherIndexResult:
    indexed: bool
    reason: str | None
    username: str | None = None
    user_id: int | None = None
    channel_id: int | None = None
    message_id: int | None = None
    label_count: int = 0


_CHANNEL_FIELD_RE = re.compile(r"^【\s*([^】]+?)\s*】\s*[:：]?\s*(.*)$")
_CHANNEL_HASHTAG_RE = re.compile(r"#\s*([^#\s,，、;；:：【】\[\]()（）]+)")
_CHANNEL_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{2,31})")
_LOCATION_FIELD_LABELS = frozenset({"所在位置", "位置", "地址", "地区"})
_PRICE_FIELD_LABELS = frozenset({"上课费用", "价格", "费用"})


def _clean_channel_field_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    if not cleaned:
        return None
    return re.sub(r"#\s*", "", cleaned).strip() or None


def _split_channel_field_line(line: str) -> tuple[str, str] | None:
    match = _CHANNEL_FIELD_RE.match(line.strip())
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _extract_channel_field(text: str, labels: frozenset[str]) -> str | None:
    for line in (text or "").splitlines():
        field = _split_channel_field_line(line)
        if field is None:
            continue
        label, value = field
        if label in labels:
            return _clean_channel_field_text(value)
    return None


def _extract_contact_username(text: str) -> str | None:
    fallback: str | None = None
    for line in (text or "").splitlines():
        mention = _CHANNEL_MENTION_RE.search(line)
        if mention is None:
            continue
        username = mention.group(1).lower()
        if "联系方式" in line:
            return username
        if fallback is None:
            fallback = username
    return fallback


def _extract_channel_labels(text: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for raw in _CHANNEL_HASHTAG_RE.findall(text or ""):
        label = _clean_channel_field_text(raw)
        if label is None or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _merge_channel_labels(existing: list[str] | None, incoming: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for label in [*(existing or []), *incoming]:
        cleaned = _clean_channel_field_text(str(label))
        if cleaned is None or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged


def _apply_channel_profile_payload(profile: TeacherProfile, text: str) -> None:
    labels = _extract_channel_labels(text)
    region_text = _extract_channel_field(text, _LOCATION_FIELD_LABELS)
    price_text = _extract_channel_field(text, _PRICE_FIELD_LABELS)
    profile.labels = _merge_channel_labels(getattr(profile, "labels", None), labels)
    if region_text is not None:
        profile.region_text = region_text
    if price_text is not None:
        profile.price_text = price_text
    profile.updated_at = dt.datetime.now(dt.UTC)


class TeacherSearchChannelIndexMixin:
    @staticmethod
    def has_channel_post_contact(text: str) -> bool:
        return _extract_contact_username(text) is not None

    @staticmethod
    async def index_channel_post_teacher_profile(
        session: AsyncSession,
        *,
        chat_id: int,
        channel_id: int,
        message_id: int,
        text: str,
    ) -> ChannelPostTeacherIndexResult:
        username = _extract_contact_username(text)
        if username is None:
            return ChannelPostTeacherIndexResult(False, "missing_contact", channel_id=channel_id, message_id=message_id)
        result = await session.execute(select(TgUser).where(func.lower(TgUser.username) == username))
        user = result.scalar_one_or_none()
        if user is None:
            return ChannelPostTeacherIndexResult(
                False,
                "contact_user_not_found",
                username=username,
                channel_id=channel_id,
                message_id=message_id,
            )

        from backend.features.garage.services.garage_auth_service import GarageAuthService

        await GarageAuthService.add_teacher_by_user_id(session, chat_id, user.id, None)
        profile = await TeacherSearchSettingsMixin.ensure_teacher_profile(session, chat_id, user.id)
        _apply_channel_profile_payload(profile, text)
        await session.flush()
        return ChannelPostTeacherIndexResult(
            True,
            None,
            username=username,
            user_id=user.id,
            channel_id=channel_id,
            message_id=message_id,
            label_count=len(profile.labels or []),
        )
