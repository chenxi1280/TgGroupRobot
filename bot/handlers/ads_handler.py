from __future__ import annotations

import structlog
import datetime as dt
import re
from telegram import Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
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
from bot.services.core.module_settings_service import ModuleSettingsService
from bot.services.core.permission_service import PermissionPolicyService
from bot.services.integration.chat_group_service import get_user_managed_chats
from bot.services.shared.publish_service import PublishService
from bot.services.state.conversation_state_service import ConversationStateService
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.models.core import AdCampaign
from bot.utils.callback_parser import CallbackParser
from bot.utils.telegram_errors import answer_callback_query_safely, build_public_error_text

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
        scheduled_count = sum(1 for ad in ads if ad.schedule_time or ad.start_time or ad.interval_hours)

        text = f"📊 广告统计\n\n"
        text += f"总广告数: {len(ads)}\n"
        text += f"启用中: {enabled_count}\n"
        text += f"含图片: {with_image_count}\n"
        text += f"定时推送: {scheduled_count}"

        keyboard = ads_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


# 创建单例实例
_ads_handler = AdsHandler()
_FREQ_LABELS = {"once": "单次", "daily": "每天", "weekly": "每周", "monthly": "每月"}


async def _resolve_ads_target_chat_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    allow_current_chat_fallback: bool = True,
    error_message: str = "请先选择一个群组",
) -> int | None:
    if update.effective_chat is None or update.effective_user is None:
        return None

    chat = update.effective_chat
    user = update.effective_user

    if chat.type != "private":
        allowed = await PermissionPolicyService.can_manage(
            context,
            chat.id,
            user.id,
            capability="automation",
        )
        if not allowed:
            await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
            return None
        return chat.id

    callback_data = update.callback_query.data if update.callback_query and update.callback_query.data else ""
    callback_chat_id = CallbackParser.parse(callback_data).get_int_optional(2) if callback_data else None
    candidate_chat_ids: list[int] = []
    if callback_chat_id not in (None, 0):
        candidate_chat_ids.append(callback_chat_id)

    if allow_current_chat_fallback:
        db: Database = context.application.bot_data["db"]
        current_chat_id = await ChatResolver.get_current_chat(db, user.id)
        if current_chat_id not in (None, 0) and current_chat_id not in candidate_chat_ids:
            candidate_chat_ids.append(current_chat_id)

    for target_chat_id in candidate_chat_ids:
        allowed = await PermissionPolicyService.can_manage(
            context,
            target_chat_id,
            user.id,
            capability="automation",
        )
        if allowed:
            return target_chat_id

    if candidate_chat_ids:
        await answer_callback_query_safely(update, "你没有该群组的管理权限", show_alert=True)
    else:
        await answer_callback_query_safely(update, error_message, show_alert=True)
    return None


def _resolve_ads_state_chat_id(update: Update, target_chat_id: int) -> int:
    if update.effective_chat is None:
        return target_chat_id
    return update.effective_chat.id if update.effective_chat.type == "private" else target_chat_id


def _format_ad_push_text(ad: AdCampaign) -> str:
    return f"【{ad.title}】\n\n{ad.content}"


def _format_ad_detail_text(ad: AdCampaign) -> str:
    status_emoji = "🟢" if ad.enabled else "🔴"
    status_text = "启用" if ad.enabled else "暂停"

    schedule_info = ""
    if ad.schedule_time:
        schedule_info = f"\n⏰ 定时: {ad.schedule_time.strftime('%Y-%m-%d %H:%M')}"
        if ad.frequency:
            schedule_info += f" [{_FREQ_LABELS.get(ad.frequency, ad.frequency)}]"

    image_info = "\n🖼️ 含图片" if ad.has_image else ""
    last_sent_info = f"\n📤 上次发送: {ad.last_sent_at.strftime('%Y-%m-%d %H:%M')}" if ad.last_sent_at else ""
    return (
        f"{status_emoji} {ad.title}\n\n"
        f"状态: {status_text}{schedule_info}{image_info}{last_sent_info}\n\n"
        f"{ad.content}"
    )


