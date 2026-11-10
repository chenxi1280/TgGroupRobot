import pytest

from backend.features.activity.room_games.flower import flower_awards, flower_compare, flower_move, flower_options, flower_start
from backend.shared.services.base import ValidationError
from vendor.golden_flower.models.card import Card


def _cards(*values):
    return [Card(rank=rank, suit=suit) for rank, suit in values]


def test_round_bets_and_twenty_circle_limit():
    game = flower_start(["A", "B", "C"], 1, 0)
    assert flower_options(game, 1, 0) == {"fold": True}
    assert flower_options(game, 1, 100)["raises"] == [2, 3, 5, 10]
    assert flower_options(game, 1, 100)["compare"] == []
    assert flower_move(game, 1, 100, action={"type": "look"}, special=True) == (0, None)
    assert flower_move(game, 1, 100, action={"type": "raise", "target": 3}, special=True) == (6, None)
    assert game.current_round.current_bet == 3
    with pytest.raises(ValidationError):
        flower_move(game, 2, 100, action={"type": "raise", "target": 11}, special=True)
    for _ in range(59):
        seat = game.current_round.current_player_index
        flower_move(game, seat, 100, action={"type": "call"}, special=True)
    assert game.current_round.turn_count == 20
    assert sum(flower_awards(game, special=True).values()) == game.current_round.pot


def test_235_duel_and_multiway_forced_showdown():
    triple = _cards((9, "spades"), (9, "hearts"), (9, "clubs"))
    special = _cards((2, "spades"), (3, "hearts"), (5, "clubs"))
    pair = _cards((14, "spades"), (14, "hearts"), (8, "clubs"))
    assert flower_compare(special, triple, special=True) > 0
    assert flower_compare(special, triple, special=False) < 0
    game = flower_start(["A", "B", "C"], 1, 0)
    game.players[0].hand, game.players[1].hand, game.players[2].hand = special, pair, triple
    game.current_round.turn_count = 20
    assert flower_awards(game, special=True) == {2: 3}


def test_showdown_ties_split_integer_remainder_from_dealer():
    game = flower_start(["A", "B"], 1, 0)
    game.players[0].hand = _cards((14, "spades"), (11, "hearts"), (6, "clubs"))
    game.players[1].hand = _cards((14, "hearts"), (11, "clubs"), (6, "diamonds"))
    game.current_round.turn_count = 20
    game.current_round.pot = 11
    assert flower_awards(game, special=True) == {1: 6, 0: 5}
