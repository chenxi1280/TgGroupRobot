from __future__ import annotations

import structlog
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.handlers.solitaire import (
    solitaire_cancel_callback,
    solitaire_close_callback,
    solitaire_create_config_message,
    solitaire_create_start_callback,
    solitaire_delete_callback,
    solitaire_detail_callback,
    solitaire_join_message_handler,
    solitaire_list_callback,
    solitaire_menu_callback,
    solitaire_refresh_callback,
    solitaire_stats_callback,
    join_solitaire_callback,
)
from bot.handlers.solitaire import solitaire_create_start_callback as solitaire_create_start
from bot.routers.base import BaseRouter

# ConversationHandler 状态常量
WAIT_CONFIG = "config"

log = structlog.get_logger(__name__)


class SolitaireRouter(BaseRouter):
    """接龙功能路由器"""

    @property
    def name(self) -> str:
        return "solitaire"

    def register(self, app: Application) -> None:
        """注册接龙相关的所有处理器"""
        log.info(f"Registering {self.name} router")

        # 回调处理器
        app.add_handler(CallbackQueryHandler(solitaire_menu_callback, pattern=r"^sol:menu$"))
        app.add_handler(CallbackQueryHandler(solitaire_list_callback, pattern=r"^sol:list"))
        app.add_handler(CallbackQueryHandler(solitaire_stats_callback, pattern=r"^sol:stats"))
        app.add_handler(CallbackQueryHandler(solitaire_detail_callback, pattern=r"^sol:detail:"))
        app.add_handler(CallbackQueryHandler(solitaire_refresh_callback, pattern=r"^sol:refresh:"))
        app.add_handler(CallbackQueryHandler(solitaire_close_callback, pattern=r"^sol:close:"))
        app.add_handler(CallbackQueryHandler(solitaire_delete_callback, pattern=r"^sol:delete:"))
        app.add_handler(CallbackQueryHandler(join_solitaire_callback, pattern=r"^join_solitaire:"))

        # 接龙创建流程对话
        solitaire_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(solitaire_create_start_callback, pattern=r"^sol:create")],
            states={
                WAIT_CONFIG: [
                    MessageHandler(
                        (filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND,
                        solitaire_create_config_message
                    )
                ],
            },
            fallbacks=[
                CommandHandler("cancel", solitaire_cancel_callback),
                CallbackQueryHandler(solitaire_cancel_callback, pattern=r"^sol:cancel$"),
            ],
            per_chat=True,
        )
        app.add_handler(solitaire_conv)

        # 接龙参与消息处理器（优先级0）
        app.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, solitaire_join_message_handler),
            group=0
        )

        log.info(f"{self.name} router registered successfully")
