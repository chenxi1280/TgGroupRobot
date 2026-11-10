"""Local-only harness for the vendored Golden Flower engine."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from vendor.golden_flower.engine.game_manager import (
    GameError,
    apply_action,
    create_game,
    get_visible_state,
    start_round,
)
from vendor.golden_flower.engine.rules import get_available_actions
from vendor.golden_flower.models.game import GameAction, GameConfig, GamePhase, GameState

app = FastAPI()
games: dict[str, GameState] = {}


class Move(BaseModel):
    action: GameAction
    target_id: str | None = None


def view(game: GameState) -> dict:
    current = game.current_round
    player = game.players[current.current_player_index]
    state = get_visible_state(game, player.id)
    if player.status != "active_seen":
        state["players"][current.current_player_index]["hand"] = None
    state["available_actions"] = get_available_actions(current, player, game.players, game.config)
    return state


@app.post("/games")
async def start() -> dict:
    game = create_game(
        [{"name": f"玩家 {i}", "player_type": "human"} for i in range(1, 4)],
        GameConfig(ante=1, max_bet=10, max_turns=20),
    )
    start_round(game)
    games[game.game_id] = game
    return view(game)


@app.post("/games/{game_id}/moves")
async def move(game_id: str, move: Move) -> dict:
    game = games.get(game_id)
    if game is None:
        raise HTTPException(404, "本地牌局已结束")
    current = game.current_round
    player = game.players[current.current_player_index]
    try:
        apply_action(game, player.id, move.action, move.target_id)
    except GameError as exc:
        raise HTTPException(400, str(exc)) from exc
    state = view(game)
    if current.phase == GamePhase.SETTLEMENT:
        del games[game_id]
    return state