def _parse_ad_id_from_callback(data: str) -> int:
    """解析广告 ID，兼容 ads:action:{id} / ads:action_{id} 两种格式。"""
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int_optional(2)
    if ad_id is not None and ad_id > 0:
        return ad_id

    match = re.search(r"^ads:(?:detail|toggle|delete|send)_(\d+)$", data)
    if match:
        return int(match.group(1))

    return 0


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
    if not await PermissionPolicyService.can_manage(context, chat.id, update.effective_user.id, capability="automation"):
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

    data = q.data or ""
    if chat.type == "private" and data == "ads:menu":
        target_chat_id = await _resolve_ads_target_chat_id(update, context)
        if target_chat_id is None:
            return
        from bot.handlers.admin_handler import _show_private_admin_menu
        await _show_private_admin_menu(update, context, target_chat_id)
        return

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

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

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
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

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
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

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    ad_id = _parse_ad_id_from_callback(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if not ad:
            await session.commit()
            await q.edit_message_text("广告不存在", reply_markup=ads_menu_keyboard(target_chat_id))
            return

        if ad.chat_id != target_chat_id:
            await session.commit()
            await answer_callback_query_safely(update, "该广告不属于当前群组")
            return

        text = _format_ad_detail_text(ad)
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

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await ModuleSettingsService.ensure(
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
        # 设置状态为一次性创建；私聊输入仍按当前会话(chat.id)保存
        await ConversationStateService.start(
            session,
            chat_id=chat.id,
            user_id=user.id,
            state_type="ads_create_config",
            state_data={"target_chat_id": target_chat_id},
        )
        await session.commit()

    config_help = """➕ 创建广告 ( /cancel 取消 )

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
• <strong>图片</strong>：可选，先发送一张图片保存 file_id，或在配置中写「图片ID: xxxxx」
• <strong>内容</strong>：使用「内容:」标记开始

<strong>简化示例：</strong>
今晚聚餐广告

内容:
欢迎大家参加今晚的聚餐活动！

<strong>图片示例：</strong>
图片ID: AgACAgUAAxkBAAIB...
内容:
图文广告内容"""

    # 添加取消按钮
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ 取消配置", callback_data=f"ads:cancel:{target_chat_id}")]
    ])

    await q.edit_message_text(config_help, parse_mode="HTML", reply_markup=keyboard)


