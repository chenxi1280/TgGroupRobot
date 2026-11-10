from __future__ import annotations

from backend.features.activity.game_notice_delivery import queue_game_notice
from backend.features.activity.services.game_blackjack import format_blackjack_round_text
from backend.features.mini_app.links import game_link


def game_player_mention(user_id: int) -> str:
    return f'<a href="tg://user?id={user_id}">玩家 {user_id}</a>'


def queue_web_game(session, bot, round_obj, *, participant, opened: bool, outcome: str | None, links_enabled: bool = True) -> list:
    notices = []
    chat_id, game = round_obj.chat_id, round_obj.game_type
    mention = game_player_mention(participant.user_id)
    keyboard = game_link(bot, chat_id, game=game) if links_enabled else None
    if opened:
        game_name = "黑杰克" if game == "blackjack" else "快三"
        notices.append(queue_game_notice(
            session, chat_id, f"🎮 {game_name}开局 · #{round_obj.id}\n{mention} 开启了这一局",
            parse_mode="HTML", keyboard=keyboard,
        ))
    if game == "k3" and (fee := (participant.choice_data or {}).get("fee")):
        notices.append(queue_game_notice(
            session, chat_id, f"🎲 {mention} 已参与快三 #{round_obj.id} · 已扣台费 {fee} 分",
            parse_mode="HTML", keyboard=keyboard,
        ))
    if outcome:
        result = format_blackjack_round_text(participant, reveal_dealer=True, outcome=outcome)
        notices.append(queue_game_notice(
            session, chat_id, f"{mention} · 牌局 #{round_obj.id}\n{result}", parse_mode="HTML",
            keyboard=game_link(bot, chat_id, game=game, round_id=round_obj.id),
        ))
    return notices


def queue_group_blackjack(session, round_obj, participant, *, outcome, keyboard=None, opening=False, reply_to=None):
    text = format_blackjack_round_text(participant, reveal_dealer=bool(outcome), outcome=outcome)
    return queue_game_notice(
        session, round_obj.chat_id, text, keyboard=keyboard,
        opening_round_id=round_obj.id if opening else None,
        message_id=None if opening else round_obj.announcement_message_id, reply_to_message_id=reply_to,
    )
