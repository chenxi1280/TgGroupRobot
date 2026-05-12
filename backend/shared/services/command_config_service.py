from __future__ import annotations

import re
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.services.chat_service import get_chat_settings


COMMAND_DEFINITIONS: list[dict[str, Any]] = [
    {"key": "start", "label": "/start", "allow_alias": True},
    {"key": "admin", "label": "/admin", "allow_alias": True},
    {"key": "inherit", "label": "/inherit", "allow_alias": True},
    {"key": "sign", "label": "/sign", "allow_alias": True},
    {"key": "points", "label": "/points", "allow_alias": True},
    {"key": "rank", "label": "/rank", "allow_alias": True},
    {"key": "link", "label": "/link", "allow_alias": True},
    {"key": "link_stat", "label": "/link_stat", "allow_alias": True},
    {"key": "renew", "label": "/renew", "allow_alias": True},
    {"key": "mydata", "label": "/mydata", "allow_alias": True},
    {"key": "nearby", "label": "/nearby", "allow_alias": True},
    {"key": "list", "label": "/list", "allow_alias": True},
    {"key": "teacher_search", "label": "老师搜索", "allow_alias": False},
    {"key": "open_teachers", "label": "开课老师", "allow_alias": False},
    {"key": "car_review", "label": "报告/车评", "allow_alias": False},
    {"key": "car_review_rank", "label": "车评排行", "allow_alias": False},
    {"key": "invite_rank", "label": "邀请排行", "allow_alias": False},
    {"key": "lottery", "label": "抽奖", "allow_alias": False},
    {"key": "solitaire", "label": "接龙", "allow_alias": False},
]


_ALIAS_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _build_default_config() -> dict[str, Any]:
    commands: dict[str, dict[str, Any]] = {}
    for item in COMMAND_DEFINITIONS:
        commands[item["key"]] = {"enabled": True, "alias": None}
    return {"commands": commands}


def _normalize_config(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _build_default_config()
    commands = raw.get("commands")
    if not isinstance(commands, dict):
        return _build_default_config()

    normalized = _build_default_config()
    for key, value in commands.items():
        if key not in normalized["commands"] or not isinstance(value, dict):
            continue
        enabled = value.get("enabled")
        alias = value.get("alias")
        normalized["commands"][key]["enabled"] = bool(enabled) if enabled is not None else True
        normalized["commands"][key]["alias"] = _normalize_alias(alias)
    return normalized


def _normalize_alias(value: Any) -> str | None:
    if not value:
        return None
    alias = str(value).strip()
    if not alias:
        return None
    if alias.startswith("/"):
        alias = alias[1:]
    alias = alias.lower()
    if not alias or not _ALIAS_PATTERN.fullmatch(alias):
        return None
    return alias


def get_command_config(settings) -> dict[str, Any]:
    raw = getattr(settings, "command_config", None)
    return _normalize_config(raw)


def is_command_enabled(settings, key: str) -> bool:
    if not bool(getattr(settings, "command_config_enabled", False)):
        return True
    config = get_command_config(settings)
    return bool(config["commands"].get(key, {}).get("enabled", True))


def get_command_alias(settings, key: str) -> str | None:
    if not bool(getattr(settings, "command_config_enabled", False)):
        return None
    definition = next((item for item in COMMAND_DEFINITIONS if item["key"] == key), None)
    if definition is not None and not definition.get("allow_alias", True):
        return None
    config = get_command_config(settings)
    return config["commands"].get(key, {}).get("alias")


def set_command_enabled(settings, key: str, enabled: bool) -> None:
    config = get_command_config(settings)
    if key not in config["commands"]:
        return
    config["commands"][key]["enabled"] = bool(enabled)
    settings.command_config = config


def set_command_alias(settings, key: str, alias: str | None) -> None:
    definition = next((item for item in COMMAND_DEFINITIONS if item["key"] == key), None)
    if definition is not None and not definition.get("allow_alias", True):
        return
    config = get_command_config(settings)
    if key not in config["commands"]:
        return
    config["commands"][key]["alias"] = _normalize_alias(alias)
    settings.command_config = config


def list_command_definitions() -> list[dict[str, Any]]:
    return COMMAND_DEFINITIONS


async def ensure_command_enabled(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    *,
    command_key: str,
    deny_text: str = "该指令已关闭。",
) -> bool:
    if update.effective_chat is None or update.effective_message is None:
        return False
    chat = update.effective_chat
    if chat.type == "private":
        return True
    db = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, chat.id)
        await session.commit()
    if not is_command_enabled(settings, command_key):
        await update.effective_message.reply_text(deny_text)
        return False
    return True


async def is_group_text_command_enabled(session, chat_id: int, command_key: str) -> bool:
    settings = await get_chat_settings(session, chat_id)
    return is_command_enabled(settings, command_key)
