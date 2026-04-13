"""通用验证器函数和工具"""

from __future__ import annotations

import datetime as dt
import re
from enum import Enum
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from backend.shared.services.result import CreateResult

if TYPE_CHECKING:
    from telegram.ext import Application

T = TypeVar("T")


async def validate_user_permission(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    """
    验证用户是否有权限操作

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        用户是否有权限
    """
    from backend.shared.services.permission_service import is_user_admin
    return await is_user_admin(app, chat_id, user_id)


async def validate_bot_permission(
    app: "Application",
    chat_id: int,
    required_permission: str,
) -> bool:
    """
    验证机器人是否有权限

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        required_permission: 需要的权限类型（如 "can_delete_messages"）

    Returns:
        机器人是否有权限
    """
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)

        # 获取机器人成员信息
        bot_member = await chat.get_member(bot.id)

        # 检查权限
        if required_permission == "can_delete_messages":
            return bot_member.can_delete_messages
        elif required_permission == "can_restrict_members":
            return bot_member.can_restrict_members
        elif required_permission == "can_promote_members":
            return bot_member.can_promote_members
        elif required_permission == "is_administrator":
            return bot_member.status in ["administrator", "creator"]
        else:
            return True
    except Exception:
        return False


def validate_positive_number(value: int, field_name: str = "数值") -> tuple[bool, str | None]:
    """
    验证数值是否为正数

    Args:
        value: 要验证的数值
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if value is None:
        return True, None

    if not isinstance(value, (int, float)):
        return False, f"{field_name}必须是数字"

    if value < 0:
        return False, f"{field_name}不能为负数"

    return True, None


def validate_future_time(time: dt.datetime, field_name: str = "时间") -> tuple[bool, str | None]:
    """
    验证时间是否为未来时间

    Args:
        time: 要验证的时间
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if time is None:
        return True, None

    now = dt.datetime.now(dt.timezone.utc)

    if time.tzinfo is None:
        return False, f"{field_name}必须包含时区信息"

    if time <= now:
        return False, f"{field_name}必须是未来时间"

    return True, None


def validate_string_length(
    text: str,
    min_length: int = 0,
    max_length: int = 1000,
    field_name: str = "文本",
) -> tuple[bool, str | None]:
    """
    验证字符串长度

    Args:
        text: 要验证的文本
        min_length: 最小长度
        max_length: 最大长度
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if text is None:
        return True, None

    length = len(text)

    if length < min_length:
        return False, f"{field_name}长度不能少于{min_length}个字符"

    if length > max_length:
        return False, f"{field_name}长度不能超过{max_length}个字符"

    return True, None


async def validate_user_in_group(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    """
    验证用户是否在群组中

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        用户是否在群组中
    """
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)
        member = await chat.get_member(user_id)
        return member is not None
    except Exception:
        return False


async def validate_user_is_admin(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> tuple[bool, str | None]:
    """
    验证用户是否是管理员

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        (是否是管理员, 错误信息)
    """
    is_admin = await validate_user_permission(app, chat_id, user_id)
    if is_admin:
        return True, None
    return False, "需要管理员权限"


# ============================================================================
# 枚举验证
# ============================================================================

def validate_enum(
    value: str,
    enum_class: type[Enum],
    field_name: str = "字段",
) -> tuple[bool, str | None]:
    """
    验证值是否为有效的枚举值

    Args:
        value: 要验证的值
        enum_class: 枚举类
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if value is None:
        return True, None

    valid_values = [e.value for e in enum_class]
    if value not in valid_values:
        return False, f"{field_name}必须是以下值之一: {', '.join(valid_values)}"

    return True, None


# ============================================================================
# 正则验证
# ============================================================================

