from __future__ import annotations

import asyncio
import atexit
import httpx
import os
import structlog
import sys

from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from bot.config import get_settings
from bot.db.session import create_database, Database
from bot.handlers.anti_flood import anti_flood_cleanup_job
from bot.handlers.auto_delete import auto_delete_handler
from bot.handlers.auto_delete_config import auto_delete_config_callback
from bot.handlers.moderation import moderation_message_handler
from bot.handlers.start import cancel_command as cancel_callback, private_message_handler, start_command as start_callback
from bot.handlers.verification import new_members_handler, verify_callback, verify_message_handler
from bot.logging_config import configure_logging
from bot.routers import (
    AdminRouter,
    AdsRouter,
    AutoReplyRouter,
    BannedWordRouter,
    GroupRouter,
    InviteRouter,
    LotteryRouter,
    PointsRouter,
    ScheduledRouter,
    SolitaireRouter,
)

log = structlog.get_logger(__name__)


def build_application() -> Application:
    """构建并配置 Telegram Bot 应用"""
    settings = get_settings()
    configure_logging(settings.log_level)

    log.warning("=== BOT APPLICATION BUILDING ===")

    db = create_database(settings.database_url)

    # 构建应用，如果配置了代理则使用代理
    builder = Application.builder().token(settings.bot_token).concurrent_updates(True)

    if settings.proxy_url:
        proxy = httpx.Proxy(url=settings.proxy_url)
        builder = builder.proxy(proxy)

    app = builder.build()

    # 注入依赖
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    # 注册命令处理器
    _register_commands(app)

    # 注册路由器
    _register_routers(app)

    # 注册其他处理器（验证、审核、自动删除等）
    _register_common_handlers(app)

    # 注册错误处理器
    app.add_error_handler(_on_error)

    log.info("=== BOT APPLICATION BUILT SUCCESSFULLY ===")
    return app


def _register_commands(app: Application) -> None:
    """注册命令处理器"""
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("start", start_callback))
    app.add_handler(CommandHandler("cancel", cancel_callback))


def _register_routers(app: Application) -> None:
    """注册所有功能路由器"""
    routers = [
        AdminRouter(),
        LotteryRouter(),
        SolitaireRouter(),
        InviteRouter(),
        AdsRouter(),
        ScheduledRouter(),
        AutoReplyRouter(),
        BannedWordRouter(),
        PointsRouter(),
        GroupRouter(),
    ]

    for router in routers:
        router.register(app)


def _register_common_handlers(app: Application) -> None:
    """注册通用处理器（验证、审核、自动删除等）"""
    # 验证相关
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, verify_message_handler),
        group=1
    )

    # 内容审核
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, moderation_message_handler),
        group=3
    )

    # 自动删除系统消息
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, auto_delete_handler), group=0)

    # 反刷屏检测
    from bot.handlers.anti_flood import anti_flood_message_handler
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, anti_flood_message_handler), group=0)

    # 自动删除配置
    app.add_handler(CallbackQueryHandler(auto_delete_config_callback, pattern=r"^autodel:"))

    # 私聊消息处理（显示群组列表等）- 最低优先级
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_message_handler))


async def _on_error(update, context) -> None:
    """错误处理器"""
    log.exception("bot_error", err=context.error)


# PID 文件路径
_PID_FILE = "/tmp/tggrouprobot.pid"


def _check_single_instance() -> None:
    """确保只有一个 bot 实例在运行"""
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"错误: bot 已经在运行 (PID: {pid})")
            print(f"如需重启，请先停止现有实例: kill {pid}")
            sys.exit(1)
        except (ValueError, OSError):
            try:
                os.remove(_PID_FILE)
            except OSError:
                pass

    with open(_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    def _cleanup_pid_file() -> None:
        try:
            if os.path.exists(_PID_FILE):
                os.remove(_PID_FILE)
        except OSError:
            pass

    atexit.register(_cleanup_pid_file)


def main() -> None:
    """主函数：启动 bot"""
    _check_single_instance()

    app = build_application()
    log.info("bot_starting")

    # 启动定时任务调度器
    async def run_bot_with_scheduler():
        from bot.services.automation.scheduler import Scheduler
        from bot.tasks import (
            AdsTask,
            CleanupTask,
            LotteryTask,
            MessageTask,
            SolitaireTask,
        )

        scheduler = Scheduler(app)
        scheduler.register_tasks([
            LotteryTask(),
            SolitaireTask(),
            AdsTask(),
            MessageTask(),
            CleanupTask(),
        ])

        await scheduler.start()

        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()
        finally:
            await scheduler.stop()

    try:
        asyncio.run(run_bot_with_scheduler())
    except KeyboardInterrupt:
        log.info("bot_shutting_down")


def main_polling() -> None:
    """简化的轮询模式入口（兼容旧版）"""
    app = build_application()
    log.info("bot_starting")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
