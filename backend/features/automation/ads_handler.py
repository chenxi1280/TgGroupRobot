from __future__ import annotations

import structlog
import datetime as dt
import re
from telegram import Update
from telegram.ext import ContextTypes

from backend.features.automation.ads_creation_actions import (
    ads_cancel_action,
    ads_create_config_message_action,
    ads_create_start_action,
)
from backend.features.automation.ads_delivery_actions import (
    ads_delete_action,
    ads_detail_action,
    ads_send_action,
    ads_toggle_action,
)
from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.features.automation.ui.ads import (
    ads_create_keyboard,
    ads_detail_keyboard,
    ads_frequency_keyboard,
    ads_list_keyboard,
    ads_menu_keyboard,
)
from backend.features.automation.services.ad_service import (
    create_ad_campaign,
    delete_ad,
    get_ad,
    get_ad_next_send_time,
    get_chat_ads,
    is_ad_exhausted,
    is_rotation_ad,
    mark_ad_sent,
    should_send_ad,
    toggle_ad,
)
from backend.shared.services.module_settings_service import ModuleSettingsService
from backend.shared.services.permission_service import PermissionPolicyService
from backend.features.group_ops.services.chat_group_service import get_user_managed_chats
from backend.shared.services.publish_service import PublishService
from backend.platform.state.conversation_state_service import ConversationStateService
from backend.shared.services.chat_service import ensure_chat, get_chat_settings
from backend.platform.db.schema.models.core import AdCampaign
from backend.platform.telegram.errors import (
    answer_callback_query_safely,
    build_public_error_text,
    mark_callback_query_answered,
)
from backend.features.automation.ads_menu import AdsHandler, _ads_handler
from backend.features.automation.ads_helpers import (
    _resolve_ads_target_chat_id,
    _resolve_ads_state_chat_id,
    _format_ad_push_text,
    _format_ad_detail_text,
    _parse_ad_id_from_callback,
)
from backend.features.automation.ads_parsing import (
    _parse_ads_config,
    _match_prefixed_value,
    _parse_start_time,
    _parse_interval,
    _parse_send_count,
)
from backend.shared.callback_parser import CallbackParser

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
    """轮播广告菜单回调"""
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
        from backend.features.admin.admin_handler import _show_private_admin_menu
        await _show_private_admin_menu(update, context, target_chat_id)
        return

    target_chat_id = await _resolve_ads_target_chat_id(update, context)
    if target_chat_id is None:
        return

    # 使用 Handler 处理
    await _ads_handler.show_menu(update, context, target_chat_id)


async def ads_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """轮播广告列表回调"""
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
    """轮播广告看板回调"""
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
    await ads_detail_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        parse_ad_id_func=_parse_ad_id_from_callback,
        get_ad_func=get_ad,
        format_ad_detail_text_func=_format_ad_detail_text,
        ads_menu_keyboard_func=ads_menu_keyboard,
        ads_detail_keyboard_func=ads_detail_keyboard,
        answer_callback_query_safely_func=answer_callback_query_safely,
        mark_callback_query_answered_func=mark_callback_query_answered,
    )


async def ads_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建轮播广告 - 显示配置格式说明"""
    await ads_create_start_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        module_settings_service=ModuleSettingsService,
        conversation_state_service=ConversationStateService,
    )


async def ads_create_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理广告创建配置（支持文本配置、图片上传、caption 一次性创建）"""
    await ads_create_config_message_action(
        update,
        context,
        parse_ads_config_func=_parse_ads_config,
        create_ad_campaign_func=create_ad_campaign,
        conversation_state_service=ConversationStateService,
    )


async def ads_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """取消轮播广告配置，返回菜单"""
    await ads_cancel_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        resolve_state_chat_id_func=_resolve_ads_state_chat_id,
        conversation_state_service=ConversationStateService,
        show_menu_func=_ads_handler.show_menu,
        ads_menu_keyboard_func=ads_menu_keyboard,
    )



async def ads_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """立即发送广告"""
    await ads_send_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        parse_ad_id_func=_parse_ad_id_from_callback,
        get_ad_func=get_ad,
        format_ad_push_text_func=_format_ad_push_text,
        format_ad_detail_text_func=_format_ad_detail_text,
        mark_ad_sent_func=mark_ad_sent,
        ads_detail_keyboard_func=ads_detail_keyboard,
        answer_callback_query_safely_func=answer_callback_query_safely,
        mark_callback_query_answered_func=mark_callback_query_answered,
        build_public_error_text_func=build_public_error_text,
        publish_service=PublishService,
    )


async def ads_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """切换广告启用状态"""
    await ads_toggle_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        parse_ad_id_func=_parse_ad_id_from_callback,
        get_ad_func=get_ad,
        toggle_ad_func=toggle_ad,
        format_ad_detail_text_func=_format_ad_detail_text,
        ads_detail_keyboard_func=ads_detail_keyboard,
        answer_callback_query_safely_func=answer_callback_query_safely,
        mark_callback_query_answered_func=mark_callback_query_answered,
    )


async def ads_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除广告"""
    await ads_delete_action(
        update,
        context,
        resolve_target_chat_id_func=_resolve_ads_target_chat_id,
        parse_ad_id_func=_parse_ad_id_from_callback,
        get_ad_func=get_ad,
        delete_ad_func=delete_ad,
        ads_menu_keyboard_func=ads_menu_keyboard,
        answer_callback_query_safely_func=answer_callback_query_safely,
        mark_callback_query_answered_func=mark_callback_query_answered,
    )
