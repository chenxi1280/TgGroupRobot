"""Web 管理端应用装配。"""
from __future__ import annotations

from fastapi import FastAPI

from backend.features.web_admin.account_router import router as account_router
from backend.features.web_admin.ad_delivery_router import router as ad_delivery_router
from backend.features.web_admin.auth_router import router as auth_router
from backend.features.web_admin.card_router import router as card_router
from backend.features.web_admin.platform_router import router as platform_router
from backend.features.web_admin.verification_timeout_router import router as verification_timeout_router
from backend.platform.config.core.settings import Settings
from backend.platform.db.runtime.session import Database

ADMIN_ROUTERS = (
    auth_router,
    card_router,
    platform_router,
    account_router,
    verification_timeout_router,
    ad_delivery_router,
)


def create_admin_web_app(db: Database, settings: Settings) -> FastAPI:
    app = FastAPI(title="TgGroupRobot Admin", docs_url=None, redoc_url=None)
    app.state.db = db
    app.state.settings = settings
    for router in ADMIN_ROUTERS:
        app.include_router(router)
    return app
