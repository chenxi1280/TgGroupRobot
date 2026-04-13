from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler

from backend.features.subscription.subscription_handler import (
    subscription_contact_callback,
    subscription_menu_callback,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)


class SubscriptionRouter(BaseRouter):
    @property
    def name(self) -> str:
        return "subscription"

    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        app.add_handler(CallbackQueryHandler(subscription_menu_callback, pattern=r"^sub:menu:-?\d+$"))
        app.add_handler(CallbackQueryHandler(subscription_contact_callback, pattern=r"^sub:contact:-?\d+$"))
        log.info(f"{self.name} router registered successfully")
