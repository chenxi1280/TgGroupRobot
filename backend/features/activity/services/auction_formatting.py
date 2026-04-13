from __future__ import annotations

from telegram import InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.activity.services.auction_time import as_utc, now_utc
from backend.platform.db.schema.models.expansion import AuctionItem, AuctionSetting


def format_auction_settings_text(chat_title: str, setting: AuctionSetting) -> str:
    return "\n".join(
        [
            f"💰 拍卖 | {chat_title}",
            "",
            f"⚙️ 状态：{'✅ 启动' if setting.enabled else '❌ 关闭'}",
            f"📌 消息置顶：{'✅ 启动' if setting.pin_message_enabled else '❌ 关闭'}",
            f"⏱ 自动延时：{'✅ 启动' if setting.auto_extend_enabled else '❌ 关闭'}",
            f"👮 创建权限：{'👑 仅管理员' if setting.create_permission == 'admin' else '👥 所有人'}",
            f"🪙 关联积分：{'🌑 主积分' if setting.points_mode == 'group_points' else '🚫 不关联'}",
            "",
            "群内回复任意消息发送“拍卖”即可进入创建流程。",
        ]
    )


def format_auction_announcement(
    item: AuctionItem,
    *,
    bidder_name: str | None = None,
    is_final: bool = False,
    settlement_note: str | None = None,
) -> str:
    status_text = {
        "running": "🟢 进行中",
        "ended": "🔴 已结束",
        "cancelled": "⚫ 已取消",
        "draft": "🟡 草稿",
    }.get(item.status, item.status)
    lines = [
        f"💰 拍卖：{item.title or '未命名拍卖'}",
        "",
        f"状态：{status_text}",
        f"起拍价：{item.start_price}",
        f"当前价：{item.current_price}",
        f"结束时间：{as_utc(item.end_at or now_utc()).astimezone().strftime('%Y-%m-%d %H:%M:%S') if item.end_at else '未设置'}",
    ]
    if bidder_name:
        lines.append(f"当前领先：{bidder_name}")
    if is_final:
        lines.append(f"结束时间：{as_utc(item.updated_at).astimezone().strftime('%Y-%m-%d %H:%M:%S')}")
    if settlement_note:
        lines.extend(["", settlement_note])
    else:
        lines.extend(["", "回复本条消息发送数字即可出价，例如：`188`"])
    return "\n".join(lines)


async def refresh_auction_message(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    item: AuctionItem,
    bidder_name: str | None = None,
    settlement_note: str | None = None,
    parse_mode: str = "Markdown",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if item.last_announce_message_id is None:
        return
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=item.last_announce_message_id,
        text=format_auction_announcement(item, bidder_name=bidder_name, is_final=item.status == "ended", settlement_note=settlement_note),
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )
