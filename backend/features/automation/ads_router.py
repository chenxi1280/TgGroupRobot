from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
from backend.features.automation.ads_handler import (
    ads_cancel_callback,
    ads_create_config_message,
    ads_create_start_callback,
    ads_delete_callback,
    ads_detail_callback,
    ads_cleanup_callback,
    ads_item_input_callback,
    ads_item_preview_callback,
    ads_item_set_callback,
    ads_item_time_callback,
    ads_list_callback,
    ads_menu_callback,
    ads_rules_callback,
    ads_rules_input_callback,
    ads_rules_set_callback,
    ads_send_callback,
    ads_stats_callback,
    ads_toggle_callback,
)
from backend.app.router_base import BaseRouter
from backend.features.automation.ads_operations import (
    ads_delivery_operation_callback,
    ads_history_callback,
    ads_pool_callback,
)

log = structlog.get_logger(__name__)

class AdsRouter(BaseRouter):
    """广告功能路由器"""

    @property
    def name(self) -> str:
        return "ads"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        # 回调处理器
        app.add_handler(CallbackQueryHandler(ads_create_start_callback, pattern=r"^ads:create(?::|$)"))
        app.add_handler(CallbackQueryHandler(ads_cancel_callback, pattern=r"^ads:cancel:"))
        app.add_handler(CallbackQueryHandler(ads_rules_input_callback, pattern=r"^ads:rules:input:"))
        app.add_handler(CallbackQueryHandler(ads_rules_set_callback, pattern=r"^ads:rules:set:"))
        app.add_handler(CallbackQueryHandler(ads_rules_callback, pattern=r"^ads:rules(?::|$)"))
        app.add_handler(CallbackQueryHandler(ads_item_input_callback, pattern=r"^ads:item:input:"))
        app.add_handler(CallbackQueryHandler(ads_item_time_callback, pattern=r"^ads:item:time:"))
        app.add_handler(CallbackQueryHandler(ads_item_set_callback, pattern=r"^ads:item:set:"))
        app.add_handler(CallbackQueryHandler(ads_item_preview_callback, pattern=r"^ads:item:preview:"))
        app.add_handler(CallbackQueryHandler(ads_cleanup_callback, pattern=r"^ads:cleanup(?::|$)"))
        app.add_handler(CallbackQueryHandler(ads_toggle_callback, pattern=r"^ads:toggle(?::|_)\d+$"))
        app.add_handler(CallbackQueryHandler(ads_delete_callback, pattern=r"^ads:delete(?::|_)\d+$"))
        app.add_handler(CallbackQueryHandler(ads_send_callback, pattern=r"^ads:send(?::|_)\d+$"))
        app.add_handler(CallbackQueryHandler(ads_toggle_callback, pattern=r"^ads:item:toggle:"))
        app.add_handler(CallbackQueryHandler(ads_delete_callback, pattern=r"^ads:item:delete:"))
        app.add_handler(CallbackQueryHandler(ads_menu_callback, pattern=r"^ads:menu"))
        app.add_handler(CallbackQueryHandler(ads_list_callback, pattern=r"^ads:list"))
        app.add_handler(CallbackQueryHandler(ads_stats_callback, pattern=r"^ads:stats"))
        app.add_handler(CallbackQueryHandler(ads_detail_callback, pattern=r"^ads:detail:(?:-?\d+:)?\d+$"))
        app.add_handler(CallbackQueryHandler(ads_history_callback, pattern=r"^ads:history:"))
        app.add_handler(CallbackQueryHandler(ads_delivery_operation_callback, pattern=r"^ads:delivery:"))
        app.add_handler(CallbackQueryHandler(ads_pool_callback, pattern=r"^ads:(pool|pool_toggle):"))

        # 注意：配置消息已被 MessageDispatcher 的 PrivateConfigHandler 统一处理
        # 此 MessageHandler 已移除，避免重复处理
        # app.add_handler(
        #     MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, ads_create_config_message),
        #     group=1
        # )

        log.debug(f"{self.name} router registered successfully")
