from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from backend.features.moderation.auto_reply_button_actions import auto_reply_text_button_callback
from backend.features.moderation.auto_reply_handler import (
    auto_reply_cancel_callback,
    auto_reply_config_handler,
    auto_reply_create_start,
    auto_reply_delete_callback,
    auto_reply_delete_confirm_callback,
    auto_reply_delete_do_callback,
    auto_reply_delay_callback,
    auto_reply_delay_set_callback,
    auto_reply_detail_callback,
    auto_reply_edit_callback,
    auto_reply_list_callback,
    auto_reply_menu_callback,
    auto_reply_move_callback,
    auto_reply_preview_callback,
    auto_reply_rule_config_callback,
    auto_reply_set_callback,
    auto_reply_toggle_callback,
)
from backend.app.router_base import BaseRouter

log = structlog.get_logger(__name__)

class AutoReplyRouter(BaseRouter):
    """自动回复功能路由器"""

    @property
    def name(self) -> str:
        return "auto_reply"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        # 回调处理器
        app.add_handler(CallbackQueryHandler(auto_reply_text_button_callback, pattern=r"^arbtn:"))
        app.add_handler(CallbackQueryHandler(auto_reply_create_start, pattern=r"^auto_reply:create"))
        app.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=r"^autoreply:cancel:"))
        app.add_handler(CallbackQueryHandler(auto_reply_list_callback, pattern=r"^auto_reply:list"))
        app.add_handler(CallbackQueryHandler(auto_reply_set_callback, pattern=r"^auto_reply:set:"))
        app.add_handler(CallbackQueryHandler(auto_reply_delay_set_callback, pattern=r"^auto_reply:delay:set:"))
        app.add_handler(CallbackQueryHandler(auto_reply_delay_callback, pattern=r"^auto_reply:delay:"))
        app.add_handler(CallbackQueryHandler(auto_reply_detail_callback, pattern=r"^auto_reply:detail:"))
        app.add_handler(CallbackQueryHandler(auto_reply_preview_callback, pattern=r"^auto_reply:preview:"))
        app.add_handler(CallbackQueryHandler(auto_reply_edit_callback, pattern=r"^auto_reply:edit:"))
        app.add_handler(CallbackQueryHandler(auto_reply_rule_config_callback, pattern=r"^auto_reply:(?:cycle|togglecfg):"))
        app.add_handler(CallbackQueryHandler(auto_reply_move_callback, pattern=r"^auto_reply:move:"))
        app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=r"^auto_reply:toggle:"))
        app.add_handler(CallbackQueryHandler(auto_reply_delete_confirm_callback, pattern=r"^auto_reply:delete:.*:confirm$"))
        app.add_handler(CallbackQueryHandler(auto_reply_delete_do_callback, pattern=r"^auto_reply:delete:.*:do$"))
        app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=r"^auto_reply_toggle_"))
        app.add_handler(CallbackQueryHandler(auto_reply_delete_callback, pattern=r"^auto_reply_delete_"))
        app.add_handler(CallbackQueryHandler(auto_reply_menu_callback, pattern=r"^auto_reply:menu"))

        # 注意：自动回复配置处理器已移至 __main__.py 的 _register_common_handlers 中统一管理

        log.debug(f"{self.name} router registered successfully")
