from __future__ import annotations

from env.game_state import GameState, Player
from env.board_texture import analyze_board, BoardTexture
from data.postflop_rules import HandStrength, PostflopAction
from engine.pot_odds import spr_from_state
from engine.street_planner import get_street_plan


def select_bet_size(
    game_state: GameState,
    hero: Player,
    strength: HandStrength,
    pot: int,
    is_value: bool = True,
) -> int:
    texture = analyze_board(game_state.board)
    plan = get_street_plan(game_state, hero.name, strength)
    base_ratio = plan.current_size

    if texture.is_dry:
        base_ratio = max(min(base_ratio, 0.40), 0.25)
    elif texture.is_wet:
        base_ratio = max(base_ratio, 0.66)

    if is_value and strength.value >= HandStrength.STRONG_MADE.value:
        base_ratio = max(base_ratio, 0.66)

    if not is_value:
        base_ratio = max(min(base_ratio, 0.75), 0.5)

    spr_val = spr_from_state(game_state, hero.name)
    if spr_val < 2 and strength.value >= HandStrength.STRONG_MADE.value:
        return hero.stack

    amount = int(pot * base_ratio)
    min_bet = max(game_state.big_blind, int(pot * 0.25)) if pot > 0 else game_state.big_blind
    amount = max(amount, min_bet)
    return min(amount, hero.stack)


def select_raise_size(
    game_state: GameState,
    hero: Player,
    strength: HandStrength,
    facing_bet: int,
    pot: int,
) -> int:
    if strength.value >= HandStrength.MONSTER.value:
        multiplier = 3.0
    elif strength.value >= HandStrength.STRONG_MADE.value:
        multiplier = 2.5
    else:
        multiplier = 2.2

    amount = int(facing_bet * multiplier)
    min_raise = game_state.get_min_raise()
    amount = max(amount, min_raise)
    return min(amount, hero.stack + hero.current_bet)


def preflop_open_size(game_state: GameState, hero: Player) -> int:
    bb = game_state.big_blind
    base = bb * 3
    limpers = sum(
        1 for p in game_state.players
        if p.current_bet == bb and p.name != hero.name and p.is_active
    )
    base += limpers * bb
    return min(base, hero.stack)


def preflop_3bet_size(game_state: GameState, hero: Player, is_ip: bool) -> int:
    facing = game_state.current_bet
    multiplier = 3.0 if is_ip else 3.5
    amount = int(facing * multiplier)
    return min(amount, hero.stack + hero.current_bet)


def preflop_4bet_size(game_state: GameState, hero: Player, is_ip: bool) -> int:
    facing = game_state.current_bet
    multiplier = 2.2 if is_ip else 2.5
    amount = int(facing * multiplier)
    return min(amount, hero.stack + hero.current_bet)
