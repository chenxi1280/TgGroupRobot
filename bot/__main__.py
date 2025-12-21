from __future__ import annotations

import structlog
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from bot.config import get_settings
from bot.db.session import create_database
from bot.handlers.admin import admin_command, admin_callback
from bot.handlers.ads import ad_command
from bot.handlers.moderation import moderation_message_handler
from bot.handlers.points import points_command, sign_command
from bot.handlers.start import start_command
from bot.handlers.verification import new_members_handler, verify_callback
from bot.logging_config import configure_logging


log = structlog.get_logger(__name__)


def build_application() -> Application:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = create_database(settings.database_url)

    app = (
        Application.builder()
        .token(settings.bot_token)
        .concurrent_updates(True)
        .build()
    )

    # 注入依赖
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    # commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("sign", sign_command))
    app.add_handler(CommandHandler("points", points_command))
    app.add_handler(CommandHandler("ad", ad_command))

    # callbacks
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))

    # group events
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, moderation_message_handler))

    async def on_error(update, context):  # type: ignore[no-untyped-def]
        log.exception("bot_error", err=context.error)

    app.add_error_handler(on_error)
    return app


def main() -> None:
    app = build_application()
    log.info("bot_starting")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


