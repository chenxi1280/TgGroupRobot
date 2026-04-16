"""Bot bootstrap wiring."""
from __future__ import annotations

import atexit
import os
import sys
import tempfile
import warnings

import structlog
from telegram import Update
from telegram.warnings import PTBUserWarning
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, ContextTypes, MessageHandler, TypeHandler, filters
from telegram.request import HTTPXRequest

from backend.platform.config.core.settings import get_settings
from backend.platform.db.runtime.schema_gate import SchemaValidationError, validate_database_schema
from backend.platform.db.runtime.startup_migrations import run_startup_schema_migrations
from backend.platform.db.runtime.session import create_database, Database
from backend.features.moderation.anti_flood_handler import anti_flood_message_handler
from backend.features.moderation.anti_flood_config_handler import anti_flood_config_callback
from backend.features.moderation.anti_spam_config_handler import anti_spam_config_callback
from backend.features.moderation.anti_spam_handler import anti_spam_message_handler
from backend.features.moderation.garbage_guard_config_handler import garbage_guard_config_callback
from backend.features.group_ops.auto_delete_config_handler import auto_delete_config_callback
from backend.features.group_ops.auto_delete_handler import auto_delete_handler
from backend.features.group_ops.command_alias_handler import command_alias_handler
from backend.app.router_registry import register_feature_routers
from backend.features.group_ops.start_handler import cancel_command as cancel_callback
from backend.features.group_ops.start_handler import start_command as start_callback
from backend.features.verification.verification_handler import (
    admin_verify_callback,
    new_members_handler,
    invite_link_join_hint_handler,
    verification_timeout_help_callback,
    verify_callback,
)
from backend.platform.config.core.logging import configure_logging
from backend.platform.telegram.message_router import MessageRouter
from backend.platform.telegram.errors import answer_callback_query_safely, build_public_error_text
from backend.shared.async_tasks import cancel_background_tasks

log = structlog.get_logger(__name__)


async def _raw_update_probe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log every received Telegram update before feature filters run."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    sender_chat = getattr(message, "sender_chat", None) if message is not None else None
    text = ""
    if message is not None:
        text = message.text or message.caption or ""

    log.info(
        "raw_update_entry",
        update_id=update.update_id,
        has_message=update.message is not None,
        has_channel_post=update.channel_post is not None,
        has_callback_query=update.callback_query is not None,
        has_chat_member=update.chat_member is not None,
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        user_id=user.id if user else None,
        sender_chat_id=sender_chat.id if sender_chat else None,
        text_preview=text[:50],
    )


def _configure_ptb_runtime() -> None:
    """配置 PTB 运行时行为与已知可接受的告警过滤。"""
    # 这几个会话流程是“按钮进入 + 文本输入”的混合模式。
    # 对这类配置，PTB 会提示 per_message=False 时 CallbackQueryHandler 不会按消息粒度追踪。
    # 当前设计本来就按 chat/user 维度管理会话，不依赖按消息粒度追踪，因此仅精确过滤该提示。
    warnings.filterwarnings(
        "ignore",
        message=r"If 'per_message=False', 'CallbackQueryHandler' will not be tracked for every message\..*",
        category=PTBUserWarning,
    )


def build_application() -> Application:
    """构建并配置 Telegram Bot 应用"""
    settings = get_settings()
    configure_logging(settings.log_level)
    _configure_ptb_runtime()

    log.info("bot_application_building")

    db = create_database(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )

    # 构建应用。
    # 显式关闭 trust_env，避免 IDE/系统环境变量中的代理设置导致 Telegram 初始化失败。
    # 如需代理，仅使用 .env 中的 PROXY_URL。
    request_kwargs = {
        "httpx_kwargs": {"trust_env": False},
        "connection_pool_size": settings.telegram_connection_pool_size,
        "pool_timeout": settings.telegram_pool_timeout_seconds,
        "connect_timeout": settings.telegram_connect_timeout_seconds,
        "read_timeout": settings.telegram_read_timeout_seconds,
        "write_timeout": settings.telegram_write_timeout_seconds,
    }
    proxy_url = settings.proxy_url or None
    request = HTTPXRequest(proxy=proxy_url, **request_kwargs)
    get_updates_request = HTTPXRequest(proxy=proxy_url, **request_kwargs)

    builder = (
        Application.builder()
        .token(settings.bot_token)
        # ConversationHandler 依赖串行处理更新；并发会导致状态追踪错位。
        .concurrent_updates(False)
        .request(request)
        .get_updates_request(get_updates_request)
        .post_shutdown(cancel_background_tasks)
    )

    app = builder.build()

    # 注入依赖
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    # 注册处理器
    _register_commands(app)
    _register_routers(app)
    _register_common_handlers(app)
    app.add_error_handler(_on_error)

    log.info("bot_application_built")
    return app


def _register_commands(app: Application) -> None:
    """注册命令处理器"""
    from telegram.ext import CommandHandler

    app.add_handler(CommandHandler("start", start_callback))
    app.add_handler(CommandHandler("cancel", cancel_callback))


