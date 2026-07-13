from __future__ import annotations

import datetime as dt
import html

import structlog
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.nearby.services.nearby_profile_service import (
    build_user_display_name,
    format_distance,
    get_or_create_profile,
    get_profile,
    get_profile_with_user,
    haversine_distance_km,
    list_nearby_entries,
)
from backend.features.nearby.ui.nearby import (
    nearby_detail_keyboard,
    nearby_list_keyboard,
    nearby_manage_keyboard,
)
from backend.platform.db.runtime.session import Database

_LOCAL_TZ = dt.timezone(dt.timedelta(hours=8))
_PAGE_SIZE = 5

log = structlog.get_logger(__name__)


def _mydata_text(profile, target_chat_id: int) -> str:
    lat = float(profile.latitude) if profile.latitude is not None else None
    lon = float(profile.longitude) if profile.longitude is not None else None
    location = f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "未设置"
    updated = profile.updated_at.astimezone(_LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    return (
        "👤 我的业务资料\n—————————————————\n"
        f"群组ID: {target_chat_id}\n状态: {'可见' if profile.is_visible else '隐藏'}\n"
        f"📍 定位: {location}\n💰 价格: {profile.price_text or '未设置'}\n"
        f"📦 方式: {profile.method_text or '未设置'}\n🏠 备注: {profile.address_text or '未设置'}\n"
        f"—————————————————\n数据更新于：{updated}"
    )


def _nearby_list_content(entries, page: int):
    normalized_page = max(page, 0)
    start = normalized_page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    lines = ["📍 周边成员信息 (按距离排序)", "—————————————————"]
    buttons: list[tuple[str, int]] = []
    for entry in entries[start:end]:
        lines.append(f"[{entry.display_name}] · 距离 {format_distance(entry.distance_km)}")
        lines.append(f"💰 价格: {entry.price_text or '未设置'} | 📦 方式: {entry.method_text or '未设置'}")
        buttons.append((entry.display_name, entry.user_id))
    lines.extend([
        "—————————————————",
        f"数据更新于：{dt.datetime.now(dt.UTC).astimezone(_LOCAL_TZ).strftime('%Y-%m-%d %H:%M')}",
        f"第 {normalized_page + 1} 页 / 共 {(len(entries) + _PAGE_SIZE - 1) // _PAGE_SIZE} 页",
    ])
    return lines, buttons, normalized_page, normalized_page > 0, end < len(entries)


async def _load_member_detail_data(update, session, target_chat_id: int, *, viewer_id: int, target_user_id: int):
    viewer = await get_profile(session, target_chat_id, viewer_id)
    if viewer is None or viewer.latitude is None or viewer.longitude is None:
        await reply_or_edit(update, "你还没有设置定位，先私聊发送 /mydata 并更新位置。")
        await session.commit()
        return None
    profile_with_user = await get_profile_with_user(session, target_chat_id, target_user_id)
    if profile_with_user is None:
        await reply_or_edit(update, "该成员资料不存在。")
        await session.commit()
        return None
    profile, user = profile_with_user
    if not profile.is_visible or profile.latitude is None or profile.longitude is None:
        await reply_or_edit(update, "该成员已隐藏位置或未设置定位。")
        await session.commit()
        return None
    distance = haversine_distance_km(float(viewer.latitude), float(viewer.longitude), float(profile.latitude), lon2=float(profile.longitude))
    await session.commit()
    return profile, user, distance


def _member_mention(user, display_name: str, target_user_id: int) -> str:
    if user.username:
        return f"@{user.username}"
    label = f"@{display_name}" if not display_name.startswith("@") else display_name
    return f'<a href="tg://user?id={target_user_id}">{html.escape(label)}</a>'


def _member_detail_text(profile, user, distance: float, *, target_user_id: int) -> str:
    display_name = build_user_display_name(user, user.id)
    mention = _member_mention(user, display_name, target_user_id)
    distance_text = format_distance(distance, fuzzy=profile.fuzzy_distance)
    distance_mode = "模糊处理" if profile.fuzzy_distance else "精确距离"
    return (
        "👤 成员详细档案\n—————————————————\n"
        f"用户： {html.escape(display_name)}\n@成员： {mention}\n距离： 📍 {distance_text} 处 ({distance_mode})\n"
        f"业务详情：\n💰 服务价格： {html.escape(profile.price_text or '未设置')}\n"
        f"📦 交付方式： {html.escape(profile.method_text or '未设置')}\n"
        f"🏠 详细描述： {html.escape(profile.address_text or '未设置')}\n—————————————————"
    )


async def reply_or_edit(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    *, parse_mode: str | None = None,
) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        except Exception as exc:
            log.warning("nearby_panel_edit_failed", error=str(exc))

    if update.effective_message is not None:
        await update.effective_message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


async def show_mydata_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
) -> None:
    if update.effective_user is None:
        return
    user = update.effective_user
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        profile = await get_or_create_profile(
            session,
            target_chat_id,
            user=user,
            chat_type="supergroup" if target_chat_id < 0 else "private",
            chat_title=None,
        )
        await session.commit()

    text = _mydata_text(profile, target_chat_id)
    keyboard = nearby_manage_keyboard(target_chat_id, profile.is_visible)
    await reply_or_edit(update, text, keyboard)


async def show_nearby_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    *, page: int,
) -> None:
    if update.effective_user is None:
        return
    user = update.effective_user
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        requester_profile = await get_profile(session, target_chat_id, user.id)
        if requester_profile is None or requester_profile.latitude is None or requester_profile.longitude is None:
            await reply_or_edit(
                update,
                "你还没有设置定位，先私聊发送 /mydata 并点击“📍 更新实时定位”。",
            )
            await session.commit()
            return

        entries = await list_nearby_entries(
            session,
            chat_id=target_chat_id,
            requester_user_id=user.id,
            requester_lat=float(requester_profile.latitude),
            requester_lon=float(requester_profile.longitude),
        )
        await session.commit()

    if not entries:
        await reply_or_edit(update, "📍 周边成员信息\n\n当前没有可展示的成员。")
        return

    lines, member_buttons, page, has_prev, has_next = _nearby_list_content(entries, page)

    keyboard = nearby_list_keyboard(
        target_chat_id,
        member_buttons,
        page=page,
        has_prev=has_prev,
        has_next=has_next,
    )
    await reply_or_edit(update, "\n".join(lines), keyboard)


async def show_member_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    *, target_user_id: int,
    back_page: int,
) -> None:
    if update.effective_user is None:
        return
    viewer_id = update.effective_user.id
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        detail_data = await _load_member_detail_data(
            update, session, target_chat_id, viewer_id=viewer_id, target_user_id=target_user_id
        )
    if detail_data is None:
        return
    profile, user, distance = detail_data
    detail_text = _member_detail_text(profile, user, distance, target_user_id=target_user_id)
    keyboard = nearby_detail_keyboard(target_chat_id, target_user_id, back_page)
    await reply_or_edit(update, detail_text, keyboard, parse_mode="HTML")
