from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.activity.game_notice_delivery import queue_game_notice
from backend.features.activity.room_games.fees import GAME_NAMES
from backend.features.mini_app.links import mini_app_url


def room_keyboard(bot, chat_id: int, *, room_id: int | None = None, number: int | None = None):
    scene = f"rooms_{-chat_id}"
    label = "打开游戏房间"
    if room_id is not None:
        scene = f"room_{-chat_id}_{room_id}"
        label = "打开牌桌"
    if number is not None:
        scene += f"_{number}"
        label = "查看小局结算"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=mini_app_url(bot, scene))]])


def room_invite_card(bot, room) -> tuple[str, InlineKeyboardMarkup]:
    name = GAME_NAMES[room.game]
    text = (
        f"🎮 {name}房间 #{room.id} 等待加入\n"
        f"底分 {room.options['base']} · 倍率 {room.options['multiplier']}×\n"
        f"每人场费 {room.fee} 分，开场时扣除 · {room.hand_limit} 小局"
    )
    scene = f"room_{-room.chat_id}_{room.id}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("加入房间", url=mini_app_url(bot, scene))]])
    return text, keyboard


def _mention(player: dict) -> str:
    return f'<a href="tg://user?id={player["id"]}">{html.escape(player["name"])}</a>'


def queue_room_notice(session, bot, room, *, event: str):
    name = GAME_NAMES[room.game]
    number = None
    if event == "started":
        players = "、".join(map(_mention, room.seats))
        text = f"🃏 {name}开场 · #{room.id}\n{players}\n每人已扣场费 {room.fee} 分，输赢逐小局结算。"
    elif event == "hand_started":
        text = f"🃏 {name} · #{room.id} 第 {len(room.history) + 1} 小局开局"
    else:
        result = room.history[-1]
        number = result["number"]
        rows = "\n".join(f'{_mention(row)} {row["delta"]:+d} 分' for row in result["rows"])
        heading = "小局已作废，游戏投入已退回" if result.get("void") else "小局已结算"
        text = f"🏁 {name} · #{room.id} 第 {number} {heading}\n{rows}"
        text += "\n本场已结束。" if room.status == "closed" else ""
    return queue_game_notice(
        session, room.chat_id, text, parse_mode="HTML",
        keyboard=room_keyboard(bot, room.chat_id, room_id=room.id, number=number),
    )


async def rooms_command(update, context) -> None:
    chat = update.effective_chat
    if chat is None or chat.id >= 0 or not context.application.bot_data["settings"].mini_app_enabled:
        return
    await update.effective_message.reply_text(
        "选择四川血战或炸金花，进房前可查看每场台费。开场后扣费，每小局即时结算。",
        reply_markup=room_keyboard(context.bot, chat.id),
    )
