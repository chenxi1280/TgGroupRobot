from __future__ import annotations

import asyncio
import datetime as dt
import structlog
import httpx
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler, filters

from bot.config import get_settings
from bot.db.session import create_database, Database
from bot.handlers.admin import admin_command, admin_callback
from bot.handlers.ads import ad_command
from bot.handlers.ads_handler import (
    ads_cancel_callback,
    ads_create_content_message,
    ads_create_frequency_callback,
    ads_create_schedule_message,
    ads_create_start_callback,
    ads_create_title_message,
    ads_delete_callback,
    ads_detail_callback,
    ads_list_callback,
    ads_menu_callback,
    ads_send_callback,
    ads_stats_callback,
    ads_toggle_callback,
    WAIT_CONTENT as ADS_WAIT_CONTENT,
    WAIT_FREQUENCY as ADS_WAIT_FREQUENCY,
    WAIT_IMAGE as ADS_WAIT_IMAGE,
    WAIT_SCHEDULE_TIME as ADS_WAIT_SCHEDULE_TIME,
    WAIT_TITLE as ADS_WAIT_TITLE,
)
from bot.handlers.anti_flood import anti_flood_cleanup_job, anti_flood_message_handler
from bot.handlers.auto_delete import auto_delete_handler
from bot.handlers.auto_delete_config import auto_delete_config_callback
from bot.handlers.auto_reply import (
    auto_reply_config_handler,
    auto_reply_create_start,
    auto_reply_delete_callback,
    auto_reply_menu_callback,
    auto_reply_message_handler,
    auto_reply_toggle_callback,
)
from bot.handlers.banned_word import (
    banned_word_add_start,
    banned_word_check_handler,
    banned_word_config_handler,
    banned_word_delete_callback,
    banned_word_menu_callback,
    banned_word_toggle_callback,
)
from bot.handlers.lottery import (
    draw_lottery_callback,
    join_lottery_callback,
    lottery_create_start,
    lottery_message_handler,
    lottery_menu_callback,
    manual_draw_complete_callback,
    manual_draw_menu_callback,
    manual_draw_select_prize_callback,
    manual_draw_select_winner_callback,
    manual_draw_winner_page_callback,
)
from bot.handlers.moderation import moderation_message_handler
from bot.handlers.points import (
    get_points_alias_handler,
    message_points_handler,
    points_command,
    points_rank_command,
    sign_command,
)
from bot.handlers.points_config import (
    points_config_cancel_callback,
    points_config_callback,
    points_config_message_handler,
    WAIT_VALUE as PTS_WAIT_VALUE,
)
from bot.handlers.scheduled import (
    scheduled_create_start,
    scheduled_delete_callback,
    scheduled_message_handler,
    scheduled_menu_callback,
    scheduled_toggle_callback,
)
from bot.handlers.start import cancel_command, start_command, private_message_handler
from bot.handlers.invite_link import (
    invite_link_cancel_callback,
    invite_link_create_expire_message,
    invite_link_create_limit_message,
    invite_link_create_name_message,
    invite_link_create_start_callback,
    invite_link_delete_callback,
    invite_link_detail_callback,
    invite_link_list_callback,
    invite_link_menu_callback,
    invite_link_refresh_callback,
    invite_link_revoke_callback,
    invite_link_stats_callback,
    link_command,
    user_invite_create_callback,
    user_invite_list_callback,
    user_invite_rank_callback,
    WAIT_NAME as INV_WAIT_NAME,
    WAIT_LIMIT as INV_WAIT_LIMIT,
    WAIT_EXPIRE as INV_WAIT_EXPIRE,
)
from bot.handlers.solitaire import (
    join_solitaire_callback,
    solitaire_cancel_callback,
    solitaire_close_callback,
    solitaire_create_config_message,
    solitaire_create_start_callback,
    solitaire_delete_callback,
    solitaire_detail_callback,
    solitaire_join_message_handler,
    solitaire_list_callback,
    solitaire_menu_callback,
    solitaire_refresh_callback,
    solitaire_stats_callback,
    WAIT_CONFIG,
)
from bot.handlers.verification import new_members_handler, verify_callback, verify_message_handler
from bot.handlers.chat_group import (
    chat_group_admin_callback,
    chat_group_list_callback,
    chat_group_refresh_callback,
    chat_group_select_callback,
)
from bot.logging_config import configure_logging
from bot.services.scheduled_message_service import get_pending_messages, mark_message_sent


