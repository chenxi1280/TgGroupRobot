from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import structlog
from sqlalchemy import select

from backend.features.group_ops.group_hooks.control_rename import _process_rename_monitor
from backend.platform.db.schema.models.core import ChatMember, ChatSettings, TgUser
from backend.platform.scheduler.core.core import ScheduledTask
from backend.platform.scheduler.core.task_config import TASK_CONFIG

log = structlog.get_logger(__name__)

LEFT_STATUSES = {"left", "kicked"}


def _display_name(user) -> str:
    return " ".join(
        part
        for part in [
            user.first_name,
            user.last_name,
        ]
        if part
    )


async def _check_member_profile(
    app,
    _session,
    settings: ChatSettings,
    *, member: ChatMember,
    stored_user: TgUser,
) -> bool:
    try:
        current_member = await app.bot.get_chat_member(chat_id=settings.chat_id, user_id=stored_user.id)
    except Exception as exc:
        log.warning(
            "rename_monitor_member_fetch_failed",
            chat_id=settings.chat_id,
            user_id=stored_user.id,
            error=str(exc),
        )
        return False

    status = str(getattr(current_member, "status", "") or "")
    if status in LEFT_STATUSES:
        member.joined_at = None
        member.updated_at = dt.datetime.now(dt.UTC)
        return False

    current_user = getattr(current_member, "user", None)
    if current_user is None:
        return False

    old_username = stored_user.username
    old_name = _display_name(stored_user)
    context = SimpleNamespace(bot=app.bot, application=app)
    chat = SimpleNamespace(id=settings.chat_id)

    changed = await _process_rename_monitor(
        context,
        chat,
        current_user,
        settings=settings,
        old_username=old_username,
        old_name=old_name,
    )

    now = dt.datetime.now(dt.UTC)
    stored_user.username = current_user.username
    stored_user.first_name = current_user.first_name
    stored_user.last_name = current_user.last_name
    stored_user.language_code = current_user.language_code or stored_user.language_code
    stored_user.updated_at = now
    member.updated_at = now
    return changed


async def _scan_chat_members(app, session, settings: ChatSettings, *, limit: int, pause_seconds: float) -> tuple[int, int]:
    member_result = await session.execute(
        select(ChatMember, TgUser)
        .join(TgUser, TgUser.id == ChatMember.user_id)
        .where(ChatMember.chat_id == settings.chat_id, ChatMember.joined_at.is_not(None))
        .order_by(ChatMember.updated_at.asc())
        .limit(limit)
    )
    checked = 0
    changed = 0
    for member, stored_user in member_result.all():
        checked += 1
        if await _check_member_profile(app, session, settings, member=member, stored_user=stored_user):
            changed += 1
        if pause_seconds > 0:
            await asyncio.sleep(pause_seconds)
    return checked, changed


class RenameMonitorTask(ScheduledTask):
    """Poll known group members so rename monitoring can work without a new message."""

    def __init__(self) -> None:
        config = TASK_CONFIG.get(
            "rename_monitor",
            {
                "interval": 300,
                "enabled": True,
                "max_consecutive_failures": 10,
                "max_members_per_chat": 50,
                "max_members_per_run": 200,
                "request_pause_seconds": 0.05,
            },
        )
        super().__init__(
            name="rename_monitor",
            interval=config["interval"],
            enabled=config["enabled"],
            max_consecutive_failures=config["max_consecutive_failures"],
        )
        self.max_members_per_chat = int(config.get("max_members_per_chat", 50))
        self.max_members_per_run = int(config.get("max_members_per_run", 200))
        self.request_pause_seconds = float(config.get("request_pause_seconds", 0.05))

    async def execute(self, app) -> None:
        db = app.bot_data["db"]
        checked = 0
        changed = 0

        async with db.session_factory() as session:
            result = await session.execute(
                select(ChatSettings).where(ChatSettings.name_change_monitor_enabled.is_(True))
            )
            settings_list = list(result.scalars().all())

            for settings in settings_list:
                remaining = self.max_members_per_run - checked
                if remaining <= 0:
                    break
                limit = max(0, min(self.max_members_per_chat, remaining))
                if limit <= 0:
                    break
                chat_checked, chat_changed = await _scan_chat_members(
                    app,
                    session,
                    settings,
                    limit=limit,
                    pause_seconds=self.request_pause_seconds,
                )
                checked += chat_checked
                changed += chat_changed

            await session.commit()

        if checked:
            log.info("rename_monitor_task_completed", checked=checked, changed=changed)
