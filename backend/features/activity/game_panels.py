from __future__ import annotations

from sqlalchemy import func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.activity.services.game_service import (
    get_active_k3_round,
    get_or_create_setting,
    update_setting,
)
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.expansion import GameParticipant


def k3_panel_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for guess, icon in [("大", "⬆️"), ("小", "⬇️"), ("单", "1️⃣"), ("双", "2️⃣"), ("豹子", "🐆")]:
        buttons.append(
            [
                InlineKeyboardButton(f"{icon}{guess}10", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:10"),
                InlineKeyboardButton(f"{icon}{guess}50", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:50"),
                InlineKeyboardButton(f"{icon}{guess}100", callback_data=f"gmrun:k3:bet:{chat_id}:{guess}:100"),
            ]
        )
    buttons.append([InlineKeyboardButton("🔄 刷新面板", callback_data=f"gmrun:k3:refresh:{chat_id}")])
    return InlineKeyboardMarkup(buttons)


def blackjack_panel_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🃏 开局10", callback_data=f"gmrun:bj:start:{chat_id}:10"),
                InlineKeyboardButton("🃏 开局50", callback_data=f"gmrun:bj:start:{chat_id}:50"),
                InlineKeyboardButton("🃏 开局100", callback_data=f"gmrun:bj:start:{chat_id}:100"),
            ],
            [InlineKeyboardButton("🔄 刷新面板", callback_data=f"gmrun:bj:refresh:{chat_id}")],
        ]
    )


def blackjack_round_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🃏 要牌", callback_data=f"gmrun:bj:hit:{chat_id}"),
                InlineKeyboardButton("✋ 停牌", callback_data=f"gmrun:bj:stand:{chat_id}"),
            ],
            [InlineKeyboardButton("🔄 刷新局面", callback_data=f"gmrun:bj:refresh:{chat_id}")],
        ]
    )


async def build_k3_panel_text(db: Database, chat_id: int) -> str:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        round_obj = await get_active_k3_round(session, chat_id)
        participant_count = 0
        if round_obj is not None:
            count_result = await session.execute(
                select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id)
            )
            participant_count = int(count_result.scalar() or 0)
        await session.commit()
    lines = [
        "🎲 快3实时面板",
        f"📌 状态：{'✅ 开启' if setting.k3_enabled else '❌ 关闭'}",
        f"💧 抽水比例：{setting.rake_ratio or '0'}",
    ]
    if round_obj is None:
        lines.append("🧾 当前暂无进行中的牌局，点击下方按钮即可下注开局。")
    else:
        lines.extend(
            [
                f"🆔 当前局：#{round_obj.id}",
                f"👥 已下注人数：{participant_count}",
                "⏳ 本局会在 60 秒后自动开奖。",
            ]
        )
    lines.append("🎯 直接点击按钮即可完成下注。")
    return "\n".join(lines)


async def build_blackjack_panel_text(db: Database, chat_id: int) -> str:
    from backend.platform.db.schema.models.expansion import GameRound

    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        result = await session.execute(
            select(func.count(GameRound.id)).where(
                GameRound.chat_id == chat_id,
                GameRound.game_type == "blackjack",
                GameRound.status == "player_turn",
            )
        )
        active_count = int(result.scalar() or 0)
        await session.commit()
    lines = [
        "🃏 黑杰克实时面板",
        f"📌 状态：{'✅ 开启' if setting.blackjack_enabled else '❌ 关闭'}",
        f"💧 抽水比例：{setting.rake_ratio or '0'}",
        f"🧾 进行中对局：{active_count}",
        "🎯 点击下方按钮即可按固定积分开局。",
    ]
    return "\n".join(lines)


async def render_panel_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    message_id: int | None,
) -> int:
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
            )
            return message_id
        except Exception:
            pass
    sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    return sent.message_id


async def show_k3_panel(context: ContextTypes.DEFAULT_TYPE, db: Database, chat_id: int) -> int:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        existing_message_id = setting.k3_panel_message_id
        await session.commit()
    text = await build_k3_panel_text(db, chat_id)
    message_id = await render_panel_message(context, chat_id, text, k3_panel_keyboard(chat_id), existing_message_id)
    async with db.session_factory() as session:
        await update_setting(session, chat_id, k3_panel_message_id=message_id)
        await session.commit()
    return message_id


async def show_blackjack_panel(context: ContextTypes.DEFAULT_TYPE, db: Database, chat_id: int) -> int:
    async with db.session_factory() as session:
        setting = await get_or_create_setting(session, chat_id)
        existing_message_id = setting.blackjack_panel_message_id
        await session.commit()
    text = await build_blackjack_panel_text(db, chat_id)
    message_id = await render_panel_message(
        context,
        chat_id,
        text,
        blackjack_panel_keyboard(chat_id),
        existing_message_id,
    )
    async with db.session_factory() as session:
        await update_setting(session, chat_id, blackjack_panel_message_id=message_id)
        await session.commit()
    return message_id
