"""Handler 装饰器工具

提供常用装饰器，简化 Handler 层的重复代码。
"""
from __future__ import annotations

import functools
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.permission_service import is_user_admin
from backend.shared.chat_context import PrivateChatContext

log = structlog.get_logger(__name__)


def with_db_session(func):
    """数据库会话管理装饰器

    自动创建和管理数据库会话，处理 commit。

    Usage:
        @with_db_session
        async def my_handler(update, context, db, session):
            # session 已创建，自动 commit
            pass

    注意：
        - 装饰的函数必须接受 (update, context, db, session) 参数
        - session 会自动提交，无需手动调用 session.commit()
        - 如果发生异常，会自动回滚

    Args:
        func: 被装饰的函数

    Returns:
        包装后的异步函数
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            try:
                result = await func(update, context, db, session)
                await session.commit()
                return result
            except Exception as e:
                await session.rollback()
                log.error("db_session_error", function=func.__name__, error=str(e))
                raise

    return wrapper


def with_db_session_no_auto_commit(func):
    """数据库会话管理装饰器（不自动 commit）

    自动创建数据库会话，但不自动提交，由业务逻辑控制。

    Usage:
        @with_db_session_no_auto_commit
        async def my_handler(update, context, db, session):
            # 需要手动调用 await session.commit()
            pass

    注意：
        - 装饰的函数必须接受 (update, context, db, session) 参数
        - 需要手动调用 session.commit()

    Args:
        func: 被装饰的函数

    Returns:
        包装后的异步函数
    """

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            return await func(update, context, db, session)

    return wrapper


def require_admin_permission(
    *,
    allow_private: bool = False,
    error_message_select_chat: str = "请先选择一个群组",
    error_message_no_permission: str = "你没有该群组的管理权限",
    error_message_private_only: str = "此功能仅限私聊使用",
):
    """管理员权限检查装饰器

    自动检查用户是否为管理员，并解析 target_chat_id。

    Usage:
        @require_admin_permission()
        async def my_handler(update, context, target_chat_id):
            # 已检查权限，target_chat_id 已解析
            pass

    Args:
        allow_private: 是否允许私聊触发（默认 False）
        error_message_select_chat: 未选择群组时的错误提示
        error_message_no_permission: 无权限时的错误提示
        error_message_private_only: 非私聊时的错误提示

    Returns:
        装饰器函数
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # 验证必要数据
            if update.effective_user is None or update.effective_chat is None:
                return None

            user = update.effective_user
            chat = update.effective_chat

            # 如果只允许私聊
            if allow_private and chat.type != "private":
                if update.effective_message:
                    await update.effective_message.reply_text(error_message_private_only)
                return None

            # 解析目标群组并检查权限
            target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
                update,
                context,
                error_message_select_chat=error_message_select_chat,
                error_message_no_permission=error_message_no_permission,
            )

            if target_chat_id is None:
                return None

            return await func(update, context, target_chat_id)

        return wrapper

    return decorator


def resolve_target_chat(
    *,
    error_message: str = "请先选择一个群组",
):
    """解析目标群组 ID 装饰器（不检查权限）

    自动解析私聊/群聊场景的目标群组 ID，不进行权限检查。

    Usage:
        @resolve_target_chat()
        async def my_handler(update, context, target_chat_id):
            # target_chat_id 已解析
            pass

    Args:
        error_message: 未选择群组时的错误提示

    Returns:
        装饰器函数
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            target_chat_id = await PrivateChatContext.require_current_chat(
                update, context, error_message
            )

            if target_chat_id is None:
                return None

            return await func(update, context, target_chat_id)

        return wrapper

    return decorator
