from __future__ import annotations
import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from backend.features.admin.admin_handler import admin_callback, admin_command
from backend.features.admin.garage.teacher_self import teacher_self_callback
from backend.features.invite.account_inherit_handler import account_inherit_callback, account_inherit_command
from backend.features.garage.garage_forward_handler import garage_forward_channel_post_handler
from backend.shared.button_layout_editor import button_layout_editor_callback
from backend.app.router_base import BaseRouter
from backend.features.admin.draft_pages import draft_callback
from backend.features.activity.publication_recovery import verify_publication_command

log = structlog.get_logger(__name__)

class AdminRouter(BaseRouter):
    """管理功能路由器"""

    @property
    def name(self) -> str:
        return "admin"

    def register(self, app: Application) -> None:
        log.debug(f"Registering {self.name} router")

        from backend.features.activity.date_picker_handler import activity_date_callback
        app.add_handler(CallbackQueryHandler(activity_date_callback, pattern=r"^acal:"))

        from backend.shared.datetime_picker_handler import datetime_picker_callback
        app.add_handler(CallbackQueryHandler(datetime_picker_callback, pattern=r"^dtp:"))

        from backend.features.admin.moderation.permission_profiles import permission_profile_callback
        app.add_handler(CallbackQueryHandler(permission_profile_callback, pattern=r"^gperm:"))
        from backend.features.admin.points.sign_feedback_config import sign_feedback_callback
        app.add_handler(CallbackQueryHandler(sign_feedback_callback, pattern=r"^signcfg:"))
        from backend.features.admin.list_browser import list_browser_callback
        app.add_handler(CallbackQueryHandler(list_browser_callback, pattern=r"^mlist:"))

        from backend.features.admin.points.level_tag_views import level_tag_callback
        app.add_handler(CallbackQueryHandler(level_tag_callback, pattern=r"^ltag:"))
        from backend.features.admin.notice_views import notice_callback
        from backend.features.admin.effect_views import effect_callback
        from backend.features.automation.notice_consent import consent_callback
        app.add_handler(CallbackQueryHandler(notice_callback, pattern=r"^(gnote|anote):"))
        app.add_handler(CallbackQueryHandler(effect_callback, pattern=r"^eff:"))
        from backend.features.admin.alliance_effect_views import alliance_effect_callback
        app.add_handler(CallbackQueryHandler(alliance_effect_callback,pattern=r'^asan:'))
        app.add_handler(CallbackQueryHandler(consent_callback, pattern=r"^ncons:"))

        # 命令处理器
        app.add_handler(CommandHandler("admin", admin_command))
        app.add_handler(CommandHandler("verifypublication", verify_publication_command))
        app.add_handler(CommandHandler("inherit", account_inherit_command))

        app.add_handler(CallbackQueryHandler(draft_callback, pattern=r"^draft:"))

        # 回调处理器（管理后台与联盟/车库转发）
        app.add_handler(CallbackQueryHandler(button_layout_editor_callback, pattern=r"^btned:"))
        app.add_handler(CallbackQueryHandler(teacher_self_callback, pattern=r"^teacher:"))
        app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^(adm|ali|gfw|grg|tsearch|crv|auc|btm|gm|guess|act|qpub):"))
        app.add_handler(CallbackQueryHandler(account_inherit_callback, pattern=r"^inh:"))

        # 频道消息处理器（车库转发）
        app.add_handler(MessageHandler(filters.ChatType.CHANNEL, garage_forward_channel_post_handler))

        log.debug(f"{self.name} router registered successfully")
