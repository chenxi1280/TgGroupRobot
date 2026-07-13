from __future__ import annotations

from collections.abc import Callable
from typing import Any

from telegram.ext import BaseHandler, CallbackQueryHandler


class PerUserConversationCallbackHandler(BaseHandler):
    """按 chat/user 对话键处理回调，不把对话错误绑定到单条消息。"""

    def __init__(self, callback: Callable, *, pattern: str) -> None:
        self._delegate = CallbackQueryHandler(callback, pattern=pattern)
        self.pattern = self._delegate.pattern
        super().__init__(callback, block=self._delegate.block)

    def check_update(self, update: object) -> bool | object | None:
        return self._delegate.check_update(update)

    async def handle_update(self, update, application, check_result, *, context) -> Any:
        return await self._delegate.handle_update(
            update,
            application,
            check_result,
            context=context,
        )
