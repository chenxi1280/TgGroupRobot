from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from backend.features.moderation.banned_word_handler import (
    banned_word_add_start,
    banned_word_cancel_callback,
    banned_word_config_handler,
    banned_word_delete_callback,
    banned_word_list_callback,
    banned_word_menu_callback,
    banned_word_toggle_callback,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)

class BannedWordRouter(BaseRouter):
    """违禁词功能路由器"""

    @property
    def name(self) -> str:
        return "banned_word"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        # 回调处理器
        app.add_handler(CallbackQueryHandler(banned_word_add_start, pattern=r"^banned_word:add"))
        app.add_handler(CallbackQueryHandler(banned_word_cancel_callback, pattern=r"^keywords:cancel:"))
        app.add_handler(CallbackQueryHandler(banned_word_toggle_callback, pattern=r"^banned_word_toggle_"))
        app.add_handler(CallbackQueryHandler(banned_word_delete_callback, pattern=r"^banned_word_delete_"))
        app.add_handler(CallbackQueryHandler(banned_word_menu_callback, pattern=r"^banned_word:menu"))
        app.add_handler(CallbackQueryHandler(banned_word_list_callback, pattern=r"^banned_word:list"))

        # 注意：配置消息已被 MessageDispatcher 的 PrivateConfigHandler 统一处理
        # 此 MessageHandler 已移除，避免重复处理
        # app.add_handler(
        #     MessageHandler(filters.TEXT & ~filters.COMMAND, banned_word_config_handler),
        #     group=0
        # )

        # 注意：违禁词检测已移至 group_message_handler.py 中的统一处理入口

        log.debug(f"{self.name} router registered successfully")
