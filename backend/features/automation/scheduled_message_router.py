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


class ScheduledMessageRouter(BaseRouter):
    """定时消息任务功能路由器"""

    @property
    def name(self) -> str:
        return "scheduled_message"

    def register(self, app: Application) -> None:
        app.add_handler(
            CallbackQueryHandler(
                sm_callback_handler,
                pattern=(
                    r"^sm:(?:list|add|open|set|edit|preview|history|occ_retry|"
                    r"occ_cancel|occ_replay_confirm|occ_replay_do|del_confirm|"
                    r"del_do|del_cancel):"
                ),
            )
        )
        app.add_handler(CallbackQueryHandler(_handle_noop, pattern=r"^_noop$"))