log = structlog.get_logger(__name__)


def build_application() -> Application:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = create_database(settings.database_url)

    # 构建应用，如果配置了代理则使用代理
    builder = Application.builder().token(settings.bot_token).concurrent_updates(True)

    # 如果配置了代理，添加代理支持
    if settings.proxy_url:
        proxy = httpx.Proxy(
            url=settings.proxy_url,
        )
        builder = builder.proxy(proxy)

    app = builder.build()

    # 注入依赖
    app.bot_data["settings"] = settings
    app.bot_data["db"] = db

    # commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("sign", sign_command))
    app.add_handler(CommandHandler("points", points_command))
    app.add_handler(CommandHandler("rank", points_rank_command))
    app.add_handler(CommandHandler("link", link_command))
    app.add_handler(CommandHandler("ad", ad_command))

    # callbacks
    app.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^vfy:"))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(lottery_create_start, pattern=r"^lot:create"))
    app.add_handler(CallbackQueryHandler(join_lottery_callback, pattern=r"^join_lottery_"))
    app.add_handler(CallbackQueryHandler(draw_lottery_callback, pattern=r"^draw_lottery_"))
    # 手动开奖回调处理器
    app.add_handler(CallbackQueryHandler(manual_draw_select_prize_callback, pattern=r"^lot:select_prize:"))
    app.add_handler(CallbackQueryHandler(manual_draw_select_winner_callback, pattern=r"^lot:select_winner:"))
    app.add_handler(CallbackQueryHandler(manual_draw_complete_callback, pattern=r"^lot:complete_manual_draw:"))
    app.add_handler(CallbackQueryHandler(manual_draw_winner_page_callback, pattern=r"^lot:winner_page:"))
    app.add_handler(CallbackQueryHandler(manual_draw_menu_callback, pattern=r"^lot:draw_menu:"))
    app.add_handler(CallbackQueryHandler(scheduled_create_start, pattern=r"^scheduled:create"))
    app.add_handler(CallbackQueryHandler(scheduled_toggle_callback, pattern=r"^scheduled_toggle_"))
    app.add_handler(CallbackQueryHandler(scheduled_delete_callback, pattern=r"^scheduled_delete_"))
    app.add_handler(CallbackQueryHandler(scheduled_menu_callback, pattern=r"^scheduled:menu$"))
    app.add_handler(CallbackQueryHandler(auto_reply_create_start, pattern=r"^auto_reply:create"))
    app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=r"^auto_reply_toggle_"))
    app.add_handler(CallbackQueryHandler(auto_reply_delete_callback, pattern=r"^auto_reply_delete_"))
    app.add_handler(CallbackQueryHandler(auto_reply_menu_callback, pattern=r"^auto_reply:menu$"))
    # 广告回调处理器
    app.add_handler(CallbackQueryHandler(ads_create_start_callback, pattern=r"^ads:create"))
    app.add_handler(CallbackQueryHandler(ads_create_frequency_callback, pattern=r"^ads:freq:"))
    app.add_handler(CallbackQueryHandler(ads_toggle_callback, pattern=r"^ads:toggle_"))
    app.add_handler(CallbackQueryHandler(ads_delete_callback, pattern=r"^ads:delete_"))
    app.add_handler(CallbackQueryHandler(ads_send_callback, pattern=r"^ads:send_"))
    app.add_handler(CallbackQueryHandler(ads_menu_callback, pattern=r"^ads:menu$"))
    app.add_handler(CallbackQueryHandler(ads_list_callback, pattern=r"^ads:list"))
    app.add_handler(CallbackQueryHandler(ads_stats_callback, pattern=r"^ads:stats"))
    app.add_handler(CallbackQueryHandler(ads_detail_callback, pattern=r"^ads:detail:\d+$"))
    app.add_handler(CallbackQueryHandler(banned_word_add_start, pattern=r"^banned_word:add"))
    app.add_handler(CallbackQueryHandler(banned_word_toggle_callback, pattern=r"^banned_word_toggle_"))
    app.add_handler(CallbackQueryHandler(banned_word_delete_callback, pattern=r"^banned_word_delete_"))
    app.add_handler(CallbackQueryHandler(banned_word_menu_callback, pattern=r"^banned_word:menu$"))
    app.add_handler(CallbackQueryHandler(invite_link_menu_callback, pattern=r"^inv:menu$"))
    app.add_handler(CallbackQueryHandler(invite_link_list_callback, pattern=r"^inv:list"))
    app.add_handler(CallbackQueryHandler(invite_link_stats_callback, pattern=r"^inv:stats$"))
    app.add_handler(CallbackQueryHandler(invite_link_detail_callback, pattern=r"^inv:detail:\d+$"))
    app.add_handler(CallbackQueryHandler(invite_link_refresh_callback, pattern=r"^inv:refresh:\d+$"))
    app.add_handler(CallbackQueryHandler(invite_link_revoke_callback, pattern=r"^inv:revoke:\d+$"))
    app.add_handler(CallbackQueryHandler(invite_link_delete_callback, pattern=r"^inv:delete:\d+$"))

    # 用户邀请链接回调
    app.add_handler(CallbackQueryHandler(user_invite_create_callback, pattern=r"^inv:user:create:\-?\d+$"))
    app.add_handler(CallbackQueryHandler(user_invite_list_callback, pattern=r"^inv:user:list:\-?\d+$"))
    app.add_handler(CallbackQueryHandler(user_invite_rank_callback, pattern=r"^inv:user:rank:\-?\d+$"))

    # 自动删除配置回调
    app.add_handler(CallbackQueryHandler(auto_delete_config_callback, pattern=r"^autodel:"))

    # 群组切换回调处理器（私聊功能）
    app.add_handler(CallbackQueryHandler(chat_group_list_callback, pattern=r"^group:list"))
    app.add_handler(CallbackQueryHandler(chat_group_select_callback, pattern=r"^group:select:\-?\d+$"))
    app.add_handler(CallbackQueryHandler(chat_group_refresh_callback, pattern=r"^group:refresh"))
    app.add_handler(CallbackQueryHandler(chat_group_admin_callback, pattern=r"^group:admin:\-?\d+$"))

    # 积分配置回调处理器
    app.add_handler(CallbackQueryHandler(points_config_callback, pattern=r"^pts:"))

    # 邀请链接创建流程对话
    invite_link_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(invite_link_create_start_callback, pattern=r"^inv:create")],
        states={
            INV_WAIT_NAME: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_name_message)],
            INV_WAIT_LIMIT: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_limit_message)],
            INV_WAIT_EXPIRE: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, invite_link_create_expire_message)],
        },
        fallbacks=[
            CommandHandler("cancel", invite_link_cancel_callback),
            CallbackQueryHandler(invite_link_cancel_callback, pattern=r"^inv:cancel$"),
        ],
        per_chat=True,
    )
    app.add_handler(invite_link_conv)

    # 接龙回调处理器
    app.add_handler(CallbackQueryHandler(solitaire_menu_callback, pattern=r"^sol:menu$"))
    app.add_handler(CallbackQueryHandler(solitaire_list_callback, pattern=r"^sol:list"))
    app.add_handler(CallbackQueryHandler(solitaire_stats_callback, pattern=r"^sol:stats"))
    app.add_handler(CallbackQueryHandler(solitaire_detail_callback, pattern=r"^sol:detail:"))
    app.add_handler(CallbackQueryHandler(solitaire_refresh_callback, pattern=r"^sol:refresh:"))
    app.add_handler(CallbackQueryHandler(solitaire_close_callback, pattern=r"^sol:close:"))
    app.add_handler(CallbackQueryHandler(solitaire_delete_callback, pattern=r"^sol:delete:"))
    # 接龙参与回调
    app.add_handler(CallbackQueryHandler(join_solitaire_callback, pattern=r"^join_solitaire:"))

    # 接龙创建流程对话
    solitaire_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(solitaire_create_start_callback, pattern=r"^sol:create")],
        states={
            WAIT_CONFIG: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, solitaire_create_config_message)],
        },
        fallbacks=[
            CommandHandler("cancel", solitaire_cancel_callback),
            CallbackQueryHandler(solitaire_cancel_callback, pattern=r"^sol:cancel$"),
        ],
        per_chat=True,
    )
    app.add_handler(solitaire_conv)

    # 广告创建流程对话
    ads_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ads_create_start_callback, pattern=r"^ads:create")],
        states={
            ADS_WAIT_TITLE: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, ads_create_title_message)],
            ADS_WAIT_CONTENT: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & (filters.TEXT | filters.PHOTO) & ~filters.COMMAND, ads_create_content_message)],
            ADS_WAIT_IMAGE: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.PHOTO, ads_create_content_message)],
            ADS_WAIT_FREQUENCY: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, ads_create_schedule_message)],
            ADS_WAIT_SCHEDULE_TIME: [MessageHandler((filters.ChatType.GROUPS | filters.ChatType.PRIVATE) & filters.TEXT & ~filters.COMMAND, ads_create_schedule_message)],
        },
        fallbacks=[
            CommandHandler("cancel", ads_cancel_callback),
            CallbackQueryHandler(ads_cancel_callback, pattern=r"^ads:cancel$"),
        ],
        per_chat=True,
    )
    app.add_handler(ads_conv)

    # 积分配置流程对话
    points_config_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(points_config_callback, pattern=r"^pts:edit:")],
        states={
            PTS_WAIT_VALUE: [
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, points_config_message_handler)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", points_config_cancel_callback),
            CallbackQueryHandler(points_config_cancel_callback, pattern=r"^adm:menu:"),
        ],
        per_chat=True,
    )
    app.add_handler(points_config_conv)

    # group events
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members_handler))
    # 自动删除系统消息（高优先级，在其他处理之前）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, auto_delete_handler), group=0)
    # 接龙参与消息处理（回复接龙消息即可参与）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, solitaire_join_message_handler), group=0)
    # 发言积分处理（低优先级，在其他功能之后）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, message_points_handler), group=4)
    # 积分别名处理（最低优先级，在发言积分之后）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, get_points_alias_handler().handle), group=5)
    # 抽奖创建流程的消息处理（优先级高于普通消息审核）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, lottery_message_handler), group=1)
    # 定时消息创建流程的消息处理
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, scheduled_message_handler), group=1)
    # 自动回复创建流程的消息处理
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, auto_reply_config_handler), group=1)
    # 违禁词添加流程的消息处理
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, banned_word_config_handler), group=1)
    # 验证答案处理（数学题/验证码模式）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, verify_message_handler), group=1)
    # 自动回复匹配（优先级低于创建流程）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, auto_reply_message_handler), group=2)
    # 反刷屏检测（高优先级，在审核之前）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, anti_flood_message_handler), group=0)
    # 违禁词检测（高优先级，在反刷屏之后）
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.ALL, banned_word_check_handler), group=0)
    # 内容审核
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, moderation_message_handler), group=3)
    
    # private chat messages (non-command)
    # 抽奖创建流程的消息处理（优先级高于普通消息）
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, lottery_message_handler), group=1)
    # 定时消息创建流程的消息处理
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, scheduled_message_handler), group=1)
    # 自动回复创建流程的消息处理（优先级高于 private_message_handler）
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, auto_reply_config_handler), group=0)
    # 违禁词添加流程的消息处理
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, banned_word_config_handler), group=1)
    # 其他私聊消息处理（显示群组列表等）
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_message_handler))

    async def on_error(update, context):  # type: ignore[no-untyped-def]
        log.exception("bot_error", err=context.error)

    app.add_error_handler(on_error)
    return app


def main() -> None:
    app = build_application()
    log.info("bot_starting")

    # 启动定时任务调度器
    async def run_bot_with_scheduler():
        from bot.services.scheduler import Scheduler
        from bot.tasks import (
            LotteryTask,
            SolitaireTask,
            AdsTask,
            MessageTask,
            CleanupTask,
        )

        # 创建并配置调度器
        scheduler = Scheduler(app)
        scheduler.register_tasks([
            LotteryTask(),
            SolitaireTask(),
            AdsTask(),
            MessageTask(),
            CleanupTask(),
        ])

        # 启动调度器
        await scheduler.start()

        # 启动机器人
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            # 保持运行
            await asyncio.Event().wait()
        finally:
            # 停止调度器
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


