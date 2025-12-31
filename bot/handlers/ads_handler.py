from __future__ import annotations

import structlog
import datetime as dt
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.db.session import Database
from bot.keyboards.ads import (
    ads_create_keyboard,
    ads_detail_keyboard,
    ads_frequency_keyboard,
    ads_list_keyboard,
    ads_menu_keyboard,
)
from bot.services.ad_service import (
    create_ad_campaign,
    delete_ad,
    get_ad,
    get_chat_ads,
    mark_ad_sent,
    should_send_ad,
    toggle_ad,
)
from bot.services.chat_group_service import get_user_current_chat, get_user_managed_chats
from bot.services.state_service import clear_user_state, set_user_state, get_user_state
from bot.services.telegram_perm import is_user_admin
from bot.handlers.admin import _show_private_admin_menu, _safe_edit_message

# 创建流程状态
WAIT_TITLE = 1
WAIT_CONTENT = 2
WAIT_IMAGE = 3
WAIT_FREQUENCY = 4
WAIT_SCHEDULE_TIME = 5

log = structlog.get_logger(__name__)


async def ads_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的广告管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return

        # 处理返回操作
        data = q.data or ""
        if data == "ads:menu":
            await _show_private_admin_menu(update, context, target_chat_id)
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    await q.edit_message_text(
        f"📢 广告管理\n\n管理群内广告推送",
        reply_markup=ads_menu_keyboard(target_chat_id if chat.type == "private" else None),
    )


async def ads_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    data = q.data or ""
    parts = data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    # 私聊中的广告管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ads = await get_chat_ads(session, target_chat_id)
        await session.commit()

    if not ads:
        keyboard = ads_menu_keyboard(target_chat_id if chat.type == "private" else None)
        await q.edit_message_text(
            "📢 广告列表\n\n暂无广告，点击「创建广告」开始",
            reply_markup=keyboard,
        )
        return

    text = f"📢 广告列表\n\n共 {len(ads)} 个广告"
    keyboard = ads_list_keyboard(
        ads,
        target_chat_id if chat.type == "private" else None,
        page
    )
    await q.edit_message_text(text, reply_markup=keyboard)


async def ads_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告统计回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的广告管理 - 从回调中获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        db: Database = context.application.bot_data["db"]
        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await q.edit_message_text("请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await q.edit_message_text("你没有该群组的管理权限")
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await q.edit_message_text("仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ads = await get_chat_ads(session, target_chat_id)
        await session.commit()

    enabled_count = sum(1 for ad in ads if ad.enabled)
    with_image_count = sum(1 for ad in ads if ad.has_image)
    scheduled_count = sum(1 for ad in ads if ad.schedule_time)

    text = f"📊 广告统计\n\n"
    text += f"总广告数: {len(ads)}\n"
    text += f"启用中: {enabled_count}\n"
    text += f"含图片: {with_image_count}\n"
    text += f"定时推送: {scheduled_count}"

    keyboard = ads_menu_keyboard(target_chat_id if chat.type == "private" else None)
    await q.edit_message_text(text, reply_markup=keyboard)


async def ads_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告详情回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    ad_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if not ad:
            await session.commit()
            await q.edit_message_text("广告不存在", reply_markup=ads_menu_keyboard())
            return

        status_emoji = "🟢" if ad.enabled else "🔴"
        status_text = "启用" if ad.enabled else "暂停"

        schedule_info = ""
        if ad.schedule_time:
            schedule_info = f"\n⏰ 定时: {ad.schedule_time.strftime('%Y-%m-%d %H:%M')}"
            if ad.frequency:
                freq_map = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}
                schedule_info += f" [{freq_map.get(ad.frequency, ad.frequency)}]"

        image_info = "\n🖼️ 含图片" if ad.has_image else ""
        last_sent_info = f"\n📤 上次发送: {ad.last_sent_at.strftime('%Y-%m-%d %H:%M')}" if ad.last_sent_at else ""

        text = f"{status_emoji} {ad.title}\n\n"
        text += f"状态: {status_text}{schedule_info}{image_info}{last_sent_info}\n\n"
        text += f"{ad.content}"

        await session.commit()

    await q.edit_message_text(text, reply_markup=ads_detail_keyboard(ad_id, ad.enabled))


async def ads_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    if not await is_user_admin(context, chat.id, user.id):
        await q.edit_message_text("仅管理员可使用此功能")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "ads_create", {})
        await session.commit()

    await q.edit_message_text(
        "➕ 创建广告\n\n请输入广告标题",
    )
    return WAIT_TITLE


