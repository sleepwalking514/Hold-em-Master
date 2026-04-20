from __future__ import annotations

import numpy as np
from typing import Optional

from treys import Evaluator

from ui.card_parser import ALL_CARDS
from profiler.hand_range_estimator import HandRangeMatrix, HandRangeEstimator
from profiler.player_profile import PlayerProfile

EVALUATOR = Evaluator()


def equity_vs_range(
    hero_cards: list[int],
    board: list[int],
    range_matrix: HandRangeMatrix,
    num_simulations: int = 5000,
) -> float:
    combos = range_matrix.to_combo_list(board)
    dead = set(hero_cards) | set(board)
    valid = [(c1, c2, w) for c1, c2, w in combos if c1 not in dead and c2 not in dead]

    if not valid:
        from engine.equity_calculator import monte_carlo_equity
        return monte_carlo_equity(hero_cards, board, 1, num_simulations)

    total_weight = sum(w for _, _, w in valid)
    if total_weight == 0:
        return 0.5

    weights = np.array([w for _, _, w in valid], dtype=np.float64)
    weights /= weights.sum()

    cards_needed = 5 - len(board)
    deck_base = [c for c in ALL_CARDS if c not in dead]
    board_arr = list(board)

    wins = 0.0
    ties = 0.0
    sims_done = 0

    indices = np.random.choice(len(valid), size=num_simulations, p=weights)

    for idx in indices:
        c1, c2, _ = valid[idx]
        deck = [c for c in deck_base if c != c1 and c != c2]
        if cards_needed > len(deck):
            continue
        np.random.shuffle(deck)
        run_board = board_arr + deck[:cards_needed]

        hero_rank = EVALUATOR.evaluate(run_board, hero_cards)
        opp_rank = EVALUATOR.evaluate(run_board, [c1, c2])

        if hero_rank < opp_rank:
            wins += 1
        elif hero_rank == opp_rank:
            ties += 1
        sims_done += 1

    if sims_done == 0:
        return 0.5
    return (wins + ties * 0.5) / sims_done


def multiway_equity(
    hero_cards: list[int],
    board: list[int],
    opponent_ranges: list[HandRangeMatrix],
    num_simulations: int = 3000,
) -> float:
    if not opponent_ranges:
        from engine.equity_calculator import monte_carlo_equity
        return monte_carlo_equity(hero_cards, board, 1, num_simulations)

    dead = set(hero_cards) | set(board)
    opp_combos = []
    for rm in opponent_ranges:
        combos = rm.to_combo_list(board)
        valid = [(c1, c2, w) for c1, c2, w in combos if c1 not in dead and c2 not in dead]
        if not valid:
            valid = [(-1, -1, 1.0)]
        opp_combos.append(valid)

    cards_needed = 5 - len(board)
    deck_base = [c for c in ALL_CARDS if c not in dead]
    board_arr = list(board)

    wins = 0.0
    ties = 0.0
    sims_done = 0

    for _ in range(num_simulations):
        used = set()
        opp_hands = []
        skip = False

        for combos in opp_combos:
            weights = np.array([w for _, _, w in combos], dtype=np.float64)
            if weights.sum() == 0:
                skip = True
                break
            weights /= weights.sum()
            idx = np.random.choice(len(combos), p=weights)
            c1, c2, _ = combos[idx]
            if c1 == -1:
                skip = True
                break
            if c1 in used or c2 in used:
                skip = True
                break
            used.add(c1)
            used.add(c2)
            opp_hands.append((c1, c2))

        if skip:
            continue

        deck = [c for c in deck_base if c not in used]
        if cards_needed > len(deck):
            continue
        np.random.shuffle(deck)
        run_board = board_arr + deck[:cards_needed]

        hero_rank = EVALUATOR.evaluate(run_board, hero_cards)
        best_opp = 7463
        for c1, c2 in opp_hands:
            opp_rank = EVALUATOR.evaluate(run_board, [c1, c2])
            if opp_rank < best_opp:
                best_opp = opp_rank

        if hero_rank < best_opp:
            wins += 1
        elif hero_rank == best_opp:
            ties += 1
        sims_done += 1

    if sims_done == 0:
        return 0.5
    return (wins + ties * 0.5) / sims_done
