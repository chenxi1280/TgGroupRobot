from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from bot.handlers.banned_word import (
    banned_word_add_start,
    banned_word_check_handler,
    banned_word_config_handler,
    banned_word_delete_callback,
    banned_word_list_callback,
    banned_word_menu_callback,
    banned_word_toggle_callback,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class BannedWordRouter(BaseRouter):
    """违禁词功能路由器"""
    
    @property
    def name(self) -> str:
        return "banned_word"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 回调处理器
        app.add_handler(CallbackQueryHandler(banned_word_add_start, pattern=r"^banned_word:add"))
        app.add_handler(CallbackQueryHandler(banned_word_toggle_callback, pattern=r"^banned_word_toggle_"))
        app.add_handler(CallbackQueryHandler(banned_word_delete_callback, pattern=r"^banned_word_delete_"))
        app.add_handler(CallbackQueryHandler(banned_word_menu_callback, pattern=r"^banned_word:menu$"))
        app.add_handler(CallbackQueryHandler(banned_word_list_callback, pattern=r"^banned_word:list"))
        
        # 消息处理器（配置和检测）
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, banned_word_config_handler),
            group=0
        )
        
        # 违禁词检测（最高优先级）
        app.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.ALL, banned_word_check_handler),
            group=0
        )
        
        log.info(f"{self.name} router registered successfully")
