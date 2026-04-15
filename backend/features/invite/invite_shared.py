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
from backend.shared.button_layout_editor import ButtonLayoutEditorService
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
            stats = await get_link_stats(session, target_chat_id)
            await session.commit()

        text = format_invite_link_admin_text(settings, stats)
        keyboard = _build_invite_home_keyboard(target_chat_id, settings)
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
            settings = await get_chat_settings(session, target_chat_id)
            await session.commit()

        if not links:
            await self.message_helper.safe_edit(
                update,
                text="🔗 邀请链接列表\n\n暂无邀请链接，成员发送「邀请」或 /link 后会自动生成。",
                reply_markup=_build_invite_home_keyboard(target_chat_id, settings),
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
        from backend.features.invite.services.invite_stats import get_invite_leaderboard

        db: Database = context.application.bot_data["db"]
        async with db.session_factory() as session:
            settings = await get_chat_settings(session, target_chat_id)
            stats = await get_link_stats(session, target_chat_id)
            leaderboard = await get_invite_leaderboard(session, target_chat_id, limit=10)
            await session.commit()

        lines = [
            "📊 邀请链接统计",
            "",
            f"总链接数: {stats['total']}",
            f"激活中: {stats['active']}",
            f"已撤销: {stats['revoked']}",
            f"已过期: {stats['expired']}",
            f"总成员数: {stats['total_members']}",
            "",
            "🏆 邀请排行榜（前10名）",
        ]
        if leaderboard:
            for idx, (user_id, count, username) in enumerate(leaderboard, 1):
                lines.append(f"{idx}. {username or f'用户{user_id}'} - {count} 人")
        else:
            lines.append("暂无邀请数据")
        text = "\n".join(lines)
        await self.message_helper.safe_edit(update, text=text, reply_markup=_build_invite_home_keyboard(target_chat_id, settings))


_invite_link_handler = InviteLinkHandler()


def _build_invite_home_keyboard(target_chat_id: int, settings) -> InlineKeyboardMarkup:
    return invite_link_menu_keyboard(
        target_chat_id,
        enabled=bool(getattr(settings, "invite_link_enabled", True)),
        remind_enabled=bool(getattr(settings, "invite_link_notify", True)),
        mode=getattr(settings, "invite_link_mode", None) or "direct",
        has_cover=bool(getattr(settings, "invite_link_cover_file_id", None)),
        text_configured=bool(str(getattr(settings, "invite_link_text_template", "") or "").strip()),
        button_rows=len(getattr(settings, "invite_link_buttons", None) or []),
    )


def format_invite_link_admin_text(settings, stats: dict[str, int]) -> str:
    enabled = bool(getattr(settings, "invite_link_enabled", True))
    mode = getattr(settings, "invite_link_mode", None) or "direct"
    total_invites = int(stats.get("total_invites", stats.get("total_members", 0)) or 0)
    generated_count = int(stats.get("total", 0) or 0)
    mode_label = "中转" if mode == "relay" else "直接"
    return (
        "🔗 邀请链接生成\n"
        "\n"
        "指令列表\n"
        "└ 自动生成链接：邀请 或 /link\n"
        "└ 查询邀请统计：邀请统计 或 /link_stat\n"
        "\n"
        "防作弊\n"
        "└ 只有第一次进群视为有效邀请数，退群再用其他人的链接加群不计算邀请数\n"
        "\n"
        "模式选择\n"
        "└ 中转（推荐）：点击链接先到机器人界面，再进去群组，开了审核也可以统计和加分！\n"
        "└ 直接：通过链接直接进群，如果开了审核则统计不到，加不了积分。\n"
        "└ 模式切换后，成员需重新使用指令获取新链接，已邀请的数据不变！\n"
        "\n"
        "当前信息\n"
        f"┌状态:{'✅ 启动' if enabled else '❌ 关闭'}\n"
        f"├当前模式:{mode_label}\n"
        f"├总邀请人数:{total_invites}\n"
        f"└已生成数量:{generated_count}"
    )


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
            row.append({
                "text": ButtonLayoutEditorService.sanitize_button_text(text),
                "url": ButtonLayoutEditorService.normalize_button_url(url[:512]),
            })
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
