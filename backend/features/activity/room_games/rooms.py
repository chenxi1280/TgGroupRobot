from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from backend.features.activity.room_games.fees import (
    change_game_points, collect_fee, fee_settings, require_closed_mall,
)
from backend.features.activity.room_games.flower import flower_awards, flower_move, flower_options, flower_start
from backend.features.activity.room_games.mahjong import RESERVE_UNITS, mahjong
from backend.features.points.services.points_service_accounts import get_balance
from backend.platform.db.schema.models.core import PointsAccount
from backend.platform.db.schema.models.room_games import RoomGame
from backend.shared.services.base import ValidationError
from vendor.golden_flower.models.game import GameState, PlayerStatus

ACTION_SECONDS = 20
WAIT_MINUTES = 10
MAHJONG_SEATS = 4
FLOWER_MIN_SEATS = 2
MAX_SEATS = 6
MAX_BETWEEN_HAND_SECONDS = 60


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def seat_for(room: RoomGame, user_id: int) -> int | None:
    return next((index for index, seat in enumerate(room.seats) if seat["id"] == user_id), None)


def hand_reserve(game: str, unit: int) -> int:
    return unit * RESERVE_UNITS if game == "sichuan" else unit


async def available_rooms(session, chat_id: int) -> list[RoomGame]:
    stmt = select(RoomGame).where(RoomGame.chat_id == chat_id, RoomGame.status != "closed")
    return list((await session.scalars(stmt.order_by(RoomGame.id.desc()).limit(50))).all())


async def create_room(session, chat_id: int, user, *, data) -> RoomGame:
    await require_closed_mall(session, chat_id)
    settings = await fee_settings(session)
    config = getattr(settings, data.game)
    if not config.enabled:
        raise ValidationError("管理员尚未启用该房间游戏")
    room = RoomGame(
        chat_id=chat_id, owner_id=user.id, game=data.game, unit=data.base * data.multiplier,
        fee=config.points, hand_limit=config.hands, status="waiting",
        seats=[{"id": user.id, "name": user.full_name}],
        options={"base": data.base, "multiplier": data.multiplier, "special": data.special},
        hand={}, history=[], created_at=now(), deadline=now() + dt.timedelta(minutes=WAIT_MINUTES),
    )
    session.add(room)
    await session.flush()
    return room


def join_room(room: RoomGame, user) -> None:
    if seat_for(room, user.id) is not None:
        return
    limit = MAHJONG_SEATS if room.game == "sichuan" else MAX_SEATS
    if room.status != "waiting" or len(room.seats) >= limit:
        raise ValidationError("本场已开场或座位已满")
    room.seats = [*room.seats, {"id": user.id, "name": user.full_name}]
    room.version += 1


def leave_room(room: RoomGame, seat: int) -> None:
    if room.status == "waiting":
        room.seats = [player for index, player in enumerate(room.seats) if index != seat]
        if room.seats:
            room.owner_id = room.seats[0]["id"]
        else:
            room.status, room.deadline = "closed", None
    elif room.status == "between" and room.seats[seat]["id"] == room.owner_id:
        room.status, room.deadline = "closed", None
    else:
        raise ValidationError("本场已开场，房主可在小局结算后结束，掉线时由系统托管")
    room.version += 1


async def _start_engine(room: RoomGame) -> dict:
    names = [seat["name"] for seat in room.seats]
    if room.game == "zhajinhua":
        dealer = len(room.history) % len(names)
        return {"engine": flower_start(names, room.unit, dealer).model_dump(mode="json")}
    if room.history:
        result = await mahjong("next", state=room.hand["engine"])
    else:
        result = await mahjong("start", names=names, rounds=room.hand_limit)
    return {"engine": result["state"], "views": result["views"]}


async def open_hand(session, room: RoomGame, *, first: bool) -> None:
    minimum = MAHJONG_SEATS if room.game == "sichuan" else FLOWER_MIN_SEATS
    if len(room.seats) < minimum:
        raise ValidationError(f"至少需要 {minimum} 名玩家")
    await require_closed_mall(session, room.chat_id)
    if not getattr(await fee_settings(session), room.game).enabled:
        raise ValidationError("管理员已停用该游戏")
    engine = await _start_engine(room)
    number = len(room.history) + 1
    reserve = hand_reserve(room.game, room.unit)
    for player in sorted(room.seats, key=lambda row: row["id"]):
        user_id = player["id"]
        if first:
            await collect_fee(session, room.chat_id, user_id, game=room.game, session_id=room.id, amount=room.fee)
        await change_game_points(
            session, room.chat_id, user_id, amount=-reserve,
            reason=f"房间 #{room.id} 第 {number} 局" + ("预扣" if room.game == "sichuan" else "底注"),
        )
    room.hand = {**engine, "comparison": None}
    room.status = "playing"
    room.version += 1
    room.deadline = now() + dt.timedelta(seconds=ACTION_SECONDS)


def _hand_deltas(room: RoomGame, engine: dict, awards: dict[int, int] | None) -> list[int] | None:
    if room.game == "sichuan":
        if not engine["result"]:
            return None
        return [delta * room.unit for delta in engine["result"]["deltas"]]
    if awards is None:
        return None
    return [awards.get(i, 0) - player["total_bet_this_round"] for i, player in enumerate(engine["players"])]


