from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.garage.services.teacher_search_queries import (
    teacher_attendance_status_label,
    teacher_profile_completeness_label,
)


def _display_teacher_name(profile, tg_user) -> str:
    if getattr(profile, "source_status", None) == "pending_bind":
        username = (getattr(profile, "source_username", None) or "").strip()
        return f"@{username}" if username else "频道资料"
    if tg_user and getattr(tg_user, "username", None):
        return f"@{tg_user.username}"
    if tg_user and getattr(tg_user, "first_name", None):
        return tg_user.first_name
    return f"用户{profile.user_id}"


def _append_pending_source_result(lines: list[str], idx: int, profile) -> None:
    name = _display_teacher_name(profile, None)
    region = getattr(profile, "region_text", None)
    title = f"{idx}. 待绑定 {name} · 频道资料" + (f" · {region}" if region else "")
    lines.append(title)
    labels = list(getattr(profile, "labels", None) or [])
    if labels:
        lines.append(f"   标签：{' / '.join(labels)}")
    price_text = getattr(profile, "price_text", None)
    if price_text:
        lines.append(f"   价格：{price_text}")
    source_title = getattr(profile, "source_channel_title", None)
    if source_title:
        lines.append(f"   来源：{source_title}")
    source_url = getattr(profile, "source_url", None)
    if source_url:
        lines.append(f"   原帖：{source_url}")


def _append_bound_teacher_result(lines: list[str], idx: int, profile, *, tg_user,  badge: str) -> None:
    labels = " ".join(getattr(profile, "labels", None) or [])
    extra = " / ".join(part for part in [labels, profile.region_text, profile.price_text] if part)
    score_extra = ""
    if getattr(profile, "review_count", 0):
        avg_score = float(getattr(profile, "avg_score", 0.0) or 0.0)
        score_extra = f" · 均分 {avg_score:g} · {int(profile.review_count)} 条"
    status = teacher_attendance_status_label(profile)
    completeness = teacher_profile_completeness_label(profile)
    lines.append(
        f"{idx}. {badge} {_display_teacher_name(profile, tg_user)} · {status} · {completeness}"
        + score_extra
        + (f" · {extra}" if extra else "")
    )
    source_title = getattr(profile, "source_channel_title", None)
    if source_title:
        lines.append(f"   来源：{source_title}")
    source_url = getattr(profile, "source_url", None)
    if source_url:
        lines.append(f"   原帖：{source_url}")


def format_teacher_keyword_search(keyword: str, rows, *, badge: str, fallback_note: str = "") -> str:
    lines = [f"老师搜索：{keyword}"]
    if fallback_note:
        lines.append(fallback_note)
    for idx, (profile, tg_user) in enumerate(rows, start=1):
        if getattr(profile, "source_status", None) == "pending_bind":
            _append_pending_source_result(lines, idx, profile)
            continue
        _append_bound_teacher_result(lines, idx, profile, tg_user=tg_user, badge=badge)
    return "\n".join(lines)


def build_teacher_keyword_search_markup(rows) -> InlineKeyboardMarkup | None:
    buttons = []
    for idx, (profile, _tg_user) in enumerate(rows, start=1):
        source_url = getattr(profile, "source_url", None)
        if source_url:
            buttons.append([InlineKeyboardButton(f"{idx}. 查看原帖", url=source_url)])
    return InlineKeyboardMarkup(buttons) if buttons else None
