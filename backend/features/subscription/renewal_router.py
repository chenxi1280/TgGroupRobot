from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from backend.features.subscription.renewal_handler import renew_callback, renew_command
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)


class RenewalRouter(BaseRouter):
    @property
    def name(self) -> str:
        return "renewal"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")
        app.add_handler(CommandHandler("renew", renew_command))
        app.add_handler(CallbackQueryHandler(renew_callback, pattern=r"^renew:"))
        log.debug(f"{self.name} router registered successfully")
