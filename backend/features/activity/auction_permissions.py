"""Activate explicit creation policy without reinterpreting historical ignored values."""
from backend.shared.services.permission_service import is_user_admin


def creation_policy(setting) -> str:
    if not getattr(setting, "permission_enforced", False):
        return "all"
    return getattr(setting, "create_permission", "admin")


async def can_create_auction(context, setting, *, chat_id: int, user_id: int) -> bool:
    policy = creation_policy(setting)
    if not setting.enabled:
        return False
    if policy == "all":
        return True
    return policy == "admin" and await is_user_admin(context, chat_id, user_id)
