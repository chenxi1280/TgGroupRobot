from __future__ import annotations

import datetime as dt
import io
import re
import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.db.session import Database
from bot.handlers.base.base_handler import BaseHandler
from bot.handlers.base.chat_resolver import ChatResolver
from bot.keyboards.integration.invite_link import (
    invite_link_create_keyboard,
    invite_link_detail_keyboard,
    invite_link_list_keyboard,
    invite_link_menu_keyboard,
)
from bot.models.enums import InviteLinkStatus
from bot.services.core.chat_service import ensure_chat, get_chat_settings
from bot.services.core.permission_service import is_user_admin
from bot.services.integration.invite_service import (
    clear_chat_invite_links,
    clear_invite_counts,
    create_invite_link,
    delete_invite_link,
    export_invite_tracking_csv,
    get_chat_invite_links,
    get_invite_link,
    get_link_stats,
    revoke_invite_link,
    update_invite_link_info,
)
from bot.services.state.state_service import clear_user_state, get_user_state, set_user_state
from bot.utils.callback_parser import CallbackParser
from bot.utils.chat_context import PrivateChatContext

# 创建流程状态
WAIT_NAME = 1
WAIT_LIMIT = 2
WAIT_EXPIRE = 3

log = structlog.get_logger(__name__)


class InviteLinkHandler(BaseHandler):
    """邀请链接 Handler"""

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
        """处理邀请链接回调（用于 BaseHandler 抽象方法）"""
        # InviteLinkHandler 不使用 process 方法，直接调用各个方法
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat_title: str | None = None,
    ) -> None:
        """显示邀请链接管理菜单"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, target_chat_id)
            await session.commit()

        mode_label = "🧭 中转模式" if settings.invite_link_mode == "relay" else "➡️ 直达模式"
        cover_label = "✅ 已设置" if settings.invite_link_cover_file_id else "❌ 未设置"
        button_rows = len(settings.invite_link_buttons or [])
        text = (
            f"🔗 [{chat_title or target_chat_id}] 邀请链接\n\n"
            f"状态：{'✅ 启动' if settings.invite_link_enabled else '❌ 关闭'}\n"
            f"邀请提醒：{'✅ 启动' if settings.invite_link_notify else '❌ 关闭'}\n\n"
            f"模式：{mode_label}\n"
            f"封面：{cover_label}\n"
            f"按钮：{button_rows} 行\n"
            f"模板：{(settings.invite_link_text_template or '')[:32] or '未配置'}\n\n"
            "当前已接通创建、列表、详情、统计、模式、封面、文本、按钮、预览、清零、清空链接与导出。"
        )
        keyboard = invite_link_menu_keyboard(
            target_chat_id,
            enabled=bool(settings.invite_link_enabled),
            remind_enabled=bool(settings.invite_link_notify),
            mode=settings.invite_link_mode or "direct",
            has_cover=bool(settings.invite_link_cover_file_id),
            button_rows=button_rows,
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_list(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        page: int = 0,
    ) -> None:
        """显示邀请链接列表"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            links = await get_chat_invite_links(session, target_chat_id)
            await session.commit()

        if not links:
            keyboard = invite_link_menu_keyboard(target_chat_id)
            await self.message_helper.safe_edit(
                update,
                text="🔗 邀请链接列表\n\n暂无邀请链接，点击「创建邀请链接」开始",
                reply_markup=keyboard,
            )
            return

        text = f"🔗 邀请链接列表\n\n共 {len(links)} 个链接"
        keyboard = invite_link_list_keyboard(links, target_chat_id, page)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        """显示邀请链接统计"""
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_link_stats(session, target_chat_id)
            await session.commit()

        text = f"📊 邀请链接统计\n\n"
        text += f"总链接数: {stats['total']}\n"
        text += f"激活中: {stats['active']}\n"
        text += f"已撤销: {stats['revoked']}\n"
        text += f"已过期: {stats['expired']}\n"
        text += f"总成员数: {stats['total_members']}"

        keyboard = invite_link_menu_keyboard(target_chat_id)
        await self.message_helper.safe_edit(update, text=text, reply_markup=keyboard)


