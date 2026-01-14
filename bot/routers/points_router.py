from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters
from bot.handlers.points import (
    get_points_alias_handler,
    message_points_handler,
    points_command,
    points_rank_command,
    sign_command,
)
from bot.handlers.points_config import (
    points_config_cancel_callback,
    points_config_callback,
    points_config_message_handler,
    WAIT_VALUE as PTS_WAIT_VALUE,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)

class PointsRouter(BaseRouter):
    """积分功能路由器"""
    
    @property
    def name(self) -> str:
        return "points"
    
    def register(self, app: Application) -> None:
        log.info(f"Registering {self.name} router")
        
        # 命令处理器
        app.add_handler(CommandHandler("sign", sign_command))
        app.add_handler(CommandHandler("points", points_command))
        app.add_handler(CommandHandler("rank", points_rank_command))
        
        # 回调处理器
        app.add_handler(CallbackQueryHandler(points_config_callback, pattern=r"^pts:"))
        
        # 积分配置流程对话
        points_config_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(points_config_callback, pattern=r"^pts:edit:")],
            states={
                PTS_WAIT_VALUE: [
                    MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, points_config_message_handler)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", points_config_cancel_callback),
                CallbackQueryHandler(points_config_cancel_callback, pattern=r"^adm:menu:"),
            ],
            per_chat=True,
        )
        app.add_handler(points_config_conv)
        
        # 消息处理器（最低优先级）
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, message_points_handler), group=4)
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, get_points_alias_handler().handle), group=5)
        
        log.info(f"{self.name} router registered successfully")
