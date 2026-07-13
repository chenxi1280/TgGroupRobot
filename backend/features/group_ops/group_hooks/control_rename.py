from __future__ import annotations

import structlog
from telegram.ext import ContextTypes

from backend.features.group_ops.group_hooks.common import _schedule_message_delete

log = structlog.get_logger(__name__)


async def _process_rename_monitor(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    *, settings,
    old_username: str | None,
    old_name: str,
) -> bool:
    if not bool(getattr(settings, "name_change_monitor_enabled", False)):
        return False

    new_username = user.username or ""
    new_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    changes: list[tuple[str, str, str]] = []
    if (old_username or "") != new_username and (old_username or ""):
        changes.append(("用户名", old_username or "空", new_username or "空"))
    if old_name and old_name != new_name:
        changes.append(("昵称", old_name, new_name or "空"))
    if not changes:
        return False

    template = getattr(settings, "name_change_monitor_template_text", None) or (
        "检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}"
    )
    configured_delete_after = getattr(
        settings,
        "name_change_monitor_delete_after_seconds",
        60,
    )
    delete_after = int(60 if configured_delete_after is None else configured_delete_after)

    for change_type, old_content, new_content in changes:
        text = (
            template
            .replace("{userId}", str(user.id))
            .replace("{changeType}", change_type)
            .replace("{oldContent}", old_content)
            .replace("{newContent}", new_content)
        )
        try:
            sent = await context.bot.send_message(chat.id, text)
            if delete_after > 0:
                _schedule_message_delete(context, sent, delete_after, name="group_hooks.rename_warn_delete")
        except Exception as exc:
            log.warning("rename_monitor_send_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True