async def _settle_hand(session, room: RoomGame, deltas: list[int], *, awards: dict[int, int] | None) -> None:
    if sum(deltas):
        raise RuntimeError("房间积分结算未守恒")
    number = len(room.history) + 1
    rows = []
    seats = sorted(enumerate(room.seats), key=lambda item: item[1]["id"])
    for index, player in seats:
        credit = hand_reserve(room.game, room.unit) + deltas[index] if awards is None else awards.get(index, 0)
        if credit < 0:
            raise RuntimeError("麻将赔付超出预扣")
        balance = await get_balance(session, room.chat_id, player["id"])
        if credit:
            balance = await change_game_points(
                session, room.chat_id, player["id"], amount=credit, reason=f"房间 #{room.id} 第 {number} 局结算",
            )
        rows.append({**player, "delta": deltas[index], "balance": balance})
    room.history = [*room.history, {"number": number, "rows": rows}]
    finished = len(room.history) >= room.hand_limit
    room.status = "closed" if finished else "between"
    room.deadline = None if finished else now() + dt.timedelta(seconds=MAX_BETWEEN_HAND_SECONDS)


async def _move_flower(session, room: RoomGame, seat: int, *, action: dict) -> tuple[dict, dict | None]:
    user_ids = [player["id"] for player in room.seats]
    await session.execute(select(PointsAccount.id).where(
        PointsAccount.chat_id == room.chat_id, PointsAccount.user_id.in_(user_ids),
    ).order_by(PointsAccount.user_id).with_for_update())
    game = GameState.model_validate(room.hand["engine"])
    user_id = room.seats[seat]["id"]
    balance = await get_balance(session, room.chat_id, user_id)
    cost, comparison = flower_move(game, seat, balance, action=action, special=room.options["special"])
    if cost:
        await change_game_points(
            session, room.chat_id, user_id, amount=-cost, reason=f"房间 #{room.id} 第 {len(room.history) + 1} 局下注",
        )
    room.hand = {**room.hand, "comparison": comparison}
    return game.model_dump(mode="json"), flower_awards(game, special=room.options["special"])


async def advance_hand(session, room: RoomGame, *, seat: int | None, action: dict) -> bool:
    engine = room.hand["engine"]
    awards = None
    if room.game == "sichuan":
        op = "timeout" if seat is None else "move"
        result = await mahjong(op, state=engine, seat=seat, action=action)
        engine = result["state"]
        room.hand = {**room.hand, "views": result["views"]}
    else:
        if seat is None:
            seat = engine["current_round"]["current_player_index"]
        engine, awards = await _move_flower(session, room, seat, action=action)
    room.hand = {**room.hand, "engine": engine}
    room.version += 1
    if (deltas := _hand_deltas(room, engine, awards)) is not None:
        await _settle_hand(session, room, deltas, awards=awards)
        return True
    if action.get("type") != "look":
        room.deadline = now() + dt.timedelta(seconds=ACTION_SECONDS)
    return False


def flower_view(room: RoomGame, seat: int, balance: int) -> dict:
    game = GameState.model_validate(room.hand["engine"])
    players = []
    comparison = room.hand["comparison"]
    visible = set(comparison["seats"]) if comparison and seat in comparison["seats"] else set()
    for index, player in enumerate(game.players):
        show = index in visible or (index == seat and player.status == PlayerStatus.ACTIVE_SEEN)
        players.append({"status": player.status, "bet": player.total_bet_this_round,
                        "cards": [card.model_dump(mode="json") for card in player.hand] if show else None})
    hand = game.current_round
    return {
        "players": players, "pot": hand.pot, "dealer": hand.dealer_index, "turn": hand.current_player_index,
        "round": hand.turn_count + 1, "current_bet": hand.current_bet,
        "legal": flower_options(game, seat, balance) if room.status == "playing" else {},
    }


def room_summary(room: RoomGame) -> dict:
    return {
        "id": room.id, "game": room.game, "status": room.status, "players": len(room.seats),
        "unit": room.unit, "fee": room.fee, "hand_limit": room.hand_limit,
    }


async def room_view(session, room: RoomGame, user_id: int) -> dict:
    seat = seat_for(room, user_id)
    balance = await get_balance(session, room.chat_id, user_id)
    table = None
    if seat is not None and room.hand:
        if room.game == "sichuan":
            table = room.hand["views"][seat]
        else:
            table = flower_view(room, seat, balance)
    results = [
        {"number": hand["number"], "void": hand.get("void", False), "rows": [
            {**row, "balance": row["balance"] if row["id"] == user_id else None} for row in hand["rows"]
        ]} for hand in room.history
    ]
    return {
        **room_summary(room), "seats": room.seats, "owner_id": room.owner_id, "seat": seat,
        "version": room.version, "deadline": room.deadline, "balance": balance,
        "requirement": room.fee + hand_reserve(room.game, room.unit),
        "fee_charged": bool(room.hand and seat is not None), "table": table, "results": results,
        "options": room.options,
    }


async def void_hand(session, room: RoomGame) -> None:
    number = len(room.history) + 1
    engine = room.hand["engine"]
    rows = []
    for index, player in sorted(enumerate(room.seats), key=lambda entry: entry[1]["id"]):
        amount = (hand_reserve(room.game, room.unit) if room.game == "sichuan"
                  else engine["players"][index]["total_bet_this_round"])
        balance = await change_game_points(
            session, room.chat_id, player["id"], amount=amount, reason=f"房间 #{room.id} 第 {number} 局作废退分",
        )
        rows.append({**player, "delta": 0, "balance": balance})
    room.history = [*room.history, {"number": number, "rows": rows, "void": True}]
    room.status, room.deadline = "closed", None
    room.version += 1
