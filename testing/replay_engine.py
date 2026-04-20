from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from env.game_state import GameState, Player
from env.action_space import ActionType, PlayerAction, Street
from ui.card_parser import parse_cards


ACTION_MAP = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "bet": ActionType.BET,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
    "allin": ActionType.ALL_IN,
}

STREET_MAP = {
    "preflop": Street.PREFLOP,
    "flop": Street.FLOP,
    "turn": Street.TURN,
    "river": Street.RIVER,
}


@dataclass
class DecisionPoint:
    hand_id: int
    street: Street
    player: str
    actual_action: PlayerAction
    suggested_action: PlayerAction | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayResult:
    hand_id: int
    decision_points: list[DecisionPoint] = field(default_factory=list)
    final_board: list[int] = field(default_factory=list)
    showdown_info: list[dict] = field(default_factory=list)
    winnings: dict[str, int] = field(default_factory=dict)


class ReplayEngine:
    def __init__(self, advisor=None) -> None:
        self.advisor = advisor
        self.results: list[ReplayResult] = []

    def replay_hand(self, hand_data: dict) -> ReplayResult:
        players = []
        for pd in hand_data["players"]:
            p = Player(name=pd["name"], position=pd.get("position", ""), stack=pd["stack"])
            if "hole_cards" in pd:
                p.hole_cards = parse_cards(" ".join(pd["hole_cards"]))
            players.append(p)

        blinds = hand_data.get("blinds", [5, 10])
        gs = GameState(players=players, small_blind=blinds[0], big_blind=blinds[1])
        gs.assign_positions()
        gs.post_blinds()

        result = ReplayResult(hand_id=hand_data.get("hand_id", 0))

        board_cards = []
        if "board" in hand_data:
            board_cards = parse_cards(" ".join(hand_data["board"]))

        current_street = Street.PREFLOP
        for action_data in hand_data.get("actions", []):
            street = STREET_MAP.get(action_data.get("street", "preflop"), Street.PREFLOP)

            while current_street != street:
                gs.advance_street()
                if street == Street.FLOP:
                    gs.board = board_cards[:3]
                elif street == Street.TURN:
                    gs.board = board_cards[:4]
                elif street == Street.RIVER:
                    gs.board = board_cards[:5]
                current_street = street

            action_type = ACTION_MAP.get(action_data["action"].lower(), ActionType.FOLD)
            amount = action_data.get("amount", 0)
            action = PlayerAction(
                player_name=action_data["player"],
                action_type=action_type,
                amount=amount,
                street=street,
            )

            dp = DecisionPoint(
                hand_id=result.hand_id,
                street=street,
                player=action_data["player"],
                actual_action=action,
            )

            if self.advisor:
                try:
                    suggested = self.advisor.get_suggestion(gs, action_data["player"])
                    dp.suggested_action = suggested
                except Exception:
                    pass

            result.decision_points.append(dp)
            gs.apply_action(action)

        if "showdown" in hand_data:
            for sd in hand_data["showdown"]:
                p = gs.get_player(sd["player"])
                p.hole_cards = parse_cards(" ".join(sd["hole_cards"]))
                result.showdown_info.append(sd)

        gs.board = board_cards[:5] if len(board_cards) >= 5 else board_cards
        result.final_board = gs.board
        result.winnings = gs.settle()

        self.results.append(result)
        return result

    def replay_file(self, path: str | Path) -> list[ReplayResult]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        hands = data if isinstance(data, list) else [data]
        return [self.replay_hand(h) for h in hands]

    def summary(self) -> str:
        lines = [f"回放完成: {len(self.results)} 手牌"]
        for r in self.results:
            lines.append(f"\n手牌 #{r.hand_id}:")
            lines.append(f"  决策点: {len(r.decision_points)}")
            for dp in r.decision_points:
                actual = f"{dp.actual_action.action_type.value}"
                if dp.actual_action.amount:
                    actual += f" {dp.actual_action.amount}"
                suggested = ""
                if dp.suggested_action:
                    suggested = f" | 建议: {dp.suggested_action.action_type.value}"
                    if dp.suggested_action.amount:
                        suggested += f" {dp.suggested_action.amount}"
                lines.append(f"    [{dp.street.name}] {dp.player}: {actual}{suggested}")
            if r.winnings:
                winners = {k: v for k, v in r.winnings.items() if v > 0}
                lines.append(f"  赢家: {winners}")
        return "\n".join(lines)
