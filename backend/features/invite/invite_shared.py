from __future__ import annotations

import io

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from backend.features.invite.services.invite_service import (
    clear_chat_invite_links,
    clear_invite_counts,
    export_invite_tracking_csv,
    get_chat_invite_links,
    get_link_stats,
)
from backend.features.invite.ui.invite_link import (
    invite_link_list_keyboard,
    invite_link_menu_keyboard,
)
from backend.platform.db.runtime.session import Database
from backend.shared.handlers.base.base_handler import BaseHandler
from backend.shared.services.chat_service import get_chat_settings
from backend.platform.state.state_service import clear_user_state

WAIT_NAME = 1
WAIT_LIMIT = 2
WAIT_EXPIRE = 3


class InviteLinkHandler(BaseHandler):
    def __init__(self) -> None:
        super().__init__()
        self._require_admin_permission = False

    async def process(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        pass

    async def show_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
        chat_title: str | None = None,
    ) -> None:
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
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            links = await get_chat_invite_links(session, target_chat_id)
            await session.commit()

        if not links:
            await self.message_helper.safe_edit(
                update,
                text="🔗 邀请链接列表\n\n暂无邀请链接，点击「创建邀请链接」开始",
                reply_markup=invite_link_menu_keyboard(target_chat_id),
            )
            return

        text = f"🔗 邀请链接列表\n\n共 {len(links)} 个链接"
        await self.message_helper.safe_edit(
            update,
            text=text,
            reply_markup=invite_link_list_keyboard(links, target_chat_id, page),
        )

    async def show_stats(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        target_chat_id: int,
    ) -> None:
        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            stats = await get_link_stats(session, target_chat_id)
            await session.commit()

        text = (
            "📊 邀请链接统计\n\n"
            f"总链接数: {stats['total']}\n"
            f"激活中: {stats['active']}\n"
            f"已撤销: {stats['revoked']}\n"
            f"已过期: {stats['expired']}\n"
            f"总成员数: {stats['total_members']}"
        )
        await self.message_helper.safe_edit(update, text=text, reply_markup=invite_link_menu_keyboard(target_chat_id))


_invite_link_handler = InviteLinkHandler()


def parse_invite_buttons(raw: str) -> list[list[dict]]:
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


def format_invite_preview(settings, chat_title: str) -> tuple[str, InlineKeyboardMarkup | None]:
    template = settings.invite_link_text_template or "🔗 邀请好友加入 {group}\n邀请人：{inviter}\n新成员：{invitee}"
    text = template.format(inviter="测试邀请人", invitee="测试新成员", group=chat_title)
    buttons = []
    for row in settings.invite_link_buttons or []:
        buttons.append([InlineKeyboardButton(item.get("text", "按钮"), url=item.get("url", "https://t.me")) for item in row])
    return text, InlineKeyboardMarkup(buttons) if buttons else None


async def show_invite_link_menu_from_message(
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
            await update.effective_message.reply_text("❌ 请发送图片、视频，或发送“清空”移除封面。")
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
            settings.invite_link_buttons = parse_invite_buttons(normalized_text)
    else:
        await update.effective_message.reply_text("❌ 当前状态不支持邀请链接配置。")
        return

    await clear_user_state(session, update.effective_user.id, update.effective_user.id)
    await session.commit()
    await show_invite_link_menu_from_message(update, context, target_chat_id)


async def export_invite_csv(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    reply_chat_id: int,
) -> None:
    db: Database = context.application.bot_data["db"]
    async with db.session_factory() as session:
        filename, content = await export_invite_tracking_csv(session, chat_id)
        await session.commit()
    await context.bot.send_document(
        chat_id=reply_chat_id,
        document=io.BytesIO(content),
        filename=filename,
        caption="📤 邀请统计导出",
    )


async def reset_invite_data(session, *, reset_type: str, chat_id: int):
    if reset_type == "count":
        cleared = await clear_invite_counts(session, chat_id)
        return f"已清零 {cleared} 条邀请统计", None
    if reset_type == "links":
        links = await clear_chat_invite_links(session, chat_id)
        return f"已清空 {len(links)} 条链接记录", links
    return None, None