# 创建单例实例
_invite_link_handler = InviteLinkHandler()


def _parse_invite_buttons(raw: str) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for line in [item.strip() for item in raw.splitlines() if item.strip()]:
        row: list[dict] = []
        for part in [item.strip() for item in line.split(";") if item.strip()]:
            if "|" not in part:
                raise ValueError("按钮格式错误，请使用 `文案|链接`，同行按钮用 `;` 分隔。")
            text, url = [item.strip() for item in part.split("|", 1)]
            if not text or not url:
                raise ValueError("按钮文案和链接都不能为空。")
            row.append({"text": text[:32], "url": url[:512]})
        if len(row) > 3:
            raise ValueError("每行最多 3 个按钮。")
        rows.append(row)
    return rows


def _format_invite_preview(settings, chat_title: str) -> tuple[str, InlineKeyboardMarkup | None]:
    template = settings.invite_link_text_template or "🔗 邀请好友加入 {group}\n邀请人：{inviter}\n新成员：{invitee}"
    text = template.format(inviter="测试邀请人", invitee="测试新成员", group=chat_title)
    buttons = []
    for row in settings.invite_link_buttons or []:
        buttons.append([InlineKeyboardButton(item.get("text", "按钮"), url=item.get("url", "https://t.me")) for item in row])
    return text, InlineKeyboardMarkup(buttons) if buttons else None


async def _show_invite_link_menu_from_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_chat_id: int,
) -> None:
    await _invite_link_handler.show_menu(update, context, target_chat_id, str(target_chat_id))


async def handle_invite_link_config_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    state,
    message_text: str,
) -> None:
    if update.effective_user is None or update.effective_message is None:
        return

    target_chat_id = int((state.state_data or {}).get("target_chat_id") or 0)
    if target_chat_id == 0:
        await clear_user_state(session, update.effective_user.id, update.effective_user.id)
        await session.commit()
        await update.effective_message.reply_text("❌ 邀请链接配置上下文已失效，请重新进入。")
        return

    settings = await get_chat_settings(session, target_chat_id)
    normalized_text = message_text.strip()

    if state.state_type == "invite_link_cover_input":
        if normalized_text in {"清空", "删除", "/clear"}:
            settings.invite_link_cover_file_id = None
            settings.invite_link_cover_media_type = None
        elif update.effective_message.photo:
            settings.invite_link_cover_file_id = update.effective_message.photo[-1].file_id
            settings.invite_link_cover_media_type = "photo"
        elif update.effective_message.video:
            settings.invite_link_cover_file_id = update.effective_message.video.file_id
            settings.invite_link_cover_media_type = "video"
        else:
            await update.effective_message.reply_text(
                "❌ 请发送图片、视频，或发送“清空”移除封面。"
            )
            return
    elif state.state_type == "invite_link_text_input":
        if normalized_text in {"清空", "默认", "恢复默认", "/default"}:
            settings.invite_link_text_template = "🔗 邀请好友加入 {group}\n邀请人：{inviter}\n新成员：{invitee}"
        else:
            settings.invite_link_text_template = normalized_text[:4000]
    elif state.state_type == "invite_link_buttons_input":
        if normalized_text in {"清空", "删除", "/clear"}:
            settings.invite_link_buttons = []
        else:
            try:
                settings.invite_link_buttons = _parse_invite_buttons(normalized_text)
            except ValueError as exc:
                await update.effective_message.reply_text(f"❌ {exc}")
                return
    else:
        await update.effective_message.reply_text("❌ 当前状态不支持邀请链接配置。")
        return

    await clear_user_state(session, update.effective_user.id, update.effective_user.id)
    await session.commit()
    await _show_invite_link_menu_from_message(update, context, target_chat_id)


# ==================== 适配器函数（供 Router 注册）====================

