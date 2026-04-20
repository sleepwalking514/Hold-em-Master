from __future__ import annotations

from dataclasses import dataclass
from treys import Card


RANK_ORDER = "23456789TJQKA"


def _rank(card: int) -> int:
    return Card.get_rank_int(card)


def _suit(card: int) -> int:
    return Card.get_suit_int(card)


@dataclass
class BoardTexture:
    is_paired: bool = False
    is_double_paired: bool = False
    is_trips_board: bool = False
    is_monotone: bool = False
    is_two_tone: bool = False
    is_rainbow: bool = False
    flush_draw_possible: bool = False
    straight_draw_possible: bool = False
    high_card_rank: int = 0
    connectedness: int = 0
    wetness: float = 0.0
    scare_cards: list[int] | None = None

    @property
    def is_dry(self) -> bool:
        return self.wetness < 0.3

    @property
    def is_wet(self) -> bool:
        return self.wetness >= 0.6


def analyze_board(board: list[int]) -> BoardTexture:
    if not board:
        return BoardTexture()

    tex = BoardTexture(scare_cards=[])
    ranks = sorted([_rank(c) for c in board], reverse=True)
    suits = [_suit(c) for c in board]
    tex.high_card_rank = ranks[0]

    rank_counts: dict[int, int] = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1

    pairs = sum(1 for c in rank_counts.values() if c >= 2)
    tex.is_paired = pairs >= 1
    tex.is_double_paired = pairs >= 2
    tex.is_trips_board = any(c >= 3 for c in rank_counts.values())

    suit_counts: dict[int, int] = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1

    max_suit = max(suit_counts.values())
    n_suits = len(suit_counts)
    tex.is_monotone = n_suits == 1 and len(board) >= 3
    tex.is_two_tone = max_suit >= 2 and not tex.is_monotone
    tex.is_rainbow = max_suit == 1
    tex.flush_draw_possible = max_suit >= 2

    unique_ranks = sorted(set(ranks))
    max_connected = 1
    current_run = 1
    for i in range(1, len(unique_ranks)):
        if unique_ranks[i] - unique_ranks[i - 1] <= 2:
            current_run += 1
            max_connected = max(max_connected, current_run)
        else:
            current_run = 1
    tex.connectedness = max_connected
    tex.straight_draw_possible = max_connected >= 2

    wetness = 0.0
    if tex.flush_draw_possible:
        wetness += 0.3
    if tex.is_monotone:
        wetness += 0.2
    if tex.straight_draw_possible:
        wetness += 0.2
    if tex.connectedness >= 3:
        wetness += 0.15
    if tex.is_paired:
        wetness -= 0.1
    tex.wetness = max(0.0, min(1.0, wetness))

    if len(board) >= 4:
        latest = board[-1]
        r = _rank(latest)
        if r >= 10 or _suit(latest) in [s for s, c in suit_counts.items() if c >= 2]:
            tex.scare_cards.append(latest)

    return tex
