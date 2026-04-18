from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from backend.features.web_admin.auth_service import append_audit
from backend.platform.db.schema.models.core import AdminAccount, AppSetting


DEFAULT_ANNOUNCEMENT_TEXT = "保安公告栏 👉 点击关注 (https://t.me/abaoantips)"
_KEYS = {
    "enabled": "admin_announcement_enabled",
    "entry_text": "admin_announcement_entry_text",
    "target_url": "admin_announcement_target_url",
    "message_text": "admin_announcement_message_text",
}


def _truthy(value: str | None) -> bool:
    return str(value or "1").strip().lower() in {"1", "true", "yes", "on"}


async def _get_value(session: AsyncSession, key: str) -> str | None:
    row = await session.get(AppSetting, key)
    return row.value if row is not None else None


async def _set_value(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
        return
    row.value = value
    row.updated_at = dt.datetime.now(dt.UTC)


async def get_announcement_settings(session: AsyncSession) -> dict:
    enabled_raw = await _get_value(session, _KEYS["enabled"])
    entry_text = await _get_value(session, _KEYS["entry_text"])
    target_url = await _get_value(session, _KEYS["target_url"])
    message_text = await _get_value(session, _KEYS["message_text"])
    return {
        "enabled": _truthy(enabled_raw),
        "entry_text": (entry_text or DEFAULT_ANNOUNCEMENT_TEXT).strip(),
        "target_url": (target_url or "").strip(),
        "message_text": (message_text or "").strip(),
    }


async def update_announcement_settings(
    session: AsyncSession,
    *,
    admin: AdminAccount,
    enabled: bool,
    entry_text: str,
    target_url: str,
    message_text: str,
) -> dict:
    normalized_entry = (entry_text or "").strip() or DEFAULT_ANNOUNCEMENT_TEXT
    normalized_url = (target_url or "").strip()
    normalized_message = (message_text or "").strip()
    if normalized_url and not normalized_url.startswith(("https://", "http://", "tg://", "https://t.me/")):
        raise ValueError("公告链接仅支持 http/https 或 Telegram 链接")

    await _set_value(session, _KEYS["enabled"], "1" if enabled else "0")
    await _set_value(session, _KEYS["entry_text"], normalized_entry)
    await _set_value(session, _KEYS["target_url"], normalized_url)
    await _set_value(session, _KEYS["message_text"], normalized_message)
    await append_audit(
        session,
        admin_account_id=admin.id,
        action="announcement.update",
        target_type="app_setting",
        target_id="admin_announcement",
        detail={
            "enabled": enabled,
            "entry_text": normalized_entry,
            "target_url": normalized_url,
            "message_length": len(normalized_message),
        },
    )
    return await get_announcement_settings(session)


def format_announcement_line(settings: dict) -> str:
    if not settings.get("enabled", True):
        return ""
    entry = (settings.get("entry_text") or DEFAULT_ANNOUNCEMENT_TEXT).strip()
    url = (settings.get("target_url") or "").strip()
    message = (settings.get("message_text") or "").strip()
    parts = [entry]
    if url and url not in entry:
        parts.append(url)
    if message:
        parts.append(message)
    return "\n".join(parts)
