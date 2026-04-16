from __future__ import annotations

import datetime as dt

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.publish_service import PublishService


async def ads_create_start_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    module_settings_service,
    conversation_state_service,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user
    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await module_settings_service.ensure(
            session,
            chat_id=target_chat_id,
            chat_type=chat.type if chat.type != "private" else "supergroup",
            title=chat.title,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )
        await conversation_state_service.start(
            session,
            chat_id=chat.id,
            user_id=user.id,
            state_type="ads_create_config",
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    config_help = """➕ 创建轮播广告 ( /cancel 取消 )

请按以下格式输入配置：

<strong>轮播标题</strong>

开始时间: 2026-01-09 10:00
推送间隔: 24小时
推送次数: 7次

内容:
这是轮播消息的详细内容
可以多行显示

<strong>参数说明：</strong>
• <strong>标题</strong>：第一行必填，最多128字
• <strong>开始时间</strong>：可选，格式 YYYY-MM-DD HH:MM
• <strong>推送间隔</strong>：可选，如「24小时」，不填则只推送一次
• <strong>推送次数</strong>：可选，如「7次」，不填则无限制
• <strong>图片</strong>：可选，先发送一张图片保存 file_id，或在配置中写「图片ID: xxxxx」
• <strong>内容</strong>：使用「内容:」标记开始

<strong>简化示例：</strong>
今晚聚餐轮播

内容:
欢迎大家参加今晚的聚餐活动！

<strong>图片示例：</strong>
图片ID: AgACAgUAAxkBAAIB...
内容:
图文轮播内容"""

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"ads:cancel:{target_chat_id}")]]
    )
    await q.edit_message_text(config_help, parse_mode="HTML", reply_markup=keyboard)


async def ads_create_config_message_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    parse_ads_config_func,
    create_ad_campaign_func,
    conversation_state_service,
) -> None:
    logger = structlog.get_logger(__name__)
    logger.warning(
        "=== ads_create_config_message CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or update.effective_message.caption or "")[:50]
        if update.effective_message else "",
    )

    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return

    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message
    text = (message.text or message.caption or "").strip()
    image_file_id = message.photo[-1].file_id if message.photo else None

    try:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            state_chat_id = chat.id
            state = await conversation_state_service.get(session, state_chat_id, user.id)
            logger.info(
                "ads_state_check",
                chat_id=state_chat_id,
                user_id=user.id,
                state_type=state.state_type if state else None,
            )

            if not state or state.state_type != "ads_create_config":
                logger.info("ads_state_not_match", state_type=state.state_type if state else None)
                await session.commit()
                return

            state_data = dict(state.state_data or {})
            target_chat_id = state_data.get("target_chat_id")
            if not target_chat_id:
                await update.effective_message.reply_text("❌ 会话已过期，请重新开始")
                await conversation_state_service.clear(session, state_chat_id, user.id)
                await session.commit()
                return

            if image_file_id:
                state_data["image_file_id"] = image_file_id
                state.state_data = state_data
                await session.flush()

            if not text:
                await session.commit()
                if image_file_id:
                    await PublishService.reply(
                        context,
                        chat_id=chat.id,
                        reply_to_message_id=message.message_id,
                        text="✅ 已保存图片 file_id。\n请继续发送轮播配置文本（可按模板直接粘贴）。",
                    )
                return

            try:
                config = parse_ads_config_func(text)
            except Exception:
                await session.commit()
                await update.effective_message.reply_text("❌ 配置格式错误，请检查后重试")
                return

            if not config.get("title"):
                await session.commit()
                await update.effective_message.reply_text("❌ 标题不能为空，请重新输入配置")
                return

            if not config.get("content"):
                await session.commit()
                await update.effective_message.reply_text("❌ 内容不能为空，请重新输入配置")
                return

            final_image_file_id = config.get("image_file_id") or state_data.get("image_file_id") or image_file_id

            result = await create_ad_campaign_func(
                session,
                chat_id=target_chat_id,
                created_by_user_id=user.id,
                title=config["title"],
                content=config["content"],
                image_file_id=final_image_file_id,
                start_time=config.get("start_time"),
                interval_hours=config.get("interval_hours"),
                max_send_count=config.get("max_send_count"),
            )

            if not result.success:
                await session.commit()
                await update.effective_message.reply_text("❌ 创建失败，请重试")
                return

            ad = result.entity
            success_msg = f"✅ 轮播广告创建成功！\n\n标题: {ad.title}\n\n"
            if ad.start_time:
                local_tz = dt.timezone(dt.timedelta(hours=8))
                local_start = ad.start_time.astimezone(local_tz)
                success_msg += f"开始时间: {local_start.strftime('%Y-%m-%d %H:%M')} (UTC+8)\n"
            if ad.interval_hours:
                success_msg += f"推送间隔: {ad.interval_hours}小时\n"
            if ad.max_send_count:
                success_msg += f"推送次数: {ad.max_send_count}次\n"
            if ad.has_image:
                success_msg += "图片: 已配置（file_id）\n"
            success_msg += f"\n{ad.content[:100]}{'...' if len(ad.content) > 100 else ''}"
            success_msg += f"\n\n任务ID: {ad.id}"

            await conversation_state_service.clear(session, state_chat_id, user.id)
            await session.commit()

            keyboard = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🔙 返回轮播广告", callback_data=f"ads:menu:{target_chat_id}")],
                    [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
                ]
            )
            await PublishService.reply(
                context,
                chat_id=chat.id,
                reply_to_message_id=message.message_id,
                text=success_msg,
                reply_markup=keyboard,
            )
            logger.info("ads_handler_done")
    except Exception as exc:
        logger.exception(
            "ads_create_config_message_error",
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=True,
        )


async def ads_cancel_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    resolve_target_chat_id_func,
    resolve_state_chat_id_func,
    conversation_state_service,
    show_menu_func,
    ads_menu_keyboard_func,
) -> None:
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await resolve_target_chat_id_func(update, context)
    if target_chat_id is None:
        return

    chat = update.effective_chat
    user = update.effective_user
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_chat_id = resolve_state_chat_id_func(update, target_chat_id)
        await conversation_state_service.clear(session, state_chat_id, user.id)
        await session.commit()

    if chat.type == "private":
        await show_menu_func(update, context, target_chat_id)
    else:
        keyboard = ads_menu_keyboard_func(target_chat_id)
        await q.edit_message_text(
            "🎠 轮播广告\n\n支持单次推送、定时开始、间隔轮播和图片广告配置。",
            reply_markup=keyboard,
        )