def validate_regex(
    pattern: str,
    field_name: str = "正则表达式",
) -> tuple[bool, str | None]:
    """
    验证正则表达式是否有效

    Args:
        pattern: 要验证的正则表达式
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if pattern is None:
        return True, None

    try:
        re.compile(pattern)
        return True, None
    except re.error:
        return False, f"{field_name}不是有效的正则表达式"


# ============================================================================
# 数据库唯一性验证
# ============================================================================

async def validate_unique(
    session: AsyncSession,
    model: type,
    filters: dict[str, Any],
    field_name: str = "字段",
    exclude_id: int | None = None,
) -> tuple[bool, str | None]:
    """
    验证记录的唯一性（数据库中是否已存在）

    Args:
        session: 数据库会话
        model: 模型类
        filters: 过滤条件字典
        field_name: 字段名称（用于错误消息）
        exclude_id: 排除的记录ID（用于更新时排除自身）

    Returns:
        (是否唯一, 错误信息)
    """
    from sqlalchemy import select

    stmt = select(model).where(*[
        getattr(model, k) == v for k, v in filters.items()
        if hasattr(model, k)
    ])

    if exclude_id is not None and hasattr(model, 'id'):
        stmt = stmt.where(model.id != exclude_id)

    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        values_str = ", ".join(f"{k}={v}" for k, v in filters.items())
        return False, f"{field_name} ({values_str}) 已存在"

    return True, None


async def validate_exists(
    session: AsyncSession,
    model: type,
    filters: dict[str, Any],
    field_name: str = "记录",
) -> tuple[bool, str | None]:
    """
    验证记录是否存在

    Args:
        session: 数据库会话
        model: 模型类
        filters: 过滤条件字典
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否存在, 错误信息)
    """
    from sqlalchemy import select

    stmt = select(model).where(*[
        getattr(model, k) == v for k, v in filters.items()
        if hasattr(model, k)
    ]).limit(1)

    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is None:
        return False, f"{field_name} 不存在"

    return True, None


# ============================================================================
# 通用字段验证
# ============================================================================

def validate_required(
    value: Any,
    field_name: str = "字段",
) -> tuple[bool, str | None]:
    """
    验证必填字段

    Args:
        value: 要验证的值
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if value is None:
        return False, f"{field_name}不能为空"

    if isinstance(value, str) and not value.strip():
        return False, f"{field_name}不能为空"

    if isinstance(value, (list, dict)) and len(value) == 0:
        return False, f"{field_name}不能为空"

    return True, None


def validate_range(
    value: int | float,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
    field_name: str = "数值",
) -> tuple[bool, str | None]:
    """
    验证数值范围

    Args:
        value: 要验证的数值
        min_value: 最小值（None表示不限制）
        max_value: 最大值（None表示不限制）
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if value is None:
        return True, None

    if min_value is not None and value < min_value:
        return False, f"{field_name}不能小于 {min_value}"

    if max_value is not None and value > max_value:
        return False, f"{field_name}不能大于 {max_value}"

    return True, None


def validate_url(
    url: str,
    field_name: str = "链接",
) -> tuple[bool, str | None]:
    """
    验证URL格式

    Args:
        url: 要验证的URL
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if url is None:
        return True, None

    url_pattern = re.compile(
        r'^https?://'  # http:// 或 https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # 域名
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # 可选端口
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )

    if not url_pattern.match(url):
        return False, f"{field_name}不是有效的URL"

    return True, None


# ============================================================================
# 验证装饰器
# ============================================================================

def validate_params(**validators: Callable[[Any], tuple[bool, str | None]]):
    """
    参数验证装饰器

    用于自动验证函数参数。

    Args:
        **validators: 参数名到验证函数的映射

    Example:
        @validate_params(
            title=lambda x: (bool(x), "标题不能为空" if not x else None),
            count=lambda x: (x > 0, "数量必须大于0" if x <= 0 else None),
        )
        async def create_item(title: str, count: int):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            # 获取函数参数绑定
            from inspect import signature
            sig = signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # 验证每个参数
            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    is_valid, error_msg = validator(value)
                    if not is_valid:
                        raise ValueError(f"参数验证失败: {param_name} - {error_msg}")

            return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            from inspect import signature
            sig = signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            for param_name, validator in validators.items():
                if param_name in bound_args.arguments:
                    value = bound_args.arguments[param_name]
                    is_valid, error_msg = validator(value)
                    if not is_valid:
                        raise ValueError(f"参数验证失败: {param_name} - {error_msg}")

            return func(*args, **kwargs)

        # 根据函数类型选择包装器
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
