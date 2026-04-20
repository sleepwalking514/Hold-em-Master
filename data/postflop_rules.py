from __future__ import annotations

import random
from enum import Enum

from treys import Card


class HandStrength(Enum):
    TRASH = 0
    WEAK_DRAW = 1
    MEDIUM_DRAW = 2
    STRONG_DRAW = 3
    WEAK_MADE = 4
    MEDIUM_MADE = 5
    STRONG_MADE = 6
    MONSTER = 7


class PostflopAction(Enum):
    CHECK = "check"
    BET_SMALL = "bet_small"
    BET_MEDIUM = "bet_medium"
    BET_LARGE = "bet_large"
    CALL = "call"
    RAISE = "raise"
    FOLD = "fold"


def _count_flush_outs(hole_cards: list[int], board: list[int]) -> int:
    """Count flush draw outs (cards needed to complete flush)."""
    suits: dict[int, int] = {}
    for c in hole_cards + board:
        s = Card.get_suit_int(c)
        suits[s] = suits.get(s, 0) + 1
    for s, count in suits.items():
        hero_in_suit = sum(1 for c in hole_cards if Card.get_suit_int(c) == s)
        if count >= 4 and hero_in_suit >= 1:
            return 13 - count
    return 0


def _count_straight_outs(hole_cards: list[int], board: list[int]) -> int:
    """Count straight draw outs. OESD=8, gutshot=4, double gutshot=8."""
    all_ranks = set()
    hero_ranks = set()
    for c in hole_cards:
        r = Card.get_rank_int(c)
        all_ranks.add(r)
        hero_ranks.add(r)
    for c in board:
        all_ranks.add(Card.get_rank_int(c))
    if 12 in all_ranks:
        all_ranks.add(-1)
    if 12 in hero_ranks:
        hero_ranks.add(-1)

    completing_ranks = set()

    for start in range(-1, 10):
        window = set(start + i for i in range(5))
        present = window & all_ranks
        missing = window - all_ranks
        if len(missing) != 1:
            continue
        if not (present & hero_ranks):
            continue
        completing_ranks.update(missing)

    outs = 0
    for r in completing_ranks:
        actual_rank = 12 if r == -1 else r
        if 0 <= actual_rank <= 12 and actual_rank not in all_ranks:
            outs += 4

    return outs


def classify_hand_strength(
    rank: int,
    board_len: int,
    hole_cards: list[int] | None = None,
    board: list[int] | None = None,
) -> HandStrength:
    """Classify hand strength considering both made hand rank and draw potential."""
    made_strength = _classify_made_hand(rank, board_len)

    if hole_cards is None or board is None or board_len >= 5:
        return made_strength

    flush_outs = _count_flush_outs(hole_cards, board)
    straight_outs = _count_straight_outs(hole_cards, board)
    total_outs = min(flush_outs + straight_outs, 15)

    if total_outs >= 12:
        draw_strength = HandStrength.STRONG_DRAW
    elif total_outs >= 8:
        draw_strength = HandStrength.STRONG_DRAW
    elif total_outs >= 4:
        draw_strength = HandStrength.MEDIUM_DRAW
    elif total_outs >= 2:
        draw_strength = HandStrength.WEAK_DRAW
    else:
        draw_strength = HandStrength.TRASH

    return max(made_strength, draw_strength, key=lambda h: h.value)


def _classify_made_hand(rank: int, board_len: int) -> HandStrength:
    """Classify based on treys rank only (made hand strength).

    Treys ranks: 1 (royal flush) → 7462 (worst high card).
    1-322: straight flush+  |  323-1600: quads/full house
    1601-3500: flush/straight  |  3501-5000: three-of-a-kind/two pair
    5001-6185: one pair  |  6186-7462: high card
    """
    if rank <= 322:
        return HandStrength.MONSTER
    elif rank <= 1600:
        return HandStrength.STRONG_MADE
    elif rank <= 3500:
        return HandStrength.MEDIUM_MADE
    elif rank <= 5000:
        return HandStrength.WEAK_MADE
    elif rank <= 6185:
        return HandStrength.WEAK_MADE
    return HandStrength.TRASH


def hand_strength_ratio(rank: int) -> float:
    return 1.0 - (rank - 1) / 7461


