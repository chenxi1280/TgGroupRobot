"""ChatSettings.module_config JSON 模块配置读写。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import cast, func, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

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
    replace: bool = False,
) -> dict[str, Any]:
    session.add(settings)
    await session.flush()
    # Merge against the row locked by UPDATE, not a possibly stale ORM snapshot.
    # Different modules and different top-level keys cannot erase one another.
    empty = cast({}, JSONB)
    root = func.coalesce(ChatSettings.module_config, empty)
    current = cast(patch, JSONB) if replace else func.coalesce(ChatSettings.module_config[module], empty).op("||")(cast(patch, JSONB))
    merged = root.op("||")(func.jsonb_build_object(module, current))
    result = await session.scalar(update(ChatSettings).where(ChatSettings.chat_id == settings.chat_id)
        .values(module_config=merged).returning(ChatSettings.module_config)
        .execution_options(synchronize_session=False))
    set_committed_value(settings, "module_config", result)
    return _as_dict(_as_dict(result).get(module))


def verification_prompt_fail_open(settings: ChatSettings | None) -> bool:
    """验证提示发送失败时是否放行。默认 True 保持历史行为。"""
    return get_module_bool(
        settings,
        VERIFICATION_MODULE,
        "prompt_fail_open",
        default=DEFAULT_PROMPT_FAIL_OPEN,
    )
