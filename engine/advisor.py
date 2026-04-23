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
from engine.exploit_rules import ExploitEngine, ExploitAdjustment, ExploitCategory
from engine.multiway_strategy import analyze_multiway, should_bluff_multiway
from engine.range_equity import equity_vs_range, multiway_equity
from data.postflop_rules import HandStrength, classify_hand_strength
from data.preflop_ranges import PreflopAction
from data.exploit_config import continuous_exploit, blend_weight, BASELINE
from profiler.player_profile import PlayerProfile
from profiler.hand_range_estimator import HandRangeEstimator, HandRangeMatrix
from profiler.style_labeler import classify_style, get_exploit_priority
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

        if effective_equity is not None:
            opponents_list = [p for p in game_state.players_in_hand if p.name != hero.name]
            min_hands = min(
                (self.profiles[o.name].total_hands if o.name in self.profiles else 0)
                for o in opponents_list
            ) if opponents_list else 999
            if min_hands < 20:
                effective_equity = self._cold_start_discount(game_state, hero, effective_equity)

        if effective_equity is not None and game_state.street != Street.PREFLOP:
            effective_equity = self._action_sequence_discount(
                game_state, hero, effective_equity,
            )

        if effective_equity is not None and game_state.street == Street.PREFLOP:
            effective_equity = self._adjust_equity_vs_tight_allin(
                game_state, hero, effective_equity,
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
        hand_strength = baseline.get("hand_strength") if game_state.street != Street.PREFLOP else None
        exploit_adjustments = self._get_exploit_adjustments(game_state, hero, hand_strength)

        multiway_note = None
        if effective_equity is not None:
            multiway_note = self._analyze_multiway(game_state, hero, effective_equity)

        if game_state.street == Street.PREFLOP:
            action, amount, confidence = self._resolve_preflop(
                game_state, hero, baseline, effective_equity, pot_odds_val,
                exploit_adjustments, multiway_note,
            )
        else:
            action, amount, confidence = self._resolve_postflop(
                game_state, hero, baseline, effective_equity, pot_odds_val,
                exploit_adjustments, multiway_note,
            )

        opp_summary = self._opponent_summary(game_state, hero)
        reasons = build_reasons(
            baseline, effective_equity, pot_odds_val, opp_summary, exploit_note,
        )
        if multiway_note:
            note_suggests_passive = "控池" in multiway_note or "过牌/弃牌" in multiway_note
            action_is_aggressive = action in (ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN)
            if not (note_suggests_passive and action_is_aggressive):
                reasons.append(multiway_note)

        if action in (ActionType.BET, ActionType.RAISE) and amount == 0:
            action = ActionType.CHECK

        confidence = self._ev_based_confidence(
            action, effective_equity, pot_odds_val, confidence,
        )

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
        """Compute actionable exploit adjustments using the ExploitEngine + style labels."""
        adjustments = {
            "widen_value": False,
            "increase_bluff": False,
            "increase_sizing": False,
            "decrease_sizing": False,
            "fold_more": False,
            "call_more": False,
            "no_bluff": False,
            "style_labels": [],
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
            is_hu = len(gs.players) <= 2
            conf_threshold = 0.08 if is_hu else 0.20
            if avg_conf < conf_threshold:
                if is_hu and profile.prior_type and profile.prior_type != "未知":
                    self._apply_prior_exploit(adjustments, profile.prior_type)
                continue

            suppress, _ = self.anti_misjudgment.should_suppress_exploit(opp.name, profile)
            if suppress:
                continue

            modifier = self.anti_misjudgment.get_exploit_modifier(opp.name, profile)

            label = classify_style(profile, num_players=len(gs.players))
            style_priorities = get_exploit_priority(label)
            adjustments["style_labels"].append(label.primary)

            skill = profile.skill_estimate.overall_skill
            if skill > 0.7:
                modifier *= 0.5

            if style_priorities.get("no_bluff", 0) > 0.5:
                adjustments["no_bluff"] = True
            if style_priorities.get("value_heavy", 0) > 0.5:
                adjustments["widen_value"] = True
                adjustments["increase_sizing"] = True

            action_adj = self.exploit_engine.get_action_adjustments(
                profile, hero_is_ip, hs_value, board_wetness, street_name,
                num_players=len(gs.players),
            )

            if action_adj["value_freq_adj"] * modifier > 0.05:
                adjustments["widen_value"] = True
                adjustments["increase_sizing"] = True
            if action_adj["bluff_freq_adj"] * modifier > 0.05:
                if not adjustments["no_bluff"]:
                    adjustments["increase_bluff"] = True
            if action_adj["call_freq_adj"] * modifier > 0.05:
                if hand_strength is None or hand_strength.value >= HandStrength.MEDIUM_MADE.value:
                    adjustments["call_more"] = True
            if action_adj["fold_freq_adj"] * modifier > 0.05:
                adjustments["fold_more"] = True

            if label.primary == "Nit" and label.confidence > 0.3:
                adjustments["fold_more"] = True

        return adjustments

    @staticmethod
    def _apply_prior_exploit(adjustments: dict, prior_type: str) -> None:
        """Light exploit adjustments based on prior label before data converges."""
        if prior_type in ("极紧Nit",):
            adjustments["increase_bluff"] = True
            adjustments["fold_more"] = True
        elif prior_type in ("跟注站",):
            adjustments["widen_value"] = True
            adjustments["no_bluff"] = True
            adjustments["increase_sizing"] = True
        elif prior_type in ("松凶LAG", "疯子Maniac"):
            adjustments["call_more"] = True
        elif prior_type in ("紧凶TAG",):
            adjustments["fold_more"] = True

    def _resolve_preflop(
        self, gs: GameState, hero: Player, baseline: dict,
        equity: float | None, pot_odds_val: float | None,
        exploit: dict | None = None, multiway_note: str | None = None,
    ) -> tuple[ActionType, int, float]:
        action = baseline["action"]
        confidence = baseline["confidence"]
        preflop_action = baseline.get("preflop_action", "")

        pot_control = multiway_note is not None and "控池" in multiway_note

        not_facing_raise = gs.current_bet <= hero.current_bet
        is_hu = len(gs.players) <= 2

        if hero.position == "BB" and not_facing_raise and action == ActionType.FOLD:
            return ActionType.CHECK, 0, 0.8

        # SB raise-or-fold: never open-limp from SB
        if hero.position == "SB" and not_facing_raise and action == ActionType.CALL:
            hand_str = baseline.get("hand", "")
            from data.preflop_ranges import _hand_tier, HU_SB_OPEN_TIER
            tier = _hand_tier(hand_str) if hand_str else 10
            open_tier = HU_SB_OPEN_TIER if len(gs.players) <= 2 else 7
            if tier <= open_tier:
                amt = preflop_open_size(gs, hero)
                return ActionType.RAISE, amt, 0.70
            return ActionType.FOLD, 0, 0.65

        # HU SB open rescue: baseline may fold hands that should be opened heads-up
        if (is_hu and hero.position == "SB" and not_facing_raise
                and action == ActionType.FOLD):
            hand_str = baseline.get("hand", "")
            from data.preflop_ranges import _hand_tier, HU_SB_OPEN_TIER
            tier = _hand_tier(hand_str) if hand_str else 10
            if tier <= HU_SB_OPEN_TIER:
                amt = preflop_open_size(gs, hero)
                return ActionType.RAISE, amt, 0.65

        if action == ActionType.ALL_IN:
            return ActionType.ALL_IN, hero.stack + hero.current_bet, confidence

        if action == ActionType.FOLD:
            hand_str = baseline.get("hand", "")
            from data.preflop_ranges import _hand_tier
            tier = _hand_tier(hand_str) if hand_str else 10
            eq_mult = 1.4 if pot_control else 1.2

            preflop_raise_count = sum(
                1 for a in gs.action_history.get(Street.PREFLOP, [])
                if a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                and a.player_name != hero.name
            )

            # BB special defense: widen call range facing single raise
            if hero.position == "BB" and preflop_raise_count == 1:
                call_amount = gs.current_bet - hero.current_bet
                if call_amount > 0 and gs.pot > 0:
                    bb_pot_odds = call_amount / (gs.pot + call_amount)
                    if is_hu:
                        from data.preflop_ranges import HU_BB_DEFEND_TIER, HU_BB_3BET_TIER
                        if tier <= HU_BB_3BET_TIER and equity and equity > 0.40:
                            from engine.gto_baseline import _hero_position_is_ip
                            is_ip = _hero_position_is_ip(gs, hero.name)
                            amt = preflop_3bet_size(gs, hero, is_ip)
                            return ActionType.RAISE, amt, 0.65
                        if tier <= HU_BB_DEFEND_TIER:
                            return ActionType.CALL, gs.current_bet, 0.55
                    elif equity and equity > bb_pot_odds * 0.9 and tier <= 9:
                        return ActionType.CALL, gs.current_bet, 0.55

            # Widen call range vs frequent 3bettors
            opp_3bet_freq = 0.0
            if preflop_raise_count >= 1:
                opponents = [p for p in gs.players_in_hand if p.name != hero.name]
                for opp in opponents:
                    if opp.name in self.profiles:
                        prof = self.profiles[opp.name]
                        tbt = prof.get_stat("three_bet_pct")
                        if prof.get_confidence("three_bet_pct") > 0.2:
                            opp_3bet_freq = max(opp_3bet_freq, tbt)
            three_bet_widen = 2 if opp_3bet_freq > 0.35 else (1 if opp_3bet_freq > 0.25 else 0)

            if preflop_raise_count >= 2:
                from data.preflop_ranges import CALL_3BET_TIERS
                base_call_tier = CALL_3BET_TIERS.get(hero.position, 3)
                if is_hu:
                    base_call_tier = max(base_call_tier, 7)
                call_tier = base_call_tier + three_bet_widen
                if tier <= 2 and equity and equity > 0.40:
                    from engine.gto_baseline import _hero_position_is_ip
                    is_ip = _hero_position_is_ip(gs, hero.name)
                    amt = preflop_4bet_size(gs, hero, is_ip)
                    return ActionType.RAISE, amt, 0.70
                if tier <= call_tier and equity and pot_odds_val and equity > pot_odds_val * eq_mult:
                    return ActionType.CALL, gs.current_bet, 0.55
            elif preflop_raise_count >= 1:
                rescue_tier = 7 if is_hu else 6
                if hero.position in ("CO", "BTN", "SB"):
                    rescue_tier = max(rescue_tier, 7)
                if tier <= rescue_tier and equity and pot_odds_val and equity > pot_odds_val * eq_mult:
                    return ActionType.CALL, gs.current_bet, 0.55
            else:
                if tier <= 8 and equity and pot_odds_val and equity > pot_odds_val * eq_mult:
                    return ActionType.CALL, gs.current_bet, 0.55
            if tier <= 7 and exploit and exploit.get("call_more") and equity and equity > 0.35:
                if preflop_raise_count < 2 and not pot_control:
                    return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            eq_fold_mult = 0.8
            if is_hu and hero.position == "BB":
                eq_fold_mult = 0.6
            if equity and pot_odds_val and equity < pot_odds_val * eq_fold_mult:
                return ActionType.FOLD, 0, 0.60
            # Tighten up in multiway 3bet pots
            preflop_callers = sum(
                1 for a in gs.action_history.get(Street.PREFLOP, [])
                if a.action_type == ActionType.CALL and a.player_name != hero.name
            )
            preflop_raises = sum(
                1 for a in gs.action_history.get(Street.PREFLOP, [])
                if a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                and a.player_name != hero.name
            )
            if preflop_raises >= 2 and preflop_callers >= 1:
                hand_str = baseline.get("hand", "")
                from data.preflop_ranges import _hand_tier
                t = _hand_tier(hand_str) if hand_str else 10
                if t > 3:
                    return ActionType.FOLD, 0, 0.60
            # Pot commitment: if call commits 90%+ of stack, shove or fold
            call_amount = gs.current_bet - hero.current_bet
            if call_amount > 0 and hero.stack > 0:
                commit_ratio = call_amount / hero.stack
                if commit_ratio >= 0.9:
                    pot_odds_for_allin = hero.stack / (gs.pot + hero.stack)
                    if equity and equity >= pot_odds_for_allin * 0.85:
                        return ActionType.ALL_IN, hero.stack + hero.current_bet, 0.80
                    else:
                        return ActionType.FOLD, 0, 0.65
            if exploit and exploit.get("increase_bluff") and not exploit.get("no_bluff") and equity and equity > 0.40:
                from engine.gto_baseline import _hero_position_is_ip
                is_ip = _hero_position_is_ip(gs, hero.name)
                amt = preflop_3bet_size(gs, hero, is_ip)
                return ActionType.RAISE, amt, 0.60
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.RAISE:
            opp_raise_count = sum(
                1 for a in gs.action_history.get(Street.PREFLOP, [])
                if a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                and a.player_name != hero.name
            )
            if opp_raise_count >= 2:
                hand_str = baseline.get("hand", "")
                from data.preflop_ranges import _hand_tier, CALL_3BET_TIERS
                tier = _hand_tier(hand_str) if hand_str else 10
                if tier <= 2:
                    pass  # continue to raise/4bet
                elif tier <= CALL_3BET_TIERS.get(hero.position, 3) + (3 if is_hu else 0):
                    return ActionType.CALL, gs.current_bet, 0.60
                else:
                    return ActionType.FOLD, 0, 0.70
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

    def _min_call_equity(self, street: Street, num_players: int = 6) -> float:
        """Minimum equity required to call on each street — hard floor."""
        hu = num_players <= 2
        if street == Street.RIVER:
            return 0.28 if hu else 0.33
        elif street == Street.TURN:
            return 0.33 if hu else 0.40
        return 0.25 if hu else 0.30

    def _ev_based_confidence(
        self, action: ActionType, equity: float | None,
        pot_odds_val: float | None, baseline_conf: float,
    ) -> float:
        if equity is None:
            return baseline_conf

        if action == ActionType.FOLD:
            if pot_odds_val is not None:
                margin = pot_odds_val - equity
                if margin > 0.15:
                    return 0.85
                elif margin > 0.05:
                    return 0.65
                else:
                    return 0.45
            if equity < 0.25:
                return 0.80
            elif equity < 0.35:
                return 0.60
            return 0.45

        if action in (ActionType.CALL, ActionType.CHECK):
            if pot_odds_val is not None:
                margin = equity - pot_odds_val
                if margin > 0.15:
                    return 0.80
                elif margin > 0.05:
                    return 0.60
                else:
                    return 0.45
            return baseline_conf

        if action in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
            if equity > 0.70:
                return 0.70
            elif equity > 0.55:
                return 0.60
            elif equity > 0.40:
                return 0.50
            return 0.40

        return baseline_conf

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
        exploit: dict | None = None, multiway_note: str | None = None,
    ) -> tuple[ActionType, int, float]:
        action = baseline["action"]
        confidence = baseline["confidence"]
        strength = baseline.get("hand_strength", HandStrength.WEAK_MADE)
        min_eq = self._min_call_equity(gs.street, len(gs.players))

        pot_control = multiway_note is not None and "控池" in multiway_note
        if pot_control:
            min_eq = max(min_eq, 0.45)

        effective_pot_odds = pot_odds_val
        implied = self._implied_pot_odds(gs, hero, strength)
        if implied is not None and pot_odds_val is not None:
            effective_pot_odds = implied

        # Pot commitment: if remaining stack <= 1 BB, just shove
        if hero.stack <= gs.big_blind and hero.stack > 0:
            return ActionType.ALL_IN, hero.stack + hero.current_bet, 0.90

        if action == ActionType.FOLD:
            discounted_eq = self._action_based_equity_discount(gs, hero, equity)
            # Never fold to tiny bets (< 33% pot) with decent equity
            call_amount = gs.current_bet - hero.current_bet
            if call_amount > 0 and gs.pot > 0:
                bet_to_pot = call_amount / gs.pot
                actual_pot_odds = call_amount / (gs.pot + call_amount)
                if bet_to_pot < 0.33 and equity and equity > actual_pot_odds * 1.1:
                    return ActionType.CALL, gs.current_bet, 0.55
            if discounted_eq and effective_pot_odds and discounted_eq > effective_pot_odds and discounted_eq >= min_eq:
                return ActionType.CALL, gs.current_bet, 0.55
            if (exploit and exploit.get("call_more") and discounted_eq
                    and effective_pot_odds and discounted_eq > effective_pot_odds * 0.85
                    and discounted_eq >= min_eq
                    and strength.value >= HandStrength.WEAK_MADE.value):
                return ActionType.CALL, gs.current_bet, 0.50
            # HU float: call in position on flop/turn with reasonable equity
            if len(gs.players) <= 2:
                from engine.gto_baseline import _hero_position_is_ip as _ip_float
                is_ip_hu = _ip_float(gs, hero.name)
                if gs.street == Street.FLOP and is_ip_hu and equity and equity > 0.30:
                    return ActionType.CALL, gs.current_bet, 0.50
                if gs.street == Street.TURN and is_ip_hu and equity and equity > 0.35:
                    return ActionType.CALL, gs.current_bet, 0.50
            return ActionType.FOLD, 0, confidence

        if action == ActionType.CALL:
            discounted_eq = self._action_based_equity_discount(gs, hero, equity)
            final_eq = discounted_eq
            if final_eq and final_eq < min_eq:
                return ActionType.FOLD, 0, 0.65
            if final_eq and effective_pot_odds and final_eq < effective_pot_odds * 0.8:
                return ActionType.FOLD, 0, 0.60
            # Unpaired overcards with no draw on dry board = fold (skip in HU flop IP)
            hu_flop_ip = False
            if len(gs.players) <= 2 and gs.street == Street.FLOP:
                from engine.gto_baseline import _hero_position_is_ip as _ip_trash
                hu_flop_ip = _ip_trash(gs, hero.name)
            if (strength is not None
                    and strength.value <= HandStrength.TRASH.value
                    and gs.board and not hu_flop_ip):
                from env.board_texture import analyze_board as _ab
                board_tex = _ab(gs.board)
                if board_tex.is_dry:
                    return ActionType.FOLD, 0, 0.70
            # TRASH with no draw should not call even if equity looks ok
            if (strength is not None
                    and strength.value <= HandStrength.TRASH.value
                    and gs.street != Street.PREFLOP
                    and not hu_flop_ip):
                return ActionType.FOLD, 0, 0.60
            # WEAK_MADE on dangerous boards should fold facing bets
            if (strength is not None
                    and strength.value <= HandStrength.WEAK_MADE.value
                    and gs.board):
                from env.board_texture import analyze_board
                board_tex = analyze_board(gs.board)
                if board_tex.board_danger >= 3 and final_eq and final_eq < 0.40:
                    return ActionType.FOLD, 0, 0.60
            # Multi-street aggression guard: fold weak/medium hands facing sustained pressure
            if (strength is not None
                    and strength.value <= HandStrength.WEAK_MADE.value
                    and gs.street in (Street.TURN, Street.RIVER)):
                prev_streets_agg = 0
                for prev_st in (Street.FLOP, Street.TURN):
                    if prev_st == gs.street:
                        break
                    prev_actions = gs.action_history.get(prev_st, [])
                    if any(a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)
                           and a.player_name != hero.name for a in prev_actions):
                        prev_streets_agg += 1
                current_actions = gs.action_history.get(gs.street, [])
                if any(a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)
                       and a.player_name != hero.name for a in current_actions):
                    prev_streets_agg += 1
                if prev_streets_agg >= 2:
                    return ActionType.FOLD, 0, 0.70
            # Pot commitment: if call commits 90%+ of stack, go all-in or fold
            call_amount = gs.current_bet - hero.current_bet
            if call_amount > 0 and hero.stack > 0:
                commit_ratio = call_amount / hero.stack
                if commit_ratio >= 0.9:
                    pot_odds_for_allin = hero.stack / (gs.pot + hero.stack)
                    if final_eq and final_eq >= pot_odds_for_allin * 0.85:
                        return ActionType.ALL_IN, hero.stack + hero.current_bet, 0.80
                    else:
                        return ActionType.FOLD, 0, 0.65
            # Check-raise: OOP facing a single bet (not a raise-back), raise with strong hands/draws
            if self._is_check_raise_spot(gs, hero, strength, final_eq):
                facing = gs.current_bet
                amt = select_raise_size(gs, hero, strength, facing, gs.pot)
                return ActionType.RAISE, amt, 0.70
            if (final_eq and final_eq > 0.70
                    and strength.value >= HandStrength.STRONG_MADE.value):
                facing = gs.current_bet
                amt = select_raise_size(gs, hero, strength, facing, gs.pot)
                return ActionType.RAISE, amt, 0.65
            return ActionType.CALL, gs.current_bet, confidence

        if action == ActionType.CHECK:
            from engine.gto_baseline import _hero_position_is_ip
            is_ip = _hero_position_is_ip(gs, hero.name)
            if self._should_cbet(gs, hero, equity, strength):
                if (strength.value <= HandStrength.WEAK_MADE.value
                        and self._is_bottom_pair(hero, gs.board)):
                    return ActionType.CHECK, 0, 0.60
                is_value = strength.value >= HandStrength.MEDIUM_MADE.value
                amt = select_bet_size(gs, hero, strength, gs.pot, is_value)
                return ActionType.BET, amt, 0.65
            if equity and equity > 0.55 and strength.value >= HandStrength.MEDIUM_MADE.value:
                amt = select_bet_size(gs, hero, strength, gs.pot, True)
                return ActionType.BET, amt, 0.60
            # Semi-bluff with strong draws (standard GTO play, no exploit signal needed)
            if (strength.value >= HandStrength.STRONG_DRAW.value
                    and gs.street in (Street.FLOP, Street.TURN)
                    and equity and equity > 0.30):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.65
            # Semi-bluff with medium draws on wet boards when IP
            if (strength.value == HandStrength.MEDIUM_DRAW.value
                    and gs.street == Street.FLOP
                    and is_ip
                    and equity and equity > 0.30):
                from env.board_texture import analyze_board as _ab3
                board_tex = _ab3(gs.board)
                if board_tex.is_wet:
                    amt = select_bet_size(gs, hero, strength, gs.pot, False)
                    return ActionType.BET, amt, 0.55
            # HU stab: bet in position on flop with any reasonable equity
            if (len(gs.players) <= 2 and is_ip
                    and gs.street == Street.FLOP
                    and equity and equity > 0.28
                    and strength.value >= HandStrength.TRASH.value):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.55
            # Probe bet: turn/river when previous street checked through
            if self._is_probe_spot(gs, hero, equity, strength):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.60
            if (exploit and exploit.get("increase_bluff")
                    and not exploit.get("no_bluff")
                    and equity and equity > 0.25
                    and strength.value <= HandStrength.WEAK_DRAW.value
                    and gs.street != Street.RIVER):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.55
            # River bluff with busted draws on scare cards
            if (gs.street == Street.RIVER
                    and strength.value <= HandStrength.WEAK_DRAW.value
                    and self._should_river_bluff(gs, hero, equity, strength)):
                amt = select_bet_size(gs, hero, strength, gs.pot, False)
                return ActionType.BET, amt, 0.50
            return ActionType.CHECK, 0, confidence

        if action == ActionType.BET:
            from engine.gto_baseline import _hero_position_is_ip as _is_ip_bet
            is_ip_bet = _is_ip_bet(gs, hero.name)
            # Trap/slow-play: OOP with monster on flop vs preflop aggressor, check to induce cbet
            if (not is_ip_bet
                    and gs.street == Street.FLOP
                    and strength.value >= HandStrength.MONSTER.value):
                num_opponents = len([p for p in gs.players_in_hand if p.name != hero.name])
                preflop_actions = gs.action_history.get(Street.PREFLOP, [])
                opp_was_aggressor = any(
                    a.player_name != hero.name
                    and a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                    for a in preflop_actions
                )
                if num_opponents == 1 and opp_was_aggressor:
                    return ActionType.CHECK, 0, 0.70
            # OOP with strong made on dry flop vs preflop aggressor, check to trap
            if (not is_ip_bet
                    and gs.street == Street.FLOP
                    and strength.value >= HandStrength.STRONG_MADE.value):
                num_opponents = len([p for p in gs.players_in_hand if p.name != hero.name])
                if num_opponents == 1:
                    from env.board_texture import analyze_board as _ab_trap2
                    board_tex = _ab_trap2(gs.board)
                    if board_tex.is_dry:
                        preflop_actions = gs.action_history.get(Street.PREFLOP, [])
                        opp_was_aggressor = any(
                            a.player_name != hero.name
                            and a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                            for a in preflop_actions
                        )
                        if opp_was_aggressor:
                            return ActionType.CHECK, 0, 0.65
            if (strength.value <= HandStrength.WEAK_MADE.value
                    and self._is_bottom_pair(hero, gs.board)):
                return ActionType.CHECK, 0, 0.60
            # Board texture guard: don't bet weak hands on scary boards
            if gs.board and strength.value <= HandStrength.WEAK_MADE.value:
                from env.board_texture import analyze_board
                board_tex = analyze_board(gs.board)
                if board_tex.board_danger >= 3:
                    return ActionType.CHECK, 0, 0.65
            # River thin value guard: one pair should check on coordinated boards
            if gs.street == Street.RIVER and strength.value <= HandStrength.WEAK_MADE.value:
                # But allow river bluff with busted draws on scare cards
                if self._should_river_bluff(gs, hero, equity, strength):
                    amt = select_bet_size(gs, hero, strength, gs.pot, False)
                    return ActionType.BET, amt, 0.55
                return ActionType.CHECK, 0, 0.60
            if gs.street == Street.RIVER and strength.value == HandStrength.MEDIUM_MADE.value:
                from env.board_texture import analyze_board as _ab2
                board_tex = _ab2(gs.board)
                if board_tex.board_danger >= 2 or board_tex.straight_draw_possible:
                    return ActionType.CHECK, 0, 0.60
            current_spr = baseline.get("spr", float("inf"))
            if current_spr <= 1.0:
                if gs.street == Street.RIVER:
                    if (strength.value >= HandStrength.STRONG_MADE.value
                            and equity and equity >= 0.55):
                        return ActionType.ALL_IN, hero.stack, confidence
                    else:
                        return ActionType.CHECK, 0, 0.60
                if (strength.value >= HandStrength.WEAK_MADE.value
                        and equity and equity >= 0.45):
                    return ActionType.ALL_IN, hero.stack, confidence
                else:
                    return ActionType.CHECK, 0, 0.60
            if gs.street == Street.RIVER and equity:
                river_floor = 0.45 if len(gs.players) <= 2 else 0.50
                if equity < river_floor:
                    return ActionType.CHECK, 0, 0.60
            if gs.street == Street.TURN and equity:
                turn_floor = 0.30 if len(gs.players) <= 2 else 0.35
                if equity < turn_floor:
                    return ActionType.CHECK, 0, 0.60
            is_value = strength.value >= HandStrength.MEDIUM_MADE.value
            amt = select_bet_size(gs, hero, strength, gs.pot, is_value)
            if equity and equity > 0.70 and is_value:
                amt = max(amt, int(gs.pot * 0.75))
                amt = min(amt, hero.stack)
            if exploit and exploit.get("increase_sizing") and is_value:
                amt = min(int(amt * 1.3), hero.stack)
            return ActionType.BET, amt, confidence

        if action == ActionType.RAISE:
            current_spr = baseline.get("spr", float("inf"))
            if current_spr <= 1.0 and strength.value >= HandStrength.WEAK_MADE.value:
                return ActionType.ALL_IN, hero.stack, confidence
            facing = gs.current_bet
            amt = select_raise_size(gs, hero, strength, facing, gs.pot)
            return ActionType.RAISE, amt, confidence

        return action, 0, confidence

    @staticmethod
    def _is_bottom_pair(hero: Player, board: list[int]) -> bool:
        """Check if hero has bottom pair (pair rank < second-highest board rank)."""
        if not hero.hole_cards or not board:
            return False
        from treys import Card as TreysCard
        hero_ranks = [TreysCard.get_rank_int(c) for c in hero.hole_cards]
        board_ranks = sorted([TreysCard.get_rank_int(c) for c in board], reverse=True)
        for hr in hero_ranks:
            if hr in board_ranks:
                if len(board_ranks) >= 2 and hr < board_ranks[1]:
                    return True
        return False

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
        is_hu = len(gs.players) <= 2
        if is_hu:
            if strength.value >= HandStrength.MEDIUM_DRAW.value:
                return True
            if equity and equity > 0.30:
                from env.board_texture import analyze_board as _ab_hu_cbet
                if _ab_hu_cbet(gs.board).is_dry:
                    return True
        return False

    def _is_check_raise_spot(
        self, gs: GameState, hero: Player,
        strength: HandStrength, equity: float | None,
    ) -> bool:
        """Detect spots where hero should check-raise instead of flat calling."""
        from engine.gto_baseline import _hero_position_is_ip
        if _hero_position_is_ip(gs, hero.name):
            return False

        street_actions = gs.action_history.get(gs.street, [])
        hero_checked = any(
            a.player_name == hero.name and a.action_type == ActionType.CHECK
            for a in street_actions
        )
        if not hero_checked:
            return False

        opp_raised_back = sum(
            1 for a in street_actions
            if a.player_name != hero.name
            and a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
        )
        if opp_raised_back > 1:
            return False

        if strength.value >= HandStrength.MONSTER.value:
            return True
        if strength.value >= HandStrength.STRONG_MADE.value and equity and equity > 0.60:
            return True
        if (strength.value >= HandStrength.STRONG_DRAW.value
                and gs.street in (Street.FLOP, Street.TURN)
                and equity and equity > 0.32):
            return True
        # Protection check-raise: medium made on wet boards
        if (strength.value >= HandStrength.MEDIUM_MADE.value
                and equity and equity > 0.50
                and gs.street == Street.FLOP):
            from env.board_texture import analyze_board as _ab_cr2
            board_tex = _ab_cr2(gs.board)
            if board_tex.is_wet:
                return True
        return False

    def _is_probe_spot(
        self, gs: GameState, hero: Player,
        equity: float | None, strength: HandStrength,
    ) -> bool:
        """Detect probe bet opportunities: turn/river after previous street checked through."""
        if gs.street not in (Street.TURN, Street.RIVER):
            return False
        prev_street = Street.FLOP if gs.street == Street.TURN else Street.TURN
        prev_actions = gs.action_history.get(prev_street, [])
        had_aggression = any(
            a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)
            for a in prev_actions
        )
        if had_aggression:
            return False
        if equity and equity > 0.40 and strength.value >= HandStrength.WEAK_MADE.value:
            return True
        if (equity and equity > 0.30
                and strength.value >= HandStrength.MEDIUM_DRAW.value
                and gs.street == Street.TURN):
            return True
        is_hu = len(gs.players) <= 2
        if is_hu and equity and equity > 0.30:
            return True
        return False

    def _should_river_bluff(
        self, gs: GameState, hero: Player,
        equity: float | None, strength: HandStrength,
    ) -> bool:
        """Allow river bluffs with busted draws when a scare card hits."""
        if gs.street != Street.RIVER or not gs.board or len(gs.board) < 5:
            return False
        if strength.value > HandStrength.WEAK_DRAW.value:
            return False

        had_draw_earlier = False
        for prev_st in (Street.FLOP, Street.TURN):
            prev_actions = gs.action_history.get(prev_st, [])
            if any(a.player_name == hero.name
                   and a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.CALL)
                   for a in prev_actions):
                had_draw_earlier = True
                break
        if not had_draw_earlier:
            return False

        from env.board_texture import analyze_board as _ab_rb
        board_tex = _ab_rb(gs.board)
        river_card = gs.board[-1]
        from treys import Card as TreysCard
        river_rank = TreysCard.get_rank_int(river_card)
        river_suit = TreysCard.get_suit_int(river_card)

        scare_card = False
        if river_rank >= 10:
            scare_card = True
        suit_counts: dict[int, int] = {}
        for c in gs.board:
            s = TreysCard.get_suit_int(c)
            suit_counts[s] = suit_counts.get(s, 0) + 1
        if suit_counts.get(river_suit, 0) >= 3:
            scare_card = True
        if board_tex.straight_draw_possible and board_tex.connectedness >= 3:
            scare_card = True

        if not scare_card:
            return False

        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile and profile.get_stat("fold_to_cbet") > 0.55:
                return True
        if len(opponents) == 1:
            return True
        return False

    def _opponent_summary(self, gs: GameState, hero: Player) -> str | None:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        summaries = []
        for opp in opponents:
            if opp.name in self.profiles:
                profile = self.profiles[opp.name]
                label = classify_style(profile, num_players=len(gs.players))
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

    def _action_sequence_discount(
        self, gs: GameState, hero: Player, equity: float,
    ) -> float:
        """Discount equity based on opponent's cumulative action sequence across streets."""
        if gs.street == Street.PREFLOP or equity is None:
            return equity

        opp_calls = 0
        opp_raises = 0
        opp_bets = 0
        streets_with_aggression = 0
        for street in (Street.FLOP, Street.TURN, Street.RIVER):
            actions = gs.action_history.get(street, [])
            street_agg = False
            for a in actions:
                if a.player_name == hero.name:
                    continue
                if a.action_type == ActionType.CALL:
                    opp_calls += 1
                elif a.action_type in (ActionType.RAISE, ActionType.ALL_IN):
                    opp_raises += 1
                    street_agg = True
                elif a.action_type == ActionType.BET:
                    opp_bets += 1
                    street_agg = True
            if street_agg:
                streets_with_aggression += 1

        if opp_calls == 0 and opp_raises == 0 and opp_bets == 0:
            return equity

        # Multi-street aggression is a strong signal of real hand strength
        if streets_with_aggression >= 3:
            discount = 0.50
        elif streets_with_aggression >= 2:
            discount = (0.90 ** opp_calls) * (0.80 ** opp_raises) * (0.85 ** opp_bets)
        else:
            discount = (0.93 ** opp_calls) * (0.85 ** opp_raises) * (0.90 ** opp_bets)
        discount = max(discount, 0.40)
        return equity * discount

    def _action_based_equity_discount(
        self, gs: GameState, hero: Player, equity: float,
    ) -> float:
        """Discount equity when facing a raise or a significant bet."""
        if gs.street == Street.PREFLOP or equity is None:
            return equity

        street_actions = gs.action_history.get(gs.street, [])
        hero_bet = any(
            a.player_name == hero.name
            and a.action_type in (ActionType.BET, ActionType.RAISE)
            for a in street_actions
        )
        opp_raised = any(
            a.player_name != hero.name
            and a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
            for a in street_actions
        )
        opp_bet = any(
            a.player_name != hero.name
            and a.action_type in (ActionType.BET, ActionType.ALL_IN)
            for a in street_actions
        )

        bet_size = gs.current_bet - hero.current_bet
        pot_ratio = bet_size / gs.pot if gs.pot > 0 else 1.0

        if hero_bet and opp_raised:
            if gs.street == Street.RIVER:
                if pot_ratio > 1.0:
                    return equity * 0.45
                elif pot_ratio > 0.5:
                    return equity * 0.55
                else:
                    return equity * 0.65
            elif gs.street == Street.TURN:
                if pot_ratio > 1.0:
                    return equity * 0.55
                elif pot_ratio > 0.5:
                    return equity * 0.65
                else:
                    return equity * 0.75
            else:
                if pot_ratio > 1.0:
                    return equity * 0.62
                else:
                    return equity * 0.72

        if opp_bet and not hero_bet and pot_ratio > 0.3:
            if gs.street == Street.RIVER:
                if pot_ratio > 1.0:
                    return equity * 0.55
                elif pot_ratio > 0.5:
                    return equity * 0.65
                else:
                    return equity * 0.75
            elif gs.street == Street.TURN:
                if pot_ratio > 1.0:
                    return equity * 0.60
                elif pot_ratio > 0.5:
                    return equity * 0.70
                else:
                    return equity * 0.80
            else:
                if pot_ratio > 1.0:
                    return equity * 0.65
                elif pot_ratio > 0.5:
                    return equity * 0.75
                else:
                    return equity * 0.85

        return equity

    def _cold_start_discount(
        self, gs: GameState, hero: Player, equity: float,
    ) -> float:
        """Discount raw monte-carlo equity when we have little data on opponents."""
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return equity
        min_hands = min(
            (self.profiles[o.name].total_hands if o.name in self.profiles else 0)
            for o in opponents
        )
        if min_hands >= 20:
            return equity
        ratio = min_hands / 20
        is_hu = len(gs.players) <= 2
        if gs.street == Street.PREFLOP:
            floor = 0.92 if is_hu else 0.85
            discount = floor + (1.0 - floor) * ratio
        else:
            floor = 0.88 if is_hu else 0.80
            discount = floor + (1.0 - floor) * ratio
        return equity * discount

    def _adjust_equity_vs_tight_allin(
        self, gs: GameState, hero: Player, equity: float,
    ) -> float:
        preflop_actions = gs.action_history.get(Street.PREFLOP, [])
        opp_raise_count = sum(
            1 for a in preflop_actions
            if a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
            and a.player_name != hero.name
        )
        facing_allin = any(
            a.action_type == ActionType.ALL_IN
            for a in preflop_actions
            if a.player_name != hero.name
        )

        if opp_raise_count == 0 and not facing_allin:
            return equity

        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile is None:
                continue
            vpip = profile.get_stat("vpip")
            vpip_conf = profile.get_confidence("vpip")

            if facing_allin:
                if vpip < 0.15 and vpip_conf > 0.25:
                    return equity * 0.70
                elif vpip < 0.22 and vpip_conf > 0.25:
                    return equity * 0.85
            elif opp_raise_count >= 2:
                # Facing 4bet: heavy discount
                if vpip < 0.22 and vpip_conf > 0.25:
                    return equity * 0.75
                else:
                    return equity * 0.85
            elif opp_raise_count >= 1:
                # Facing 3bet: moderate discount
                if vpip < 0.22 and vpip_conf > 0.25:
                    return equity * 0.85
                else:
                    return equity * 0.90

        if facing_allin:
            return equity
        if opp_raise_count >= 2:
            return equity * 0.88
        elif opp_raise_count >= 1:
            return equity * 0.93
        return equity

    def _compute_exploit(self, gs: GameState, hero: Player) -> tuple[str | None, float]:
        opponents = [p for p in gs.players_in_hand if p.name != hero.name]
        if not opponents:
            return None, 0.0

        from engine.gto_baseline import _hero_position_is_ip
        hero_is_ip = _hero_position_is_ip(gs, hero.name)
        facing_bet = gs.current_bet > hero.current_bet

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
            top_exploits = self.exploit_engine.top_exploits(
                profile, hero_is_ip, 2, num_players=len(gs.players),
            )

            for adj in top_exploits:
                if adj.category == ExploitCategory.DEFENSE and not facing_bet:
                    continue
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

        if gs.street == Street.PREFLOP:
            committed = [
                p for p in opponents
                if p.current_bet > gs.big_blind or p.is_all_in
            ]
            effective_opponents = len(committed)
        else:
            effective_opponents = len(opponents)

        if effective_opponents < 2:
            return None

        opp_profiles = []
        for opp in opponents:
            profile = self.profiles.get(opp.name)
            if profile:
                opp_profiles.append((opp.name, profile))

        if len(opp_profiles) < 2:
            return None

        street = gs.street.name.lower() if gs.street != Street.PREFLOP else "flop"
        analysis = analyze_multiway(opp_profiles, equity, gs.pot, street)
        return f"多人底池({effective_opponents + 1}人): {analysis.strategy_note}"

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
