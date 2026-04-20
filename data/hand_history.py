from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from env.game_state import GameState, Player
from env.action_space import PlayerAction, Street
from ui.card_parser import card_to_short

HISTORY_DIR = Path(__file__).parent / "hands"


def _card_strs(cards: list[int]) -> list[str]:
    return [card_to_short(c) for c in cards]


def export_hand(gs: GameState, winnings: dict[str, int]) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    hand: dict[str, Any] = {
        "hand_id": gs.hand_number,
        "timestamp": datetime.now().isoformat(),
        "blinds": [gs.small_blind, gs.big_blind],
        "players": [],
        "board": _card_strs(gs.board),
        "actions": [],
        "winnings": {k: v for k, v in winnings.items() if v != 0},
    }

    for p in gs.players:
        pd: dict[str, Any] = {
            "name": p.name,
            "position": p.position,
            "stack": p.initial_stack if p.initial_stack > 0 else p.stack,
        }
        if p.hole_cards:
            pd["hole_cards"] = _card_strs(p.hole_cards)
        hand["players"].append(pd)

    for street in Street:
        for action in gs.action_history.get(street, []):
            ad: dict[str, Any] = {
                "street": street.name.lower(),
                "player": action.player_name,
                "action": action.action_type.value,
            }
            if action.amount:
                ad["amount"] = action.amount
            hand["actions"].append(ad)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = HISTORY_DIR / f"hand_{gs.hand_number}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hand, f, indent=2, ensure_ascii=False)

    return path
