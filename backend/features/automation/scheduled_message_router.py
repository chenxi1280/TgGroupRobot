"""定时消息任务路由器

提供定时消息任务功能的所有路由注册。
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler
from backend.features.automation.scheduled_message_handler import sm_callback_handler
from backend.app.router_base import BaseRouter


async def _handle_noop(update: Update, context) -> None:
    del context
    if update.callback_query:
        await update.callback_query.answer()


_CALLBACK_PATTERNS = (
    r"^sm:list:", r"^sm:add:", r"^sm:open:", r"^sm:set:", r"^sm:edit:",
    r"^sm:preview:", r"^sm:(history|occ_retry|occ_cancel|occ_replay_confirm|occ_replay_do):",
    r"^sm:del_confirm:", r"^sm:del_do:", r"^sm:del_cancel:",
)


class ScheduledMessageRouter(BaseRouter):
    """定时消息任务功能路由器"""

    @property
    def name(self) -> str:
        return "scheduled_message"

    def register(self, app: Application) -> None:
        for pattern in _CALLBACK_PATTERNS:
            app.add_handler(CallbackQueryHandler(sm_callback_handler, pattern=pattern))
        app.add_handler(CallbackQueryHandler(_handle_noop, pattern=r"^_noop$"))
