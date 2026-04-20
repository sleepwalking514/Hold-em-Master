from __future__ import annotations

import random
import re
from treys import Card

VALID_RANKS = set("23456789TJQKAtjqka")
VALID_SUITS = set("shdc")
SUIT_SYMBOLS = {"s": "\u2660", "h": "\u2665", "d": "\u2666", "c": "\u2663"}
SUIT_FROM_SYMBOL = {v: k for k, v in SUIT_SYMBOLS.items()}

_CARD_PATTERN = re.compile(r"([2-9TJQKAtjqka])([shdc\u2660\u2665\u2666\u2663])")

ALL_CARDS = [Card.new(r + s) for r in "23456789TJQKA" for s in "shdc"]


def parse_card(text: str) -> int:
    text = text.strip()
    for symbol, letter in SUIT_FROM_SYMBOL.items():
        text = text.replace(symbol, letter)
    text = text[0].upper() + text[1:].lower() if len(text) == 2 else text
    m = _CARD_PATTERN.match(text)
    if not m:
        raise ValueError(f"Invalid card: {text}")
    rank, suit = m.group(1).upper(), m.group(2).lower()
    return Card.new(rank + suit)


def parse_cards(text: str) -> list[int]:
    text = text.strip()
    tokens = text.split()
    if len(tokens) == 1 and len(text) >= 4:
        tokens = [text[i:i+2] for i in range(0, len(text), 2)]
    return [parse_card(t) for t in tokens]


def card_to_str(card: int) -> str:
    return Card.int_to_pretty_str(card)


def card_to_short(card: int) -> str:
    return Card.int_to_str(card)


def validate_no_duplicates(cards: list[int], used: set[int] | None = None) -> None:
    seen = set(used) if used else set()
    for c in cards:
        if c in seen:
            raise ValueError(f"Duplicate card: {card_to_short(c)}")
        seen.add(c)


def random_cards(count: int, used: set[int]) -> list[int]:
    available = [c for c in ALL_CARDS if c not in used]
    return random.sample(available, count)
