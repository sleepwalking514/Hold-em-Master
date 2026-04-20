from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from env.action_space import ActionType, PlayerAction, Street
from env.board_texture import BoardTexture, analyze_board
from profiler.player_profile import PlayerProfile


@dataclass
class SizingTell:
    value_avg: float = 0.0
    bluff_avg: float = 0.0
    has_tell: bool = False
    confidence: float = 0.0

    @property
    def tell_gap(self) -> float:
        return abs(self.value_avg - self.bluff_avg)


@dataclass
class StreetAggressionProfile:
    flop_aggr: float = 0.0
    turn_aggr: float = 0.0
    river_aggr: float = 0.0
    gives_up_turn_rate: float = 0.0
    barrel_drop_off: float = 0.0

    @property
    def aggression_pattern(self) -> str:
        if self.barrel_drop_off > 0.3:
            return "one_and_done"
        if self.river_aggr > self.flop_aggr:
            return "river_heavy"
        if self.flop_aggr > 0.5 and self.turn_aggr > 0.4 and self.river_aggr > 0.3:
            return "relentless"
        return "balanced"


@dataclass
class TextureResponse:
    wet_board_cbet: float = 0.5
    dry_board_cbet: float = 0.5
    scare_card_shutdown: float = 0.0
    wet_board_samples: int = 0
    dry_board_samples: int = 0


@dataclass
class PatternAnalysis:
    sizing_tell: SizingTell = field(default_factory=SizingTell)
    street_aggression: StreetAggressionProfile = field(default_factory=StreetAggressionProfile)
    texture_response: TextureResponse = field(default_factory=TextureResponse)


class PatternAnalyzer:
    def __init__(self):
        self._sizing_history: dict[str, list[tuple[float, bool]]] = {}
        self._street_actions: dict[str, dict[Street, list[bool]]] = {}
        self._texture_cbets: dict[str, list[tuple[bool, bool]]] = {}
        self._scare_card_events: dict[str, list[bool]] = {}

    def record_bet(
        self, player_name: str, bet_ratio: float, is_value: Optional[bool] = None
    ) -> None:
        if player_name not in self._sizing_history:
            self._sizing_history[player_name] = []
        history = self._sizing_history[player_name]
        if is_value is not None:
            history.append((bet_ratio, is_value))
            if len(history) > 60:
                history.pop(0)

    def record_street_action(
        self, player_name: str, street: Street, is_aggressive: bool
    ) -> None:
        if player_name not in self._street_actions:
            self._street_actions[player_name] = {}
        actions = self._street_actions[player_name]
        if street not in actions:
            actions[street] = []
        actions[street].append(is_aggressive)
        if len(actions[street]) > 100:
            actions[street].pop(0)

    def record_cbet(
        self, player_name: str, did_cbet: bool, board_is_wet: bool
    ) -> None:
        if player_name not in self._texture_cbets:
            self._texture_cbets[player_name] = []
        self._texture_cbets[player_name].append((did_cbet, board_is_wet))
        if len(self._texture_cbets[player_name]) > 60:
            self._texture_cbets[player_name].pop(0)

    def record_scare_card_reaction(
        self, player_name: str, shut_down: bool
    ) -> None:
        if player_name not in self._scare_card_events:
            self._scare_card_events[player_name] = []
        self._scare_card_events[player_name].append(shut_down)
        if len(self._scare_card_events[player_name]) > 30:
            self._scare_card_events[player_name].pop(0)

    def analyze(self, player_name: str) -> PatternAnalysis:
        return PatternAnalysis(
            sizing_tell=self._detect_sizing_tell(player_name),
            street_aggression=self._compute_street_aggression(player_name),
            texture_response=self._compute_texture_response(player_name),
        )

    def _detect_sizing_tell(self, player_name: str) -> SizingTell:
        history = self._sizing_history.get(player_name, [])
        if len(history) < 10:
            return SizingTell()

        value_sizes = [r for r, is_val in history if is_val]
        bluff_sizes = [r for r, is_val in history if not is_val]

        if len(value_sizes) < 3 or len(bluff_sizes) < 3:
            return SizingTell()

        val_avg = sum(value_sizes) / len(value_sizes)
        bluff_avg = sum(bluff_sizes) / len(bluff_sizes)
        gap = abs(val_avg - bluff_avg)
        n = min(len(value_sizes), len(bluff_sizes))
        conf = 1 - 1 / (1 + n ** 0.5)

        return SizingTell(
            value_avg=val_avg,
            bluff_avg=bluff_avg,
            has_tell=gap > 0.15 and conf > 0.4,
            confidence=conf,
        )

    def _compute_street_aggression(self, player_name: str) -> StreetAggressionProfile:
        actions = self._street_actions.get(player_name, {})

        def _rate(street: Street) -> float:
            data = actions.get(street, [])
            if not data:
                return 0.0
            return sum(data) / len(data)

        flop = _rate(Street.FLOP)
        turn = _rate(Street.TURN)
        river = _rate(Street.RIVER)
        drop_off = max(0.0, flop - river) if flop > 0 else 0.0

        gives_up = 0.0
        flop_data = actions.get(Street.FLOP, [])
        turn_data = actions.get(Street.TURN, [])
        if flop_data and turn_data and len(flop_data) == len(turn_data):
            pairs = list(zip(flop_data, turn_data))
            aggressive_flop = [(f, t) for f, t in pairs if f]
            if aggressive_flop:
                gives_up = sum(1 for _, t in aggressive_flop if not t) / len(aggressive_flop)

        return StreetAggressionProfile(
            flop_aggr=flop,
            turn_aggr=turn,
            river_aggr=river,
            gives_up_turn_rate=gives_up,
            barrel_drop_off=drop_off,
        )

    def _compute_texture_response(self, player_name: str) -> TextureResponse:
        cbets = self._texture_cbets.get(player_name, [])
        if not cbets:
            return TextureResponse()

        wet_cbets = [did for did, is_wet in cbets if is_wet]
        dry_cbets = [did for did, is_wet in cbets if not is_wet]

        wet_rate = sum(wet_cbets) / len(wet_cbets) if wet_cbets else 0.5
        dry_rate = sum(dry_cbets) / len(dry_cbets) if dry_cbets else 0.5

        scare_events = self._scare_card_events.get(player_name, [])
        scare_rate = sum(scare_events) / len(scare_events) if scare_events else 0.0

        return TextureResponse(
            wet_board_cbet=wet_rate,
            dry_board_cbet=dry_rate,
            scare_card_shutdown=scare_rate,
            wet_board_samples=len(wet_cbets),
            dry_board_samples=len(dry_cbets),
        )

    def to_dict(self) -> dict:
        return {
            "sizing_history": self._sizing_history,
            "street_actions": {
                p: {s.name: v for s, v in streets.items()}
                for p, streets in self._street_actions.items()
            },
            "texture_cbets": self._texture_cbets,
            "scare_card_events": self._scare_card_events,
        }

    @classmethod
    def from_dict(cls, d: dict) -> PatternAnalyzer:
        pa = cls()
        pa._sizing_history = d.get("sizing_history", {})
        raw_streets = d.get("street_actions", {})
        for p, streets in raw_streets.items():
            pa._street_actions[p] = {
                Street[k]: v for k, v in streets.items()
            }
        pa._texture_cbets = {
            k: [tuple(x) for x in v]
            for k, v in d.get("texture_cbets", {}).items()
        }
        pa._scare_card_events = d.get("scare_card_events", {})
        return pa
