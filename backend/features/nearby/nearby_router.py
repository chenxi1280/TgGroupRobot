from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from backend.features.nearby.nearby_handler import (
    list_command,
    mydata_command,
    nearby_callback,
    nearby_command,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)


class NearbyRouter(BaseRouter):
    """周边资料功能路由器"""

    @property
    def name(self) -> str:
        return "nearby"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        app.add_handler(CommandHandler("mydata", mydata_command))
        app.add_handler(CommandHandler("nearby", nearby_command))
        app.add_handler(CommandHandler("list", list_command))

        app.add_handler(CallbackQueryHandler(nearby_callback, pattern=r"^lbs:"))

        log.debug(f"{self.name} router registered successfully")