async def invite_link_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接菜单回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的邀请链接管理 - 返回到管理面板
    if chat.type == "private":
        from bot.services.integration.chat_group_service import get_user_managed_chats
        db: Database = context.application.bot_data["db"]
        target_chat_id = await ChatResolver.get_current_chat(db, user.id)
        if target_chat_id is None:
            await _invite_link_handler.message_helper.safe_edit(update, "请先选择一个群组")
            return
        if not await is_user_admin(context, target_chat_id, user.id):
            await _invite_link_handler.message_helper.safe_edit(update, "你没有该群组的管理权限")
            return

        # 返回到管理面板
        from bot.handlers.admin_handler import _show_private_admin_menu
        await _show_private_admin_menu(update, context, target_chat_id)
        return

    if not await is_user_admin(context, chat.id, user.id):
        await _invite_link_handler.message_helper.safe_edit(update, "仅管理员可使用此功能")
        return

    # 使用 Handler 处理
    await _invite_link_handler.show_menu(update, context, chat.id, chat.title)


async def invite_link_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接基础版首页回调。"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context)
    if target_chat_id is None:
        return

    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接列表回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    # 使用 PrivateChatContext 解析目标群组并检查权限
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update, context, chat_index=3
    )
    if target_chat_id is None:
        return  # 错误消息已发送

    data = q.data or ""
    cb = CallbackParser.parse(data)
    page = cb.get_int(2, default=0)

    # 使用 Handler 处理
    await _invite_link_handler.show_list(update, context, target_chat_id, page)


async def invite_link_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接统计回调"""
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
    await _invite_link_handler.show_stats(update, context, target_chat_id)


async def invite_link_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接基础版开关切换。"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return

    cb = CallbackParser.parse(q.data or "")
    field = cb.get(2)
    value = cb.get_int_optional(4)
    if value not in {0, 1}:
        await q.answer("无效开关值", show_alert=True)
        return

    field_map = {
        "enabled": "invite_link_enabled",
        "remind": "invite_link_notify",
    }
    setting_field = field_map.get(field)
    if setting_field is None:
        await q.answer("无效配置项", show_alert=True)
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        setattr(settings, setting_field, bool(value))
        await session.commit()

    await _invite_link_handler.show_menu(update, context, target_chat_id)

async def invite_link_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return

    mode = CallbackParser.parse(q.data or "").get(3)
    if mode not in {"relay", "direct"}:
        await q.answer("无效模式", show_alert=True)
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        settings.invite_link_mode = mode
        await session.commit()
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_cover_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_cover_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        "🖼️ 邀请链接 | 修改封面\n\n请发送图片或视频，发送“清空”可移除封面。",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_text_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_text_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        (
            "📝 邀请链接 | 修改文本\n\n"
            f"当前模板：\n{settings.invite_link_text_template}\n\n"
            "支持变量：{inviter} {invitee} {group}"
        ),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        await set_user_state(session, update.effective_user.id, update.effective_user.id, "invite_link_buttons_input", {"target_chat_id": target_chat_id})
        await session.commit()
    await _invite_link_handler.message_helper.safe_edit(
        update,
        (
            "⌨️ 邀请链接 | 修改按钮\n\n"
            "每行最多 3 个按钮，同行按钮用 `;` 分隔。\n"
            "格式：按钮文案|https://example.com\n"
            "示例：点击关注|https://t.me/demo; 联系管理|https://t.me/admin"
        ),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"inv:home:{target_chat_id}")]]),
    )


async def invite_link_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        settings = await get_chat_settings(session, target_chat_id)
        await session.commit()
    chat_title = str(target_chat_id)
    preview_text, keyboard = _format_invite_preview(settings, chat_title)
    if settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "photo":
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    elif settings.invite_link_cover_file_id and settings.invite_link_cover_media_type == "video":
        await context.bot.send_video(chat_id=update.effective_chat.id, video=settings.invite_link_cover_file_id, caption=preview_text, reply_markup=keyboard)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=preview_text, reply_markup=keyboard)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=3)
    if target_chat_id is None:
        return
    reset_type = CallbackParser.parse(q.data or "").get(2)
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        if reset_type == "count":
            cleared = await clear_invite_counts(session, target_chat_id)
            await session.commit()
            await q.answer(f"已清零 {cleared} 条邀请统计", show_alert=True)
        elif reset_type == "links":
            links = await clear_chat_invite_links(session, target_chat_id)
            await session.commit()
            for link in links:
                try:
                    await context.bot.revoke_chat_invite_link(chat_id=target_chat_id, invite_link=link.invite_link)
                except Exception:
                    continue
            await q.answer(f"已清空 {len(links)} 条链接记录", show_alert=True)
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query is None:
        return
    q = update.callback_query
    await q.answer()
    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(update, context, chat_index=2)
    if target_chat_id is None:
        return
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        filename, content = await export_invite_tracking_csv(session, target_chat_id)
        await session.commit()
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=io.BytesIO(content),
        filename=filename,
        caption="📤 邀请统计导出",
    )
    await _invite_link_handler.show_menu(update, context, target_chat_id)


async def invite_link_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """邀请链接详情回调"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    link_id = cb.get_int(2)
    if link_id == 0:
        log.warning("invalid_link_id", data=q.data)
        await q.answer("无效的链接ID", show_alert=True)
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=3,
    )
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        link = await get_invite_link(session, link_id)
        if not link:
            await session.commit()
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))
            return

        status_emoji = {
            InviteLinkStatus.active.value: "🟢 激活",
            InviteLinkStatus.revoked.value: "🔴 已撤销",
            InviteLinkStatus.expired.value: "⚫ 已过期",
        }.get(link.status, link.status)

        text = f"🔗 邀请链接详情\n\n"
        text += f"名称: {link.name or '未命名'}\n"
        text += f"状态: {status_emoji}\n"
        text += f"链接: `{link.invite_link}`\n"
        text += f"成员数: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n"
        if link.expire_date:
            text += f"过期时间: {link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        text += f"需要审批: {'是' if link.creates_join_request else '否'}"

        await session.commit()

    await q.edit_message_text(
        text,
        reply_markup=invite_link_detail_keyboard(link_id, target_chat_id),
        parse_mode="Markdown",
    )


