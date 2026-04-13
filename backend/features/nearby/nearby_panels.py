from __future__ import annotations

import datetime as dt
import html

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


async def reply_or_edit(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    if update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        except Exception:
            pass

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

    lat = float(profile.latitude) if profile.latitude is not None else None
    lon = float(profile.longitude) if profile.longitude is not None else None
    location_text = f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "未设置"
    updated_local = profile.updated_at.astimezone(_LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    text = (
        "👤 我的业务资料\n"
        "—————————————————\n"
        f"群组ID: {target_chat_id}\n"
        f"状态: {'可见' if profile.is_visible else '隐藏'}\n"
        f"📍 定位: {location_text}\n"
        f"💰 价格: {profile.price_text or '未设置'}\n"
        f"📦 方式: {profile.method_text or '未设置'}\n"
        f"🏠 备注: {profile.address_text or '未设置'}\n"
        "—————————————————\n"
        f"数据更新于：{updated_local}"
    )
    keyboard = nearby_manage_keyboard(target_chat_id, profile.is_visible)
    await reply_or_edit(update, text, keyboard)


async def show_nearby_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
    page: int,
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

    page = max(page, 0)
    start = page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    page_entries = entries[start:end]
    has_prev = page > 0
    has_next = end < len(entries)

    lines = ["📍 周边成员信息 (按距离排序)", "—————————————————"]
    member_buttons: list[tuple[str, int]] = []
    for entry in page_entries:
        lines.append(f"[{entry.display_name}] · 距离 {format_distance(entry.distance_km)}")
        lines.append(
            f"💰 价格: {entry.price_text or '未设置'} | 📦 方式: {entry.method_text or '未设置'}"
        )
        member_buttons.append((entry.display_name, entry.user_id))
    lines.append("—————————————————")
    lines.append(f"数据更新于：{dt.datetime.now(dt.UTC).astimezone(_LOCAL_TZ).strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"第 {page + 1} 页 / 共 {(len(entries) + _PAGE_SIZE - 1) // _PAGE_SIZE} 页")

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
    target_user_id: int,
    back_page: int,
) -> None:
    if update.effective_user is None:
        return
    viewer_id = update.effective_user.id
    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        viewer_profile = await get_profile(session, target_chat_id, viewer_id)
        if viewer_profile is None or viewer_profile.latitude is None or viewer_profile.longitude is None:
            await reply_or_edit(update, "你还没有设置定位，先私聊发送 /mydata 并更新位置。")
            await session.commit()
            return

        profile_with_user = await get_profile_with_user(session, target_chat_id, target_user_id)
        if profile_with_user is None:
            await reply_or_edit(update, "该成员资料不存在。")
            await session.commit()
            return

        profile, user = profile_with_user
        if not profile.is_visible or profile.latitude is None or profile.longitude is None:
            await reply_or_edit(update, "该成员已隐藏位置或未设置定位。")
            await session.commit()
            return

        distance = haversine_distance_km(
            float(viewer_profile.latitude),
            float(viewer_profile.longitude),
            float(profile.latitude),
            float(profile.longitude),
        )
        display_name = build_user_display_name(user, user.id)
        distance_text = format_distance(distance, fuzzy=profile.fuzzy_distance)
        distance_mode = "模糊处理" if profile.fuzzy_distance else "精确距离"
        await session.commit()

    if user.username:
        mention_text = f"@{user.username}"
    else:
        mention_label = f"@{display_name}" if not display_name.startswith("@") else display_name
        mention_text = f'<a href="tg://user?id={target_user_id}">{html.escape(mention_label)}</a>'

    escaped_display_name = html.escape(display_name)
    escaped_price = html.escape(profile.price_text or "未设置")
    escaped_method = html.escape(profile.method_text or "未设置")
    escaped_address = html.escape(profile.address_text or "未设置")
    detail_text = (
        "👤 成员详细档案\n"
        "—————————————————\n"
        f"用户： {escaped_display_name}\n"
        f"@成员： {mention_text}\n"
        f"距离： 📍 {distance_text} 处 ({distance_mode})\n"
        "业务详情：\n"
        f"💰 服务价格： {escaped_price}\n"
        f"📦 交付方式： {escaped_method}\n"
        f"🏠 详细描述： {escaped_address}\n"
        "—————————————————"
    )
    keyboard = nearby_detail_keyboard(target_chat_id, target_user_id, back_page)
    await reply_or_edit(update, detail_text, keyboard, parse_mode="HTML")
