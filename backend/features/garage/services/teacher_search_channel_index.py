from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.garage.services.teacher_search_settings import TeacherSearchSettingsMixin
from backend.platform.db.schema.models.core import TgUser
from backend.platform.db.schema.models.garage_features import TeacherProfile, TeacherSourcePost


@dataclass(frozen=True)
class ChannelPostTeacherIndexResult:
    indexed: bool
    reason: str | None
    username: str | None = None
    user_id: int | None = None
    channel_id: int | None = None
    message_id: int | None = None
    label_count: int = 0
    source_post_id: int | None = None
    source_url: str | None = None


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


def _build_channel_source_url(channel_id: int, message_id: int, channel_username: str | None = None) -> str:
    username = (channel_username or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}/{message_id}"
    channel_text = str(abs(int(channel_id)))
    internal_id = channel_text[3:] if channel_text.startswith("100") else channel_text
    return f"https://t.me/c/{internal_id}/{message_id}"


async def _get_source_post(
    session: AsyncSession,
    *,
    chat_id: int,
    channel_id: int,
    message_id: int,
) -> TeacherSourcePost | None:
    result = await session.execute(
        select(TeacherSourcePost).where(
            TeacherSourcePost.chat_id == chat_id,
            TeacherSourcePost.source_channel_id == channel_id,
            TeacherSourcePost.source_message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


def _apply_source_post_payload(
    source_post: TeacherSourcePost,
    *,
    text: str,
    username: str,
    channel_username: str | None,
    channel_title: str | None,
    source_url: str,
    user_id: int | None,
) -> None:
    source_post.source_channel_username = (channel_username or "").strip().lstrip("@") or None
    source_post.source_channel_title = (channel_title or "").strip() or None
    source_post.source_url = source_url
    source_post.username = username
    source_post.teacher_user_id = user_id
    source_post.bind_status = "bound" if user_id is not None else "pending_bind"
    source_post.failure_reason = None if user_id is not None else "contact_user_not_found"
    source_post.labels = _extract_channel_labels(text)
    source_post.region_text = _extract_channel_field(text, _LOCATION_FIELD_LABELS)
    source_post.price_text = _extract_channel_field(text, _PRICE_FIELD_LABELS)
    source_post.raw_text = text
    source_post.updated_at = dt.datetime.now(dt.UTC)


async def _upsert_source_post(
    session: AsyncSession,
    *,
    chat_id: int,
    channel_id: int,
    message_id: int,
    text: str,
    username: str,
    channel_username: str | None,
    channel_title: str | None,
    user_id: int | None,
) -> tuple[TeacherSourcePost, str]:
    source_url = _build_channel_source_url(channel_id, message_id, channel_username)
    source_post = await _get_source_post(session, chat_id=chat_id, channel_id=channel_id, message_id=message_id)
    if source_post is None:
        source_post = TeacherSourcePost(
            chat_id=chat_id,
            source_channel_id=channel_id,
            source_message_id=message_id,
            username=username,
        )
        session.add(source_post)
    _apply_source_post_payload(
        source_post,
        text=text,
        username=username,
        channel_username=channel_username,
        channel_title=channel_title,
        source_url=source_url,
        user_id=user_id,
    )
    return source_post, source_url


def _channel_index_result(
    *,
    indexed: bool,
    reason: str | None,
    username: str | None,
    user_id: int | None,
    channel_id: int,
    message_id: int,
    labels: list[str] | None,
    source_post: TeacherSourcePost | None = None,
    source_url: str | None = None,
) -> ChannelPostTeacherIndexResult:
    return ChannelPostTeacherIndexResult(
        indexed,
        reason,
        username=username,
        user_id=user_id,
        channel_id=channel_id,
        message_id=message_id,
        label_count=len(labels or []),
        source_post_id=getattr(source_post, "id", None),
        source_url=source_url,
    )


def _pending_source_index_result(
    *,
    username: str,
    channel_id: int,
    message_id: int,
    source_post: TeacherSourcePost,
    source_url: str,
) -> ChannelPostTeacherIndexResult:
    return _channel_index_result(
        indexed=True,
        reason="pending_bind",
        username=username,
        user_id=None,
        channel_id=channel_id,
        message_id=message_id,
        labels=source_post.labels,
        source_post=source_post,
        source_url=source_url,
    )


async def _bind_channel_source_to_teacher(
    session: AsyncSession,
    *,
    chat_id: int,
    user_id: int,
    text: str,
) -> TeacherProfile:
    from backend.features.garage.services.garage_auth_service import GarageAuthService

    await GarageAuthService.add_teacher_by_user_id(session, chat_id, user_id, None)
    profile = await TeacherSearchSettingsMixin.ensure_teacher_profile(session, chat_id, user_id)
    _apply_channel_profile_payload(profile, text)
    await session.flush()
    return profile


async def bind_pending_source_posts_for_user(session: AsyncSession, user: TgUser) -> int:
    username = (getattr(user, "username", None) or "").strip().lower()
    if not username:
        return 0
    result = await session.execute(
        select(TeacherSourcePost).where(
            func.lower(TeacherSourcePost.username) == username,
            TeacherSourcePost.teacher_user_id.is_(None),
        )
    )
    pending_posts = result.scalars().all()
    for source_post in pending_posts:
        source_post.teacher_user_id = int(user.id)
        source_post.bind_status = "bound"
        source_post.failure_reason = None
        await _bind_channel_source_to_teacher(
            session,
            chat_id=int(source_post.chat_id),
            user_id=int(user.id),
            text=source_post.raw_text or "",
        )
    return len(pending_posts)


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
        channel_username: str | None = None,
        channel_title: str | None = None,
    ) -> ChannelPostTeacherIndexResult:
        username = _extract_contact_username(text)
        if username is None:
            return ChannelPostTeacherIndexResult(False, "missing_contact", channel_id=channel_id, message_id=message_id)
        result = await session.execute(select(TgUser).where(func.lower(TgUser.username) == username))
        user = result.scalar_one_or_none()
        user_id = int(user.id) if user is not None else None
        source_post, source_url = await _upsert_source_post(
            session,
            chat_id=chat_id,
            channel_id=channel_id,
            message_id=message_id,
            text=text,
            username=username,
            channel_username=channel_username,
            channel_title=channel_title,
            user_id=user_id,
        )
        if user is None:
            return _pending_source_index_result(
                username=username,
                channel_id=channel_id,
                message_id=message_id,
                source_post=source_post,
                source_url=source_url,
            )

        profile = await _bind_channel_source_to_teacher(session, chat_id=chat_id, user_id=user_id, text=text)
        return _channel_index_result(
            indexed=True,
            reason=None,
            username=username,
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_id,
            labels=profile.labels,
            source_post=source_post,
            source_url=source_url,
        )