async def ads_create_title_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理标题输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    title = update.effective_message.text.strip()[:128]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state_data = await set_user_state(session, chat.id, user.id, "ads_create", {"title": title})
        await session.commit()

    await update.effective_message.reply_text(
        f"标题: {state_data.state_data.get('title')}\n\n请输入广告内容",
    )
    return WAIT_CONTENT


async def ads_create_content_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理内容输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    content = update.effective_message.text.strip()

    # 检查是否有图片
    has_photo = update.effective_message.photo is not None

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        state_data["content"] = content

        # 保存图片（如果有）
        image_file_id = None
        if has_photo and update.effective_message.photo:
            # 获取最大尺寸的照片
            photo = update.effective_message.photo[-1]
            image_file_id = photo.file_id
            state_data["image_file_id"] = image_file_id

        await set_user_state(session, chat.id, user.id, "ads_create", state_data)
        await session.commit()

    image_info = "\n🖼️ 已添加图片" if has_photo else ""
    await update.effective_message.reply_text(
        f"内容: {content[:50]}...\n{image_info}\n\n请选择推送频次",
        reply_markup=ads_frequency_keyboard(),
    )
    return WAIT_FREQUENCY


async def ads_create_frequency_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理频次选择"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    user = update.effective_user
    chat = update.effective_chat
    data = q.data or ""

    parts = data.split(":")
    if len(parts) < 3:
        return ConversationHandler.END

    frequency = parts[2]

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        state_data["frequency"] = frequency if frequency != "once" else None
        await set_user_state(session, chat.id, user.id, "ads_create", state_data)
        await session.commit()

    # 如果是定时推送，询问时间；否则直接创建
    if frequency in ["daily", "weekly", "monthly"]:
        await q.edit_message_text(
            f"频次: {frequency}\n\n请输入定时推送时间（可选，UTC时区）\n格式: HH:MM 或 /skip 立即创建\n示例: 09:00, 14:30\n⚠️ 注意：使用 UTC 时间（比北京时间晚8小时）",
        )
        return WAIT_SCHEDULE_TIME
    else:
        # 单次推送，直接创建
        return await _finalize_ad_creation(update, context, chat.id, user.id)


async def ads_create_schedule_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理定时时间输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text.strip()

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

    schedule_time = None
    if text != "/skip":
        try:
            # 解析时间 HH:MM
            hour, minute = map(int, text.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                await update.effective_message.reply_text("时间范围错误，小时应在 0-23，分钟应在 0-59")
                return WAIT_SCHEDULE_TIME

            now = dt.datetime.now(dt.UTC)
            # 创建今天的调度时间（UTC）
            schedule_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # 如果时间已过，设置为明天
            if schedule_time < now:
                schedule_time += dt.timedelta(days=1)

            # 显示给用户的时间信息
            time_str = schedule_time.strftime('%Y-%m-%d %H:%M UTC')
        except ValueError:
            await update.effective_message.reply_text("时间格式错误，请使用 HH:MM 格式（24小时制）或 /skip 立即创建\n示例: 09:00, 14:30")
            return WAIT_SCHEDULE_TIME

    state_data["schedule_time"] = schedule_time

    async with db.session_factory() as session:
        await set_user_state(session, chat.id, user.id, "ads_create", state_data)
        await session.commit()

    return await _finalize_ad_creation(update, context, chat.id, user.id, schedule_time)


async def _finalize_ad_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, schedule_time: dt.datetime | None = None) -> int | None:
    """完成广告创建"""
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        state = await get_user_state(session, chat_id, user_id)
        if not state:
            await update.effective_message.reply_text("创建失败，请重试")
            return ConversationHandler.END

        state_data = state.state_data

        result = await create_ad_campaign(
            session,
            chat_id=chat_id,
            created_by_user_id=user_id,
            title=state_data.get("title"),
            content=state_data.get("content"),
            image_file_id=state_data.get("image_file_id"),
            schedule_time=schedule_time or state_data.get("schedule_time"),
            frequency=state_data.get("frequency"),
        )

        await clear_user_state(session, chat_id, user_id)
        await session.commit()

        if result.success:
            if result.ad.schedule_time:
                time_str = result.ad.schedule_time.strftime('%Y-%m-%d %H:%M')
                freq_str = result.ad.frequency or "单次"
                await update.effective_message.reply_text(
                    f"✅ 广告创建成功！\n\n将根据设置定时推送\n时间: {time_str}\n频次: {freq_str}",
                    reply_markup=ads_menu_keyboard(),
                )
            else:
                await update.effective_message.reply_text(
                    "✅ 广告创建成功！\n\n请使用「广告列表」-「立即发送」来推送",
                    reply_markup=ads_menu_keyboard(),
                )
        else:
            await update.effective_message.reply_text("❌ 创建失败", reply_markup=ads_menu_keyboard())

    return ConversationHandler.END


