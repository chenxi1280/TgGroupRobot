from __future__ import annotations

import structlog
import datetime as dt
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.keyboards.content.ads import (
    ads_create_keyboard,
    ads_detail_keyboard,
    ads_frequency_keyboard,
    ads_list_keyboard,
    ads_menu_keyboard,
)
from bot.services.automation.ad_service import (
    create_ad_campaign,
    delete_ad,
    get_ad,
    get_chat_ads,
    mark_ad_sent,
    should_send_ad,
    toggle_ad,
)
from bot.services.integration.chat_group_service import get_user_current_chat, get_user_managed_chats
from bot.services.state.state_service import clear_user_state, set_user_state, get_user_state
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.permission_service import is_user_admin
from bot.models.core import AdCampaign
from bot.utils.callback_parser import CallbackParser
from bot.utils.chat_context import PrivateChatContext

log = structlog.get_logger(__name__)


class AdsHandler(BaseHandler):
    """广告 Handler"""

    def __init__(self) -> None:
        super().__init__()
        # 关闭默认权限检查，因为我们在各个方法中自己处理
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """处理广告回调（用于 BaseHandler 抽象方法）"""
        # AdsHandler 不使用 process 方法，直接调用各个方法
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示广告管理菜单"""
        text = "📢 广告管理\n\n管理群内广告推送"
        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        """显示广告列表"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            ads = await get_chat_ads(session, target_chat_id)
            await session.commit()

        if not ads:
            keyboard = ads_menu_keyboard(target_chat_id)
            await self.message_helper.safe_edit(
                update,
                text="📢 广告列表\n\n暂无广告，点击「创建广告」开始",
                reply_markup=keyboard,
            )
            return

        text = f"📢 广告列表\n\n共 {len(ads)} 个广告"
        keyboard = ads_list_keyboard(ads, target_chat_id, page)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示广告统计"""
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

        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


# 创建单例实例
_ads_handler = AdsHandler()


# ==================== 命令和适配器函数（供 Router 注册）====================

async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    管理员发布广告（MVP）：/ad 标题|内容
    提供快速的命令行方式创建广告
    """
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("请在群里使用 /ad。")
        return
    if not await is_user_admin(context, chat.id, update.effective_user.id):
        await update.effective_message.reply_text("需要管理员权限。")
        return

    text = (update.effective_message.text or "").strip()
    if text == "/ad" or text.startswith("/ad@") or len(text.split(maxsplit=1)) == 1:
        await update.effective_message.reply_text("用法：/ad 标题|内容\n示例：/ad 置顶活动|今晚 8 点直播，欢迎参加")
        return

    payload = text.split(maxsplit=1)[1]
    if "|" in payload:
        title, content = payload.split("|", 1)
    else:
        title, content = "广告", payload
    title = title.strip()[:120]
    content = content.strip()
    if not content:
        await update.effective_message.reply_text("内容不能为空。")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        if not settings.ads_enabled:
            await session.commit()
            await update.effective_message.reply_text("本群未开启广告功能（/admin → 群设置 中开启）。")
            return
        session.add(AdCampaign(chat_id=chat.id, created_by_user_id=update.effective_user.id, title=title, content=content))
        await session.commit()

    await context.bot.send_message(chat_id=chat.id, text=f"【{title}】\n{content}")


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
            await _ads_handler.message_helper.safe_edit(update, "请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await _ads_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
            return

        # 处理返回操作
        data = q.data or ""
        if data == "ads:menu":
            from bot.handlers.admin_handler import _show_private_admin_menu
            await _show_private_admin_menu(update, context, target_chat_id)
            return
    else:
        if not await is_user_admin(context, chat.id, user.id):
            await _ads_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
            return
        target_chat_id = chat.id

    # 使用 Handler 处理
    await _ads_handler.show_menu(update, context, target_chat_id)


async def ads_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    page = cb.get_int(2, default=0)

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    # 使用 Handler 处理
    await _ads_handler.show_list(update, context, target_chat_id, page)


async def ads_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """广告统计回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    # 使用 Handler 处理
    await _ads_handler.show_stats(update, context, target_chat_id)


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
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int(2)
    if ad_id == 0:
        return

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
    """开始创建广告 - 显示配置格式说明"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的广告创建 - 优先从 callback_data 获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        # 优先从 callback_data 提取 chat_id
        data = q.data or ""
        if data.startswith("ads:create:"):
            cb = CallbackParser.parse(data)
            target_chat_id = cb.get_int(2)

        # 如果 callback_data 中没有 chat_id，从数据库获取
        if target_chat_id is None:
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
        # 设置状态为一次性创建
        await set_user_state(session, chat.id, user.id, "ads_create_config", {"target_chat_id": target_chat_id})
        await session.commit()

    config_help = """➕ 创建广告

请按以下格式输入配置：

<strong>广告标题</strong>

开始时间: 2026-01-09 10:00
推送间隔: 24小时
推送次数: 7次

内容:
这是广告的详细内容
可以多行显示

<strong>参数说明：</strong>
• <strong>标题</strong>：第一行必填，最多128字
• <strong>开始时间</strong>：可选，格式 YYYY-MM-DD HH:MM
• <strong>推送间隔</strong>：可选，如「24小时」，不填则只推送一次
• <strong>推送次数</strong>：可选，如「7次」，不填则无限制
• <strong>内容</strong>：使用「内容:」标记开始

<strong>简化示例：</strong>
今晚聚餐广告

内容:
欢迎大家参加今晚的聚餐活动！"""

    await q.edit_message_text(config_help, parse_mode="HTML")


async def ads_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理一次性配置输入"""
    # 添加调试日志
    import structlog
    log = structlog.get_logger(__name__)
    log.warning(
        "=== ads_create_config_message CALLED ===",
        user_id=update.effective_user.id if update.effective_user else None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        text_preview=(update.effective_message.text or "")[:50] if update.effective_message else "",
    )

    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text or ""

    if not text:
        return

    try:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            # 获取用户状态 - 私聊中使用 user.id 查询状态，与其他处理器保持一致
            state_chat_id = user.id if chat.type == "private" else chat.id
            state = await get_user_state(session, state_chat_id, user.id)
            log.info("ads_state_check", chat_id=state_chat_id, user_id=user.id, state_type=state.state_type if state else None)

            # 静默忽略非广告创建状态，避免干扰其他功能
            # 关键修复：不要 return，让代码继续执行到块结束
            if not state or state.state_type != "ads_create_config":
                log.info("ads_state_not_match", state_type=state.state_type if state else None)
                # 不要在这里 return，让代码继续执行到块结束
            else:
                target_chat_id = state.state_data.get("target_chat_id")
                if not target_chat_id:
                    await update.effective_message.reply_text("❌ 会话已过期，请重新开始")
                    await clear_user_state(session, chat.id, user.id)
                    await session.commit()
                    return

                # 解析配置
                try:
                    config = _parse_ads_config(text)

                    # 验证标题
                    if not config.get("title"):
                        await update.effective_message.reply_text("❌ 标题不能为空\n\n请重新输入配置")
                        await session.commit()
                        return

                    # 验证内容
                    if not config.get("content"):
                        await update.effective_message.reply_text("❌ 内容不能为空\n\n请重新输入配置")
                        await session.commit()
                        return

                    # 创建广告
                    result = await create_ad_campaign(
                        session,
                        chat_id=target_chat_id,
                        created_by_user_id=user.id,
                        title=config["title"],
                        content=config["content"],
                        start_time=config.get("start_time"),
                        interval_hours=config.get("interval_hours"),
                        max_send_count=config.get("max_send_count"),
                    )

                    if result.success:
                        ad = result.entity

                        # 构建成功消息
                        success_msg = f"✅ 广告创建成功！\n\n标题: {ad.title}\n\n"
                        if ad.start_time:
                            success_msg += f"开始时间: {ad.start_time.strftime('%Y-%m-%d %H:%M')}\n"
                        if ad.interval_hours:
                            success_msg += f"推送间隔: {ad.interval_hours}小时\n"
                        if ad.max_send_count:
                            success_msg += f"推送次数: {ad.max_send_count}次\n"
                        success_msg += f"\n{ad.content[:100]}{'...' if len(ad.content) > 100 else ''}"
                        success_msg += f"\n\n广告ID: {ad.id}"

                        # 清除状态
                        await clear_user_state(session, chat.id, user.id)
                        await session.commit()

                        # 只显示一个返回按钮
                        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("« 返回管理菜单", callback_data=f"adm:menu:{target_chat_id}")]
                        ])

                        await update.effective_message.reply_text(success_msg, reply_markup=keyboard)
                    else:
                        await update.effective_message.reply_text("❌ 创建失败，请重试")
                        await session.commit()

                except Exception as e:
                    log.exception(
                        "ads_create_error",
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=True
                    )
                    await update.effective_message.reply_text(f"❌ 配置格式错误: {str(e)}\n\n请检查后重试")
                    await session.commit()

            log.info("ads_handler_done")
    except Exception as e:
        # 确保异常被记录但不会阻止后续处理器
        import structlog
        log = structlog.get_logger(__name__)
        log.exception(
            "ads_create_config_message_error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=True
        )
        # 明确返回，不重新抛出异常，让后续处理器继续执行
        return


def _parse_ads_config(text: str) -> dict:
    """解析广告配置

    Args:
        text: 配置文本

    Returns:
        配置字典，包含:
        - title: 广告标题
        - content: 广告内容
        - start_time: 开始时间（可选）
        - interval_hours: 推送间隔（可选）
        - max_send_count: 最大推送次数（可选）
    """
    lines = text.strip().split("\n")

    if not lines:
        raise ValueError("配置不能为空")

    # 第一行是标题
    title = lines[0].strip()

    content = ""
    start_time = None
    interval_hours = None
    max_send_count = None

    # 解析参数
    content_started = False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # 如果已经开始解析内容，所有行都是内容
        if content_started:
            content += line + "\n"
            continue

        # 检查是否是参数行
        if line.startswith("开始时间:") or line.startswith("开始时间："):
            start_time = _parse_start_time(line.split(":")[1].split("：")[1].strip())
        elif line.startswith("推送间隔:") or line.startswith("推送间隔："):
            interval_hours = _parse_interval(line.split(":")[1].split("：")[1].strip())
        elif line.startswith("推送次数:") or line.startswith("推送次数："):
            max_send_count = _parse_send_count(line.split(":")[1].split("：")[1].strip())
        elif line.startswith("内容:") or line.startswith("内容："):
            content_started = True
            # 提取同行的内容
            if ":" in line or "：" in line:
                parts = line.split(":") if ":" in line else line.split("：")
                if len(parts) > 1:
                    content += parts[1].strip() + "\n"
        else:
            # 不是已知参数，作为描述或内容
            if not content:
                content += line + "\n"

    return {
        "title": title,
        "content": content.strip(),
        "start_time": start_time,
        "interval_hours": interval_hours,
        "max_send_count": max_send_count,
    }


def _parse_start_time(time_str: str) -> dt.datetime | None:
    """解析开始时间并转换为 UTC

    Args:
        time_str: 时间字符串，格式 YYYY-MM-DD HH:MM

    Returns:
        UTC 时间或 None
    """
    try:
        # 解析用户输入的本地时间（北京时间 UTC+8）
        local_time = dt.datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        # 转换为 UTC
        local_tz = dt.timezone(dt.timedelta(hours=8))
        return local_time.replace(tzinfo=local_tz).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def _parse_interval(interval_str: str) -> int | None:
    """解析推送间隔（小时）

    Args:
        interval_str: 间隔字符串，如「24小时」

    Returns:
        间隔小时数或 None
    """
    try:
        # 提取数字
        import re
        match = re.search(r'\d+', interval_str)
        if match:
            return int(match.group())
    except (ValueError, AttributeError):
        pass
    return None


def _parse_send_count(count_str: str) -> int | None:
    """解析推送次数

    Args:
        count_str: 次数字符串，如「7次」

    Returns:
        次数或 None
    """
    try:
        # 提取数字
        import re
        match = re.search(r'\d+', count_str)
        if match:
            return int(match.group())
    except (ValueError, AttributeError):
        pass
    return None


async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """立即发送广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    data = q.data or ""
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int(2)
    if ad_id == 0:
        return

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
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int(2)
    if ad_id == 0:
        return

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
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int(2)
    if ad_id == 0:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_ad(session, ad_id)
        await session.commit()

        if success:
            await q.edit_message_text("✅ 广告已删除", reply_markup=ads_menu_keyboard())
        else:
            await q.edit_message_text("❌ 广告不存在")

