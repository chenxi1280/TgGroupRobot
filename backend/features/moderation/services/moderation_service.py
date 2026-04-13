from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Literal

import structlog
from telegram import Bot, ChatMember
from telegram.ext import ContextTypes

from backend.platform.db.schema.models.core import ChatSettings, ModerationViolation
from backend.platform.db.schema.models.enums import ModerationAction
from backend.shared.services.permission_service import is_bot_admin_user, is_user_admin
from backend.shared.services.publish_service import PublishService


log = structlog.get_logger(__name__)


ModerationActionType = Literal["delete", "mute", "ban"]


def _has_link(text: str) -> bool:
    t = text.lower()
    return "http://" in t or "https://" in t or "t.me/" in t or "www." in t


@dataclass(slots=True)
class ModerationActionResolution:
    action: ModerationActionType
    fallback_reason: str = ""


@dataclass(slots=True)
class ModerationNotice:
    text: str
    delete_after_seconds: int | None = None


def normalize_moderation_actor_id(user_id: int | None, sender_chat_id: int | None) -> int:
    if sender_chat_id is not None:
        return -abs(sender_chat_id)
    if user_id is None:
        return 0
    return user_id


def build_moderation_action_label(action: str, mute_duration: int | None = None) -> str:
    if action == "delete":
        return "删除消息"
    if action == "mute":
        return f"禁言 {max(mute_duration or 0, 1)} 秒"
    if action == "ban":
        return "封禁用户"
    return action or "已处理"


def build_moderation_notice(
    title: str,
    user_text: str,
    rule_text: str | None,
    action_label: str,
    *,
    fallback_reason: str = "",
    extra_lines: list[str] | None = None,
) -> str:
    lines = [title, f"用户: {user_text}"]
    if rule_text:
        lines.append(f"规则: {rule_text}")
    lines.append(f"处罚: {action_label}")
    if fallback_reason:
        lines.append(f"说明: {fallback_reason}")
    if extra_lines:
        lines.extend(line for line in extra_lines if line)
    return "\n".join(lines)


async def should_exempt_admin(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int | None,
    exempt_admin: bool,
) -> bool:
    """统一管理员豁免逻辑：群管理员或 Bot 全局管理员都视为豁免对象。"""
    if not exempt_admin or user_id is None:
        return False

    try:
        if await is_user_admin(context, chat_id, user_id):
            return True
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("moderation_admin_check_failed", chat_id=chat_id, user_id=user_id, error=str(exc))

    try:
        if is_bot_admin_user(user_id, context):
            return True
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("moderation_bot_admin_check_failed", chat_id=chat_id, user_id=user_id, error=str(exc))

    return False


async def resolve_effective_action(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
    requested_action: str,
    *,
    sender_chat_id: int | None = None,
) -> ModerationActionResolution:
    """把配置里的处罚动作收敛成机器人能实际执行的动作。"""
    action = (requested_action or "delete").strip()
    if action not in {"delete", "mute", "ban"}:
        action = "delete"

    if sender_chat_id is not None and action in {"mute", "ban"}:
        return ModerationActionResolution(action="delete", fallback_reason="频道身份发言仅支持删除")

    if action in {"mute", "ban"} and user_id > 0:
        try:
            member: ChatMember = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in {"creator", "administrator"}:
                return ModerationActionResolution(
                    action="delete",
                    fallback_reason="目标为群主/管理员，无法禁言，已改为删除",
                )
        except Exception as exc:
            log.warning(
                "moderation_member_status_check_failed",
                chat_id=chat_id,
                user_id=user_id,
                action=action,
                error=str(exc),
            )

    if user_id <= 0 and action in {"mute", "ban"}:
        return ModerationActionResolution(action="delete", fallback_reason="目标无法禁言或封禁，已改为删除")

    return ModerationActionResolution(action=action)


async def record_violation(
    session,
    *,
    chat_id: int,
    user_id: int,
    message_id: int | None,
    rule: str,
    detail: str | None,
    action: str,
) -> None:
    session.add(
        ModerationViolation(
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            rule=rule,
            detail=detail,
            action=action or ModerationAction.delete.value,
        )
    )
    await session.flush()


async def send_temporary_notice(
    bot: Bot,
    *,
    chat_id: int,
    text: str,
    delete_after_seconds: int | None = None,
) -> None:
    try:
        result = await PublishService.send_temporary(
            type("ModerationContext", (), {"bot": bot})(),
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            delete_after_seconds=delete_after_seconds,
        )
    except Exception as exc:
        log.warning("moderation_notice_send_failed", chat_id=chat_id, error=str(exc))
        return None
    return None


async def check_text_and_record(
    session,
    settings: ChatSettings,
    chat_id: int,
    user_id: int,
    message_id: int | None,
    text: str,
) -> tuple[bool, str]:
    """
    返回 (should_delete, reason)
    """
    if not settings.moderation_enabled:
        return False, ""

    if settings.moderation_block_links and _has_link(text):
        await record_violation(
            session,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            rule="block_links",
            detail="link detected",
            action=settings.moderation_action,
        )
        return True, "block_links"

    keywords = settings.moderation_keywords or []
    for kw in keywords:
        if kw and kw in text:
            await record_violation(
                session,
                chat_id=chat_id,
                user_id=user_id,
                message_id=message_id,
                rule="keyword",
                detail=f"keyword={kw}",
                action=settings.moderation_action,
            )
            return True, "keyword"

    return False, ""