IP_STRATEGY = {
    HandStrength.MONSTER:     {"action": PostflopAction.BET_LARGE, "freq": 0.90, "alt": PostflopAction.RAISE},
    HandStrength.STRONG_MADE: {"action": PostflopAction.BET_MEDIUM, "freq": 0.80, "alt": PostflopAction.BET_LARGE},
    HandStrength.MEDIUM_MADE: {"action": PostflopAction.BET_SMALL, "freq": 0.65, "alt": PostflopAction.CHECK},
    HandStrength.WEAK_MADE:   {"action": PostflopAction.BET_SMALL, "freq": 0.45, "alt": PostflopAction.CHECK},
    HandStrength.STRONG_DRAW: {"action": PostflopAction.BET_MEDIUM, "freq": 0.65, "alt": PostflopAction.CALL},
    HandStrength.MEDIUM_DRAW: {"action": PostflopAction.BET_SMALL, "freq": 0.40, "alt": PostflopAction.CHECK},
    HandStrength.WEAK_DRAW:   {"action": PostflopAction.CHECK, "freq": 0.60, "alt": PostflopAction.BET_SMALL},
    HandStrength.TRASH:       {"action": PostflopAction.CHECK, "freq": 0.50, "alt": PostflopAction.BET_MEDIUM},
}

OOP_STRATEGY = {
    HandStrength.MONSTER:     {"action": PostflopAction.BET_LARGE, "freq": 0.70, "alt": PostflopAction.CHECK},
    HandStrength.STRONG_MADE: {"action": PostflopAction.BET_MEDIUM, "freq": 0.70, "alt": PostflopAction.CHECK},
    HandStrength.MEDIUM_MADE: {"action": PostflopAction.BET_SMALL, "freq": 0.50, "alt": PostflopAction.CHECK},
    HandStrength.WEAK_MADE:   {"action": PostflopAction.CHECK, "freq": 0.60, "alt": PostflopAction.BET_SMALL},
    HandStrength.STRONG_DRAW: {"action": PostflopAction.BET_MEDIUM, "freq": 0.50, "alt": PostflopAction.CHECK},
    HandStrength.MEDIUM_DRAW: {"action": PostflopAction.CHECK, "freq": 0.55, "alt": PostflopAction.BET_SMALL},
    HandStrength.WEAK_DRAW:   {"action": PostflopAction.CHECK, "freq": 0.70, "alt": PostflopAction.FOLD},
    HandStrength.TRASH:       {"action": PostflopAction.CHECK, "freq": 0.60, "alt": PostflopAction.BET_MEDIUM},
}

FACING_BET_STRATEGY = {
    HandStrength.MONSTER:     {"action": PostflopAction.RAISE, "freq": 0.75, "alt": PostflopAction.CALL},
    HandStrength.STRONG_MADE: {"action": PostflopAction.RAISE, "freq": 0.45, "alt": PostflopAction.CALL},
    HandStrength.MEDIUM_MADE: {"action": PostflopAction.CALL, "freq": 0.65, "alt": PostflopAction.RAISE},
    HandStrength.WEAK_MADE:   {"action": PostflopAction.CALL, "freq": 0.45, "alt": PostflopAction.FOLD},
    HandStrength.STRONG_DRAW: {"action": PostflopAction.CALL, "freq": 0.70, "alt": PostflopAction.RAISE},
    HandStrength.MEDIUM_DRAW: {"action": PostflopAction.CALL, "freq": 0.50, "alt": PostflopAction.FOLD},
    HandStrength.WEAK_DRAW:   {"action": PostflopAction.FOLD, "freq": 0.65, "alt": PostflopAction.CALL},
    HandStrength.TRASH:       {"action": PostflopAction.FOLD, "freq": 0.80, "alt": PostflopAction.CALL},
}


SPR_ADJUSTMENTS = {
    "low":    {"threshold": 3.0,  "monster_bet": PostflopAction.BET_LARGE, "medium_caution": 0.0},
    "medium": {"threshold": 8.0,  "monster_bet": PostflopAction.BET_MEDIUM, "medium_caution": 0.1},
    "high":   {"threshold": 999,  "monster_bet": PostflopAction.BET_SMALL, "medium_caution": 0.2},
}


def get_spr_category(spr_value: float) -> str:
    if spr_value < 3.0:
        return "low"
    elif spr_value < 8.0:
        return "medium"
    return "high"


def get_postflop_advice(
    strength: HandStrength,
    is_ip: bool,
    facing_bet: bool,
    spr_value: float = 6.0,
    is_wet_board: bool = False,
    mix: bool = True,
) -> dict:
    if facing_bet:
        strategy = FACING_BET_STRATEGY[strength]
    elif is_ip:
        strategy = IP_STRATEGY[strength]
    else:
        strategy = OOP_STRATEGY[strength]

    result = dict(strategy)

    spr_cat = get_spr_category(spr_value)
    if spr_cat == "low" and strength in (HandStrength.STRONG_MADE, HandStrength.MONSTER):
        result["action"] = PostflopAction.BET_LARGE
        result["freq"] = min(result["freq"] + 0.1, 0.95)

    if is_wet_board and strength in (HandStrength.STRONG_MADE, HandStrength.MONSTER):
        result["freq"] = min(result["freq"] + 0.1, 0.95)

    if mix and random.random() > result["freq"]:
        result["action"] = result["alt"]

    return result
