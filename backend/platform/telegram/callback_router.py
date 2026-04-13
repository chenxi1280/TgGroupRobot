from __future__ import annotations

from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

CallbackHandler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


class CallbackRouter:
    """Prefix-based callback registry for feature-level callback handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, CallbackHandler] = {}

    def register(self, prefix: str, handler: CallbackHandler) -> None:
        self._handlers[prefix] = handler

    async def dispatch(self, prefix: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        handler = self._handlers.get(prefix)
        if handler is None:
            return False
        await handler(update, context)
        return True

