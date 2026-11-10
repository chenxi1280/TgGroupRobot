from __future__ import annotations

from vendor.golden_flower.engine.evaluator import compare_hands, evaluate_hand
from vendor.golden_flower.engine.game_manager import create_game, start_round
from vendor.golden_flower.engine.rules import get_call_cost
from vendor.golden_flower.models.game import GameConfig, GameState, HandType, PlayerStatus

from backend.shared.services.base import ValidationError

TURN_LIMIT = 20
RAISE_LEVELS = (2, 3, 5, 10)
MIN_COMPARE_ROUND = 2
SPECIAL_RANKS = {2, 3, 5}
DUEL_PLAYERS = 2


def flower_start(names: list[str], unit: int, dealer: int) -> GameState:
    game = create_game(
        [{"name": name, "player_type": "human"} for name in names],
        GameConfig(initial_chips=unit, ante=unit, max_bet=unit * max(RAISE_LEVELS), max_turns=TURN_LIMIT),
    )
    start_round(game)
    game.current_round.dealer_index = dealer
    game.current_round.current_player_index = (dealer + 1) % len(names)
    for seat, player in enumerate(game.players):
        player.id = str(seat)
    return game


def _is_235(cards) -> bool:
    return {int(card.rank) for card in cards} == SPECIAL_RANKS and len({card.suit for card in cards}) == len(cards)


def flower_compare(cards, other, *, special: bool) -> int:
    left, right = evaluate_hand(cards), evaluate_hand(other)
    if special and right.hand_type == HandType.THREE_OF_A_KIND and _is_235(cards):
        return 1
    if special and left.hand_type == HandType.THREE_OF_A_KIND and _is_235(other):
        return -1
    return compare_hands(left, right)


def _compare_targets(game: GameState, seat: int) -> list[int]:
    if game.current_round.turn_count + 1 < MIN_COMPARE_ROUND:
        return []
    return [i for i, other in enumerate(game.players) if i != seat and other.is_active]


def flower_options(game: GameState, seat: int, balance: int) -> dict:
    player = game.players[seat]
    hand = game.current_round
    cost = get_call_cost(hand, player)
    blind = player.status == PlayerStatus.ACTIVE_BLIND
    can_look = blind and balance >= cost
    if not player.is_active or seat != hand.current_player_index:
        return {"look": can_look}
    if balance < cost:
        return {"fold": True}
    raises = [level * game.config.ante for level in RAISE_LEVELS]
    max_raise = balance if blind else balance // 2
    return {
        "fold": True, "look": can_look, "call": cost,
        "raises": [value for value in raises if hand.current_bet < value <= max_raise],
        "compare": _compare_targets(game, seat),
    }


def _advance(game: GameState, seat: int) -> None:
    hand = game.current_round
    count = len(game.players)
    offset = (seat - hand.dealer_index - 1) % count
    for step in range(1, count + 1):
        index = (seat + step) % count
        if game.players[index].is_active:
            hand.current_player_index = index
            hand.turn_count += int(offset + step >= count)
            return


def _valid_target(target, choices: list[int]) -> bool:
    return type(target) is int and target in choices


def _compare_action(game: GameState, seat: int, target: int, *, special: bool) -> dict:
    player, other = game.players[seat], game.players[target]
    loser = other if flower_compare(player.hand, other.hand, special=special) > 0 else player
    loser.status = PlayerStatus.COMPARE_LOST
    return {"seats": [seat, target], "loser": int(loser.id)}


def _bet_action(game: GameState, seat: int, options: dict, *, kind, target, special: bool) -> tuple[int, dict | None]:
    player = game.players[seat]
    hand = game.current_round
    if kind == "fold" and options.get("fold"):
        player.status = PlayerStatus.FOLDED
        return 0, None
    if kind == "call" and options.get("call"):
        return options["call"], None
    if kind == "raise" and _valid_target(target, options.get("raises", [])):
        hand.current_bet = target
        multiplier = 2 if player.status == PlayerStatus.ACTIVE_SEEN else 1
        return target * multiplier, None
    if kind == "compare" and _valid_target(target, options.get("compare", [])):
        return options["call"], _compare_action(game, seat, target, special=special)
    raise ValidationError("当前不能执行该操作")


def flower_move(game: GameState, seat: int, balance: int, *, action: dict, special: bool) -> tuple[int, dict | None]:
    player = game.players[seat]
    hand = game.current_round
    kind, target = action.get("type"), action.get("target")
    options = flower_options(game, seat, balance)
    if kind == "look" and options.get("look"):
        player.status = PlayerStatus.ACTIVE_SEEN
        return 0, None
    cost, comparison = _bet_action(game, seat, options, kind=kind, target=target, special=special)
    player.total_bet_this_round += cost
    hand.pot += cost
    _advance(game, seat)
    return cost, comparison


def _top_players(active, *, special: bool):
    best = active[:1]
    for player in active[1:]:
        comparison = flower_compare(player.hand, best[0].hand, special=special)
        if comparison > 0:
            best = [player]
        elif comparison == 0:
            best.append(player)
    return best


def flower_awards(game: GameState, *, special: bool) -> dict[int, int] | None:
    hand = game.current_round
    active = [p for i in range(len(game.players))
              if (p := game.players[(hand.dealer_index + i + 1) % len(game.players)]).is_active]
    if len(active) > 1 and hand.turn_count < hand.max_turns:
        return None
    best = _top_players(active, special=special and len(active) == DUEL_PLAYERS)
    share, remainder = divmod(hand.pot, len(best))
    return {int(player.id): share + (remainder if index == 0 else 0) for index, player in enumerate(best)}