async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """立即发送广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    ad_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if not ad:
            await q.edit_message_text("广告不存在")
            return

        # 发送广告
        target_chat_id = ad.chat_id
        try:
            if ad.has_image and ad.image_file_id:
                await context.bot.send_photo(target_chat_id, ad.image_file_id, caption=f"【{ad.title}】\n\n{ad.content}")
            else:
                await context.bot.send_message(target_chat_id, f"【{ad.title}】\n\n{ad.content}")

            # 标记已发送
            await mark_ad_sent(session, ad_id)
            await session.commit()

            await q.answer("✅ 广告已发送")
            # 刷新详情
            ad_updated = await get_ad(session, ad_id)
            status_emoji = "🟢" if ad_updated.enabled else "🔴"
            status_text = "启用" if ad_updated.enabled else "暂停"

            schedule_info = ""
            if ad_updated.schedule_time:
                schedule_info = f"\n⏰ 定时: {ad_updated.schedule_time.strftime('%Y-%m-%d %H:%M')}"
                if ad_updated.frequency:
                    freq_map = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}
                    schedule_info += f" [{freq_map.get(ad_updated.frequency, ad_updated.frequency)}]"

            image_info = "\n🖼️ 含图片" if ad_updated.has_image else ""
            last_sent_info = f"\n📤 上次发送: {ad_updated.last_sent_at.strftime('%Y-%m-%d %H:%M')}" if ad_updated.last_sent_at else ""

            text = f"{status_emoji} {ad_updated.title}\n\n"
            text += f"状态: {status_text}{schedule_info}{image_info}{last_sent_info}\n\n"
            text += f"{ad_updated.content}"

            await q.edit_message_text(text, reply_markup=ads_detail_keyboard(ad_id, ad_updated.enabled))
        except Exception as e:
            await q.edit_message_text(f"❌ 发送失败: {str(e)}")


async def ads_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换广告启用状态"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    ad_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await toggle_ad(session, ad_id)
        if not ad:
            await q.edit_message_text("广告不存在")
            return

        await session.commit()

        status_emoji = "🟢" if ad.enabled else "🔴"
        status_text = "启用" if ad.enabled else "暂停"

        schedule_info = ""
        if ad.schedule_time:
            schedule_info = f"\n⏰ 定时: {ad.schedule_time.strftime('%Y-%m-%d %H:%M')}"
            if ad.frequency:
                freq_map = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}
                schedule_info += f" [{freq_map.get(ad.frequency, ad.frequency)}]"

        image_info = "\n🖼️ 含图片" if ad.has_image else ""
        last_sent_info = f"\n📤 上次发送: {ad.last_sent_at.strftime('%Y-%m-%d %H:%M')}" if ad.last_sent_at else ""

        text = f"{status_emoji} {ad.title}\n\n"
        text += f"状态: {status_text}{schedule_info}{image_info}{last_sent_info}\n\n"
        text += f"{ad.content}"

        await q.edit_message_text(text, reply_markup=ads_detail_keyboard(ad_id, ad.enabled))


async def ads_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    parts = data.split(":")
    if len(parts) < 3:
        return

    ad_id = int(parts[2])

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_ad(session, ad_id)
        await session.commit()

        if success:
            await q.edit_message_text("✅ 广告已删除", reply_markup=ads_menu_keyboard())
        else:
            await q.edit_message_text("❌ 广告不存在")


async def ads_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """取消创建流程"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await clear_user_state(session, chat.id, user.id)
        await session.commit()

    await q.edit_message_text("已取消创建", reply_markup=ads_menu_keyboard())
    return ConversationHandler.END
