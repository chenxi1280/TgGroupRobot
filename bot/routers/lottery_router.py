from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from bot.handlers.lottery import (
    draw_lottery_callback,
    join_lottery_callback,
    lottery_create_start,
    lottery_message_handler,
    manual_draw_complete_callback,
    manual_draw_menu_callback,
    manual_draw_select_prize_callback,
    manual_draw_select_winner_callback,
    manual_draw_winner_page_callback,
)
from bot.routers.base import BaseRouter

log = structlog.get_logger(__name__)


class LotteryRouter(BaseRouter):
    """抽奖功能路由器"""

    @property
    def name(self) -> str:
        return "lottery"

    def register(self, app: Application) -> None:
        """注册抽奖相关的所有处理器"""
        log.info(f"Registering {self.name} router")

        # 回调处理器
        app.add_handler(CallbackQueryHandler(lottery_create_start, pattern=r"^lot:create"))
        app.add_handler(CallbackQueryHandler(join_lottery_callback, pattern=r"^join_lottery_"))
        app.add_handler(CallbackQueryHandler(draw_lottery_callback, pattern=r"^draw_lottery_"))
        app.add_handler(CallbackQueryHandler(manual_draw_select_prize_callback, pattern=r"^lot:select_prize:"))
        app.add_handler(CallbackQueryHandler(manual_draw_select_winner_callback, pattern=r"^lot:select_winner:"))
        app.add_handler(CallbackQueryHandler(manual_draw_complete_callback, pattern=r"^lot:complete_manual_draw:"))
        app.add_handler(CallbackQueryHandler(manual_draw_winner_page_callback, pattern=r"^lot:winner_page:"))
        app.add_handler(CallbackQueryHandler(manual_draw_menu_callback, pattern=r"^lot:draw_menu:"))

        # 群组消息处理器（优先级1，高于普通消息）
        app.add_handler(
            MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, lottery_message_handler),
            group=1
        )

        # 私聊消息处理器（优先级0，创建流程）
        app.add_handler(
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, lottery_message_handler),
            group=0
        )

        log.info(f"{self.name} router registered successfully")