async def ads_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理广告创建配置（支持文本配置、图片上传、caption 一次性创建）"""
    import structlog

    logger = structlog.get_logger(__name__)
    log.warning(
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
            state_chat_id = chat.id if chat.type == "private" else chat.id
            state = await ConversationStateService.get(session, state_chat_id, user.id)
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
                await ConversationStateService.clear(session, state_chat_id, user.id)
                await session.commit()
                return

            # 支持先发图再发配置文本：先缓存 file_id
            if image_file_id:
                state_data["image_file_id"] = image_file_id
                state.state_data = state_data
                await session.flush()

            # 只有图片没有文本：仅保存图片，等待后续配置文本
            if not text:
                await session.commit()
                if image_file_id:
                    await PublishService.reply(
                        context,
                        chat_id=chat.id,
                        reply_to_message_id=message.message_id,
                        text="✅ 已保存图片 file_id。\n请继续发送广告配置文本（可按模板直接粘贴）。",
                    )
                return

            try:
                config = _parse_ads_config(text)
            except Exception as e:
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

            final_image_file_id = (
                config.get("image_file_id")
                or state_data.get("image_file_id")
                or image_file_id
            )

            result = await create_ad_campaign(
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
            success_msg = f"✅ 广告创建成功！\n\n标题: {ad.title}\n\n"
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
            success_msg += f"\n\n广告ID: {ad.id}"

            await ConversationStateService.clear(session, state_chat_id, user.id)
            await session.commit()

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回广告管理", callback_data=f"ads:menu:{target_chat_id}")],
                [InlineKeyboardButton("🏠 返回主菜单", callback_data=f"adm:menu:{target_chat_id}")],
            ])

            await PublishService.reply(
                context,
                chat_id=chat.id,
                reply_to_message_id=message.message_id,
                text=success_msg,
                reply_markup=keyboard,
            )
            logger.info("ads_handler_done")
    except Exception as e:
        logger.exception(
            "ads_create_config_message_error",
            error=str(e),
            error_type=type(e).__name__,
            traceback=True,
        )
        return


async def ads_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消广告配置，返回广告菜单"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        # 清除配置状态
        state_chat_id = _resolve_ads_state_chat_id(update, target_chat_id)
        await ConversationStateService.clear(session, state_chat_id, user.id)
        await session.commit()

    # 返回广告菜单
    if chat.type == "private":
        # 私聊中返回广告管理菜单
        await _ads_handler.show_menu(update, context, target_chat_id)
    else:
        # 群聊中直接返回广告菜单
        keyboard = ads_menu_keyboard(target_chat_id)
        await q.edit_message_text("📢 广告管理\n\n管理群内广告推送", reply_markup=keyboard)


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

    content_lines: list[str] = []
    start_time = None
    interval_hours = None
    max_send_count = None
    image_file_id = None

    # 解析参数
    content_started = False
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        # 如果已经开始解析内容，所有行都是内容
        if content_started:
            content_lines.append(line)
            continue

        matched, value = _match_prefixed_value(line, "开始时间")
        if matched:
            start_time = _parse_start_time(value)
            if start_time is None:
                raise ValueError("开始时间格式错误，应为 YYYY-MM-DD HH:MM")
            continue

        matched, value = _match_prefixed_value(line, "推送间隔")
        if matched:
            interval_hours = _parse_interval(value)
            if interval_hours is None:
                raise ValueError("推送间隔格式错误，应为如“24小时”")
            continue

        matched, value = _match_prefixed_value(line, "推送次数")
        if matched:
            max_send_count = _parse_send_count(value)
            if max_send_count is None:
                raise ValueError("推送次数格式错误，应为如“7次”")
            continue

        matched, value = _match_prefixed_value(line, "图片ID")
        if not matched:
            matched, value = _match_prefixed_value(line, "图片id")
        if not matched:
            matched, value = _match_prefixed_value(line, "image_file_id")
        if matched:
            image_file_id = value.strip() or None
            continue

        matched, value = _match_prefixed_value(line, "内容")
        if matched:
            content_started = True
            if value.strip():
                content_lines.append(value.strip())
            continue

        # 未匹配参数时，默认视为正文
        content_lines.append(line)

    return {
        "title": title,
        "content": "\n".join(content_lines).strip(),
        "start_time": start_time,
        "interval_hours": interval_hours,
        "max_send_count": max_send_count,
        "image_file_id": image_file_id,
    }


def _match_prefixed_value(line: str, key: str) -> tuple[bool, str]:
    """匹配 `key: value` 或 `key：value`。"""
    for sep in (":", "："):
        prefix = f"{key}{sep}"
        if line.startswith(prefix):
            return True, line[len(prefix):].strip()
    return False, ""


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
        match = re.search(r"\d+", interval_str)
        if match:
            value = int(match.group())
            return value if value > 0 else None
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
        match = re.search(r"\d+", count_str)
        if match:
            value = int(match.group())
            return value if value > 0 else None
    except (ValueError, AttributeError):
        pass
    return None


async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """立即发送广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    ad_id = _parse_ad_id_from_callback(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if not ad:
            await q.edit_message_text("广告不存在")
            return

        if ad.chat_id != target_chat_id:
            await answer_callback_query_safely(update, "该广告不属于当前群组")
            await session.commit()
            return

        # 发送广告
        try:
            if ad.image_file_id:
                await PublishService.send_photo(
                    context,
                    chat_id=ad.chat_id,
                    photo=ad.image_file_id,
                    caption=_format_ad_push_text(ad),
                )
            else:
                await PublishService.send(
                    context,
                    chat_id=ad.chat_id,
                    text=_format_ad_push_text(ad),
                )

            # 标记已发送
            await mark_ad_sent(session, ad_id)
            await session.commit()

            # 刷新详情
            ad_updated = await get_ad(session, ad_id)
            text = _format_ad_detail_text(ad_updated)
            await q.edit_message_text(text, reply_markup=ads_detail_keyboard(ad_id, ad_updated.enabled))
        except Exception as e:
            await q.edit_message_text(f"❌ 发送失败: {build_public_error_text(e, fallback='请稍后重试')}")


async def ads_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换广告启用状态"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    ad_id = _parse_ad_id_from_callback(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if ad is None:
            await q.edit_message_text("广告不存在")
            return

        if ad.chat_id != target_chat_id:
            await answer_callback_query_safely(update, "该广告不属于当前群组")
            await session.commit()
            return

        ad = await toggle_ad(session, ad_id)
        await session.commit()

        text = _format_ad_detail_text(ad)
        await q.edit_message_text(text, reply_markup=ads_detail_keyboard(ad_id, ad.enabled))


async def ads_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除广告"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    ad_id = _parse_ad_id_from_callback(q.data or "")
    if ad_id == 0:
        await answer_callback_query_safely(update, "广告 ID 无效")
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        ad = await get_ad(session, ad_id)
        if ad is None:
            await q.edit_message_text("广告不存在")
            await session.commit()
            return

        if ad.chat_id != target_chat_id:
            await answer_callback_query_safely(update, "该广告不属于当前群组")
            await session.commit()
            return

        success = await delete_ad(session, ad_id)
        await session.commit()

        if success:
            await q.edit_message_text("✅ 广告已删除", reply_markup=ads_menu_keyboard(target_chat_id))
        else:
            await q.edit_message_text("❌ 广告不存在")
