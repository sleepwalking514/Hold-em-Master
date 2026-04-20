from __future__ import annotations

import numpy as np
from treys import Card, Evaluator

from ui.card_parser import ALL_CARDS

EVALUATOR = Evaluator()


def monte_carlo_equity(
    hero_cards: list[int],
    board: list[int],
    num_opponents: int = 1,
    num_simulations: int = 10000,
    used_cards: set[int] | None = None,
) -> float:
    if used_cards is None:
        used_cards = set()
    dead = set(hero_cards) | set(board) | used_cards
    deck = np.array([c for c in ALL_CARDS if c not in dead], dtype=np.int32)
    deck_size = len(deck)
    cards_needed = 5 - len(board)
    cards_per_sim = cards_needed + num_opponents * 2

    if deck_size < cards_per_sim:
        return 0.5

    indices = np.array([
        np.random.permutation(deck_size)[:cards_per_sim]
        for _ in range(num_simulations)
    ])
    sampled = deck[indices]

    board_arr = list(board)
    wins = 0
    ties = 0

    for i in range(num_simulations):
        row = sampled[i]
        run_board = board_arr + row[:cards_needed].tolist()
        hero_rank = EVALUATOR.evaluate(run_board, hero_cards)
        best_opp = 7463
        idx = cards_needed
        for _ in range(num_opponents):
            opp_cards = [row[idx], row[idx + 1]]
            idx += 2
            opp_rank = EVALUATOR.evaluate(run_board, opp_cards)
            if opp_rank < best_opp:
                best_opp = opp_rank
        if hero_rank < best_opp:
            wins += 1
        elif hero_rank == best_opp:
            ties += 1

    return (wins + ties * 0.5) / num_simulations


def equity_vs_range(
    hero_cards: list[int],
    board: list[int],
    opponent_range: list[tuple[int, int]],
    num_simulations: int = 10000,
    used_cards: set[int] | None = None,
) -> float:
    if used_cards is None:
        used_cards = set()
    if not opponent_range:
        return monte_carlo_equity(hero_cards, board, 1, num_simulations, used_cards)

    dead = set(hero_cards) | set(board) | used_cards
    valid_combos = np.array(
        [(a, b) for a, b in opponent_range if a not in dead and b not in dead],
        dtype=np.int32,
    )
    if len(valid_combos) == 0:
        return monte_carlo_equity(hero_cards, board, 1, num_simulations, used_cards)

    deck_base = [c for c in ALL_CARDS if c not in dead]
    cards_needed = 5 - len(board)
    board_arr = list(board)

    combo_indices = np.random.randint(0, len(valid_combos), size=num_simulations)
    wins = 0
    ties = 0

    for i in range(num_simulations):
        opp = valid_combos[combo_indices[i]]
        deck = [c for c in deck_base if c != opp[0] and c != opp[1]]
        np.random.shuffle(deck)
        run_board = board_arr + deck[:cards_needed]
        hero_rank = EVALUATOR.evaluate(run_board, hero_cards)
        opp_rank = EVALUATOR.evaluate(run_board, opp.tolist())
        if hero_rank < opp_rank:
            wins += 1
        elif hero_rank == opp_rank:
            ties += 1

    return (wins + ties * 0.5) / num_simulations
