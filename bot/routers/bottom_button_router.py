from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler

from bot.handlers.bottom_button_handler import bottom_button_runtime_callback
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)


class BottomButtonRouter(BaseRouter):
    @property
    def name(self) -> str:
        return "bottom_button"

    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        app.add_handler(CallbackQueryHandler(bottom_button_runtime_callback, pattern=r"^btmrun:"))
        log.info(f"{self.name} router registered successfully")
