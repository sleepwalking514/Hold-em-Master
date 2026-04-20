from __future__ import annotations

RANKS = "23456789TJQKA"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}

HAND_TIERS = {
    1: ["AA", "KK", "QQ", "AKs"],
    2: ["JJ", "TT", "AQs", "AKo", "AJs"],
    3: ["99", "88", "ATs", "AQo", "KQs", "KJs"],
    4: ["77", "66", "AJo", "ATo", "KTs", "KQo", "QJs", "QTs"],
    5: ["55", "44", "A9s", "A8s", "A7s", "A6s", "A5s", "KJo", "KTo", "QJo", "JTs", "J9s"],
    6: ["33", "22", "A4s", "A3s", "A2s", "A9o", "K9s", "K8s", "Q9s", "QTo", "T9s", "T8s", "98s"],
    7: ["A8o", "A7o", "A6o", "A5o", "K7s", "K6s", "K5s", "K9o", "Q8s", "J8s", "J9o", "T9o", "97s", "87s", "86s", "76s"],
    8: ["A4o", "A3o", "A2o", "K4s", "K3s", "K2s", "K8o", "Q7s", "Q6s", "Q5s", "Q9o", "J7s", "T7s", "96s", "85s", "75s", "65s", "54s"],
    9: ["K7o", "K6o", "Q8o", "Q4s", "Q3s", "Q2s", "J6s", "J5s", "J8o", "T6s", "T8o", "98o", "87o", "95s", "84s", "74s", "64s", "53s", "43s"],
}


def _hand_tier(hand: str) -> int:
    for tier, hands in HAND_TIERS.items():
        if hand in hands:
            return tier
    return 10


def _normalize_hand(rank1: str, rank2: str, suited: bool) -> str:
    r1i, r2i = RANK_INDEX[rank1], RANK_INDEX[rank2]
    if r1i > r2i:
        high, low = rank1, rank2
    elif r1i < r2i:
        high, low = rank2, rank1
    else:
        return rank1 + rank2
    return high + low + ("s" if suited else "o")


POSITION_OPEN_TIERS = {
    "UTG":   4, "UTG+1": 4, "UTG+2": 5,
    "MP":    5, "MP+1":  6,
    "CO":    7, "BTN":   8,
    "SB":    7, "BB":    0,
}

STACK_DEPTH_ADJUSTMENTS = {
    "push_fold":  {"max_tier": 6, "description": "≤20bb push/fold"},
    "short":      {"max_tier": 7, "tier_shift": -1, "description": "20-40bb short"},
    "medium":     {"max_tier": 8, "tier_shift": 0, "description": "40-60bb medium"},
    "standard":   {"max_tier": 9, "tier_shift": 0, "description": "60-100bb standard"},
    "deep":       {"max_tier": 9, "tier_shift": 1, "description": "100-200bb deep"},
    "ultra_deep": {"max_tier": 9, "tier_shift": 1, "description": "200bb+ ultra deep"},
}


def get_stack_category(effective_bb: float) -> str:
    if effective_bb <= 20:
        return "push_fold"
    elif effective_bb <= 40:
        return "short"
    elif effective_bb <= 60:
        return "medium"
    elif effective_bb <= 100:
        return "standard"
    elif effective_bb <= 200:
        return "deep"
    return "ultra_deep"


PUSH_FOLD_RANGES = {
    "UTG":  3, "UTG+1": 3, "UTG+2": 4,
    "MP":   4, "MP+1":  4,
    "CO":   5, "BTN":   6,
    "SB":   7, "BB":    0,
}

THREE_BET_TIERS = {
    "UTG": 1, "UTG+1": 1, "UTG+2": 2,
    "MP": 2, "MP+1": 2,
    "CO": 3, "BTN": 4,
    "SB": 4, "BB": 4,
}

CALL_OPEN_TIERS = {
    "UTG": 2, "UTG+1": 3, "UTG+2": 3,
    "MP": 4, "MP+1": 4,
    "CO": 5, "BTN": 6,
    "SB": 5, "BB": 7,
}


class PreflopAction:
    FOLD = "fold"
    OPEN = "open"
    CALL = "call"
    CHECK = "check"
    THREE_BET = "3bet"
    PUSH = "push"


def _short_handed_boost(num_players: int) -> int:
    """Widen opening ranges for short-handed tables (fewer players = less risk)."""
    if num_players <= 3:
        return 3
    elif num_players <= 4:
        return 2
    elif num_players <= 6:
        return 1
    return 0


def get_preflop_advice(
    hand: str,
    position: str,
    effective_bb: float,
    facing_raise: bool = False,
    facing_3bet: bool = False,
    num_limpers: int = 0,
    num_players: int = 9,
) -> tuple[str, float]:
    tier = _hand_tier(hand)
    stack_cat = get_stack_category(effective_bb)
    sh_boost = _short_handed_boost(num_players)

    if stack_cat == "push_fold":
        max_tier = PUSH_FOLD_RANGES.get(position, 4) + sh_boost
        if tier <= max_tier:
            return PreflopAction.PUSH, 0.9
        return PreflopAction.FOLD, 0.9

    if facing_3bet:
        if tier == 1:
            return PreflopAction.THREE_BET, 0.7
        if tier <= 2 + (sh_boost // 2):
            return PreflopAction.CALL, 0.8
        return PreflopAction.FOLD, 0.7

    if facing_raise:
        call_tier = CALL_OPEN_TIERS.get(position, 4) + sh_boost
        three_bet_tier = THREE_BET_TIERS.get(position, 2) + (sh_boost // 2)
        if tier <= three_bet_tier:
            return PreflopAction.THREE_BET, 0.75
        if tier <= call_tier:
            return PreflopAction.CALL, 0.7
        return PreflopAction.FOLD, 0.7

    open_tier = POSITION_OPEN_TIERS.get(position, 5) + sh_boost
    adj = STACK_DEPTH_ADJUSTMENTS.get(stack_cat, {})
    tier_shift = adj.get("tier_shift", 0)
    adjusted_open = min(open_tier + tier_shift, adj.get("max_tier", 9))

    if position == "BB" and not facing_raise:
        if tier <= 3 + (sh_boost // 2):
            return PreflopAction.OPEN, 0.75
        return PreflopAction.CHECK, 0.8

    if tier <= adjusted_open:
        return PreflopAction.OPEN, 0.8
    return PreflopAction.FOLD, 0.8


def hand_in_range(hand: str, max_tier: int) -> bool:
    return _hand_tier(hand) <= max_tier


def cards_to_hand(card1_rank: str, card2_rank: str, suited: bool) -> str:
    return _normalize_hand(card1_rank, card2_rank, suited)
