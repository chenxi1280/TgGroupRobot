from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler
from backend.features.group_ops.chat_group_handler import (
    chat_group_admin_callback,
    chat_group_list_callback,
    chat_group_refresh_callback,
    chat_group_select_callback,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)

class GroupRouter(BaseRouter):
    """群组管理路由器"""

    @property
    def name(self) -> str:
        return "group"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        # 群组切换回调处理器（私聊功能）
        app.add_handler(CallbackQueryHandler(chat_group_list_callback, pattern=r"^group:list"))
        app.add_handler(CallbackQueryHandler(chat_group_select_callback, pattern=r"^group:select:\-?\d+$"))
        app.add_handler(CallbackQueryHandler(chat_group_refresh_callback, pattern=r"^group:refresh"))
        app.add_handler(CallbackQueryHandler(chat_group_admin_callback, pattern=r"^group:admin:\-?\d+$"))

        log.debug(f"{self.name} router registered successfully")
