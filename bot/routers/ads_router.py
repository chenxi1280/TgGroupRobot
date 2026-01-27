from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from bot.handlers.ads_handler import (
    ads_cancel_callback,
    ads_create_config_message,
    ads_create_start_callback,
    ads_delete_callback,
    ads_detail_callback,
    ads_list_callback,
    ads_menu_callback,
    ads_send_callback,
    ads_stats_callback,
    ads_toggle_callback,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class AdsRouter(BaseRouter):
    """广告功能路由器"""
    
    @property
    def name(self) -> str:
        return "ads"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 回调处理器
        app.add_handler(CallbackQueryHandler(ads_create_start_callback, pattern=r"^ads:create"))
        app.add_handler(CallbackQueryHandler(ads_cancel_callback, pattern=r"^ads:cancel:"))
        app.add_handler(CallbackQueryHandler(ads_toggle_callback, pattern=r"^ads:toggle_"))
        app.add_handler(CallbackQueryHandler(ads_delete_callback, pattern=r"^ads:delete_"))
        app.add_handler(CallbackQueryHandler(ads_send_callback, pattern=r"^ads:send_"))
        app.add_handler(CallbackQueryHandler(ads_menu_callback, pattern=r"^ads:menu"))
        app.add_handler(CallbackQueryHandler(ads_list_callback, pattern=r"^ads:list"))
        app.add_handler(CallbackQueryHandler(ads_stats_callback, pattern=r"^ads:stats"))
        app.add_handler(CallbackQueryHandler(ads_detail_callback, pattern=r"^ads:detail:\d+$"))
        
        # 注意：配置消息已被 MessageDispatcher 的 PrivateConfigHandler 统一处理
        # 此 MessageHandler 已移除，避免重复处理
        # app.add_handler(
        #     MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ads_create_config_message),
        #     group=1
        # )
        
        log.info(f"{self.name} router registered successfully")
