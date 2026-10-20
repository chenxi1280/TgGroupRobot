from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters
from backend.features.points.points_handler import (
    get_points_alias_handler,
    mall_callback,
    message_points_handler,
    points_command,
    points_rank_command,
    sign_command,
)
from backend.features.admin.points_config_handler import (
    points_config_cancel_callback,
    points_config_callback,
    points_config_message_handler,
    WAIT_VALUE as PTS_WAIT_VALUE,
)
from backend.app.router_base import BaseRouter
from backend.features.points.mall_order_handler import order_callback, deliver_command, assign_command, order_command
from backend.platform.telegram.conversation_callback_handler import PerUserConversationCallbackHandler

log = structlog.get_logger(__name__)

class PendingPointsInputFilter(filters.MessageFilter):
    """An exited points conversation must not consume another editor's text."""
    def __init__(self, application):
        super().__init__(name="PendingPointsInput")
        self.application = application

    def filter(self, message):
        if message.from_user is None:
            return False
        state = self.application.user_data.get(message.from_user.id, {})
        return bool(state.get("points_edit_field") and state.get("points_edit_chat_id"))


class PointsRouter(BaseRouter):
    """积分功能路由器"""

    @property
    def name(self) -> str:
        return "points"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        app.add_handler(CommandHandler("order", order_command))
        app.add_handler(CommandHandler("deliver", deliver_command))
        app.add_handler(CommandHandler("assign", assign_command))
        app.add_handler(CallbackQueryHandler(order_callback, pattern=r"^morder:"))

        # 命令处理器
        app.add_handler(CommandHandler("sign", sign_command))
        app.add_handler(CommandHandler("points", points_command))
        app.add_handler(CommandHandler("rank", points_rank_command))

        # 积分配置流程对话
        points_config_conv = ConversationHandler(
            entry_points=[PerUserConversationCallbackHandler(points_config_callback, pattern=r"^pts:edit:")],
            states={
                PTS_WAIT_VALUE: [
                    MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & PendingPointsInputFilter(app), points_config_message_handler)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", points_config_cancel_callback),
                PerUserConversationCallbackHandler(points_config_cancel_callback, pattern=r"^pts:home:-?\d+(?::(?:main|display|manage))?$"),
                PerUserConversationCallbackHandler(points_config_cancel_callback, pattern=r"^adm:menu:"),
            ],
            per_chat=True,
        )
        app.add_handler(points_config_conv)

        # 回调处理器
        app.add_handler(CallbackQueryHandler(points_config_callback, pattern=r"^pts:"))
        app.add_handler(CallbackQueryHandler(mall_callback, pattern=r"^mall:"))

        # 注意：积分消息处理器已移至 __main__.py 的 _register_common_handlers 中统一管理

        log.debug(f"{self.name} router registered successfully")
