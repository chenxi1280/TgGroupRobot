"""验证功能路由器"""
from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler

from backend.features.verification.verification_handler import (
    admin_verify_callback,
    new_members_handler,
    verification_cancel_callback,
    verification_config_handler,
    verify_callback,
    verify_message_handler,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)


class VerificationRouter(BaseRouter):
    """验证功能路由器"""

    @property
    def name(self) -> str:
        return "verification"

    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")

        # 注册验证配置取消回调
        app.add_handler(CallbackQueryHandler(verification_cancel_callback, pattern=r"^verification:cancel:"))

        # 验证配置回调已移至 admin_handler 处理（使用 adm:vfy_config 格式）
        # 验证相关回调（已在 __main__.py 中注册，这里保留引用）
        # app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
        # app.add_handler(CallbackQueryHandler(admin_verify_callback, pattern=r"^adm_vfy:"))
        # app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))

        log.info(f"{self.name} router registered successfully")
