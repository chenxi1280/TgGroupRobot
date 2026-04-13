from __future__ import annotations

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.chat_service import get_chat_settings
from backend.shared.services.command_config_service import get_command_alias, is_command_enabled

log = structlog.get_logger(__name__)


def _extract_command_key(text: str) -> str | None:
    if not text or not text.startswith("/"):
        return None
    command_part = text.split(None, 1)[0]
    command = command_part[1:].split("@", 1)[0]
    return command.lower() if command else None


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

    # 只处理别名，不重复处理原始指令
    alias_map: dict[str, str] = {}
    for key in (
        "start",
        "admin",
        "inherit",
        "sign",
        "points",
        "rank",
        "link",
        "renew",
        "mydata",
        "nearby",
        "list",
    ):
        alias = get_command_alias(settings, key)
        if alias:
            alias_map[alias] = key

    target_key = alias_map.get(command_text)
    if not target_key:
        return

    if not is_command_enabled(settings, target_key):
        await message.reply_text("该指令已关闭。")
        return

    # 延迟导入，避免循环依赖
    if target_key == "start":
        from backend.features.group_ops.start_handler import start_command

        await start_command(update, context)
        return
    if target_key == "admin":
        from backend.features.admin.admin_handler import admin_command

        await admin_command(update, context)
        return
    if target_key == "inherit":
        from backend.features.invite.account_inherit_handler import account_inherit_command

        await account_inherit_command(update, context)
        return
    if target_key == "sign":
        from backend.features.points.points_handler import sign_command

        await sign_command(update, context)
        return
    if target_key == "points":
        from backend.features.points.points_handler import points_command

        await points_command(update, context)
        return
    if target_key == "rank":
        from backend.features.points.points_handler import points_rank_command

        await points_rank_command(update, context)
        return
    if target_key == "link":
        from backend.features.invite.invite_link_handler import link_command

        await link_command(update, context)
        return
    if target_key == "renew":
        from backend.features.subscription.renewal_handler import renew_command

        await renew_command(update, context)
        return
    if target_key == "mydata":
        from backend.features.nearby.nearby_handler import mydata_command

        await mydata_command(update, context)
        return
    if target_key == "nearby":
        from backend.features.nearby.nearby_handler import nearby_command

        await nearby_command(update, context)
        return
    if target_key == "list":
        from backend.features.nearby.nearby_handler import list_command

        await list_command(update, context)
        return

    log.warning("command_alias_unhandled", key=target_key, chat_id=chat.id)
