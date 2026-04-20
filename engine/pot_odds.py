from __future__ import annotations

from env.game_state import GameState, Player


def pot_odds(call_amount: int, pot: int) -> float:
    if call_amount <= 0:
        return 0.0
    return call_amount / (pot + call_amount)


def implied_odds(call_amount: int, pot: int, expected_future_winnings: int) -> float:
    total = pot + call_amount + expected_future_winnings
    if total <= 0:
        return 0.0
    return call_amount / total


def effective_stack(hero: Player, villain: Player) -> int:
    return min(hero.stack + hero.current_bet, villain.stack + villain.current_bet)


def effective_stack_bb(hero: Player, villain: Player, big_blind: int) -> float:
    return effective_stack(hero, villain) / big_blind


def spr(effective_stk: int, pot: int) -> float:
    if pot <= 0:
        return float("inf")
    return effective_stk / pot


def spr_from_state(game_state: GameState, hero_name: str) -> float:
    hero = game_state.get_player(hero_name)
    opponents = [p for p in game_state.players_in_hand if p.name != hero_name]
    if not opponents:
        return float("inf")
    eff = min(effective_stack(hero, v) for v in opponents)
    remaining = eff - hero.current_bet
    return spr(remaining, game_state.pot)


def call_ev(equity: float, pot: int, call_amount: int) -> float:
    return equity * (pot + call_amount) - call_amount


def bet_ev(equity: float, pot: int, bet_amount: int, fold_equity: float) -> float:
    win_uncontested = fold_equity * pot
    win_called = (1 - fold_equity) * (equity * (pot + 2 * bet_amount) - bet_amount)
    return win_uncontested + win_called


def minimum_defense_frequency(bet_amount: int, pot: int) -> float:
    if pot + bet_amount <= 0:
        return 0.0
    return pot / (pot + bet_amount)
