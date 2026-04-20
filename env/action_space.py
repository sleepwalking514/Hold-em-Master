from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class GameMode(Enum):
    LIVE = "live"
    TEST = "test"


class Street(Enum):
    PREFLOP = auto()
    FLOP = auto()
    TURN = auto()
    RIVER = auto()


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"


@dataclass
class PlayerAction:
    player_name: str
    action_type: ActionType
    amount: int = 0
    street: Street = Street.PREFLOP
    is_all_in: bool = False

    def __str__(self) -> str:
        if self.action_type in (ActionType.FOLD, ActionType.CHECK):
            return f"{self.player_name}: {self.action_type.value}"
        return f"{self.player_name}: {self.action_type.value} {self.amount}"


POSITIONS_BY_SIZE = {
    2: ["SB", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "UTG"],
    5: ["BTN", "SB", "BB", "UTG", "CO"],
    6: ["BTN", "SB", "BB", "UTG", "MP", "CO"],
    7: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "CO"],
    8: ["BTN", "SB", "BB", "UTG", "UTG+1", "MP", "MP+1", "CO"],
    9: ["BTN", "SB", "BB", "UTG", "UTG+1", "UTG+2", "MP", "MP+1", "CO"],
}
