from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler
from bot.handlers.admin import admin_callback
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class AdminRouter(BaseRouter):
    """管理功能路由器"""
    
    @property
    def name(self) -> str:
        return "admin"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 命令处理器
        app.add_handler(CommandHandler("admin", admin_callback))
        
        # 回调处理器（所有 adm: 开头的回调）
        app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
        
        log.info(f"{self.name} router registered successfully")
