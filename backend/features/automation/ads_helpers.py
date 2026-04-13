from __future__ import annotations

import datetime as dt
import re

from telegram import Update
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.chat_resolver import ChatResolver
from backend.shared.services.permission_service import PermissionPolicyService
from backend.platform.db.schema.models.core import AdCampaign
from backend.shared.callback_parser import CallbackParser
from backend.platform.telegram.errors import answer_callback_query_safely
from backend.features.automation.services.ad_service import (
    get_ad_next_send_time,
    is_ad_exhausted,
    is_rotation_ad,
)

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
    local_tz = dt.timezone(dt.timedelta(hours=8))
    mode_text = "轮播" if is_rotation_ad(ad) else "单次"

    schedule_info = ""
    if ad.start_time:
        schedule_info = f"\n🕒 开始: {ad.start_time.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')} (UTC+8)"
    elif ad.schedule_time:
        schedule_info = f"\n🕒 开始: {ad.schedule_time.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')} (UTC+8)"

    rotation_info = f"\n🔁 间隔: {ad.interval_hours}小时" if ad.interval_hours else ""
    if not ad.interval_hours and ad.frequency:
        rotation_info = f"\n🔁 频率: {_FREQ_LABELS.get(ad.frequency, ad.frequency)}"

    quota_info = ""
    if ad.max_send_count:
        quota_info = f"\n📈 进度: {ad.send_count}/{ad.max_send_count}"
        if is_ad_exhausted(ad):
            quota_info += "（已达上限）"
    elif ad.send_count:
        quota_info = f"\n📈 已推送: {ad.send_count}次"

    next_send_at = get_ad_next_send_time(ad)
    next_send_info = ""
    if next_send_at:
        next_send_info = f"\n⏭️ 下次: {next_send_at.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')} (UTC+8)"

    image_info = "\n🖼️ 含图片" if ad.has_image else ""
    last_sent_info = (
        f"\n📤 上次发送: {ad.last_sent_at.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')} (UTC+8)"
        if ad.last_sent_at
        else ""
    )
    return (
        f"{status_emoji} {ad.title}\n\n"
        f"状态: {status_text}\n"
        f"模式: {mode_text}"
        f"{schedule_info}{rotation_info}{quota_info}{next_send_info}{image_info}{last_sent_info}\n\n"
        f"{ad.content}"
    )


def _parse_ad_id_from_callback(data: str) -> int:
    cb = CallbackParser.parse(data)
    ad_id = cb.get_int_optional(2)
    if ad_id is not None and ad_id > 0:
        return ad_id

    match = re.search(r"^ads:(?:detail|toggle|delete|send)_(\d+)$", data)
    if match:
        return int(match.group(1))
    return 0