def _register_routers(app: Application) -> None:
    """注册所有功能路由器"""
    register_feature_routers(app)


def _register_common_handlers(app: Application) -> None:
    """注册通用处理器"""
    dispatcher = MessageRouter()

    app.add_handler(TypeHandler(Update, _raw_update_probe), group=-99)

    # ==================== Group -3: 群风控入口（优先于业务处理）====================
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.ALL, anti_flood_message_handler),
        group=-3,
    )
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.ALL, anti_spam_message_handler),
        group=-3,
    )

    # 命令别名处理（仅群内，优先于其他命令）
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.COMMAND, command_alias_handler),
        group=-2,
    )

    # ==================== Group -2: 统一消息分发入口 ====================
    # 群聊统一入口：非命令消息都进入分发器，确保媒体消息也能经过等级限制/商城/欢迎等规则
    app.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS & ~filters.COMMAND)
            | (filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND),
            dispatcher.dispatch,
        ),
        group=-2,
    )

    # 私聊 /clear 命令入口（FSM 清空文本/按钮/时间等）
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Regex(r"^/clear(?:@\w+)?\s*$"),
            dispatcher.dispatch,
        ),
        group=-2,
    )

    # 私聊媒体消息入口（用于 FSM 场景，例如定时消息编辑媒体）
    media_filters = filters.ChatType.PRIVATE & (
        filters.PHOTO
        | filters.VIDEO
        | filters.Document.ALL
        | filters.Sticker.ALL
        | filters.ANIMATION
        | filters.LOCATION
    )
    app.add_handler(
        MessageHandler(media_filters, dispatcher.dispatch),
        group=-2,
    )

    # ==================== 按钮回调处理器 ====================
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
    app.add_handler(CallbackQueryHandler(admin_verify_callback, pattern=r"^adm_vfy:"))
    app.add_handler(CallbackQueryHandler(verification_timeout_help_callback, pattern=r"^vfy_help:"))
    app.add_handler(CallbackQueryHandler(auto_delete_config_callback, pattern=r"^autodel:"))
    app.add_handler(CallbackQueryHandler(anti_flood_config_callback, pattern=r"^afcfg:"))
    app.add_handler(CallbackQueryHandler(anti_spam_config_callback, pattern=r"^ascfg:"))
    app.add_handler(CallbackQueryHandler(garbage_guard_config_callback, pattern=r"^gg:"))

    # ==================== 新成员加入事件 ====================
    app.add_handler(ChatMemberHandler(invite_link_join_hint_handler, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))

    # ==================== Group 0: 自动删除 ====================
    # 自动删除系统消息（文本与非文本都需要覆盖，例如匿名管理员消息）
    app.add_handler(
        MessageHandler(filters.ChatType.GROUPS & filters.ALL, auto_delete_handler),
        group=0,
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """错误处理器"""
    log.exception("bot_error", err=context.error)
    if isinstance(update, object) and hasattr(update, "callback_query"):
        public_error = build_public_error_text(context.error)
        await answer_callback_query_safely(
            update,
            f"❌ {public_error}",
            show_alert=True,
        )


async def _validate_schema_or_exit(app: Application) -> None:
    """启动前执行严格 schema gate。"""
    db: Database = app.bot_data["db"]
    allow_compat = os.getenv("BOT_ALLOW_SCHEMA_COMPAT", "").strip() == "1"

    try:
        await run_startup_schema_migrations(db.engine)
        await validate_database_schema(db.engine)
        log.info("schema_gate_passed")
    except SchemaValidationError:
        if allow_compat:
            log.warning("schema_gate_bypassed_by_env", env_var="BOT_ALLOW_SCHEMA_COMPAT")
            return
        log.exception("schema_gate_failed")
        raise


# PID 文件路径（跨平台兼容：使用系统临时目录）
_PID_FILE = os.path.join(tempfile.gettempdir(), "tggrouprobot.pid")


def _should_skip_single_instance_lock() -> bool:
    """容器内由容器编排保证单实例，不再依赖本地 PID 文件。"""
    if os.getenv("BOT_DISABLE_SINGLE_INSTANCE", "").strip() == "1":
        return True
    return os.path.exists("/.dockerenv")


def _check_single_instance() -> None:
    """确保只有一个 bot 实例在运行"""
    if _should_skip_single_instance_lock():
        return

    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                return
            os.kill(pid, 0)
            print(f"错误: bot 已经在运行 (PID: {pid})")
            print(f"如需重启，请先停止现有实例: kill {pid}")
            sys.exit(1)
        except (ValueError, OSError):
            try:
                os.remove(_PID_FILE)
            except OSError:
                pass

    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def _cleanup_pid_file() -> None:
        try:
            if os.path.exists(_PID_FILE):
                os.remove(_PID_FILE)
        except OSError:
            pass

    atexit.register(_cleanup_pid_file)
