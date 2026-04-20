from __future__ import annotations

from env.game_state import GameState, Player
from env.action_space import Street, ActionType
from engine.equity_calculator import monte_carlo_equity
from engine.pot_odds import pot_odds, call_ev, spr_from_state
from engine.gto_baseline import get_baseline_advice
from engine.bet_sizing import (
    select_bet_size, select_raise_size, preflop_open_size, preflop_3bet_size,
    preflop_4bet_size,
)
from engine.street_planner import get_street_plan
from engine.reasoning import format_advice, build_reasons, ACTION_NAMES
from engine.exploit_rules import ExploitEngine, ExploitAdjustment
from engine.multiway_strategy import analyze_multiway, should_bluff_multiway
from engine.range_equity import equity_vs_range, multiway_equity
from data.postflop_rules import HandStrength, classify_hand_strength
from data.preflop_ranges import PreflopAction
from data.exploit_config import continuous_exploit, blend_weight, BASELINE
from profiler.player_profile import PlayerProfile
from profiler.hand_range_estimator import HandRangeEstimator, HandRangeMatrix
from profiler.style_labeler import classify_style
from profiler.anti_misjudgment import AntiMisjudgment


class Advisor:
    def __init__(self) -> None:
        self.profiles: dict[str, PlayerProfile] = {}
        self.exploit_engine = ExploitEngine()
        self.anti_misjudgment = AntiMisjudgment()
        self._range_estimators: dict[str, HandRangeEstimator] = {}

    def set_profiles(self, profiles: dict[str, PlayerProfile]) -> None:
        self.profiles = profiles

    def reset_hand(self) -> None:
        self._range_estimators.clear()

    def get_advice(
        self, game_state: GameState, hero: Player,
    ) -> dict:
        baseline = get_baseline_advice(game_state, hero)
        num_opponents = len(game_state.players_in_hand) - 1

        equity = None
        range_equity_val = None
        if hero.hole_cards and len(hero.hole_cards) == 2:
            equity = monte_carlo_equity(
                hero.hole_cards, game_state.board,
                num_opponents=max(num_opponents, 1),
                num_simulations=5000,
                used_cards=game_state.used_cards,
            )
            range_equity_val = self._compute_range_equity(game_state, hero)

        effective_equity = equity
        if range_equity_val is not None and equity is not None:
            opponents = [p for p in game_state.players_in_hand if p.name != hero.name]
            range_confidence = self._range_confidence(opponents)
            effective_equity = range_equity_val * range_confidence + equity * (1 - range_confidence)
        elif range_equity_val is not None:
            effective_equity = range_equity_val

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
        hand_strength = baseline.get("hand_strength") if game_state.street != Street.PREFLOP else None
        exploit_adjustments = self._get_exploit_adjustments(game_state, hero, hand_strength)

        multiway_note = None
        if num_opponents >= 2 and effective_equity is not None:
            multiway_note = self._analyze_multiway(game_state, hero, effective_equity)

        if game_state.street == Street.PREFLOP:
            action, amount, confidence = self._resolve_preflop(
                game_state, hero, baseline, effective_equity, pot_odds_val,
                exploit_adjustments,
            )
        else:
            action, amount, confidence = self._resolve_postflop(
                game_state, hero, baseline, effective_equity, pot_odds_val,
                exploit_adjustments,
            )

        opp_summary = self._opponent_summary(game_state, hero)
        reasons = build_reasons(
            baseline, effective_equity, pot_odds_val, opp_summary, exploit_note,
        )
        if multiway_note:
            reasons.append(multiway_note)

        if action in (ActionType.BET, ActionType.RAISE) and amount == 0:
            action = ActionType.CHECK

        advice_text = format_advice(action, amount, confidence, reasons, alternatives)

        return {
            "action": action,
            "amount": amount,
            "confidence": confidence,
            "equity": effective_equity,
            "raw_equity": equity,
            "range_equity": range_equity_val,
            "text": advice_text,
            "baseline": baseline,
            "exploit_note": exploit_note,
            "multiway_note": multiway_note,
        }

    def _get_exploit_adjustments(
        self, gs: GameState, hero: Player,
        hand_strength: HandStrength | None = None,
    ) -> dict:
        """Compute actionable exploit adjustments using the ExploitEngine."""
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

        from engine.gto_baseline import _hero_position_is_ip
        from env.board_texture import analyze_board
        hero_is_ip = _hero_position_is_ip(gs, hero.name)

        board_wetness = 0.5
        if gs.board:
            board_wetness = analyze_board(gs.board).wetness
        street_name = gs.street.name.lower() if gs.street else "flop"
        hs_value = hand_strength.value if hand_strength else None

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

            suppress, _ = self.anti_misjudgment.should_suppress_exploit(opp.name, profile)
            if suppress:
                continue

            modifier = self.anti_misjudgment.get_exploit_modifier(opp.name, profile)
            action_adj = self.exploit_engine.get_action_adjustments(
                profile, hero_is_ip, hs_value, board_wetness, street_name,
            )

            if action_adj["value_freq_adj"] * modifier > 0.05:
                adjustments["widen_value"] = True
                adjustments["increase_sizing"] = True
            if action_adj["bluff_freq_adj"] * modifier > 0.05:
                adjustments["increase_bluff"] = True
            if action_adj["call_freq_adj"] * modifier > 0.05:
                if hand_strength is None or hand_strength.value >= HandStrength.WEAK_MADE.value:
                    adjustments["call_more"] = True
            if action_adj["fold_freq_adj"] * modifier > 0.05:
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

        not_facing_raise = gs.current_bet <= hero.current_bet

        if hero.position == "BB" and not_facing_raise and action == ActionType.FOLD:
            return ActionType.CHECK, 0, 0.8

        if action == ActionType.ALL_IN:
            return ActionType.ALL_IN, hero.stack + hero.current_bet, confidence

        if action == ActionType.FOLD:
            hand_str = baseline.get("hand", "")
            from data.preflop_ranges import _hand_tier
            tier = _hand_tier(hand_str) if hand_str else 10
            if tier <= 8 and equity and pot_odds_val and equity > pot_odds_val * 1.2:
                return ActionType.CALL, gs.current_bet, 0.55
            if tier <= 7 and exploit and exploit.get("call_more") and equity and equity > 0.35:
                return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            if equity and pot_odds_val and equity < pot_odds_val * 0.8:
                return ActionType.FOLD, 0, 0.60
            if exploit and exploit.get("increase_bluff") and equity and equity > 0.40:
                from engine.gto_baseline import _hero_position_is_ip
                is_ip = _hero_position_is_ip(gs, hero.name)
                amt = preflop_3bet_size(gs, hero, is_ip)
                return ActionType.RAISE, amt, 0.60
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.RAISE:
            if preflop_action in (PreflopAction.THREE_BET, PreflopAction.FOUR_BET):
                from engine.gto_baseline import _hero_position_is_ip
                is_ip = _hero_position_is_ip(gs, hero.name)
                if preflop_action == PreflopAction.FOUR_BET:
                    amt = preflop_4bet_size(gs, hero, is_ip)
                else:
                    amt = preflop_3bet_size(gs, hero, is_ip)
            else:
                amt = preflop_open_size(gs, hero)
            return ActionType.RAISE, amt, confidence

        return action, 0, confidence

    def _min_call_equity(self, street: Street) -> float:
        """Minimum equity required to call on each street — hard floor."""
        if street == Street.RIVER:
            return 0.33
        elif street == Street.TURN:
            return 0.40
        return 0.30

    def _implied_pot_odds(
        self, gs: GameState, hero: Player, strength: HandStrength,
    ) -> float | None:
        """On flop/turn with draws, reduce effective pot odds via implied odds."""
        if gs.street == Street.RIVER:
            return None
        if strength.value > HandStrength.STRONG_DRAW.value:
            return None
        if strength.value < HandStrength.MEDIUM_DRAW.value:
            return None

        call_amount = gs.current_bet - hero.current_bet
        if call_amount <= 0:
            return None

        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return None
        min_opp_stack = min(p.stack for p in opponents)
        implied_winnings = int(min(min_opp_stack * 0.4, gs.pot * 1.5))

        from engine.pot_odds import implied_odds as calc_implied
        return calc_implied(call_amount, gs.pot, implied_winnings)

    def _resolve_postflop(
        self, gs: GameState, hero: Player, baseline: dict,
        equity: float | None, pot_odds_val: float | None,
        exploit: dict | None = None,
    ) -> tuple[ActionType, int, float]:
        action = baseline["action"]
        confidence = baseline["confidence"]
        strength = baseline.get("hand_strength", HandStrength.WEAK_MADE)
        min_eq = self._min_call_equity(gs.street)

        effective_pot_odds = pot_odds_val
        implied = self._implied_pot_odds(gs, hero, strength)
        if implied is not None and pot_odds_val is not None:
            effective_pot_odds = implied

        if action == ActionType.FOLD:
            if equity and effective_pot_odds and equity > effective_pot_odds and equity >= min_eq:
                return ActionType.CALL, gs.current_bet, 0.55
            if (exploit and exploit.get("call_more") and equity
                    and effective_pot_odds and equity > effective_pot_odds * 0.85
                    and equity >= min_eq
                    and strength.value >= HandStrength.WEAK_MADE.value):
                return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            if equity and equity < min_eq:
                return ActionType.FOLD, 0, 0.65
            if equity and effective_pot_odds and equity < effective_pot_odds * 0.8:
                return ActionType.FOLD, 0, 0.60
            if (equity and equity > 0.70
                    and strength.value >= HandStrength.STRONG_MADE.value):
                facing = gs.current_bet
                amt = select_raise_size(gs, hero, strength, facing, gs.pot)
                return ActionType.RAISE, amt, 0.65
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.CHECK:
            if self._should_cbet(gs, hero, equity, strength):
                is_value = strength.value >= HandStrength.MEDIUM_MADE.value
                amt = select_bet_size(gs, hero, strength, gs.pot, is_value)
                return ActionType.BET, amt, 0.65
            if equity and equity > 0.55 and strength.value >= HandStrength.MEDIUM_MADE.value:
                amt = select_bet_size(gs, hero, strength, gs.pot, True)
                return ActionType.BET, amt, 0.60
            if (exploit and exploit.get("increase_bluff")
                    and equity and equity > 0.25
                    and strength.value <= HandStrength.WEAK_DRAW.value):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.55
            return ActionType.CHECK, 0, confidence

        if action == ActionType.BET:
            is_value = strength.value >= HandStrength.MEDIUM_MADE.value
            amt = select_bet_size(gs, hero, strength, gs.pot, is_value)
            if equity and equity > 0.70 and is_value:
                amt = max(amt, int(gs.pot * 0.75))
                amt = min(amt, hero.stack)
            if exploit and exploit.get("increase_sizing") and is_value:
                amt = min(int(amt * 1.3), hero.stack)
            return ActionType.BET, amt, confidence

        if action == ActionType.RAISE:
            facing = gs.current_bet
            amt = select_raise_size(gs, hero, strength, facing, gs.pot)
            return ActionType.RAISE, amt, confidence

        return action, 0, confidence

    def _should_cbet(
        self, gs: GameState, hero: Player,
        equity: float | None, strength: HandStrength,
    ) -> bool:
        if gs.street != Street.FLOP:
            return False
        preflop_actions = gs.action_history.get(Street.PREFLOP, [])
        hero_was_aggressor = any(
            a.player_name == hero.name and a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
            for a in preflop_actions
        )
        if not hero_was_aggressor:
            return False
        if strength.value >= HandStrength.WEAK_MADE.value:
            return True
        if equity and equity > 0.40:
            return True
        if strength.value >= HandStrength.STRONG_DRAW.value:
            return True
        return False

    def _opponent_summary(self, gs: GameState, hero: Player) -> str | None:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        summaries = []
        for opp in opponents:
            if opp.name in self.profiles:
                profile = self.profiles[opp.name]
                label = classify_style(profile)
                tilt = self.anti_misjudgment.detect_tilt(opp.name, profile)
                base = profile.summary()
                if tilt.is_tilting:
                    base += f" [TILT:{tilt.tilt_confidence:.0%}]"
                if label.secondary:
                    base += f" ({label.secondary})"
                summaries.append(base)
        return "; ".join(summaries) if summaries else None

    def _range_confidence(self, opponents: list[Player]) -> float:
        if not opponents:
            return 0.0
        confidences = []
        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile is None:
                confidences.append(0.0)
                continue
            avg_conf = sum(
                profile.get_confidence(s)
                for s in ("vpip", "pfr", "aggression_freq", "fold_to_cbet")
            ) / 4
            confidences.append(min(avg_conf, 1.0))
        return sum(confidences) / len(confidences) if confidences else 0.0

    def _compute_exploit(self, gs: GameState, hero: Player) -> tuple[str | None, float]:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return None, 0.0

        from engine.gto_baseline import _hero_position_is_ip
        hero_is_ip = _hero_position_is_ip(gs, hero.name)

        best_note = None
        max_magnitude = 0.0

        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile is None:
                continue

            suppress, reason = self.anti_misjudgment.should_suppress_exploit(opp.name, profile)
            if suppress:
                best_note = f"{opp.name}: {reason}"
                continue

            modifier = self.anti_misjudgment.get_exploit_modifier(opp.name, profile)
            top_exploits = self.exploit_engine.top_exploits(profile, hero_is_ip, 2)

            for adj in top_exploits:
                effective_mag = abs(adj.magnitude) * modifier
                if effective_mag > max_magnitude:
                    max_magnitude = effective_mag
                    best_note = f"{opp.name}: {adj.detail}"

        return best_note, max_magnitude

    def _compute_range_equity(self, gs: GameState, hero: Player) -> float | None:
        if not gs.board or len(gs.board) < 3:
            return None

        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        ranges = []
        for opp in opponents:
            if opp.name in self._range_estimators:
                est = self._range_estimators[opp.name]
                if est.range_matrix is not None:
                    ranges.append(est.range_matrix)

        if not ranges:
            return None

        if len(ranges) == 1:
            return equity_vs_range(hero.hole_cards, gs.board, ranges[0], 3000)
        else:
            return multiway_equity(hero.hole_cards, gs.board, ranges, 2000)

    def _analyze_multiway(
        self, gs: GameState, hero: Player, equity: float
    ) -> str | None:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        opp_profiles = []
        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile:
                opp_profiles.append((opp.name, profile))

        if len(opp_profiles) < 2:
            return None

        street = gs.street.name.lower() if gs.street != Street.PREFLOP else "flop"
        analysis = analyze_multiway(opp_profiles, equity, gs.pot, street)
        return f"多人底池({analysis.num_opponents}人): {analysis.strategy_note}"

    def update_opponent_range(
        self, player_name: str, position: str, action: str,
        board: list[int] | None = None, bet_size: float = 0, pot_size: float = 0,
    ) -> None:
        profile = self.profiles.get(player_name)
        if profile is None:
            return

        if player_name not in self._range_estimators:
            self._range_estimators[player_name] = HandRangeEstimator(profile)

        est = self._range_estimators[player_name]
        if est.range_matrix is None:
            est.init_range(position, action)
        elif board and len(board) >= 3:
            est.update(board, action, bet_size, pot_size)
