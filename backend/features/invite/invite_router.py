from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters
from backend.features.invite.invite_link_handler import (
    invite_link_cancel_callback,
    invite_link_buttons_callback,
    invite_link_cover_callback,
    invite_link_create_expire_message,
    invite_link_create_limit_message,
    invite_link_create_name_message,
    invite_link_create_start_callback,
    invite_link_delete_callback,
    invite_link_detail_callback,
    invite_link_export_callback,
    invite_link_home_callback,
    invite_link_list_callback,
    invite_link_menu_callback,
    invite_link_mode_callback,
    invite_link_preview_callback,
    invite_link_reset_callback,
    invite_link_toggle_callback,
    invite_link_refresh_callback,
    invite_link_revoke_callback,
    invite_link_stats_callback,
    invite_link_text_callback,
    link_command,
    link_stat_command,
    user_invite_create_callback,
    user_invite_list_callback,
    user_invite_menu_callback,
    user_invite_rank_callback,
    WAIT_NAME, WAIT_LIMIT, WAIT_EXPIRE,
)
from backend.app.router_base import BaseRouter
from backend.platform.telegram.conversation_callback_handler import PerUserConversationCallbackHandler

log = structlog.get_logger(__name__)

class InviteRouter(BaseRouter):
    """邀请链接功能路由器"""

    @property
    def name(self) -> str:
        return "invite"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        # 命令处理器
        app.add_handler(CommandHandler("link", link_command))
        app.add_handler(CommandHandler("link_stat", link_stat_command))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.Regex(r"^邀请$"), link_command))
        app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.Regex(r"^邀请统计$"), link_stat_command))

        # 回调处理器
        app.add_handler(CallbackQueryHandler(invite_link_menu_callback, pattern=r"^inv:menu$"))
        app.add_handler(CallbackQueryHandler(invite_link_home_callback, pattern=r"^inv:home:"))
        app.add_handler(CallbackQueryHandler(invite_link_toggle_callback, pattern=r"^inv:toggle:"))
        app.add_handler(CallbackQueryHandler(invite_link_mode_callback, pattern=r"^inv:mode:"))
        app.add_handler(CallbackQueryHandler(invite_link_cover_callback, pattern=r"^inv:cover"))
        app.add_handler(CallbackQueryHandler(invite_link_text_callback, pattern=r"^inv:text"))
        app.add_handler(CallbackQueryHandler(invite_link_buttons_callback, pattern=r"^inv:buttons"))
        app.add_handler(CallbackQueryHandler(invite_link_preview_callback, pattern=r"^inv:preview"))
        app.add_handler(CallbackQueryHandler(invite_link_reset_callback, pattern=r"^inv:reset:"))
        app.add_handler(CallbackQueryHandler(invite_link_export_callback, pattern=r"^inv:export"))
        app.add_handler(CallbackQueryHandler(invite_link_list_callback, pattern=r"^inv:list"))
        app.add_handler(CallbackQueryHandler(invite_link_stats_callback, pattern=r"^inv:stats"))
        app.add_handler(CallbackQueryHandler(invite_link_detail_callback, pattern=r"^inv:detail:\d+(?::-?\d+)?$"))
        app.add_handler(CallbackQueryHandler(invite_link_refresh_callback, pattern=r"^inv:refresh:\d+(?::-?\d+)?$"))
        app.add_handler(CallbackQueryHandler(invite_link_revoke_callback, pattern=r"^inv:revoke:\d+(?::-?\d+)?$"))
        app.add_handler(CallbackQueryHandler(invite_link_delete_callback, pattern=r"^inv:delete:\d+(?::-?\d+)?$"))

        # 用户邀请链接回调
        app.add_handler(CallbackQueryHandler(user_invite_menu_callback, pattern=r"^inv:user:menu:\-?\d+$"))
        app.add_handler(CallbackQueryHandler(user_invite_create_callback, pattern=r"^inv:user:create:\-?\d+$"))
        app.add_handler(CallbackQueryHandler(user_invite_list_callback, pattern=r"^inv:user:list:\-?\d+$"))
        app.add_handler(CallbackQueryHandler(user_invite_rank_callback, pattern=r"^inv:user:rank:\-?\d+$"))

        # 邀请链接创建流程对话
        invite_link_conv = ConversationHandler(
            entry_points=[PerUserConversationCallbackHandler(invite_link_create_start_callback, pattern=r"^inv:create")],
            states={
                WAIT_NAME: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_name_message)],
                WAIT_LIMIT: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_limit_message)],
                WAIT_EXPIRE: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_expire_message)],
            },
            fallbacks=[
                CommandHandler("cancel", invite_link_cancel_callback),
                PerUserConversationCallbackHandler(invite_link_cancel_callback, pattern=r"^inv:cancel$"),
            ],
            per_chat=True,
        )
        app.add_handler(invite_link_conv)

        log.debug(f"{self.name} router registered successfully")
