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
    9: ["K7o", "K6o", "K5o", "Q8o", "Q7o", "Q6o", "Q5o", "Q4s", "Q3s", "Q2s", "J6s", "J5s", "J8o", "J7o", "T6s", "T8o", "T7o", "98o", "87o", "95s", "84s", "74s", "64s", "53s", "43s"],
    10: ["K4o", "K3o", "K2o", "Q4o", "Q3o", "Q2o", "J6o", "J5o", "J4s", "J3s", "J2s", "T6o", "T5s", "T4s", "96o", "94s", "93s", "85o", "83s", "75o", "73s", "63s", "52s", "42s", "32s"],
    11: ["J4o", "J3o", "J2o", "T5o", "T4o", "T3o", "T2o", "95o", "94o", "93o", "92o", "84o", "83o", "82o", "74o", "73o", "72o", "64o", "63o", "62o", "54o", "53o", "52o", "43o", "42o", "32o"],
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
    "UTG":   5, "UTG+1": 5, "UTG+2": 6,
    "MP":    6, "MP+1":  7,
    "CO":    7, "BTN":   7,
    "SB":    6, "BB":    0,
}

STACK_DEPTH_ADJUSTMENTS = {
    "push_fold":  {"max_tier": 6, "description": "≤20bb push/fold"},
    "short":      {"max_tier": 7, "tier_shift": -1, "description": "20-40bb short"},
    "medium":     {"max_tier": 11, "tier_shift": 0, "description": "40-60bb medium"},
    "standard":   {"max_tier": 11, "tier_shift": 0, "description": "60-100bb standard"},
    "deep":       {"max_tier": 11, "tier_shift": 1, "description": "100-200bb deep"},
    "ultra_deep": {"max_tier": 11, "tier_shift": 1, "description": "200bb+ ultra deep"},
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
    "UTG": 2, "UTG+1": 2, "UTG+2": 2,
    "MP": 3, "MP+1": 3,
    "CO": 4, "BTN": 5,
    "SB": 5, "BB": 5,
}

CALL_OPEN_TIERS = {
    "UTG": 3, "UTG+1": 3, "UTG+2": 4,
    "MP": 5, "MP+1": 5,
    "CO": 6, "BTN": 7,
    "SB": 6, "BB": 9,
}


class PreflopAction:
    FOLD = "fold"
    OPEN = "open"
    CALL = "call"
    CHECK = "check"
    THREE_BET = "3bet"
    FOUR_BET = "4bet"
    PUSH = "push"


def _short_handed_boost(num_players: int) -> int:
    """Widen opening ranges for short-handed tables (fewer players = less risk)."""
    if num_players <= 2:
        return 4
    elif num_players <= 3:
        return 2
    elif num_players <= 4:
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
        stack_cat = get_stack_category(effective_bb)
        if stack_cat == "push_fold":
            if tier <= 2 + (sh_boost // 2):
                return PreflopAction.PUSH, 0.9
            return PreflopAction.FOLD, 0.8
        if tier == 1:
            if effective_bb <= 40:
                return PreflopAction.PUSH, 0.85
            return PreflopAction.FOUR_BET, 0.8
        if tier <= 2 + (sh_boost // 2):
            if effective_bb <= 40:
                return PreflopAction.PUSH, 0.75
            return PreflopAction.CALL, 0.8
        return PreflopAction.FOLD, 0.7

    if facing_raise:
        call_tier = CALL_OPEN_TIERS.get(position, 4) + sh_boost
        three_bet_tier = THREE_BET_TIERS.get(position, 2) + (sh_boost // 2)
        is_small_pair = len(hand) == 2 and hand[0] == hand[1] and RANK_INDEX[hand[0]] <= RANK_INDEX["6"]
        if tier <= three_bet_tier and not is_small_pair:
            return PreflopAction.THREE_BET, 0.75
        if tier <= call_tier:
            return PreflopAction.CALL, 0.7
        return PreflopAction.FOLD, 0.7

    open_tier = POSITION_OPEN_TIERS.get(position, 5) + sh_boost
    adj = STACK_DEPTH_ADJUSTMENTS.get(stack_cat, {})
    tier_shift = adj.get("tier_shift", 0)
    max_tier = adj.get("max_tier", 9)
    if num_players <= 2:
        max_tier = 11
    adjusted_open = min(open_tier + tier_shift, max_tier)

    if position == "BB" and not facing_raise:
        raise_tier = 3 + (sh_boost // 2)
        if num_players <= 2:
            raise_tier = 7
        if tier <= raise_tier:
            return PreflopAction.OPEN, 0.75
        return PreflopAction.CHECK, 0.8

    if tier <= adjusted_open:
        return PreflopAction.OPEN, 0.8
    return PreflopAction.FOLD, 0.8


def hand_in_range(hand: str, max_tier: int) -> bool:
    return _hand_tier(hand) <= max_tier


def cards_to_hand(card1_rank: str, card2_rank: str, suited: bool) -> str:
    return _normalize_hand(card1_rank, card2_rank, suited)
