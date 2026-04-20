from __future__ import annotations

from env.game_state import GameState, Player
from env.action_space import Street, ActionType
from engine.equity_calculator import monte_carlo_equity
from engine.pot_odds import pot_odds, call_ev, spr_from_state
from engine.gto_baseline import get_baseline_advice
from engine.bet_sizing import (
    select_bet_size, select_raise_size, preflop_open_size, preflop_3bet_size,
)
from engine.street_planner import get_street_plan
from engine.reasoning import format_advice, build_reasons, ACTION_NAMES
from data.postflop_rules import HandStrength, classify_hand_strength
from data.preflop_ranges import PreflopAction
from data.exploit_config import continuous_exploit, blend_weight, BASELINE
from profiler.player_profile import PlayerProfile


class Advisor:
    def __init__(self) -> None:
        self.profiles: dict[str, PlayerProfile] = {}

    def set_profiles(self, profiles: dict[str, PlayerProfile]) -> None:
        self.profiles = profiles

    def get_advice(
        self, game_state: GameState, hero: Player,
    ) -> dict:
        baseline = get_baseline_advice(game_state, hero)
        num_opponents = len(game_state.players_in_hand) - 1

        equity = None
        if hero.hole_cards and len(hero.hole_cards) == 2:
            equity = monte_carlo_equity(
                hero.hole_cards, game_state.board,
                num_opponents=max(num_opponents, 1),
                num_simulations=5000,
                used_cards=game_state.used_cards,
            )

        action = baseline["action"]
        confidence = baseline["confidence"]
        amount = 0
        reasons = []
        alternatives = []

        pot_odds_val = None
        if game_state.current_bet > hero.current_bet:
            call_amount = game_state.current_bet - hero.current_bet
            pot_odds_val = pot_odds(call_amount, game_state.pot)

        exploit_note, exploit_magnitude = self._compute_exploit(game_state, hero)
        exploit_adjustments = self._get_exploit_adjustments(game_state, hero)

        if game_state.street == Street.PREFLOP:
            action, amount, confidence = self._resolve_preflop(
                game_state, hero, baseline, equity, pot_odds_val,
                exploit_adjustments,
            )
        else:
            action, amount, confidence = self._resolve_postflop(
                game_state, hero, baseline, equity, pot_odds_val,
                exploit_adjustments,
            )

        opp_summary = self._opponent_summary(game_state, hero)
        reasons = build_reasons(
            baseline, equity, pot_odds_val, opp_summary, exploit_note,
        )

        if action in (ActionType.BET, ActionType.RAISE) and amount == 0:
            action = ActionType.CHECK

        advice_text = format_advice(action, amount, confidence, reasons, alternatives)

        return {
            "action": action,
            "amount": amount,
            "confidence": confidence,
            "equity": equity,
            "text": advice_text,
            "baseline": baseline,
            "exploit_note": exploit_note,
        }

    def _get_exploit_adjustments(self, gs: GameState, hero: Player) -> dict:
        """Compute actionable exploit adjustments based on opponent profiles."""
        adjustments = {
            "widen_value": False,
            "increase_bluff": False,
            "increase_sizing": False,
            "decrease_sizing": False,
            "fold_more": False,
            "call_more": False,
        }
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return adjustments

        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile is None:
                continue
            avg_conf = sum(
                profile.get_confidence(s)
                for s in ("vpip", "pfr", "aggression_freq", "fold_to_cbet")
            ) / 4
            if avg_conf < 0.12:
                continue

            vpip = profile.get_stat("vpip")
            aggr = profile.get_stat("aggression_freq")
            fold_cbet = profile.get_stat("fold_to_cbet")
            fold_3bet = profile.get_stat("fold_to_3bet")

            if vpip > 0.40 and aggr < 0.30:
                adjustments["widen_value"] = True
                adjustments["increase_sizing"] = True
            if fold_cbet > 0.60:
                adjustments["increase_bluff"] = True
            if fold_3bet > 0.65:
                adjustments["increase_bluff"] = True
            if aggr > 0.50:
                adjustments["call_more"] = True
            if vpip < 0.18 and aggr > 0.40:
                adjustments["fold_more"] = True

        return adjustments

    def _resolve_preflop(
        self, gs: GameState, hero: Player, baseline: dict,
        equity: float | None, pot_odds_val: float | None,
        exploit: dict | None = None,
    ) -> tuple[ActionType, int, float]:
        action = baseline["action"]
        confidence = baseline["confidence"]
        preflop_action = baseline.get("preflop_action", "")

        if action == ActionType.ALL_IN:
            return ActionType.ALL_IN, hero.stack + hero.current_bet, confidence

        if action == ActionType.FOLD:
            if equity and pot_odds_val and equity > pot_odds_val * 1.2:
                return ActionType.CALL, gs.current_bet, 0.55
            if exploit and exploit.get("call_more") and equity and equity > 0.35:
                return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            if exploit and exploit.get("increase_bluff") and equity and equity > 0.40:
                from engine.gto_baseline import _hero_position_is_ip
                is_ip = _hero_position_is_ip(gs, hero.name)
                amt = preflop_3bet_size(gs, hero, is_ip)
                return ActionType.RAISE, amt, 0.60
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.RAISE:
            if preflop_action == PreflopAction.THREE_BET:
                from engine.gto_baseline import _hero_position_is_ip
                is_ip = _hero_position_is_ip(gs, hero.name)
                amt = preflop_3bet_size(gs, hero, is_ip)
            else:
                amt = preflop_open_size(gs, hero)
            return ActionType.RAISE, amt, confidence

        return action, 0, confidence

    def _resolve_postflop(
        self, gs: GameState, hero: Player, baseline: dict,
        equity: float | None, pot_odds_val: float | None,
        exploit: dict | None = None,
    ) -> tuple[ActionType, int, float]:
        action = baseline["action"]
        confidence = baseline["confidence"]
        strength = baseline.get("hand_strength", HandStrength.WEAK_MADE)

        if action == ActionType.FOLD:
            if equity and pot_odds_val and equity > pot_odds_val:
                return ActionType.CALL, gs.current_bet, 0.55
            if exploit and exploit.get("call_more") and equity and equity > pot_odds_val * 0.85 if pot_odds_val else False:
                return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.CHECK:
            if (exploit and exploit.get("increase_bluff")
                    and equity and equity > 0.25
                    and strength.value <= HandStrength.WEAK_DRAW.value):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.55
            return ActionType.CHECK, 0, confidence

        if action == ActionType.BET:
            is_value = strength.value >= HandStrength.MEDIUM_MADE.value
            amt = select_bet_size(gs, hero, strength, gs.pot, is_value)
            if exploit and exploit.get("increase_sizing") and is_value:
                amt = min(int(amt * 1.3), hero.stack)
            return ActionType.BET, amt, confidence

        if action == ActionType.RAISE:
            facing = gs.current_bet
            amt = select_raise_size(gs, hero, strength, facing, gs.pot)
            return ActionType.RAISE, amt, confidence

        return action, 0, confidence

    def _opponent_summary(self, gs: GameState, hero: Player) -> str | None:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        summaries = []
        for opp in opponents:
            if opp.name in self.profiles:
                summaries.append(self.profiles[opp.name].summary())
        return "; ".join(summaries) if summaries else None

    def _compute_exploit(self, gs: GameState, hero: Player) -> tuple[str | None, float]:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return None, 0.0

        best_note = None
        max_magnitude = 0.0

        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile is None:
                continue
            avg_conf = sum(
                profile.get_confidence(s) for s in ("vpip", "pfr", "aggression_freq", "fold_to_cbet")
            ) / 4
            solid_w, exploit_w = blend_weight(avg_conf)
            if exploit_w < 0.06:
                continue

            notes = []
            for stat_key in BASELINE:
                stat_val = profile.get_stat(stat_key) if stat_key in profile.stats else None
                if stat_val is None:
                    continue
                exploit_val = continuous_exploit(stat_val, BASELINE[stat_key])
                if abs(exploit_val) > 0.05:
                    notes.append((stat_key, exploit_val))

            if notes:
                notes.sort(key=lambda x: abs(x[1]), reverse=True)
                top = notes[0]
                magnitude = abs(top[1]) * exploit_w
                if magnitude > max_magnitude:
                    max_magnitude = magnitude
                    direction = "↑" if top[1] > 0 else "↓"
                    best_note = f"{opp.name} {top[0]}偏离基线{direction} (exploit权重{exploit_w:.0%})"

        return best_note, max_magnitude
