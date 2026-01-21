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
from bot.handlers.anti_flood_handler import anti_flood_cleanup_job
from bot.handlers.auto_delete_handler import auto_delete_handler
from bot.handlers.auto_delete_config_handler import auto_delete_config_callback
from bot.handlers.dispatcher import MessageDispatcher
from bot.handlers.start_handler import cancel_command as cancel_callback, start_command as start_callback
from bot.handlers.verification_handler import admin_verify_callback, new_members_handler, verify_callback
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
    VerificationRouter,
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
        VerificationRouter(),
    ]

    for router in routers:
        router.register(app)


def _register_common_handlers(app: Application) -> None:
    """注册通用处理器（验证、审核、自动删除等）"""
    log.warning("=== REGISTERING COMMON HANDLERS ===")

    # ==================== Group -2: 统一消息分发入口（最高优先级）====================
    log.warning("=== REGISTERING GROUP -2: MESSAGE DISPATCHER ===")
    # 统一消息分发器：根据消息来源（私聊/群聊）和用户状态，分发到对应的处理器
    # 这是所有文本消息的统一入口
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, MessageDispatcher().dispatch),
        group=-2
    )
    log.warning("=== MESSAGE DISPATCHER REGISTERED (GROUP -2) ===")

    # ==================== Group -1: 核心功能（已被分发器接管，保留兼容）====================
    log.warning("=== REGISTERING GROUP -1: CORE FUNCTIONALITY ===")
    # 注意：以下处理器已被 MessageDispatcher 接管，保留作为兼容性备份
    # 统一消息处理入口（违禁词检测 + 自动回复）
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT, unified_group_message_handler),
    #     group=-1
    # )
    # log.warning("=== UNIFIED_GROUP_MESSAGE_HANDLER REGISTERED (GROUP -1) ===")

    # 验证配置处理器（已被 MessageDispatcher 的 PrivateConfigHandler 接管）
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, verification_config_handler),
    #     group=-1
    # )

    # 自动回复配置处理器（已被 MessageDispatcher 的 PrivateConfigHandler 接管）
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply_config_handler),
    #     group=-1
    # )

    # ==================== 以下处理器已被 MessageDispatcher 接管 ====================
    # 注意：以下 MessageHandler 现在由 GroupMessageHandler 统一调用，不需要单独注册

    # 群聊核心功能（违禁词检测 + 自动回复）- 已由 GroupMessageHandler 调用
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT, unified_group_message_handler),
    #     group=-1
    # )

    # 配置处理器 - 已由 PrivateConfigHandler 调用
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, verification_config_handler),
    #     group=-1
    # )
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply_config_handler),
    #     group=-1
    # )

    # 业务功能处理器 - 已由 GroupMessageHandler 按顺序调用
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, verify_message_handler),
    #     group=1
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, lottery_message_handler),
    #     group=1
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, solitaire_join_message_handler),
    #     group=1
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, scheduled_message_handler),
    #     group=2
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, moderation_message_handler),
    #     group=3
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, message_points_handler),
    #     group=4
    # )
    # app.add_handler(
    #     MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, get_points_alias_handler().handle),
    #     group=5
    # )

    # 私聊消息处理（显示群组列表等）- 已由 MessageDispatcher 调用
    # app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_message_handler))

    # ==================== 保留必要的处理器（非文本消息）====================
    log.warning("=== REGISTERING NON-MESSAGE HANDLERS ===")

    # 按钮回调处理器
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
    app.add_handler(CallbackQueryHandler(admin_verify_callback, pattern=r"^adm_vfy:"))  # 管理员确认验证
    app.add_handler(CallbackQueryHandler(auto_delete_config_callback, pattern=r"^autodel:"))

    # 新成员加入事件
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))

    # ==================== Group 0: 自动删除和反刷屏（保留，处理所有消息类型）====================
    log.warning("=== REGISTERING GROUP 0: AUTO DELETE & ANTI-FLOOD ===")

    # 自动删除系统消息（处理非文本消息，如图片、贴纸等）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & ~filters.TEXT, auto_delete_handler), group=0)

    # 反刷屏检测（处理所有消息类型）
    from bot.handlers.anti_flood_handler import anti_flood_message_handler
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, anti_flood_message_handler), group=0)

    log.warning("=== ALL COMMON HANDLERS REGISTERED SUCCESSFULLY ===")

    # 验证关键 handlers 是否已注册
    log.warning("=== VERIFYING KEY HANDLERS ===")
    try:
        handlers_dict = app.handlers
        if -1 in handlers_dict:
            log.warning(f"=== Group -1 has {len(handlers_dict[-1])} handlers ===")
            for h in handlers_dict[-1]:
                if hasattr(h, 'callback'):
                    cb_name = h.callback.__name__ if hasattr(h.callback, '__name__') else '?'
                    log.warning(f"  Group -1: {cb_name} ({h.__class__.__name__})")
        # 特别检查 verification_config_handler
        found = False
        for group_handlers in handlers_dict.values():
            for h in group_handlers:
                if hasattr(h, 'callback') and hasattr(h.callback, '__name__'):
                    if 'verification_config' in h.callback.__name__:
                        log.warning(f"=== FOUND verification_config_handler in group ===")
                        found = True
        if not found:
            log.error("=== verification_config_handler NOT FOUND in any group! ===")
    except Exception as e:
        log.error(f"=== Error verifying handlers: {e} ===")


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
            VerificationTimeoutTask,
        )

        scheduler = Scheduler(app)
        scheduler.register_tasks([
            LotteryTask(),
            SolitaireTask(),
            AdsTask(),
            MessageTask(),
            CleanupTask(),
            VerificationTimeoutTask(),  # 验证超时检查任务
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
