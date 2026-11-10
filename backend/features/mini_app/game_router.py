from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from telegram import User
from telegram.error import BadRequest, Forbidden, TelegramError

from backend.features.activity.game_web_notifications import announce_web_game
from backend.features.activity.services.game_base import MAX_GAME_BET_POINTS
from backend.features.activity.services.game_blackjack import (
    blackjack_hit, blackjack_stand, get_active_blackjack_round, place_blackjack_bet,
)
from backend.features.activity.services.game_k3 import create_or_join_k3_round
from backend.features.mini_app.auth import VERIFICATION_AUTH_SECONDS, request_identity
from backend.features.mini_app.game_views import game_view, latest_player_game
from backend.platform.db.schema.models.expansion import GameSetting
from backend.shared.services.base import ValidationError
from backend.shared.services.user_service import ensure_user

router = APIRouter(prefix="/miniapp/api/games")
Game = Literal["blackjack", "k3"]


@dataclass(frozen=True)
class GameMember:
    user: User
    chat_id: int


class GameMove(BaseModel):
    action: Literal["start", "bet", "hit", "stand"]
    round_id: int = Field(ge=0, strict=True)
    bet: int | None = Field(default=None, ge=1, le=MAX_GAME_BET_POINTS, strict=True)
    fee: int | None = Field(default=None, ge=0, le=100_000, strict=True)
    guess: str | None = Field(default=None, max_length=24)
    target_round_id: int | None = Field(default=None, ge=1, strict=True)
    card_count: int | None = Field(default=None, ge=2, strict=True)


async def game_member(request: Request) -> GameMember:
    actor = request_identity(request, max_age=VERIFICATION_AUTH_SECONDS)
    match = re.fullmatch(r"game_(?:blackjack|k3)_([1-9][0-9]{0,15})", actor.start_param)
    if match is None:
        raise HTTPException(403, "请从群里的游戏按钮打开")
    chat_id = -int(match[1])
    try:
        member = await request.app.state.telegram_app.bot.get_chat_member(chat_id, actor.user.id)
    except (BadRequest, Forbidden) as exc:
        raise HTTPException(403, "无法确认你的群成员资格") from exc
    except TelegramError as exc:
        raise HTTPException(503, "暂时无法验证群成员资格，请稍后重试") from exc
    can_play = member.status in {"creator", "administrator", "member"}
    if member.status == "restricted":
        can_play = member.is_member and member.can_send_messages
    if not can_play:
        raise HTTPException(403, "仅当前可发言的群成员可以进入游戏")
    return GameMember(actor.user, chat_id)


async def _game_setting(session, chat_id: int, *, lock: bool = False) -> GameSetting:
    setting = await session.get(GameSetting, chat_id, with_for_update=lock or None)
    if setting is None:
        raise HTTPException(404, "本群尚未配置游戏")
    return setting


async def _open_game(session, setting, member: GameMember, *, game: Game, move: GameMove):
    enabled = setting.blackjack_enabled if game == "blackjack" else setting.k3_enabled
    if not enabled:
        raise HTTPException(409, "本群未开启这个游戏")
    latest = await latest_player_game(session, member.chat_id, member.user.id, game=game)
    if move.round_id != (latest[0].id if latest else 0):
        raise HTTPException(409, "牌局已更新，请查看当前状态")
    if move.bet is None:
        raise HTTPException(422, "请选择有效的下注积分")
    if move.action != ("bet" if game == "k3" else "start"):
        raise HTTPException(422, "此游戏不支持该操作")
    if game == "k3":
        round_obj, participant = await create_or_join_k3_round(
            session, member.chat_id, member.user.id, guess=move.guess or "",
            bet_points=move.bet, expected_round_id=move.target_round_id, expected_fee=move.fee,
        )
        return round_obj, participant, round_obj.creator_user_id == member.user.id, None
    round_obj, participant, outcome = await place_blackjack_bet(session, setting, member.user.id, bet=move.bet)
    round_obj.result_data = {**round_obj.result_data, "mini_app": True}
    return round_obj, participant, True, outcome


async def _play_blackjack(session, member: GameMember, move: GameMove):
    round_obj, participant = await get_active_blackjack_round(session, member.chat_id, member.user.id, lock=True)
    if round_obj is None or participant is None or move.round_id != round_obj.id:
        raise HTTPException(409, "牌局已结束或更换，请查看最新结果")
    if move.card_count != len(round_obj.result_data["player_cards"]):
        raise HTTPException(409, "手牌已更新，请查看当前状态")
    if move.action == "hit":
        _, participant, outcome = await blackjack_hit(session, round_obj, participant)
    else:
        outcome = await blackjack_stand(session, round_obj, participant)
    return round_obj, participant, False, outcome


@router.get("/{game}")
async def read_game(game: Game, request: Request, response: Response, *, member: GameMember = Depends(game_member)):
    response.headers["Cache-Control"] = "no-store"
    async with request.app.state.db.session_factory() as session:
        setting = await _game_setting(session, member.chat_id)
        return await game_view(session, setting, member.user.id, game=game)


async def _apply_move(session, member: GameMember, *, game: Game, move: GameMove):
    if move.action in {"start", "bet"}:
        user = member.user
        await ensure_user(
            session, user.id, user.username, first_name=user.first_name,
            last_name=user.last_name, language_code=user.language_code,
        )
        setting = await _game_setting(session, member.chat_id, lock=True)
        return await _open_game(session, setting, member, game=game, move=move)
    if game == "blackjack":
        return await _play_blackjack(session, member, move)
    raise HTTPException(422, "此游戏不支持该操作")


@router.post("/{game}")
async def play_game(
    game: Game, move: GameMove, *, request: Request, response: Response, tasks: BackgroundTasks,
    member: GameMember = Depends(game_member),
):
    response.headers["Cache-Control"] = "no-store"
    async with request.app.state.db.session_factory() as session:
        try:
            round_obj, participant, opened, outcome = await _apply_move(session, member, game=game, move=move)
            setting = await _game_setting(session, member.chat_id)
            result = await game_view(session, setting, member.user.id, game=game)
            await session.commit()
        except ValidationError as exc:
            raise HTTPException(409, str(exc)) from exc
    if opened or outcome or (game == "k3" and move.fee):
        tasks.add_task(announce_web_game, request.app.state.telegram_app.bot, round_obj, participant,
                       opened=opened, outcome=outcome)
    return result
