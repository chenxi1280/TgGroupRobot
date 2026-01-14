from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from bot.handlers.auto_reply import (
    auto_reply_config_handler,
    auto_reply_create_start,
    auto_reply_delete_callback,
    auto_reply_menu_callback,
    auto_reply_message_handler,
    auto_reply_toggle_callback,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class AutoReplyRouter(BaseRouter):
    """自动回复功能路由器"""
    
    @property
    def name(self) -> str:
        return "auto_reply"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 回调处理器
        app.add_handler(CallbackQueryHandler(auto_reply_create_start, pattern=r"^auto_reply:create"))
        app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=r"^auto_reply_toggle_"))
        app.add_handler(CallbackQueryHandler(auto_reply_delete_callback, pattern=r"^auto_reply_delete_"))
        app.add_handler(CallbackQueryHandler(auto_reply_menu_callback, pattern=r"^auto_reply:menu$"))
        
        # 群组消息处理器（匹配）
        app.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, auto_reply_message_handler),
            group=2
        )
        
        # 配置处理器（私聊和群聊）
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply_config_handler),
            group=1
        )
        
        log.info(f"{self.name} router registered successfully")
