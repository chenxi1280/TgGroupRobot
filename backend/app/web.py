import logging

from fastapi import FastAPI

from backend.features.mini_app.router import mount_assets, router as member_router
from backend.features.mini_app.verification_router import router as verification_router
from backend.features.web_admin.app import ADMIN_ROUTERS


class MiniAppAccessFilter(logging.Filter):
    def filter(self, record):
        return not record.args[2].startswith("/miniapp/")


def create_web_app(telegram_app, settings) -> FastAPI:
    app = FastAPI(title="TgGroupRobot", docs_url=None, redoc_url=None)
    app.state.db = telegram_app.bot_data["db"]
    app.state.settings = settings
    app.state.telegram_app = telegram_app
    if "scheduler" in telegram_app.bot_data:
        app.state.scheduler = telegram_app.bot_data["scheduler"]
    if settings.admin_web_enabled:
        for router in ADMIN_ROUTERS:
            app.include_router(router)
    if settings.mini_app_enabled:
        logging.getLogger("uvicorn.access").addFilter(MiniAppAccessFilter())
        app.include_router(member_router)
        app.include_router(verification_router)
        mount_assets(app)
    return app
