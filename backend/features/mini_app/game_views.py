from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.features.activity.room_games.fees import fee_settings
from backend.features.activity.services.game_base import (
    MAX_GAME_BET_POINTS, get_game_points_chat_label, get_round_points_chat_id, now_utc, resolve_points_chat_id,
)
from backend.features.activity.services.game_blackjack import blackjack_total
from backend.features.activity.services.game_k3 import K3_OPTION_LABELS, K3_OPTION_MULTIPLIERS, get_active_k3_round
from backend.features.points.services.points_service import get_balance
from backend.platform.db.schema.models.core import TgChat
from backend.platform.db.schema.models.expansion import GameParticipant, GameRound


async def latest_player_game(session, chat_id: int, user_id: int, *, game: str):
    statement = (
        select(GameRound, GameParticipant)
        .join(GameParticipant, GameParticipant.round_id == GameRound.id)
        .where(GameRound.chat_id == chat_id, GameRound.game_type == game, GameParticipant.user_id == user_id)
        .order_by(GameRound.id.desc())
        .limit(1)
    )
    return (await session.execute(statement)).first()


def _round_fields(round_obj) -> dict:
    return {
        "id": round_obj.id,
        "status": round_obj.status,
        "settle_at": round_obj.settle_at,
    }


def _player_fields(participant) -> dict:
    return {
        "bet": participant.bet_points,
        "payout": participant.payout_points,
        "player_status": participant.status,
    }


def _blackjack_view(latest) -> dict | None:
    if latest is None:
        return None
    round_obj, participant = latest
    data = participant.choice_data or {}
    player = data.get("player_cards") or []
    dealer = data.get("dealer_cards") or []
    finished = round_obj.status == "finished"
    return {
        **_round_fields(round_obj), **_player_fields(participant),
        "player": player, "player_total": blackjack_total(player),
        "dealer": dealer if finished else [*dealer[:1], None],
        "dealer_total": blackjack_total(dealer) if finished else None,
    }


def _k3_player_view(latest) -> dict | None:
    if latest is None:
        return None
    round_obj, participant = latest
    data = round_obj.result_data or {}
    return {
        **_round_fields(round_obj), **_player_fields(participant),
        "guess": (participant.choice_data or {}).get("guess"),
        "fee": (participant.choice_data or {}).get("fee", 0),
        "dice": data.get("dice"), "label": data.get("label"),
    }


async def _k3_active_view(session, round_obj) -> dict | None:
    if round_obj is None:
        return None
    count = await session.scalar(
        select(func.count(GameParticipant.id)).where(GameParticipant.round_id == round_obj.id)
    )
    return {**_round_fields(round_obj), "players": count}


async def _latest_k3_draw(session, chat_id: int) -> dict | None:
    round_obj = await session.scalar(
        select(GameRound).where(GameRound.chat_id == chat_id, GameRound.game_type == "k3", GameRound.status == "finished")
        .order_by(GameRound.id.desc()).limit(1)
    )
    if round_obj is None:
        return None
    data = round_obj.result_data or {}
    return {"id": round_obj.id, "dice": data.get("dice"), "label": data.get("label")}


async def _k3_view(session, *, active, latest, draw) -> dict:
    return {
        "round": await _k3_active_view(session, active),
        "fee": (await fee_settings(session)).k3,
        "my_k3": _k3_player_view(latest),
        "draw": draw,
        "options": [
            {"key": key, "label": label, "multiplier": str(K3_OPTION_MULTIPLIERS[key])}
            for key, label in K3_OPTION_LABELS.items()
        ],
    }


async def _historical_result(session, chat_id: int, user_id: int, *, game: str, round_id: int):
    result = await session.get(GameRound, round_id)
    if result is None or result.chat_id != chat_id or result.game_type != game or result.status != "finished":
        raise HTTPException(404, "这局结果不可用")
    statement = select(GameParticipant).where(GameParticipant.round_id == result.id)
    draw = None
    if game == "k3":
        statement = statement.where(GameParticipant.user_id == user_id)
        data = result.result_data or {}
        draw = {"id": result.id, "dice": data.get("dice"), "label": data.get("label")}
    participant = await session.scalar(statement)
    return ((result, participant) if participant else None), draw


async def game_view(session, setting, user_id: int, *, game: str, result_round_id: int | None = None) -> dict:
    chat_id = setting.chat_id
    k3_round = draw = None
    if result_round_id is not None:
        latest, draw = await _historical_result(session, chat_id, user_id, game=game, round_id=result_round_id)
    else:
        latest = await latest_player_game(session, chat_id, user_id, game=game)
        if game == "k3":
            k3_round = await get_active_k3_round(session, chat_id)
            draw = await _latest_k3_draw(session, chat_id)
    balance_round = k3_round
    if game == "blackjack" and latest and latest[0].status == "player_turn":
        balance_round = latest[0]
    points_chat = resolve_points_chat_id(setting, chat_id)
    if balance_round is not None:
        points_chat = get_round_points_chat_id(balance_round, points_chat)
    chat = await session.get(TgChat, chat_id)
    details = await _k3_view(session, active=k3_round, latest=latest, draw=draw) if game == "k3" else {"round": _blackjack_view(latest)}
    return {
        **details, "game": game, "chat_title": chat.title or "群游戏",
        "historical": result_round_id is not None, "own_result": bool(latest and latest[1].user_id == user_id),
        "enabled": {"k3": setting.k3_enabled, "blackjack": setting.blackjack_enabled},
        "balance": await get_balance(session, points_chat, user_id),
        "balance_label": await get_game_points_chat_label(session, chat_id, points_chat),
        "max_bet": MAX_GAME_BET_POINTS,
        "server_time": now_utc(),
    }
