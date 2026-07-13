from __future__ import annotations

import datetime as dt

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.services.publish_service import PublishService
_ADS_CREATE_CONFIG_MESSAGE_ACTION_THRESHOLD_100 = 100
_ADS_CONFIG_HELP = """➕ 创建轮播广告 ( /cancel 取消 )

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

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ 取消配置", callback_data=f"ads:cancel:{target_chat_id}")]]
    )
    await q.edit_message_text(_ADS_CONFIG_HELP, parse_mode="HTML", reply_markup=keyboard)


def _log_ads_config_call(logger, update) -> None:
    logger.warning(
        "=== ads_create_config_message CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or update.effective_message.caption or "")[:50]
        if update.effective_message else "",
    )


async def _load_ads_creation_state(update, session, service, *, chat_id: int, user_id: int, logger):
    state = await service.get(session, chat_id, user_id)
    logger.info("ads_state_check", chat_id=chat_id, user_id=user_id, state_type=state.state_type if state else None)
    if not state or state.state_type != "ads_create_config":
        logger.info("ads_state_not_match", state_type=state.state_type if state else None)
        await session.commit()
        return None
    target_chat_id = (state.state_data or {}).get("target_chat_id")
    if target_chat_id:
        return state, dict(state.state_data or {}), target_chat_id
    await update.effective_message.reply_text("❌ 会话已过期，请重新开始")
    await service.clear(session, chat_id, user_id)
    await session.commit()
    return None


async def _save_ads_image_or_wait(context, session, state, *, state_data: dict, image_file_id, text: str, chat_id: int, message_id: int) -> bool:
    if image_file_id:
        state_data = {**state_data, "image_file_id": image_file_id}
        state.state_data = state_data
        await session.flush()
    if text:
        return False
    await session.commit()
    if image_file_id:
        await PublishService.reply(
            context,
            chat_id=chat_id,
            reply_to_message_id=message_id,
            text="✅ 已保存图片 file_id。\n请继续发送轮播配置文本（可按模板直接粘贴）。",
        )
    return True


async def _parse_ads_creation_config(update, session, text: str, *, parse_ads_config_func):
    try:
        config = parse_ads_config_func(text)
    except Exception as exc:
        structlog.get_logger(__name__).warning("ads_config_parse_failed", user_id=update.effective_user.id, error=str(exc))
        await session.commit()
        await update.effective_message.reply_text("❌ 配置格式错误，请检查后重试")
        return None
    if not config.get("title"):
        await session.commit()
        await update.effective_message.reply_text("❌ 标题不能为空，请重新输入配置")
        return None
    if not config.get("content"):
        await session.commit()
        await update.effective_message.reply_text("❌ 内容不能为空，请重新输入配置")
        return None
    return config


def _format_ad_creation_success(ad) -> str:
    lines = ["✅ 轮播广告创建成功！", "", f"标题: {ad.title}", ""]
    if ad.start_time:
        local_tz = dt.timezone(dt.timedelta(hours=8))
        lines.append(f"开始时间: {ad.start_time.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')} (UTC+8)")
    if ad.interval_hours:
        lines.append(f"推送间隔: {ad.interval_hours}小时")
    if ad.max_send_count:
        lines.append(f"推送次数: {ad.max_send_count}次")
    if ad.has_image:
        lines.append("图片: 已配置（file_id）")
    suffix = "..." if len(ad.content) > _ADS_CREATE_CONFIG_MESSAGE_ACTION_THRESHOLD_100 else ""
    lines.extend(["", f"{ad.content[:100]}{suffix}", "", f"任务ID: {ad.id}"])
    return "\n".join(lines)


async def _publish_ad_creation_success(context, message, ad, *, chat_id: int, target_chat_id: int) -> None:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回轮播广告", callback_data=f"ads:menu:{target_chat_id}")],
        [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:main:{target_chat_id}")],
    ])
    await PublishService.reply(
        context,
        chat_id=chat_id,
        reply_to_message_id=message.message_id,
        text=_format_ad_creation_success(ad),
        reply_markup=keyboard,
    )


async def _execute_ads_creation(
    update,
    context,
    db,
    *,
    parse_ads_config_func,
    create_ad_campaign_func,
    conversation_state_service,
    logger,
) -> None:
    user, chat, message = update.effective_user, update.effective_chat, update.effective_message
    text = (message.text or message.caption or "").strip()
    image_file_id = message.photo[-1].file_id if message.photo else None
    async with db.session_factory() as session:
        loaded = await _load_ads_creation_state(
            update, session, conversation_state_service, chat_id=chat.id, user_id=user.id, logger=logger
        )
        if loaded is None:
            return
        state, state_data, target_chat_id = loaded
        waiting = await _save_ads_image_or_wait(
            context, session, state, state_data=state_data, image_file_id=image_file_id,
            text=text, chat_id=chat.id, message_id=message.message_id,
        )
        if waiting:
            return
        config = await _parse_ads_creation_config(update, session, text, parse_ads_config_func=parse_ads_config_func)
        if config is None:
            return
        image_id = config.get("image_file_id") or state_data.get("image_file_id") or image_file_id
        result = await create_ad_campaign_func(
            session, chat_id=target_chat_id, created_by_user_id=user.id,
            title=config["title"], content=config["content"], image_file_id=image_id,
            start_time=config.get("start_time"), interval_hours=config.get("interval_hours"),
            max_send_count=config.get("max_send_count"),
        )
        if not result.success:
            await session.commit()
            await message.reply_text("❌ 创建失败，请重试")
            return
        await conversation_state_service.clear(session, chat.id, user.id)
        await session.commit()
        await _publish_ad_creation_success(
            context, message, result.entity, chat_id=chat.id, target_chat_id=target_chat_id
        )
        logger.info("ads_handler_done")


async def ads_create_config_message_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    parse_ads_config_func,
    create_ad_campaign_func,
    conversation_state_service,
) -> None:
    logger = structlog.get_logger(__name__)
    _log_ads_config_call(logger, update)
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return
    try:
        db: Database = context.application.bot_data["db"]
        await _execute_ads_creation(
            update,
            context,
            db,
            parse_ads_config_func=parse_ads_config_func,
            create_ad_campaign_func=create_ad_campaign_func,
            conversation_state_service=conversation_state_service,
            logger=logger,
        )
    except Exception as exc:
        logger.exception(
            "ads_create_config_message_error",
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=True,
        )
        raise


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
