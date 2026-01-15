from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from bot.handlers.lottery_handler import (
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

        # 注意：抽奖消息处理器已移至 __main__.py 的 _register_common_handlers 中统一管理

        log.info(f"{self.name} router registered successfully")
