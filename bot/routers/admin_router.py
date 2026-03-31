from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from bot.handlers.admin_handler import admin_callback
from bot.handlers.account_inherit_handler import account_inherit_callback, account_inherit_command
from bot.handlers.garage_forward_handler import garage_forward_channel_post_handler
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
        app.add_handler(CommandHandler("inherit", account_inherit_command))
        
        # 回调处理器（管理后台与联盟/车库转发）
        app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^(adm|ali|gfw|grg|tsearch|crv|auc|btm|gm|guess|act):"))
        app.add_handler(CallbackQueryHandler(account_inherit_callback, pattern=r"^inh:"))

        # 频道消息处理器（车库转发）
        app.add_handler(MessageHandler(filters.ChatType.CHANNEL, garage_forward_channel_post_handler))
        
        log.info(f"{self.name} router registered successfully")
