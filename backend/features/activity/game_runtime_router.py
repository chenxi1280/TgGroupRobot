from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler

from backend.features.activity.game_handler import game_runtime_callback
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)


class GameRuntimeRouter(BaseRouter):
    @property
    def name(self) -> str:
        return "game_runtime"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")
        app.add_handler(CallbackQueryHandler(game_runtime_callback, pattern=r"^gmrun:"))
        log.debug(f"{self.name} router registered successfully")
