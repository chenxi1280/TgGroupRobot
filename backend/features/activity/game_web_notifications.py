from __future__ import annotations

import structlog
from telegram.error import TelegramError

from backend.features.activity.services.game_blackjack import format_blackjack_round_text
from backend.features.mini_app.links import game_link

log = structlog.get_logger(__name__)


def game_player_mention(user_id: int) -> str:
    return f'<a href="tg://user?id={user_id}">玩家 {user_id}</a>'


async def send_game_notice(bot, round_obj, *, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=round_obj.chat_id, text=text, parse_mode="HTML",
            reply_markup=game_link(bot, round_obj.chat_id, game=round_obj.game_type),
        )
    except TelegramError as exc:
        log.warning("game_web_notice_failed", round_id=round_obj.id, error_type=type(exc).__name__)


async def announce_web_game(bot, round_obj, participant, *, opened: bool, outcome: str | None) -> None:
    mention = game_player_mention(participant.user_id)
    if opened:
        game_name = "黑杰克" if round_obj.game_type == "blackjack" else "快三"
        await send_game_notice(bot, round_obj, text=f"🎮 {game_name}开局 · #{round_obj.id}\n{mention} 开启了这一局")
    if round_obj.game_type == "k3" and (fee := (participant.choice_data or {}).get("fee")):
        await send_game_notice(bot, round_obj, text=f"🎲 {mention} 已参与快三 #{round_obj.id} · 已扣台费 {fee} 分")
    if outcome:
        result = format_blackjack_round_text(participant, reveal_dealer=True, outcome=outcome)
        await send_game_notice(bot, round_obj, text=f"{mention} · 牌局 #{round_obj.id}\n{result}")
