from __future__ import annotations

from dataclasses import dataclass

from env.game_state import GameState, Player
from env.action_space import Street
from env.board_texture import analyze_board, BoardTexture
from engine.pot_odds import spr_from_state
from data.postflop_rules import HandStrength


@dataclass
class BetPlan:
    streets_remaining: int
    sizes: list[float]
    allow_overbet: bool = False

    @property
    def current_size(self) -> float:
        return self.sizes[0] if self.sizes else 0.5


def _streets_left(street: Street) -> int:
    if street == Street.FLOP:
        return 3
    elif street == Street.TURN:
        return 2
    elif street == Street.RIVER:
        return 1
    return 3


def plan_bet_geometry(spr_value: float, streets_remaining: int = 3) -> BetPlan:
    if spr_value < 1.5:
        return BetPlan(1, [1.0])
    elif spr_value < 4:
        if streets_remaining <= 1:
            return BetPlan(1, [1.0])
        s1 = (spr_value - 1) / spr_value
        return BetPlan(2, [s1, 1.0])
    elif spr_value < 8:
        if streets_remaining <= 1:
            return BetPlan(1, [0.75])
        elif streets_remaining == 2:
            per_street = spr_value / 2
            s = per_street / (1 + per_street)
            return BetPlan(2, [s, 1.0])
        per_street = spr_value / 3
        s = per_street / (1 + per_street)
        return BetPlan(3, [s, s * 1.1, 1.0])
    else:
        if streets_remaining <= 1:
            return BetPlan(1, [0.75], allow_overbet=True)
        elif streets_remaining == 2:
            return BetPlan(2, [0.66, 1.0], allow_overbet=True)
        return BetPlan(3, [0.75, 0.75, 1.0], allow_overbet=True)


def get_street_plan(
    game_state: GameState,
    hero_name: str,
    strength: HandStrength,
) -> BetPlan:
    current_spr = spr_from_state(game_state, hero_name)
    streets_remaining = _streets_left(game_state.street)
    plan = plan_bet_geometry(current_spr, streets_remaining)

    if strength.value <= HandStrength.WEAK_MADE.value:
        plan.sizes = [min(s * 0.7, 0.5) for s in plan.sizes]
        plan.allow_overbet = False

    return plan