async def invite_link_create_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """开始创建邀请链接"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 私聊中的邀请链接创建 - 优先从 callback_data 获取目标群组ID
    target_chat_id = None
    if chat.type == "private":
        # 优先从 callback_data 提取 chat_id
        data = q.data or ""
        if data.startswith("inv:create:"):
            cb = CallbackParser.parse(data)
            target_chat_id = cb.get_int(2)

        # 如果 callback_data 中没有 chat_id，从数据库获取
        if target_chat_id == 0:
            db: Database = context.application.bot_data["db"]
            target_chat_id = await ChatResolver.get_current_chat(db, user.id)
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
        # 修复：使用 chat.id 保存状态，而不是 target_chat_id
        # 与后续的状态查询和更新保持一致
        await set_user_state(session, chat.id, user.id, "invite_link_create", {"target_chat_id": target_chat_id})
        await session.commit()

    await q.edit_message_text(
        "➕ 创建邀请链接\n\n请输入链接名称（可选）\n\n输入 /skip 跳过",
    )
    return WAIT_NAME


async def invite_link_create_name_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理链接名称输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    raw_name = (update.effective_message.text or "").strip()

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = dict(state.state_data if state else {})
        state_data["name"] = None if raw_name == "/skip" else raw_name
        state_record = await set_user_state(session, chat.id, user.id, "invite_link_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"名称: {state_record.state_data.get('name') or '未命名'}\n\n请输入成员数量限制（可选）\n\n输入数字或 /skip 跳过"
    )
    return WAIT_LIMIT


async def invite_link_create_limit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理成员数量限制输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}

        member_limit = None
        if text != "/skip":
            try:
                member_limit = int(text)
                if member_limit <= 0:
                    await update.effective_message.reply_text("成员数量必须大于0，请重新输入或 /skip 跳过")
                    return WAIT_LIMIT
            except ValueError as e:
                log.warning("invalid_member_limit_input", user_input=text, error=str(e))
                await update.effective_message.reply_text("请输入有效的数字或 /skip 跳过")
                return WAIT_LIMIT

        state_data["member_limit"] = member_limit
        await set_user_state(session, chat.id, user.id, "invite_link_create", state_data)
        await session.commit()

    await update.effective_message.reply_text(
        f"成员限制: {member_limit or '无限制'}\n\n请输入过期时间（可选）\n格式: 天数\n输入 /skip 跳过"
    )
    return WAIT_EXPIRE


async def invite_link_create_expire_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """处理过期时间输入"""
    if update.effective_message is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    user = update.effective_user
    chat = update.effective_chat
    text = update.effective_message.text

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        state_data = state.state_data if state else {}
        target_chat_id = int(state_data.get("target_chat_id") or chat.id)

        expire_date = None
        if text != "/skip":
            try:
                days = int(text)
                if days <= 0:
                    await update.effective_message.reply_text("天数必须大于0，请重新输入或 /skip 跳过")
                    return WAIT_EXPIRE
                expire_date = dt.datetime.now(dt.UTC) + dt.timedelta(days=days)
            except ValueError as e:
                log.warning("invalid_expire_days_input", user_input=text, error=str(e))
                await update.effective_message.reply_text("请输入有效的天数或 /skip 跳过")
                return WAIT_EXPIRE

        state_data["expire_date"] = expire_date

        # 创建链接
        result = await create_invite_link(
            session,
            chat_id=target_chat_id,
            created_by_user_id=user.id,
            bot=context.bot,
            name=state_data.get("name"),
            member_limit=state_data.get("member_limit"),
            expire_date=state_data.get("expire_date"),
        )

        await clear_user_state(session, chat.id, user.id)

        await session.commit()

        if result.success:
            text = f"✅ 邀请链接创建成功！\n\n"
            text += f"链接: `{result.invite_link.invite_link}`\n"
            text += f"名称: {result.invite_link.name or '未命名'}\n"
            text += f"成员限制: {result.invite_link.member_limit or '无限制'}\n"
            if result.invite_link.expire_date:
                text += f"过期时间: {result.invite_link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"

            await update.effective_message.reply_text(
                text,
                reply_markup=invite_link_menu_keyboard(target_chat_id),
                parse_mode="Markdown",
            )
        else:
            reason_text = {
                "limit_reached": "已达到创建限制",
                "permission_denied": "权限不足",
                "error": "创建失败",
            }.get(result.reason, "未知错误")
            await update.effective_message.reply_text(
                f"❌ {reason_text}",
                reply_markup=invite_link_menu_keyboard(target_chat_id),
            )

    return ConversationHandler.END


async def invite_link_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """取消创建流程"""
    if update.callback_query is None or update.effective_user is None or update.effective_chat is None:
        return ConversationHandler.END

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]
    target_chat_id = chat.id
    async with db.session_factory() as session:
        state = await get_user_state(session, chat.id, user.id)
        if state is not None:
            target_chat_id = int((state.state_data or {}).get("target_chat_id") or target_chat_id)
        await clear_user_state(session, chat.id, user.id)
        await session.commit()

    await q.edit_message_text("已取消创建", reply_markup=invite_link_menu_keyboard(target_chat_id))
    return ConversationHandler.END


async def invite_link_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """刷新邀请链接信息"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    link_id = cb.get_int(2)
    if link_id == 0:
        log.warning("invalid_link_id", data=q.data)
        await q.answer("无效的链接ID", show_alert=True)
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=3,
    )
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await update_invite_link_info(session, context.bot, link_id)
        await session.commit()

        if not success:
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))
            return

        link = await get_invite_link(session, link_id)
        if not link:
            await q.edit_message_text("链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))
            return

        status_emoji = {
            InviteLinkStatus.active.value: "🟢 激活",
            InviteLinkStatus.revoked.value: "🔴 已撤销",
            InviteLinkStatus.expired.value: "⚫ 已过期",
        }.get(link.status, link.status)

        text = f"🔗 邀请链接详情\n\n"
        text += f"名称: {link.name or '未命名'}\n"
        text += f"状态: {status_emoji}\n"
        text += f"链接: `{link.invite_link}`\n"
        text += f"成员数: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n"
        if link.expire_date:
            text += f"过期时间: {link.expire_date.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        text += f"需要审批: {'是' if link.creates_join_request else '否'}"

    await q.edit_message_text(
        text,
        reply_markup=invite_link_detail_keyboard(link_id, target_chat_id),
        parse_mode="Markdown",
    )


async def invite_link_revoke_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """撤销邀请链接"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    link_id = cb.get_int(2)
    if link_id == 0:
        log.warning("invalid_link_id", data=q.data)
        await q.answer("无效的链接ID", show_alert=True)
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=3,
    )
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        result = await revoke_invite_link(session, context.bot, link_id)
        await session.commit()

        if result.success:
            await q.edit_message_text("✅ 链接已撤销", reply_markup=invite_link_menu_keyboard(target_chat_id))
        else:
            reason_text = {
                "not_found": "链接不存在",
                "already_revoked": "链接已被撤销",
                "error": "撤销失败",
            }.get(result.reason, "未知错误")
            await q.edit_message_text(f"❌ {reason_text}", reply_markup=invite_link_menu_keyboard(target_chat_id))


async def invite_link_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """删除邀请链接记录"""
    if update.callback_query is None or update.effective_user is None:
        return
    q = update.callback_query
    await q.answer()

    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    link_id = cb.get_int(2)
    if link_id == 0:
        log.warning("invalid_link_id", data=q.data)
        await q.answer("无效的链接ID", show_alert=True)
        return

    target_chat_id = await PrivateChatContext.resolve_target_chat_with_permission_check(
        update,
        context,
        chat_index=3,
    )
    if target_chat_id is None:
        return

    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        success = await delete_invite_link(session, link_id)
        await session.commit()

        if success:
            await q.edit_message_text("✅ 链接记录已删除", reply_markup=invite_link_menu_keyboard(target_chat_id))
        else:
            await q.edit_message_text("❌ 链接不存在", reply_markup=invite_link_menu_keyboard(target_chat_id))


# ==================== 用户邀请链接功能 (/link 命令) ====================

async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户邀请链接命令 - /link"""
    if update.effective_chat is None or update.effective_user is None or update.effective_message is None:
        return

    # 只在群聊中有效
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.effective_message.reply_text("请在群组中使用此功能")
        return

    chat = update.effective_chat
    user = update.effective_user

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        await ensure_chat(session, chat_id=chat.id, chat_type=chat.type, title=chat.title)
        settings = await get_chat_settings(session, chat.id)
        await session.commit()

    # 检查是否开启邀请链接功能
    if not settings.invite_link_enabled:
        await update.effective_message.reply_text("本群未开启邀请链接功能")
        return

    # 显示用户邀请链接界面
    await _show_user_invite_menu(update, context, chat.id, user.id)


async def _show_user_invite_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> None:
    """显示用户邀请链接菜单"""
    from bot.services.integration.invite_service import get_user_invite_stats
    from bot.keyboards.integration.invite_link import user_invite_menu_keyboard

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        from bot.models.core import ChatSettings

        settings_result = await session.execute(
            select(ChatSettings).where(ChatSettings.chat_id == chat_id)
        )
        settings = settings_result.scalar_one_or_none()

        stats = await get_user_invite_stats(session, chat_id, user_id)
        await session.commit()

    text = f"🔗 邀请链接\n\n"
    text += f"状态: {'✅ 启用' if settings and settings.invite_link_enabled else '❌ 禁用'}\n"
    text += f"总邀请人数: {stats.total_invites}\n"
    text += f"活跃链接: {stats.active_links}\n"
    text += f"链接过期: {settings.invite_link_expire_days or '无限制'} 天\n"
    text += f"最大邀请: {settings.invite_link_max_joins or '无限制'} 人\n"
    if stats.link_limit:
        text += f"生成上限: {stats.link_limit} 个\n"
    text += f"已生成: {stats.links_generated} 个"

    keyboard = user_invite_menu_keyboard(chat_id)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def user_invite_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户创建邀请链接回调"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    chat = update.effective_chat
    user = update.effective_user

    # 从回调数据中获取 chat_id
    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    chat_id = cb.get_int(2)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await q.answer("无效的群组ID", show_alert=True)
        return

    from bot.services.integration.invite_service import create_invite_link as user_create_link

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        success, link, error = await user_create_link(
            session,
            context.bot,
            chat_id,
            user.id,
            name=f"{user.first_name or user.username or '用户'}的链接",
        )
        await session.commit()

    if success and link:
        text = f"✅ 邀请链接创建成功！\n\n"
        text += f"`{link.invite_link}`\n\n"
        text += f"点击链接即可邀请好友加入群组"

        # 重新显示菜单
        await _show_user_invite_menu(update, context, chat_id, user.id)

        # 发送链接消息（单独发送，方便转发）
        await context.bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
    else:
        await q.edit_message_text(f"❌ {error or '创建失败'}")
        # 重新显示菜单
        await _show_user_invite_menu(update, context, chat_id, user.id)


async def user_invite_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户查看我的链接列表"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    # 从回调数据中获取 chat_id
    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    chat_id = cb.get_int(2)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await q.answer("无效的群组ID", show_alert=True)
        return

    from bot.services.integration.invite_service import get_user_links

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        links = await get_user_links(session, chat_id, user.id)
        await session.commit()

    if not links:
        text = "🔗 我的邀请链接\n\n暂无链接，点击「生成链接」创建"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = f"🔗 我的邀请链接\n\n共 {len(links)} 个链接\n\n"
    for link in links[:5]:  # 只显示前5个
        status_emoji = "🟢" if link.status == InviteLinkStatus.active.value else "🔴"
        text += f"{status_emoji} {link.name or '未命名'}\n"
        text += f"   成员: {link.member_count}"
        if link.member_limit:
            text += f" / {link.member_limit}"
        text += "\n\n"

    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def user_invite_rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """用户查看邀请排行榜"""
    if update.callback_query is None or update.effective_chat is None or update.effective_user is None:
        return

    q = update.callback_query
    await q.answer()

    user = update.effective_user

    # 从回调数据中获取 chat_id
    data = q.data or ""
    cb = CallbackParser.parse(data)
    if cb.length() < 3:
        return

    chat_id = cb.get_int(2)
    if chat_id == 0:
        log.warning("invalid_chat_id", data=q.data)
        await q.answer("无效的群组ID", show_alert=True)
        return

    from bot.services.integration.invite_service import get_invite_leaderboard, get_user_rank

    db: Database = context.application.bot_data["db"]

    async with db.session_factory() as session:
        leaderboard = await get_invite_leaderboard(session, chat_id, limit=10)
        user_rank = await get_user_rank(session, chat_id, user.id)
        await session.commit()

    if not leaderboard:
        text = "🏆 邀请排行榜\n\n暂无邀请数据"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    text = "🏆 邀请排行榜（前10名）\n\n"
    for i, (uid, count, username) in enumerate(leaderboard, 1):
        name = username or f"用户{uid}"
        text += f"{i}. {name} - {count} 人\n"

    if user_rank:
        text += f"\n你的排名: 第 {user_rank} 名"

    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
