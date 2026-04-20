from __future__ import annotations

import random
from typing import Optional

from treys import Card

from ui.card_parser import ALL_CARDS


class SimDealer:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        self._deck: list[int] = []
        self._dealt: set[int] = set()

    def new_hand(self) -> None:
        self._deck = list(ALL_CARDS)
        self._rng.shuffle(self._deck)
        self._dealt = set()

    def deal_hole_cards(self, num_players: int) -> list[list[int]]:
        hands = []
        for _ in range(num_players):
            c1 = self._draw()
            c2 = self._draw()
            hands.append([c1, c2])
        return hands

    def deal_flop(self) -> list[int]:
        self._draw()  # burn
        return [self._draw() for _ in range(3)]

    def deal_turn(self) -> int:
        self._draw()  # burn
        return self._draw()

    def deal_river(self) -> int:
        self._draw()  # burn
        return self._draw()

    def _draw(self) -> int:
        card = self._deck.pop()
        self._dealt.add(card)
        return card

    @property
    def dealt_cards(self) -> set[int]:
        return self._dealt.copy()

    @property
    def remaining(self) -> int:
        return len(self._deck)
