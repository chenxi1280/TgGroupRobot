from __future__ import annotations

import datetime as dt

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db.session import Database
from bot.keyboards.integration.nearby import (
    nearby_clear_confirm_keyboard,
    nearby_detail_keyboard,
    nearby_list_keyboard,
    nearby_manage_keyboard,
)
from bot.services.core.chat_service import ensure_chat
from bot.services.core.user_service import ensure_user
from bot.services.integration.chat_group_service import get_user_current_chat, set_user_current_chat
from bot.services.integration.nearby_profile_service import (
    build_user_display_name,
    clear_profile,
    format_distance,
    get_or_create_profile,
    get_profile,
    get_profile_with_user,
    haversine_distance_km,
    list_nearby_entries,
    update_profile,
)
from bot.services.state.state_service import clear_user_state, set_user_state
from bot.utils.callback_parser import CallbackParser

log = structlog.get_logger(__name__)

_LOCAL_TZ = dt.timezone(dt.timedelta(hours=8))
_PAGE_SIZE = 5


class NearbyHandler:
    """周边资料与距离查询功能。"""

    async def mydata_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        chat = update.effective_chat
        user = update.effective_user
        db: Database = context.application.bot_data["db"]

        if chat.type in ("group", "supergroup"):
            async with db.session_factory() as session:
                await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
                await ensure_user(
                    session,
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    language_code=user.language_code,
                )
                await session.commit()

            await set_user_current_chat(db, user.id, chat.id)
            text = (
                "✅ 已绑定当前群组。\n\n"
                "请到私聊发送 /mydata 继续编辑资料。\n"
                "你也可以在本群使用 /nearby 查看周边。"
            )
            await update.effective_message.reply_text(text)
            return

        target_chat_id = await get_user_current_chat(db, user.id)
        if target_chat_id is None:
            await update.effective_message.reply_text("请先在目标群发送 /mydata 绑定群组，再来私聊编辑资料。")
            return

        await self._show_mydata_panel(update, context, target_chat_id)

    async def nearby_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
            return

        chat = update.effective_chat
        user = update.effective_user
        db: Database = context.application.bot_data["db"]

        if chat.type in ("group", "supergroup"):
            target_chat_id = chat.id
            await set_user_current_chat(db, user.id, target_chat_id)
            async with db.session_factory() as session:
                await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
                await ensure_user(
                    session,
                    user_id=user.id,
                    username=user.username,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    language_code=user.language_code,
                )
                await session.commit()
        else:
            target_chat_id = await get_user_current_chat(db, user.id)
            if target_chat_id is None:
                await update.effective_message.reply_text("请先在目标群发送 /mydata 绑定群组，再来私聊查看周边。")
                return

        await self._show_nearby_list(update, context, target_chat_id, page=0)

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.callback_query is None or update.effective_user is None:
            return

        q = update.callback_query
        await q.answer()

        data = q.data or ""
        cb = CallbackParser.parse(data)
        action = cb.get(1)
        db: Database = context.application.bot_data["db"]

        try:
            if action == "close":
                try:
                    await q.message.delete()
                except Exception:
                    await q.edit_message_text("已关闭。")
                return

            if action == "my":
                chat_id = cb.get_int(2)
                if chat_id == 0:
                    await q.edit_message_text("群组参数错误")
                    return
                await self._show_mydata_panel(update, context, chat_id)
                return

            if action == "set":
                chat_id = cb.get_int(2)
                field = cb.get(3)
                await self._start_edit_state(update, context, db, chat_id, field)
                return

            if action == "toggle":
                chat_id = cb.get_int(2)
                await self._toggle_visible(update, context, db, chat_id)
                return

            if action == "clear":
                chat_id = cb.get_int(2)
                step = cb.get(3)
                await self._handle_clear(update, context, db, chat_id, step)
                return

            if action in {"list", "refresh"}:
                chat_id = cb.get_int(2)
                page = cb.get_int(3, default=0)
                await self._show_nearby_list(update, context, chat_id, page=page)
                return

            if action == "detail":
                chat_id = cb.get_int(2)
                target_user_id = cb.get_int(3)
                back_page = cb.get_int(4, default=0)
                await self._show_member_detail(update, context, chat_id, target_user_id, back_page)
                return

            if action in {"fav", "report"}:
                label = "收藏" if action == "fav" else "举报"
                await self._reply_or_edit(update, f"{label}功能即将上线。")
                return

            await self._reply_or_edit(update, "未知操作。")
        except Exception as e:
            log.exception("nearby_callback_error", data=data, error=str(e))
            await q.edit_message_text(f"操作失败: {e}")

    async def handle_fsm_text_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
        message_text: str,
    ) -> None:
        if update.effective_user is None or update.effective_message is None:
            return

        user = update.effective_user
        state_type = str(state.state_type)
        target_chat_id = int(state.state_data.get("target_chat_id", 0)) if state.state_data else 0
        if target_chat_id == 0:
            await update.effective_message.reply_text("会话已过期，请重新发送 /mydata。")
            return

        text = (message_text or "").strip()
        if not text:
            await update.effective_message.reply_text("请输入有效内容。")
            return

        if text.startswith("/clear"):
            text_value: str | None = None
        else:
            text_value = text

        if state_type == "nearby_edit_price":
            await update_profile(session, target_chat_id, user, price_text=(text_value[:128] if text_value else None))
        elif state_type == "nearby_edit_method":
            await update_profile(session, target_chat_id, user, method_text=(text_value[:128] if text_value else None))
        elif state_type == "nearby_edit_address":
            await update_profile(session, target_chat_id, user, address_text=(text_value[:500] if text_value else None))
        else:
            await update.effective_message.reply_text("当前状态不支持文本输入。")
            return

        await clear_user_state(session, state.chat_id, user.id)
        profile = await get_profile(session, target_chat_id, user.id)

        await update.effective_message.reply_text(
            "✅ 已更新。",
            reply_markup=nearby_manage_keyboard(target_chat_id, bool(profile.is_visible if profile else True)),
        )

    async def handle_fsm_location_input(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session: AsyncSession,
        state,
    ) -> None:
        if update.effective_user is None or update.effective_message is None:
            return

        user = update.effective_user
        message = update.effective_message
        target_chat_id = int(state.state_data.get("target_chat_id", 0)) if state.state_data else 0
        if target_chat_id == 0:
            await message.reply_text("会话已过期，请重新发送 /mydata。")
            return

        if message.location is None:
            await message.reply_text("请直接发送 Telegram 定位消息。")
            return

        await update_profile(
            session,
            target_chat_id,
            user,
            latitude=message.location.latitude,
            longitude=message.location.longitude,
        )
        await clear_user_state(session, state.chat_id, user.id)

        profile = await get_profile(session, target_chat_id, user.id)
        await message.reply_text(
            "✅ 定位已更新。",
            reply_markup=nearby_manage_keyboard(target_chat_id, bool(profile.is_visible if profile else True)),
        )

    async def _show_mydata_panel(
        self,
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
        await self._reply_or_edit(update, text, keyboard)

    async def _show_nearby_list(
        self,
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
                await self._reply_or_edit(
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
            await self._reply_or_edit(update, "📍 周边成员信息\n\n当前没有可展示的成员。")
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
        await self._reply_or_edit(update, "\n".join(lines), keyboard)

    async def _show_member_detail(
        self,
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
                await self._reply_or_edit(update, "你还没有设置定位，先私聊发送 /mydata 并更新位置。")
                await session.commit()
                return

            profile_with_user = await get_profile_with_user(session, target_chat_id, target_user_id)
            if profile_with_user is None:
                await self._reply_or_edit(update, "该成员资料不存在。")
                await session.commit()
                return

            profile, user = profile_with_user
            if not profile.is_visible or profile.latitude is None or profile.longitude is None:
                await self._reply_or_edit(update, "该成员已隐藏位置或未设置定位。")
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
            await session.commit()

        detail_text = (
            "👤 成员详细档案\n"
            "—————————————————\n"
            f"用户： {display_name}\n"
            f"距离： 📍 {distance_text} 处 (模糊处理)\n"
            "业务详情：\n"
            f"💰 服务价格： {profile.price_text or '未设置'}\n"
            f"📦 交付方式： {profile.method_text or '未设置'}\n"
            f"🏠 详细描述： {profile.address_text or '未设置'}\n"
            "—————————————————"
        )
        keyboard = nearby_detail_keyboard(target_chat_id, target_user_id, back_page)
        await self._reply_or_edit(update, detail_text, keyboard)

    async def _start_edit_state(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        target_chat_id: int,
        field: str,
    ) -> None:
        if update.effective_user is None:
            return
        user = update.effective_user

        if update.effective_chat is None or update.effective_chat.type != "private":
            await self._reply_or_edit(update, "请私聊机器人发送 /mydata 后再编辑。")
            return

        state_map = {
            "price": ("nearby_edit_price", "请输入价格（支持数字或文本），输入 /clear 可清空。"),
            "method": ("nearby_edit_method", "请输入交付方式（如：自提/送货/远程），输入 /clear 可清空。"),
            "address": ("nearby_edit_address", "请输入详细地址或备注，输入 /clear 可清空。"),
            "location": ("nearby_edit_location", "请直接发送 Telegram 定位消息。"),
        }
        if field not in state_map:
            await self._reply_or_edit(update, "未知编辑项。")
            return

        state_type, prompt = state_map[field]
        async with db.session_factory() as session:
            await set_user_state(
                session,
                chat_id=user.id,
                user_id=user.id,
                state_type=state_type,
                state_data={"target_chat_id": target_chat_id},
            )
            await session.commit()

        await self._reply_or_edit(update, prompt)

    async def _toggle_visible(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        target_chat_id: int,
    ) -> None:
        if update.effective_user is None:
            return
        user = update.effective_user

        async with db.session_factory() as session:
            profile = await get_or_create_profile(
                session,
                target_chat_id,
                user=user,
                chat_type="supergroup" if target_chat_id < 0 else "private",
                chat_title=None,
            )
            profile.is_visible = not profile.is_visible
            await session.flush()
            await session.commit()

        await self._show_mydata_panel(update, context, target_chat_id)

    async def _handle_clear(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        db: Database,
        target_chat_id: int,
        step: str,
    ) -> None:
        if update.effective_user is None:
            return
        user = update.effective_user

        if step == "confirm":
            await self._reply_or_edit(
                update,
                "⚠️ 确认清空你的资料吗？此操作会清除位置、价格、方式和备注。",
                nearby_clear_confirm_keyboard(target_chat_id),
            )
            return

        if step == "cancel":
            await self._show_mydata_panel(update, context, target_chat_id)
            return

        if step != "do":
            await self._reply_or_edit(update, "未知操作。")
            return

        async with db.session_factory() as session:
            await clear_profile(session, target_chat_id, user.id)
            await clear_user_state(session, user.id, user.id)
            await session.commit()

        await self._show_mydata_panel(update, context, target_chat_id)

    async def _reply_or_edit(
        self,
        update: Update,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        if update.callback_query is not None:
            try:
                await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
                return
            except Exception:
                pass

        if update.effective_message is not None:
            await update.effective_message.reply_text(text, reply_markup=reply_markup)


_nearby_handler = NearbyHandler()


async def mydata_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _nearby_handler.mydata_command(update, context)


async def nearby_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _nearby_handler.nearby_command(update, context)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _nearby_handler.nearby_command(update, context)


async def nearby_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _nearby_handler.callback_handler(update, context)
