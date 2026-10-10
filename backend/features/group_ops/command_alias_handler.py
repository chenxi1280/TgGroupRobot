from __future__ import annotations

from importlib import import_module
from typing import Awaitable, Callable

import structlog
from telegram import Update
from telegram.ext import ContextTypes, ApplicationHandlerStop

from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.command_config_service import get_command_alias, is_command_enabled, command_alias_conflicts

log = structlog.get_logger(__name__)

CommandHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]
COMMAND_TARGETS: dict[str, tuple[str, str]] = {
    "start": ("backend.features.group_ops.start_handler", "start_command"),
    "admin": ("backend.features.admin.admin_handler", "admin_command"),
    "inherit": ("backend.features.invite.account_inherit_handler", "account_inherit_command"),
    "sign": ("backend.features.points.points_handler", "sign_command"),
    "points": ("backend.features.points.points_handler", "points_command"),
    "rank": ("backend.features.points.points_handler", "points_rank_command"),
    "link": ("backend.features.invite.invite_link_handler", "link_command"),
    "link_stat": ("backend.features.invite.invite_link_handler", "link_stat_command"),
    "renew": ("backend.features.subscription.renewal_handler", "renew_command"),
    "mydata": ("backend.features.nearby.nearby_handler", "mydata_command"),
    "nearby": ("backend.features.nearby.nearby_handler", "nearby_command"),
    "list": ("backend.features.nearby.nearby_handler", "list_command"),
}


def _extract_command_key(text: str) -> str | None:
    if not text or not text.startswith("/"):
        return None
    command_part = text.split(None, 1)[0]
    command = command_part[1:].split("@", 1)[0]
    return command.lower() if command else None


def _build_alias_map(settings: object) -> dict[str, str]:
    conflicts = command_alias_conflicts(settings)
    return {
        alias: key
        for key in COMMAND_TARGETS
        if (alias := get_command_alias(settings, key)) is not None and alias not in conflicts
    }


def _load_command_handler(target_key: str) -> CommandHandler | None:
    target = COMMAND_TARGETS.get(target_key)
    if target is None:
        return None
    module_name, attribute_name = target
    return getattr(import_module(module_name), attribute_name)


async def command_alias_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_message is None:
        return
    chat = update.effective_chat
    message = update.effective_message
    if chat.type == "private":
        return

    command_text = _extract_command_key(message.text or "")
    if not command_text:
        return

    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    if not await _alias_dispatch_allowed(update, context, command_text=command_text, settings=settings):
        return
    target_key = _build_alias_map(settings).get(command_text)
    if not target_key:
        return

    if not is_command_enabled(settings, target_key):
        await message.reply_text("该指令已关闭。")
        raise ApplicationHandlerStop

    handler = _load_command_handler(target_key)
    if handler is None:
        log.warning("command_alias_unhandled", key=target_key, chat_id=chat.id)
        return
    await handler(update, context)
    raise ApplicationHandlerStop


async def _alias_dispatch_allowed(update, context, *, command_text, settings):
    message = update.effective_message
    command_token = (message.text or "").split(None, 1)[0]
    if "@" in command_token and command_token.split("@", 1)[1].lower() != context.bot.username.lower():
        return
    if command_text in COMMAND_TARGETS:
        return  # Original command is owned by its registered CommandHandler.
    if command_text in command_alias_conflicts(settings):
        await message.reply_text("此历史命令别名存在冲突，请管理员在命令配置中修改。")
        raise ApplicationHandlerStop
    return True
