"""Handler 基类

提供统一的 Handler 处理模板，减少重复代码。
"""
from __future__ import annotations

import structlog
from abc import ABC, abstractmethod
from telegram import Update
from telegram.ext import ContextTypes

from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.handlers.base.message_helper import MessageHelper
from backend.shared.handlers.base.permission import PermissionHelper

log = structlog.get_logger(__name__)


class BaseHandler(ABC):
    """Handler 基类

    提供 Handler 处理的模板方法，封装通用流程：
    1. 验证必要数据
    2. 解析目标群组
    3. 检查权限（可选）
    4. 执行具体处理逻辑（由子类实现）

    子类可以选择性地重写模板方法的各个步骤。
    """

    def __init__(self) -> None:
        """初始化 Handler 基类"""
        self.permission = PermissionHelper()
        self.chat_resolver = ChatResolver()
        self.message_helper = MessageHelper()
        self.permission_helper = PermissionHelper()  # 兼容旧代码

    async def handle_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        require_admin: bool = True,
        admin_error_message: str | None = None,
    ) -> int | None:
        """统一回调处理模板方法

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            require_admin: 是否要求管理员权限（默认 True）
            admin_error_message: 管理员权限错误提示（可选）

        Returns:
            int | None: 目标群组 ID，如果处理失败返回 None
        """
        # 1. 验证必要数据
        if not self._validate_update(update):
            return None

        # 2. 解析目标群组
        target_chat_id = await self.chat_resolver.resolve_target_chat(update, context)
        if target_chat_id is None:
            return None

        # 3. 检查权限（可选）
        if require_admin:
            if not await self.permission.require_admin(
                update,
                context,
                target_chat_id,
                error_message=admin_error_message,
            ):
                return None

        # 4. 执行具体处理（由子类实现）
        await self.process(update, context, target_chat_id)

        return target_chat_id

    def _validate_update(self, update: Update) -> bool:
        """验证更新对象是否包含必要数据

        Args:
            update: Telegram 更新对象

        Returns:
            bool: 是否验证通过
        """
        if update.effective_user is None:
            log.warning("update_missing_effective_user")
            return False
        return True

    @abstractmethod
    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """执行具体的处理逻辑

        由子类实现具体的业务逻辑。

        Args:
            update: Telegram 更新对象
            context: Bot 上下文
            target_chat_id: 目标群组 ID
        """
        raise NotImplementedError
