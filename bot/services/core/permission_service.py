from __future__ import annotations

from dataclasses import dataclass

import structlog
from telegram import ChatMember
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from bot.config import get_settings
from bot.db.session import Database
from bot.models.enums import ControlPermissionPolicy
from bot.services.core.chat_service import get_chat_settings

log = structlog.get_logger(__name__)


async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """检查用户是否是群组管理员"""
    try:
        m: ChatMember = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        is_admin = m.status in ("administrator", "creator")
        log.info("check_admin_status", chat_id=chat_id, user_id=user_id, status=m.status, is_admin=is_admin)
        return is_admin
    except TelegramError as e:
        log.warning("failed_to_check_admin_status", chat_id=chat_id, user_id=user_id, error=str(e))
        return False


def get_bot_admin_ids(context: ContextTypes.DEFAULT_TYPE | None = None) -> set[int]:
    """获取 Bot 全局管理员 ID 集合（来自 BOT_ADMIN_IDS）"""
    settings = None
    if context is not None:
        application = getattr(context, "application", None)
        bot_data = getattr(application, "bot_data", None)
        if isinstance(bot_data, dict):
            settings = bot_data.get("settings")
    if settings is None:
        settings = get_settings()
    raw = (settings.bot_admin_ids or "").strip()
    if not raw:
        return set()

    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            log.warning("invalid_bot_admin_id", value=item)
    return ids


def is_bot_admin_user(user_id: int, context: ContextTypes.DEFAULT_TYPE | None = None) -> bool:
    """检查用户是否为 Bot 全局管理员"""
    return user_id in get_bot_admin_ids(context)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str | None = None


class PermissionPolicyService:
    """
    集中式权限决策入口。

    先支持最常见的管理员能力判断：
    - Bot 全局管理员直接放行
    - 常规管理能力由群管理员判断
    - 系统级能力仅允许 Bot 全局管理员
    """

    BOT_ONLY_CAPABILITIES = {"bot_admin", "system", "global_admin"}
    GROUP_ADMIN_CAPABILITIES = {
        "manage",
        "settings",
        "moderation",
        "automation",
        "points",
        "engagement",
        "commerce",
        "external_sync",
        "group_admin",
    }

    @classmethod
    def _get_member_policy_allowed(cls, member: ChatMember, policy: str) -> bool:
        if member.status == "creator":
            return True

        if member.status != "administrator":
            return False

        if policy == ControlPermissionPolicy.all_admins.value:
            return True
        if policy == ControlPermissionPolicy.can_restrict_members.value:
            return bool(getattr(member, "can_restrict_members", False))
        if policy == ControlPermissionPolicy.can_change_info.value:
            return bool(getattr(member, "can_change_info", False))
        if policy == ControlPermissionPolicy.can_promote_members.value:
            return bool(getattr(member, "can_promote_members", False))
        if policy == ControlPermissionPolicy.owner_only.value:
            return False
        return True

    @classmethod
    async def _resolve_chat_policy(
        cls,
        context: ContextTypes.DEFAULT_TYPE | None,
        chat_id: int,
    ) -> str:
        default_policy = ControlPermissionPolicy.can_promote_members.value
        if context is None:
            return default_policy

        db: Database | None = context.application.bot_data.get("db")
        if db is None:
            return default_policy

        try:
            async with db.session_factory() as session:
                settings = await get_chat_settings(session, chat_id)
                await session.commit()
            return getattr(
                settings,
                "control_permission_policy",
                default_policy,
            ) or default_policy
        except Exception as exc:  # pragma: no cover - defensive fallback
            log.warning("permission_policy_resolve_failed", chat_id=chat_id, error=str(exc))
            return default_policy

    @classmethod
    async def can_manage(
        cls,
        context: ContextTypes.DEFAULT_TYPE | None,
        chat_id: int,
        user_id: int,
        capability: str = "manage",
    ) -> bool:
        decision = await cls.evaluate(context, chat_id, user_id, capability=capability)
        return decision.allowed

    @classmethod
    async def evaluate(
        cls,
        context: ContextTypes.DEFAULT_TYPE | None,
        chat_id: int,
        user_id: int,
        capability: str = "manage",
    ) -> PermissionDecision:
        if is_bot_admin_user(user_id, context):
            return PermissionDecision(True, "bot_admin")

        if capability in cls.BOT_ONLY_CAPABILITIES:
            return PermissionDecision(False, "bot_admin_required")

        if capability not in cls.GROUP_ADMIN_CAPABILITIES and capability != "manage":
            return PermissionDecision(False, "unknown_capability")

        if context is None:
            return PermissionDecision(False, "context_required")

        try:
            if not hasattr(context, "bot") or context.bot is None:
                is_admin = await is_user_admin(context, chat_id, user_id)
                return PermissionDecision(True, "group_admin") if is_admin else PermissionDecision(False, "group_admin_required")

            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status not in ("administrator", "creator"):
                return PermissionDecision(False, "group_admin_required")

            policy = await cls._resolve_chat_policy(context, chat_id)
            if cls._get_member_policy_allowed(member, policy):
                return PermissionDecision(True, "group_admin")
            return PermissionDecision(False, "group_admin_required")
        except Exception as exc:  # pragma: no cover - defensive guard
            log.warning("permission_policy_check_failed", chat_id=chat_id, user_id=user_id, error=str(exc))
            return PermissionDecision(False, "permission_check_failed")

    @classmethod
    async def require_manage(
        cls,
        context: ContextTypes.DEFAULT_TYPE | None,
        chat_id: int,
        user_id: int,
        capability: str = "manage",
    ) -> tuple[bool, str | None]:
        """返回 (allowed, short_error_text)，方便 handler 统一短提示。"""
        decision = await cls.evaluate(context, chat_id, user_id, capability=capability)
        if decision.allowed:
            return True, None

        message_map = {
            "bot_admin_required": "需要更高权限",
            "group_admin_required": "需要管理员权限",
            "context_required": "上下文不可用",
            "permission_check_failed": "权限检查失败",
            "unknown_capability": "无效权限配置",
        }
        return False, message_map.get(decision.reason or "", "没有权限")
