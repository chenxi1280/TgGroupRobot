from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from bot.handlers.scheduled_handler import (
    scheduled_cancel_callback,
    scheduled_create_start,
    scheduled_delete_callback,
    scheduled_list_callback,
    scheduled_message_handler,
    scheduled_menu_callback,
    scheduled_toggle_callback,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class ScheduledRouter(BaseRouter):
    """定时消息功能路由器"""
    
    @property
    def name(self) -> str:
        return "scheduled"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 回调处理器
        app.add_handler(CallbackQueryHandler(scheduled_create_start, pattern=r"^scheduled:create"))
        app.add_handler(CallbackQueryHandler(scheduled_cancel_callback, pattern=r"^scheduled:cancel:"))
        app.add_handler(CallbackQueryHandler(scheduled_toggle_callback, pattern=r"^scheduled_toggle_"))
        app.add_handler(CallbackQueryHandler(scheduled_delete_callback, pattern=r"^scheduled_delete_"))
        app.add_handler(CallbackQueryHandler(scheduled_menu_callback, pattern=r"^scheduled:menu"))
        app.add_handler(CallbackQueryHandler(scheduled_list_callback, pattern=r"^scheduled:list"))

        # 注意：定时消息处理器已移至 __main__.py 的 _register_common_handlers 中统一管理

        log.info(f"{self.name} router registered successfully")
