from __future__ import annotations

import copy
from dataclasses import dataclass

from env.game_state import GameState


@dataclass
class RunItTwiceResult:
    board_1: list[int]
    board_2: list[int]
    winnings_1: dict[str, int]
    winnings_2: dict[str, int]
    combined: dict[str, int]


def run_it_twice(
    game_state: GameState,
    remaining_board_1: list[int],
    remaining_board_2: list[int],
) -> RunItTwiceResult:
    game_state.calculate_side_pots()

    gs1 = copy.deepcopy(game_state)
    gs2 = copy.deepcopy(game_state)

    gs1.board = game_state.board[:] + remaining_board_1
    gs2.board = game_state.board[:] + remaining_board_2

    half_pot = game_state.pot // 2
    remainder = game_state.pot % 2

    gs1.pot = half_pot + remainder
    gs2.pot = half_pot

    for sp in gs1.side_pots:
        orig = sp.amount
        sp.amount = orig // 2 + orig % 2
    for sp in gs2.side_pots:
        sp.amount = sp.amount // 2

    w1 = gs1.settle()
    w2 = gs2.settle()

    combined: dict[str, int] = {}
    all_names = set(w1.keys()) | set(w2.keys())
    for name in all_names:
        combined[name] = w1.get(name, 0) + w2.get(name, 0)

    return RunItTwiceResult(
        board_1=gs1.board,
        board_2=gs2.board,
        winnings_1=w1,
        winnings_2=w2,
        combined=combined,
    )
