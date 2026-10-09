"""ChatSettings.module_config JSON 模块配置读写。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSettings

VERIFICATION_MODULE = "verification"
DEFAULT_PROMPT_FAIL_OPEN = True


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def get_module_config(settings: ChatSettings | None, module: str) -> dict[str, Any]:
    if settings is None:
        return {}
    root = _as_dict(getattr(settings, "module_config", None))
    return _as_dict(root.get(module))


def get_module_bool(
    settings: ChatSettings | None,
    module: str,
    key: str,
    *,
    default: bool,
) -> bool:
    config = get_module_config(settings, module)
    if key not in config:
        return default
    value = config.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def update_module_config(
    session: AsyncSession,
    settings: ChatSettings,
    *,
    module: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    root = _as_dict(getattr(settings, "module_config", None))
    current = _as_dict(root.get(module))
    current.update(patch)
    root[module] = current
    settings.module_config = deepcopy(root)
    session.add(settings)
    await session.flush()
    return current


def verification_prompt_fail_open(settings: ChatSettings | None) -> bool:
    """验证提示发送失败时是否放行。默认 True 保持历史行为。"""
    return get_module_bool(
        settings,
        VERIFICATION_MODULE,
        "prompt_fail_open",
        default=DEFAULT_PROMPT_FAIL_OPEN,
    )
