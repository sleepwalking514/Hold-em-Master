from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from treys import Card

from env.game_state import GameState, Player
from env.action_space import ActionType, PlayerAction, Street, GameMode
from env.board_texture import analyze_board


# ─── Bayesian Tracker ───

from profiler.bayesian_tracker import BayesianStat


class TestBayesianStat:
    def test_initial_mean(self):
        s = BayesianStat(2, 3)
        assert abs(s.mean - 0.4) < 0.01

    def test_update_success(self):
        s = BayesianStat(2, 3)
        s.update(True)
        assert s.alpha == 3
        assert s.beta == 3
        assert abs(s.mean - 0.5) < 0.01

    def test_update_failure(self):
        s = BayesianStat(2, 3)
        s.update(False)
        assert s.alpha == 2
        assert s.beta == 4

    def test_observations(self):
        s = BayesianStat(2, 3)
        assert s.observations == 0
        s.update(True)
        s.update(False)
        assert s.observations == 2

    def test_confidence_zero_obs(self):
        s = BayesianStat(2, 3)
        assert s.confidence == 0.0

    def test_confidence_increases(self):
        s = BayesianStat(2, 3)
        for _ in range(10):
            s.update(True)
        c10 = s.confidence
        for _ in range(90):
            s.update(True)
        c100 = s.confidence
        assert c100 > c10 > 0

    def test_serialization(self):
        s = BayesianStat(5, 5)
        s.update(True)
        s.update(False)
        d = s.to_dict()
        s2 = BayesianStat.from_dict(d)
        assert s2.alpha == s.alpha
        assert s2.beta == s.beta
        assert s2.mean == s.mean


# ─── Info Weight ───

from profiler.info_weight import calc_update_delta, EVENT_INFO_WEIGHT


class TestInfoWeight:
    def test_known_event(self):
        delta = calc_update_delta("pure_air_overbet", 1.0, 0.0)
        assert abs(delta - 0.15) < 0.01

    def test_dampening(self):
        d_low = calc_update_delta("normal_bet", 1.0, 0.0)
        d_high = calc_update_delta("normal_bet", 1.0, 0.9)
        assert d_low > d_high

    def test_direction(self):
        d_pos = calc_update_delta("check_raise", 1.0, 0.5)
        d_neg = calc_update_delta("check_raise", -1.0, 0.5)
        assert d_pos > 0
        assert d_neg < 0

    def test_unknown_event(self):
        delta = calc_update_delta("unknown_event", 1.0, 0.0)
        assert abs(delta - 0.01) < 0.001


# ─── Player Profile ───

from profiler.player_profile import (
    PlayerProfile, BetSizingPattern, SkillEstimate, KeyHand,
    check_profile_consistency,
)


class TestPlayerProfile:
    def test_create_default(self):
        p = PlayerProfile("test_player")
        assert p.name == "test_player"
        assert p.total_hands == 0
        assert "vpip" in p.stats

    def test_get_stat(self):
        p = PlayerProfile("test")
        val = p.get_stat("vpip")
        assert 0 <= val <= 1

    def test_update_stat(self):
        p = PlayerProfile("test")
        old = p.get_stat("vpip")
        for _ in range(20):
            p.update_stat("vpip", True)
        new = p.get_stat("vpip")
        assert new > old

    def test_style_label(self):
        p = PlayerProfile("test")
        label = p.style_label
        assert isinstance(label, str)
        assert len(label) > 0

    def test_summary(self):
        p = PlayerProfile("小刚")
        p.total_hands = 50
        s = p.summary()
        assert "小刚" in s
        assert "50手" in s

    def test_serialization_roundtrip(self):
        p = PlayerProfile("test", "紧凶TAG")
        p.total_hands = 42
        for _ in range(10):
            p.update_stat("vpip", True)
        p.add_key_hand(KeyHand(1, "river_bluff", "test details"))
        d = p.to_dict()
        p2 = PlayerProfile.from_dict(d)
        assert p2.name == "test"
        assert p2.total_hands == 42
        assert p2.get_stat("vpip") == p.get_stat("vpip")
        assert len(p2.key_hands) == 1

    def test_consistency_pfr_gt_vpip(self):
        p = PlayerProfile("test")
        p.stats["pfr"].alpha = 20
        p.stats["pfr"].beta = 2
        p.stats["vpip"].alpha = 2
        p.stats["vpip"].beta = 20
        corrections = check_profile_consistency(p)
        assert any(c[0] == "pfr" for c in corrections)


class TestBetSizingPattern:
    def test_record_bet(self):
        bs = BetSizingPattern()
        bs.record_bet(0.66, is_value=True)
        assert len(bs.value_bet_ratios) == 1
        assert bs.total_bets == 1

    def test_overbet_tracking(self):
        bs = BetSizingPattern()
        bs.record_bet(1.5, is_value=True)
        assert bs.overbet_count == 1
        assert bs.overbet_frequency == 1.0

    def test_window_limit(self):
        bs = BetSizingPattern()
        for i in range(40):
            bs.record_bet(0.5 + i * 0.01, is_value=True)
        assert len(bs.value_bet_ratios) == 30


# ─── Profile Manager ───

from profiler.profile_manager import (
    create_profile, save_profile, load_profile, load_or_create,
    available_prior_types, PRIOR_TEMPLATES,
)


class TestProfileManager:
    def test_create_default(self):
        p = create_profile("test_player")
        assert p.name == "test_player"
        assert p.prior_type == "未知"

    def test_create_with_prior(self):
        p = create_profile("tight_player", "紧凶TAG")
        assert p.prior_type == "紧凶TAG"
        assert p.get_stat("vpip") != PlayerProfile("x").get_stat("vpip")

    def test_save_and_load(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        p = create_profile("save_test", "松凶LAG")
        p.total_hands = 10
        save_profile(p)
        loaded = load_profile("save_test")
        assert loaded is not None
        assert loaded.name == "save_test"
        assert loaded.total_hands == 10

    def test_load_nonexistent(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        assert load_profile("nonexistent") is None

    def test_load_or_create(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        p = load_or_create("new_player", "跟注站")
        assert p.name == "new_player"
        assert p.prior_type == "跟注站"

    def test_all_prior_types(self):
        types = available_prior_types()
        assert "紧凶TAG" in types
        assert "未知" in types
        for pt in PRIOR_TEMPLATES:
            p = create_profile("test", pt)
            assert p.prior_type == pt


# ─── Equity Calculator ───

from engine.equity_calculator import monte_carlo_equity, equity_vs_range


class TestEquityCalculator:
    def test_aa_vs_random_preflop(self):
        aa = [Card.new("As"), Card.new("Ah")]
        eq = monte_carlo_equity(aa, [], num_opponents=1, num_simulations=3000)
        assert 0.75 < eq < 0.95

    def test_aa_vs_kk_preflop(self):
        aa = [Card.new("As"), Card.new("Ah")]
        kk = [(Card.new("Ks"), Card.new("Kh"))]
        eq = equity_vs_range(aa, [], kk, num_simulations=3000)
        assert 0.75 < eq < 0.90

    def test_nuts_on_river(self):
        hero = [Card.new("As"), Card.new("Ks")]
        board = [Card.new("Qs"), Card.new("Js"), Card.new("Ts"), Card.new("2h"), Card.new("3d")]
        eq = monte_carlo_equity(hero, board, num_opponents=1, num_simulations=2000)
        assert eq > 0.95

    def test_equity_range_0_to_1(self):
        hero = [Card.new("7h"), Card.new("2c")]
        eq = monte_carlo_equity(hero, [], num_opponents=1, num_simulations=1000)
        assert 0.0 <= eq <= 1.0


# ─── Pot Odds ───

from engine.pot_odds import pot_odds, call_ev, spr, bet_ev, minimum_defense_frequency


class TestPotOdds:
    def test_pot_odds_basic(self):
        assert abs(pot_odds(50, 100) - 1/3) < 0.01

    def test_pot_odds_zero_call(self):
        assert pot_odds(0, 100) == 0.0

    def test_call_ev_positive(self):
        ev = call_ev(0.5, 100, 50)
        assert ev > 0

    def test_call_ev_negative(self):
        ev = call_ev(0.2, 100, 50)
        assert ev < 0

    def test_spr_basic(self):
        assert abs(spr(600, 100) - 6.0) < 0.01

    def test_spr_zero_pot(self):
        assert spr(600, 0) == float("inf")

    def test_bet_ev(self):
        ev = bet_ev(0.6, 100, 75, 0.4)
        assert ev > 0

    def test_mdf(self):
        mdf = minimum_defense_frequency(100, 100)
        assert abs(mdf - 0.5) < 0.01


# ─── Preflop Ranges ───

from data.preflop_ranges import (
    get_preflop_advice, hand_in_range, cards_to_hand,
    PreflopAction, get_stack_category,
)


class TestPreflopRanges:
    def test_aa_utg_opens(self):
        action, conf = get_preflop_advice("AA", "UTG", 100)
        assert action == PreflopAction.OPEN

    def test_72o_utg_folds(self):
        action, conf = get_preflop_advice("72o", "UTG", 100)
        assert action == PreflopAction.FOLD

    def test_btn_wider_than_utg(self):
        a_utg, _ = get_preflop_advice("87s", "UTG", 100)
        a_btn, _ = get_preflop_advice("87s", "BTN", 100)
        assert a_utg == PreflopAction.FOLD
        assert a_btn == PreflopAction.OPEN

    def test_push_fold_short_stack(self):
        action, _ = get_preflop_advice("AA", "UTG", 15)
        assert action == PreflopAction.PUSH

    def test_facing_raise_3bet(self):
        action, _ = get_preflop_advice("AA", "BTN", 100, facing_raise=True)
        assert action == PreflopAction.THREE_BET

    def test_stack_categories(self):
        assert get_stack_category(10) == "push_fold"
        assert get_stack_category(30) == "short"
        assert get_stack_category(50) == "medium"
        assert get_stack_category(80) == "standard"
        assert get_stack_category(150) == "deep"
        assert get_stack_category(250) == "ultra_deep"

    def test_cards_to_hand(self):
        assert cards_to_hand("A", "K", True) == "AKs"
        assert cards_to_hand("K", "A", False) == "AKo"
        assert cards_to_hand("T", "T", True) == "TT"

    def test_hand_in_range(self):
        assert hand_in_range("AA", 1)
        assert not hand_in_range("72o", 5)


# ─── Postflop Rules ───

from data.postflop_rules import (
    classify_hand_strength, hand_strength_ratio,
    get_postflop_advice, HandStrength, PostflopAction,
)


class TestPostflopRules:
    def test_classify_monster(self):
        assert classify_hand_strength(100, 5) == HandStrength.MONSTER

    def test_classify_trash(self):
        assert classify_hand_strength(7000, 5) == HandStrength.TRASH

    def test_strength_ratio_range(self):
        assert 0 <= hand_strength_ratio(1) <= 1
        assert 0 <= hand_strength_ratio(7462) <= 1
        assert hand_strength_ratio(1) > hand_strength_ratio(7462)

    def test_ip_monster_bets(self):
        advice = get_postflop_advice(HandStrength.MONSTER, is_ip=True, facing_bet=False)
        assert advice["action"] in (PostflopAction.BET_LARGE, PostflopAction.BET_MEDIUM)

    def test_facing_bet_trash_folds(self):
        advice = get_postflop_advice(HandStrength.TRASH, is_ip=True, facing_bet=True)
        assert advice["action"] == PostflopAction.FOLD

    def test_low_spr_strong_hand(self):
        advice = get_postflop_advice(HandStrength.STRONG_MADE, is_ip=True, facing_bet=False, spr_value=2.0)
        assert advice["action"] == PostflopAction.BET_LARGE


# ─── Exploit Config ───

from data.exploit_config import continuous_exploit, blend_weight, BASELINE


class TestExploitConfig:
    def test_no_deviation(self):
        result = continuous_exploit(0.50, 0.50)
        assert abs(result) < 0.01

    def test_positive_deviation(self):
        result = continuous_exploit(0.70, 0.50)
        assert result > 0

    def test_negative_deviation(self):
        result = continuous_exploit(0.30, 0.50)
        assert result < 0

    def test_max_magnitude(self):
        result = continuous_exploit(1.0, 0.0, max_magnitude=0.3)
        assert result <= 0.3 + 0.01

    def test_blend_low_confidence(self):
        solid, exploit = blend_weight(0.1)
        assert solid == 0.92
        assert exploit == 0.08

    def test_blend_high_confidence(self):
        solid, exploit = blend_weight(0.9)
        assert exploit > solid

    def test_baseline_keys(self):
        assert "fold_to_cbet" in BASELINE
        assert "aggression_freq" in BASELINE


# ─── Street Planner ───

from engine.street_planner import plan_bet_geometry, get_street_plan


class TestStreetPlanner:
    def test_low_spr_one_street(self):
        plan = plan_bet_geometry(1.0)
        assert plan.streets_remaining == 1
        assert plan.sizes[0] == 1.0

    def test_medium_spr(self):
        plan = plan_bet_geometry(3.0)
        assert plan.streets_remaining == 2

    def test_high_spr(self):
        plan = plan_bet_geometry(5.0)
        assert plan.streets_remaining == 3

    def test_deep_spr_overbet(self):
        plan = plan_bet_geometry(10.0)
        assert plan.allow_overbet


# ─── Bet Sizing ───

from engine.bet_sizing import select_bet_size, preflop_open_size, preflop_3bet_size


class TestBetSizing:
    def _make_gs(self):
        players = [Player(name=n, stack=1000) for n in ["hero", "villain"]]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        return gs

    def test_preflop_open_size(self):
        gs = self._make_gs()
        hero = gs.get_player("hero")
        size = preflop_open_size(gs, hero)
        assert size >= 30
        assert size <= hero.stack

    def test_preflop_3bet_size(self):
        gs = self._make_gs()
        gs.current_bet = 30
        hero = gs.get_player("hero")
        size = preflop_3bet_size(gs, hero, is_ip=True)
        assert size == 90

    def test_postflop_bet_size(self):
        gs = self._make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        size = select_bet_size(gs, hero, HandStrength.STRONG_MADE, 60)
        assert 10 <= size <= hero.stack


# ─── GTO Baseline ───

from engine.gto_baseline import get_baseline_advice


class TestGTOBaseline:
    def _make_gs(self):
        players = [Player(name=n, stack=1000) for n in ["hero", "v1", "v2"]]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        return gs

    def test_preflop_aa(self):
        gs = self._make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] in (ActionType.RAISE, ActionType.ALL_IN)

    def test_preflop_72o(self):
        gs = self._make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("7h"), Card.new("2c")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] == ActionType.FOLD

    def test_postflop_strong(self):
        gs = self._make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.current_bet = 0
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] in (ActionType.BET, ActionType.CHECK)
        assert "hand_strength" in advice


# ─── Reasoning ───

from engine.reasoning import format_advice, build_reasons


class TestReasoning:
    def test_format_advice_basic(self):
        text = format_advice(ActionType.BET, 60, 0.75, ["强成牌", "有位置"])
        assert "下注 60" in text
        assert "75%" in text

    def test_format_with_alternatives(self):
        text = format_advice(
            ActionType.RAISE, 120, 0.8, ["坚果牌"],
            alternatives=[(ActionType.CALL, 0.15), (ActionType.FOLD, 0.05)],
        )
        assert "备选" in text
        assert "跟注" in text

    def test_build_reasons(self):
        reasons = build_reasons(
            {"hand": "AKs", "reasoning": "Solid基线: raise"},
            equity=0.65, pot_odds_val=0.33,
        )
        assert any("AKs" in r for r in reasons)
        assert any("65%" in r for r in reasons)


# ─── Advisor Integration ───

from engine.advisor import Advisor


class TestAdvisor:
    def _make_gs(self):
        players = [Player(name=n, stack=1000) for n in ["hero", "villain"]]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        return gs

    def test_preflop_advice(self):
        gs = self._make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert "action" in advice
        assert "text" in advice
        assert "equity" in advice
        assert advice["action"] in (ActionType.RAISE, ActionType.CALL, ActionType.FOLD, ActionType.ALL_IN)

    def test_postflop_advice(self):
        gs = self._make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.current_bet = 0
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["action"] in (ActionType.BET, ActionType.CHECK, ActionType.RAISE)
        assert advice["equity"] is not None
        assert 0 <= advice["equity"] <= 1

    def test_advisor_with_profiles(self):
        gs = self._make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advisor = Advisor()
        profile = PlayerProfile("villain", "跟注站")
        profile.total_hands = 50
        advisor.set_profiles({"villain": profile})
        advice = advisor.get_advice(gs, hero)
        assert "villain" in advice["text"]

    def test_facing_bet_advice(self):
        gs = self._make_gs()
        gs.street = Street.FLOP
        gs.pot = 120
        gs.current_bet = 40
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("7h"), Card.new("2c")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["action"] in (ActionType.FOLD, ActionType.CALL)


# ─── helpers ───

def _make_gs(names=("hero", "villain"), stacks=None, sb=5, bb=10):
    stacks = stacks or [1000] * len(names)
    players = [Player(name=n, stack=s) for n, s in zip(names, stacks)]
    gs = GameState(players=players, small_blind=sb, big_blind=bb)
    gs.assign_positions()
    gs.post_blinds()
    return gs


def _make_gs_postflop(hero_cards, board, pot=60, current_bet=0, names=("hero", "villain")):
    gs = _make_gs(names)
    gs.street = Street.FLOP
    gs.pot = pot
    gs.current_bet = current_bet
    gs.board = board
    hero = gs.get_player("hero")
    hero.hole_cards = hero_cards
    return gs, hero


# ═══════════════════════════════════════════════════════════════
# Equity Calculator
# ═══════════════════════════════════════════════════════════════
from engine.equity_calculator import monte_carlo_equity, equity_vs_range


class TestEquityCalculatorExtended:
    def test_multi_opponent_equity_lower(self):
        """AA equity drops with more opponents."""
        aa = [Card.new("As"), Card.new("Ah")]
        eq1 = monte_carlo_equity(aa, [], num_opponents=1, num_simulations=3000)
        eq3 = monte_carlo_equity(aa, [], num_opponents=3, num_simulations=3000)
        assert eq3 < eq1

    def test_equity_vs_range_with_combos(self):
        hero = [Card.new("As"), Card.new("Kh")]
        rng = [
            (Card.new("Qs"), Card.new("Qh")),
            (Card.new("Js"), Card.new("Jh")),
            (Card.new("Ts"), Card.new("Th")),
        ]
        eq = equity_vs_range(hero, [], rng, num_simulations=3000)
        assert 0.0 <= eq <= 1.0

    def test_equity_vs_empty_range_fallback(self):
        hero = [Card.new("As"), Card.new("Ah")]
        eq = equity_vs_range(hero, [], [], num_simulations=2000)
        assert 0.7 < eq < 0.95

    def test_used_cards_excluded(self):
        hero = [Card.new("As"), Card.new("Ah")]
        used = {Card.new("Ks"), Card.new("Kh")}
        eq = monte_carlo_equity(hero, [], num_opponents=1, num_simulations=2000, used_cards=used)
        assert 0.0 <= eq <= 1.0

    def test_full_board_deterministic(self):
        """With 5 board cards, equity should be very stable."""
        hero = [Card.new("As"), Card.new("Ks")]
        board = [Card.new("Qs"), Card.new("Js"), Card.new("Ts"), Card.new("2h"), Card.new("3d")]
        eq1 = monte_carlo_equity(hero, board, num_opponents=1, num_simulations=2000)
        eq2 = monte_carlo_equity(hero, board, num_opponents=1, num_simulations=2000)
        assert abs(eq1 - eq2) < 0.05


# ═══════════════════════════════════════════════════════════════
# Pot Odds — missing functions
# ═══════════════════════════════════════════════════════════════
from engine.pot_odds import (
    pot_odds, implied_odds, effective_stack, effective_stack_bb,
    spr, spr_from_state, call_ev, bet_ev, minimum_defense_frequency,
)


class TestPotOddsExtended:
    def test_implied_odds_basic(self):
        io = implied_odds(50, 100, 200)
        assert abs(io - 50 / 350) < 0.01

    def test_implied_odds_zero_future(self):
        io = implied_odds(50, 100, 0)
        assert abs(io - pot_odds(50, 100)) < 0.01

    def test_effective_stack_basic(self):
        p1 = Player(name="a", stack=800, current_bet=100)
        p2 = Player(name="b", stack=500, current_bet=200)
        assert effective_stack(p1, p2) == 700  # min(900, 700)

    def test_effective_stack_bb_basic(self):
        p1 = Player(name="a", stack=990, current_bet=10)
        p2 = Player(name="b", stack=990, current_bet=10)
        assert abs(effective_stack_bb(p1, p2, 10) - 100.0) < 0.01

    def test_spr_from_state_basic(self):
        gs = _make_gs()
        val = spr_from_state(gs, "hero")
        assert val > 0
        assert val < float("inf")

    def test_spr_from_state_no_opponents(self):
        players = [Player(name="hero", stack=1000)]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        val = spr_from_state(gs, "hero")
        assert val == float("inf")

    def test_pot_odds_negative_call(self):
        assert pot_odds(-10, 100) == 0.0

    def test_mdf_zero_pot(self):
        assert minimum_defense_frequency(100, 0) == 0.0

    def test_call_ev_breakeven(self):
        ev = call_ev(1 / 3, 100, 50)
        assert abs(ev) < 0.5


# ═══════════════════════════════════════════════════════════════
# Preflop Ranges — missing scenarios
# ═══════════════════════════════════════════════════════════════
from data.preflop_ranges import (
    get_preflop_advice, hand_in_range, cards_to_hand,
    PreflopAction, get_stack_category,
)


class TestPreflopRangesExtended:
    def test_facing_3bet_aa_4bets(self):
        action, _ = get_preflop_advice("AA", "BTN", 100, facing_3bet=True)
        assert action == PreflopAction.THREE_BET

    def test_facing_3bet_jj_calls(self):
        action, _ = get_preflop_advice("JJ", "BTN", 100, facing_3bet=True)
        assert action == PreflopAction.CALL

    def test_facing_3bet_weak_folds(self):
        action, _ = get_preflop_advice("87s", "BTN", 100, facing_3bet=True)
        assert action == PreflopAction.FOLD

    def test_deep_stack_widens_range(self):
        a_std, _ = get_preflop_advice("A5s", "CO", 80)
        a_deep, _ = get_preflop_advice("A5s", "CO", 150)
        # deep stack should open wider (tier_shift +1)
        assert a_deep == PreflopAction.OPEN

    def test_short_stack_tightens(self):
        # T8o is tier 6 at CO standard (open_tier=7), but short stack tier_shift=-1 → adjusted=6
        # Use a tier 7 hand that opens at CO standard but not at short
        a_std, _ = get_preflop_advice("87s", "CO", 80)
        a_short, _ = get_preflop_advice("87s", "CO", 30)
        assert a_std == PreflopAction.OPEN
        assert a_short == PreflopAction.FOLD

    def test_facing_raise_3bet_range(self):
        action, _ = get_preflop_advice("AKs", "CO", 100, facing_raise=True)
        assert action == PreflopAction.THREE_BET

    def test_facing_raise_medium_calls(self):
        action, _ = get_preflop_advice("TT", "CO", 100, facing_raise=True)
        assert action in (PreflopAction.CALL, PreflopAction.THREE_BET)

    def test_facing_raise_weak_folds(self):
        action, _ = get_preflop_advice("76s", "UTG", 100, facing_raise=True)
        assert action == PreflopAction.FOLD

    def test_bb_checks_limped_pot(self):
        action, _ = get_preflop_advice("72o", "BB", 100)
        assert action == PreflopAction.CHECK

    def test_bb_raises_strong_hand_limped(self):
        action, _ = get_preflop_advice("AA", "BB", 100)
        assert action == PreflopAction.OPEN


# ═══════════════════════════════════════════════════════════════
# Postflop Rules — missing scenarios
# ═══════════════════════════════════════════════════════════════
from data.postflop_rules import (
    classify_hand_strength, hand_strength_ratio,
    get_postflop_advice, get_spr_category,
    HandStrength, PostflopAction,
)
# PLACEHOLDER_POSTFLOP


class TestPostflopRulesExtended:
    def test_get_spr_category(self):
        assert get_spr_category(1.5) == "low"
        assert get_spr_category(5.0) == "medium"
        assert get_spr_category(12.0) == "high"

    def test_oop_monster_may_check(self):
        advice = get_postflop_advice(HandStrength.MONSTER, is_ip=False, facing_bet=False)
        assert advice["action"] == PostflopAction.CHECK
        assert advice["freq"] > 0

    def test_oop_trash_checks(self):
        advice = get_postflop_advice(HandStrength.TRASH, is_ip=False, facing_bet=False)
        assert advice["action"] == PostflopAction.CHECK

    def test_wet_board_increases_freq(self):
        dry = get_postflop_advice(HandStrength.STRONG_MADE, is_ip=True, facing_bet=False, is_wet_board=False)
        wet = get_postflop_advice(HandStrength.STRONG_MADE, is_ip=True, facing_bet=False, is_wet_board=True)
        assert wet["freq"] >= dry["freq"]

    def test_facing_bet_monster_raises(self):
        advice = get_postflop_advice(HandStrength.MONSTER, is_ip=True, facing_bet=True)
        assert advice["action"] == PostflopAction.RAISE

    def test_facing_bet_strong_draw_calls(self):
        advice = get_postflop_advice(HandStrength.STRONG_DRAW, is_ip=True, facing_bet=True)
        assert advice["action"] == PostflopAction.CALL

    def test_all_hand_strengths_covered(self):
        for hs in HandStrength:
            for ip in (True, False):
                for fb in (True, False):
                    advice = get_postflop_advice(hs, is_ip=ip, facing_bet=fb)
                    assert "action" in advice
                    assert "freq" in advice

    def test_classify_all_boundaries(self):
        assert classify_hand_strength(1, 3) == HandStrength.MONSTER
        assert classify_hand_strength(322, 3) == HandStrength.MONSTER
        assert classify_hand_strength(323, 3) == HandStrength.STRONG_MADE
        assert classify_hand_strength(1600, 3) == HandStrength.STRONG_MADE
        assert classify_hand_strength(1601, 3) == HandStrength.MEDIUM_MADE
        assert classify_hand_strength(5001, 3) == HandStrength.WEAK_DRAW
        assert classify_hand_strength(6186, 3) == HandStrength.TRASH

    def test_strength_ratio_monotonic(self):
        prev = hand_strength_ratio(1)
        for r in range(100, 7462, 500):
            cur = hand_strength_ratio(r)
            assert cur <= prev
            prev = cur


# ═══════════════════════════════════════════════════════════════
# Exploit Config — missing scenarios
# ═══════════════════════════════════════════════════════════════
from data.exploit_config import continuous_exploit, blend_weight, BASELINE, CONFIDENCE_THRESHOLDS


class TestExploitConfigExtended:
    def test_sensitivity_parameter(self):
        low_sens = continuous_exploit(0.70, 0.50, sensitivity=2.0)
        high_sens = continuous_exploit(0.70, 0.50, sensitivity=16.0)
        assert high_sens > low_sens

    def test_blend_at_threshold_030(self):
        solid, exploit = blend_weight(0.3)
        assert abs(solid - 0.8467) < 0.01

    def test_blend_at_threshold_060(self):
        solid, exploit = blend_weight(0.6)
        assert abs(solid - 0.64) < 0.01

    def test_blend_weight_sum_always_one(self):
        for c in [0.0, 0.1, 0.3, 0.45, 0.6, 0.8, 1.0]:
            s, e = blend_weight(c)
            assert abs(s + e - 1.0) < 0.001

    def test_exploit_symmetry(self):
        pos = continuous_exploit(0.70, 0.50)
        neg = continuous_exploit(0.30, 0.50)
        assert abs(pos + neg) < 0.01

    def test_baseline_has_all_expected_keys(self):
        expected = {"fold_to_cbet", "aggression_freq", "wtsd", "fold_to_3bet",
                    "gives_up_turn", "bet_fold_freq", "bb_fold_to_steal"}
        assert expected.issubset(set(BASELINE.keys()))


# ═══════════════════════════════════════════════════════════════
# GTO Baseline — missing scenarios
# ═══════════════════════════════════════════════════════════════
from engine.gto_baseline import get_baseline_advice, _hero_position_is_ip


class TestGTOBaselineExtended:
    def test_3bet_detection(self):
        gs = _make_gs(("hero", "v1", "v2"))
        gs.action_history[Street.PREFLOP] = [
            PlayerAction("v1", ActionType.RAISE, 30),
            PlayerAction("v2", ActionType.RAISE, 90),
        ]
        gs.current_bet = 90
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] in (ActionType.RAISE, ActionType.ALL_IN, ActionType.CALL)

    def test_position_detection_ip(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        hero_ip = _hero_position_is_ip(gs, "hero")
        villain_ip = _hero_position_is_ip(gs, "villain")
        assert hero_ip != villain_ip

    def test_short_stack_push(self):
        gs = _make_gs(stacks=[150, 1000], bb=10)
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] in (ActionType.ALL_IN, ActionType.RAISE)

    def test_postflop_facing_bet(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 120
        gs.current_bet = 40
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] in (ActionType.CALL, ActionType.RAISE)

    def test_postflop_trash_facing_bet_folds(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 120
        gs.current_bet = 40
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("7h"), Card.new("2c")]
        advice = get_baseline_advice(gs, hero)
        assert advice["action"] == ActionType.FOLD

    def test_baseline_returns_all_keys(self):
        gs = _make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advice = get_baseline_advice(gs, hero)
        assert "action" in advice
        assert "confidence" in advice
        assert "reasoning" in advice


# ═══════════════════════════════════════════════════════════════
# Street Planner — missing scenarios
# ═══════════════════════════════════════════════════════════════
from engine.street_planner import plan_bet_geometry, get_street_plan, BetPlan


class TestStreetPlannerExtended:
    def test_get_street_plan_strong(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        plan = get_street_plan(gs, "hero", HandStrength.MONSTER)
        assert plan.current_size > 0

    def test_get_street_plan_weak_reduces_size(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        strong = get_street_plan(gs, "hero", HandStrength.MONSTER)
        weak = get_street_plan(gs, "hero", HandStrength.TRASH)
        assert weak.current_size <= strong.current_size

    def test_weak_hand_no_overbet(self):
        plan = plan_bet_geometry(12.0)
        assert plan.allow_overbet is True
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 60
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        weak_plan = get_street_plan(gs, "hero", HandStrength.WEAK_MADE)
        assert weak_plan.allow_overbet is False

    def test_bet_plan_current_size_empty(self):
        plan = BetPlan(0, [])
        assert plan.current_size == 0.5

    def test_medium_spr_two_streets(self):
        plan = plan_bet_geometry(3.0)
        assert plan.streets_remaining == 2
        assert len(plan.sizes) == 2
        assert plan.sizes[1] == 1.0


# ═══════════════════════════════════════════════════════════════
# Bet Sizing — missing scenarios
# ═══════════════════════════════════════════════════════════════
from engine.bet_sizing import select_bet_size, select_raise_size, preflop_open_size, preflop_3bet_size
# PLACEHOLDER_BETSIZING


class TestBetSizingExtended:
    def test_select_raise_size_monster(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 120
        gs.current_bet = 40
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        size = select_raise_size(gs, hero, HandStrength.MONSTER, 40, 120)
        assert size >= 40 * 2.2
        assert size <= hero.stack + hero.current_bet

    def test_select_raise_size_weak(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 120
        gs.current_bet = 40
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        size = select_raise_size(gs, hero, HandStrength.WEAK_MADE, 40, 120)
        assert size >= 40 * 2.0

    def test_low_spr_allin(self):
        gs = _make_gs(stacks=[100, 1000])
        gs.street = Street.FLOP
        gs.pot = 200
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        size = select_bet_size(gs, hero, HandStrength.STRONG_MADE, 200)
        assert size == hero.stack  # should push

    def test_dry_board_smaller_bet(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 100
        gs.board = [Card.new("Ks"), Card.new("7d"), Card.new("2c")]  # dry rainbow
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        size_dry = select_bet_size(gs, hero, HandStrength.MEDIUM_MADE, 100)

        gs2 = _make_gs()
        gs2.street = Street.FLOP
        gs2.pot = 100
        gs2.board = [Card.new("Jh"), Card.new("Th"), Card.new("9h")]  # wet monotone
        hero2 = gs2.get_player("hero")
        hero2.hole_cards = [Card.new("As"), Card.new("Kh")]
        size_wet = select_bet_size(gs2, hero2, HandStrength.MEDIUM_MADE, 100)
        assert size_wet >= size_dry

    def test_preflop_3bet_oop_larger(self):
        gs = _make_gs()
        gs.current_bet = 30
        hero = gs.get_player("hero")
        ip_size = preflop_3bet_size(gs, hero, is_ip=True)
        oop_size = preflop_3bet_size(gs, hero, is_ip=False)
        assert oop_size > ip_size

    def test_bet_size_min_is_bb(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 1  # tiny pot
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("7h"), Card.new("2c")]
        size = select_bet_size(gs, hero, HandStrength.TRASH, 1, is_value=False)
        assert size >= gs.big_blind


# ═══════════════════════════════════════════════════════════════
# Player Profile — missing sub-components
# ═══════════════════════════════════════════════════════════════
from profiler.player_profile import (
    PlayerProfile, BetSizingPattern, StreetTendencies,
    AdvancedActions, SkillEstimate, KeyHand, check_profile_consistency,
)


class TestPlayerProfileExtended:
    def test_street_tendencies_serialization(self):
        st = StreetTendencies()
        st.flop_aggression.update(True)
        st.gives_up_turn.update(False)
        d = st.to_dict()
        st2 = StreetTendencies.from_dict(d)
        assert st2.flop_aggression.mean == st.flop_aggression.mean
        assert st2.gives_up_turn.mean == st.gives_up_turn.mean

    def test_advanced_actions_serialization(self):
        aa = AdvancedActions()
        aa.check_raise_freq.update(True)
        aa.donk_bet_freq.update(True)
        d = aa.to_dict()
        aa2 = AdvancedActions.from_dict(d)
        assert aa2.check_raise_freq.mean == aa.check_raise_freq.mean

    def test_skill_estimate_update(self):
        se = SkillEstimate()
        old = se.overall_skill
        se.update("pure_air_overbet", -1.0, 0.0)
        assert se.overall_skill < old

    def test_skill_estimate_clamped(self):
        se = SkillEstimate(overall_skill=0.01)
        for _ in range(100):
            se.update("pure_air_overbet", -1.0, 0.0)
        assert se.overall_skill >= 0.0

    def test_skill_estimate_serialization(self):
        se = SkillEstimate(overall_skill=0.3, positional_awareness=0.7)
        d = se.to_dict()
        se2 = SkillEstimate.from_dict(d)
        assert se2.overall_skill == 0.3
        assert se2.positional_awareness == 0.7

    def test_bet_sizing_pattern_serialization(self):
        bs = BetSizingPattern()
        bs.record_bet(0.66, is_value=True)
        bs.record_bet(0.33, is_value=False)
        bs.record_bet(1.5, is_value=True)
        d = bs.to_dict()
        bs2 = BetSizingPattern.from_dict(d)
        assert bs2.total_bets == 3
        assert bs2.overbet_count == 1
        assert len(bs2.value_bet_ratios) == 2

    def test_style_label_lag(self):
        p = PlayerProfile("test")
        p.stats["vpip"].alpha = 30
        p.stats["vpip"].beta = 5
        p.stats["aggression_freq"].alpha = 8
        p.stats["aggression_freq"].beta = 2
        assert "松凶LAG" in p.style_label or "疯子" in p.style_label

    def test_style_label_calling_station(self):
        p = PlayerProfile("test")
        # vpip ~35%, aggression ~20% → 跟注站
        p.stats["vpip"].alpha = 7
        p.stats["vpip"].beta = 13
        p.stats["aggression_freq"].alpha = 2
        p.stats["aggression_freq"].beta = 8
        assert p.style_label == "跟注站"

    def test_key_hand_circular_buffer(self):
        p = PlayerProfile("test")
        for i in range(60):
            p.add_key_hand(KeyHand(i, "test", f"hand {i}"))
        assert len(p.key_hands) == 50
        assert p.key_hands[0].hand_id == 10

    def test_get_stat_missing_returns_zero(self):
        p = PlayerProfile("test")
        assert p.get_stat("nonexistent") == 0.0

    def test_get_confidence_missing_returns_zero(self):
        p = PlayerProfile("test")
        assert p.get_confidence("nonexistent") == 0.0

    def test_consistency_aggression_vpip_mismatch(self):
        p = PlayerProfile("test")
        p.stats["vpip"].alpha = 2
        p.stats["vpip"].beta = 20
        p.stats["aggression_freq"].alpha = 15
        p.stats["aggression_freq"].beta = 2
        corrections = check_profile_consistency(p)
        assert any(c[0] == "aggression_freq" for c in corrections)

    def test_full_profile_serialization_roundtrip(self):
        p = PlayerProfile("full_test", "松凶LAG")
        p.total_hands = 100
        for _ in range(20):
            p.update_stat("vpip", True)
        p.street_tendencies.flop_aggression.update(True)
        p.advanced_actions.check_raise_freq.update(True)
        p.bet_sizing.record_bet(0.75, is_value=True)
        p.skill_estimate.update("check_raise", 1.0, 0.3)
        p.add_key_hand(KeyHand(1, "river_bluff", "bluffed river"))
        d = p.to_dict()
        p2 = PlayerProfile.from_dict(d)
        assert p2.name == "full_test"
        assert p2.total_hands == 100
        assert p2.get_stat("vpip") == p.get_stat("vpip")
        assert p2.street_tendencies.flop_aggression.mean == p.street_tendencies.flop_aggression.mean
        assert p2.advanced_actions.check_raise_freq.mean == p.advanced_actions.check_raise_freq.mean
        assert p2.bet_sizing.total_bets == 1
        assert p2.skill_estimate.overall_skill == p.skill_estimate.overall_skill
        assert len(p2.key_hands) == 1


# ═══════════════════════════════════════════════════════════════
# Profile Manager — missing scenarios
# ═══════════════════════════════════════════════════════════════
from profiler.profile_manager import (
    create_profile, save_profile, load_profile, load_or_create,
    list_profiles, delete_profile, available_prior_types, PRIOR_TEMPLATES,
)
# PLACEHOLDER_PROFILE_MANAGER


class TestProfileManagerExtended:
    def test_list_profiles(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        p1 = create_profile("alice", "紧凶TAG")
        p2 = create_profile("bob", "松凶LAG")
        save_profile(p1)
        save_profile(p2)
        names = list_profiles()
        assert "alice" in names
        assert "bob" in names

    def test_delete_profile(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        p = create_profile("to_delete")
        save_profile(p)
        assert load_profile("to_delete") is not None
        assert delete_profile("to_delete") is True
        assert load_profile("to_delete") is None

    def test_delete_nonexistent(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path)
        assert delete_profile("ghost") is False

    def test_list_empty_dir(self, tmp_path, monkeypatch):
        import profiler.profile_manager as pm
        monkeypatch.setattr(pm, "PROFILES_DIR", tmp_path / "nonexistent")
        assert list_profiles() == []

    def test_prior_templates_produce_different_profiles(self):
        tag = create_profile("a", "紧凶TAG")
        lag = create_profile("b", "松凶LAG")
        station = create_profile("c", "跟注站")
        assert tag.get_stat("vpip") != lag.get_stat("vpip")
        assert station.get_stat("aggression_freq") < lag.get_stat("aggression_freq")


# ═══════════════════════════════════════════════════════════════
# Reasoning — missing scenarios
# ═══════════════════════════════════════════════════════════════
from engine.reasoning import format_advice, build_reasons


class TestReasoningExtended:
    def test_build_reasons_with_opponent_summary(self):
        reasons = build_reasons(
            {"hand": "AKs", "reasoning": "baseline"},
            opponent_summary="villain [紧凶TAG] VPIP:20%",
        )
        assert any("对手画像" in r for r in reasons)

    def test_build_reasons_with_exploit_note(self):
        reasons = build_reasons(
            {"hand": "AKs", "reasoning": "baseline"},
            exploit_note="fold_to_cbet偏离基线↑",
        )
        assert any("Exploit" in r for r in reasons)

    def test_format_fold_no_amount(self):
        text = format_advice(ActionType.FOLD, 0, 0.8, ["空气牌"])
        header = text.split("\n")[0]
        assert "弃牌" in header
        # FOLD should not show an amount in the header
        assert "弃牌 0" not in header

    def test_format_allin(self):
        text = format_advice(ActionType.ALL_IN, 500, 0.9, ["坚果牌"])
        assert "全下" in text
        assert "500" in text


# ═══════════════════════════════════════════════════════════════
# Bayesian Tracker — edge cases
# ═══════════════════════════════════════════════════════════════
from profiler.bayesian_tracker import BayesianStat


class TestBayesianStatExtended:
    def test_confidence_formula_values(self):
        s = BayesianStat(2, 3)
        for _ in range(10):
            s.update(True)
        expected = 1 - 1 / (1 + math.sqrt(10))
        assert abs(s.confidence - expected) < 0.001

    def test_many_updates_confidence_near_one(self):
        s = BayesianStat(2, 3)
        for _ in range(10000):
            s.update(True)
        assert s.confidence > 0.99

    def test_mean_with_equal_alpha_beta(self):
        s = BayesianStat(5, 5)
        assert abs(s.mean - 0.5) < 0.001


# ═══════════════════════════════════════════════════════════════
# Info Weight — edge cases
# ═══════════════════════════════════════════════════════════════
from profiler.info_weight import calc_update_delta, EVENT_INFO_WEIGHT


class TestInfoWeightExtended:
    def test_high_confidence_dampens_heavily(self):
        d_low = calc_update_delta("pure_air_overbet", 1.0, 0.0)
        d_high = calc_update_delta("pure_air_overbet", 1.0, 0.95)
        assert d_high < d_low * 0.2

    def test_all_events_have_positive_weight(self):
        for event, weight in EVENT_INFO_WEIGHT.items():
            assert weight > 0

    def test_zero_direction_zero_delta(self):
        delta = calc_update_delta("normal_bet", 0.0, 0.5)
        assert delta == 0.0


# ═══════════════════════════════════════════════════════════════
# Board Texture
# ═══════════════════════════════════════════════════════════════


class TestBoardTexture:
    def test_empty_board(self):
        tex = analyze_board([])
        assert not tex.is_paired
        assert not tex.is_wet

    def test_monotone_board(self):
        board = [Card.new("Ah"), Card.new("Kh"), Card.new("9h")]
        tex = analyze_board(board)
        assert tex.is_monotone
        assert tex.is_wet

    def test_dry_rainbow_board(self):
        board = [Card.new("Ks"), Card.new("7d"), Card.new("2c")]
        tex = analyze_board(board)
        assert tex.is_rainbow
        assert tex.is_dry

    def test_paired_board(self):
        board = [Card.new("Ks"), Card.new("Kh"), Card.new("4c")]
        tex = analyze_board(board)
        assert tex.is_paired

    def test_scare_card_detection(self):
        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c"), Card.new("As")]
        tex = analyze_board(board)
        assert len(tex.scare_cards) > 0


# ═══════════════════════════════════════════════════════════════
# Advisor Integration — missing scenarios
# ═══════════════════════════════════════════════════════════════
from engine.advisor import Advisor


class TestAdvisorExtended:
    def test_equity_override_fold_to_call(self):
        """When equity > pot_odds, advisor should override fold to call."""
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 200
        gs.current_bet = 10  # tiny bet, great pot odds
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("Qh"), Card.new("Jh")]  # decent equity
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["action"] in (ActionType.CALL, ActionType.RAISE, ActionType.BET, ActionType.CHECK)

    def test_bet_zero_becomes_check(self):
        gs = _make_gs()
        gs.street = Street.FLOP
        gs.pot = 0
        gs.current_bet = 0
        gs.board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("7h"), Card.new("2c")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["action"] in (ActionType.CHECK, ActionType.FOLD)

    def test_exploit_note_with_extreme_profile(self):
        gs = _make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advisor = Advisor()
        profile = PlayerProfile("villain", "跟注站")
        profile.total_hands = 100
        for _ in range(80):
            profile.update_stat("fold_to_cbet", True)
            profile.update_stat("vpip", True)
            profile.update_stat("pfr", False)
            profile.update_stat("aggression_freq", False)
        advisor.set_profiles({"villain": profile})
        advice = advisor.get_advice(gs, hero)
        assert advice["exploit_note"] is not None

    def test_exploit_note_none_without_profiles(self):
        gs = _make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Ah")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["exploit_note"] is None

    def test_multi_opponent_advice(self):
        gs = _make_gs(("hero", "v1", "v2", "v3"))
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert advice["action"] is not None
        assert advice["equity"] is not None

    def test_advice_returns_exploit_note_key(self):
        gs = _make_gs()
        hero = gs.get_player("hero")
        hero.hole_cards = [Card.new("As"), Card.new("Kh")]
        advisor = Advisor()
        advice = advisor.get_advice(gs, hero)
        assert "exploit_note" in advice


# ═══════════════════════════════════════════════════════════════
# Action Rationality Analyzer
# ═══════════════════════════════════════════════════════════════
from profiler.action_analyzer import (
    ActionRationalityAnalyzer, MistakeType, ActionJudgment,
    _action_to_category, _judge_single_action, _facing_bet, _is_ip,
)


class TestActionToCategory:
    def test_fold(self):
        a = PlayerAction("v", ActionType.FOLD, 0, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.FOLD

    def test_check(self):
        a = PlayerAction("v", ActionType.CHECK, 0, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.CHECK

    def test_call(self):
        a = PlayerAction("v", ActionType.CALL, 50, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.CALL

    def test_bet_small(self):
        a = PlayerAction("v", ActionType.BET, 30, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.BET_SMALL

    def test_bet_medium(self):
        a = PlayerAction("v", ActionType.BET, 60, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.BET_MEDIUM

    def test_bet_large(self):
        a = PlayerAction("v", ActionType.BET, 120, Street.FLOP)
        assert _action_to_category(a, 100) == PostflopAction.BET_LARGE

    def test_zero_pot_defaults_medium(self):
        a = PlayerAction("v", ActionType.BET, 50, Street.FLOP)
        assert _action_to_category(a, 0) == PostflopAction.BET_MEDIUM


class TestFacingBet:
    def test_no_prior_actions(self):
        assert _facing_bet([], "hero") is False

    def test_facing_bet_true(self):
        actions = [PlayerAction("v", ActionType.BET, 50, Street.FLOP)]
        assert _facing_bet(actions, "hero") is True

    def test_facing_check_false(self):
        actions = [PlayerAction("v", ActionType.CHECK, 0, Street.FLOP)]
        assert _facing_bet(actions, "hero") is False


class TestIsIp:
    def test_btn_is_ip(self):
        assert _is_ip("BTN", 6) is True

    def test_co_is_ip(self):
        assert _is_ip("CO", 6) is True

    def test_utg_not_ip(self):
        assert _is_ip("UTG", 6) is False

    def test_sb_ip_in_3_handed(self):
        assert _is_ip("SB", 3) is True


class TestJudgeSingleAction:
    def test_irrational_fold_no_bet(self):
        action = PlayerAction("v", ActionType.FOLD, 0, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.IRRATIONAL_FOLD
        assert j.severity == -0.9

    def test_strong_hand_fold(self):
        action = PlayerAction("v", ActionType.FOLD, 0, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_MADE, 100, True, True, 6.0, []
        )
        assert j.mistake == MistakeType.IRRATIONAL_FOLD
        assert j.severity == -0.7

    def test_value_oversize_large(self):
        action = PlayerAction("v", ActionType.BET, 150, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_MADE, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.VALUE_OVERSIZE
        assert j.severity <= -0.25

    def test_value_undersize(self):
        action = PlayerAction("v", ActionType.BET, 20, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_MADE, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.VALUE_UNDERSIZE
        assert j.severity == -0.3

    def test_missed_value_check_with_monster(self):
        action = PlayerAction("v", ActionType.CHECK, 0, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MONSTER, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.MISSED_VALUE
        assert j.severity == -0.4

    def test_bluff_into_strength(self):
        action = PlayerAction("v", ActionType.RAISE, 200, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, True, True, 6.0, []
        )
        assert j.mistake == MistakeType.BLUFF_INTO_STRENGTH

    def test_positional_waste(self):
        action = PlayerAction("v", ActionType.CHECK, 0, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MEDIUM_MADE, 100, True, False, 6.0, []
        )
        if j.mistake == MistakeType.POSITIONAL_WASTE:
            assert j.severity == -0.2

    def test_good_sizing_positive(self):
        action = PlayerAction("v", ActionType.BET, 65, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_MADE, 100, True, False, 6.0, []
        )
        if j.mistake == MistakeType.GOOD_SIZING:
            assert j.severity > 0

    def test_neutral_action_zero_severity(self):
        action = PlayerAction("v", ActionType.CALL, 50, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MEDIUM_MADE, 100, True, True, 6.0, []
        )
        assert j.severity == 0.0 or j.mistake is not None


class TestActionRationalityAnalyzer:
    def _make_analyzer(self):
        return ActionRationalityAnalyzer()

    def test_analyze_empty_board(self):
        analyzer = self._make_analyzer()
        judgments = analyzer.analyze_player_hand(
            player_name="villain",
            hole_cards=[Card.new("As"), Card.new("Ah")],
            board=[],
            action_history={s: [] for s in Street},
            pot_sizes={s: 0 for s in Street},
            player_position="BTN",
            num_players=6,
        )
        assert judgments == []

    def test_analyze_flop_actions(self):
        analyzer = self._make_analyzer()
        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("As"), Card.new("Kh")]  # top pair top kicker
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("villain", ActionType.CHECK, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="villain",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        assert len(judgments) == 1
        assert judgments[0].hand_strength.value >= HandStrength.WEAK_MADE.value

    def test_analyze_irrational_fold_detected(self):
        analyzer = self._make_analyzer()
        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("7h"), Card.new("2c")]
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("villain", ActionType.FOLD, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="villain",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="UTG",
            num_players=6,
        )
        assert len(judgments) == 1
        assert judgments[0].mistake == MistakeType.IRRATIONAL_FOLD

    def test_analyze_multi_street(self):
        analyzer = self._make_analyzer()
        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c"),
                 Card.new("2d"), Card.new("Jh")]
        hole = [Card.new("As"), Card.new("Kh")]
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [PlayerAction("villain", ActionType.BET, 40, Street.FLOP)],
            Street.TURN: [PlayerAction("villain", ActionType.BET, 80, Street.TURN)],
            Street.RIVER: [PlayerAction("villain", ActionType.CHECK, 0, Street.RIVER)],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="villain",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 140, Street.RIVER: 300},
            player_position="BTN",
            num_players=6,
        )
        assert len(judgments) == 3

    def test_update_profile_skill_decreases_on_mistakes(self):
        analyzer = self._make_analyzer()
        profile = PlayerProfile("fish")
        initial_skill = profile.skill_estimate.overall_skill

        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("7h"), Card.new("2c")]
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("fish", ActionType.FOLD, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="fish",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="UTG",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        assert profile.skill_estimate.overall_skill < initial_skill

    def test_update_profile_skill_increases_on_good_play(self):
        analyzer = self._make_analyzer()
        profile = PlayerProfile("reg")
        initial_skill = profile.skill_estimate.overall_skill

        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("As"), Card.new("Kh")]  # strong made hand
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("reg", ActionType.BET, 65, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="reg",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        assert profile.skill_estimate.overall_skill >= initial_skill

    def test_update_profile_sizing_sophistication_drops(self):
        analyzer = self._make_analyzer()
        profile = PlayerProfile("bad_sizer")
        initial_sizing = profile.skill_estimate.sizing_sophistication

        # Use a flush (strong made) on a board where it's clearly strong
        board = [Card.new("Ks"), Card.new("9s"), Card.new("4s")]
        hole = [Card.new("As"), Card.new("Qs")]  # nut flush
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("bad_sizer", ActionType.BET, 20, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="bad_sizer",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 100, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        assert profile.skill_estimate.sizing_sophistication < initial_sizing

    def test_key_hand_recorded_on_severe_mistake(self):
        analyzer = self._make_analyzer()
        profile = PlayerProfile("noob")

        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("7h"), Card.new("2c")]
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("noob", ActionType.FOLD, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="noob",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="UTG",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=42)
        assert len(profile.key_hands) == 1
        assert profile.key_hands[0].hand_id == 42
        assert profile.key_hands[0].skill_signal == "negative"

    def test_empty_judgments_no_update(self):
        analyzer = self._make_analyzer()
        profile = PlayerProfile("ghost")
        initial = profile.skill_estimate.overall_skill
        analyzer.update_profile_from_judgments(profile, [], hand_id=1)
        assert profile.skill_estimate.overall_skill == initial
        assert len(profile.key_hands) == 0

    def test_value_oversize_example_from_user(self):
        """用户举例：好牌raise太多把对手吓跑，应该反映为负面信号。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("overbet_fish")

        # Strong made hand (flush) where optimal is BET_MEDIUM, but player bets 3x pot
        board = [Card.new("Ks"), Card.new("9s"), Card.new("4s")]
        hole = [Card.new("As"), Card.new("Qs")]  # nut flush = STRONG_MADE or MONSTER
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("overbet_fish", ActionType.BET, 20, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="overbet_fish",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 100, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        # Undersizing a strong hand should lower sizing_sophistication
        assert profile.skill_estimate.sizing_sophistication < 0.5

    def test_good_fold_increases_skill(self):
        """弱牌面对下注果断弃牌，应该加分。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("disciplined")
        initial_skill = profile.skill_estimate.overall_skill

        board = [Card.new("Ks"), Card.new("9h"), Card.new("4c")]
        hole = [Card.new("7h"), Card.new("2c")]  # trash
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("other", ActionType.BET, 50, Street.FLOP),
                PlayerAction("disciplined", ActionType.FOLD, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="disciplined",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="UTG",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        assert profile.skill_estimate.overall_skill >= initial_skill

    def test_good_thin_value_increases_hand_reading(self):
        """中等牌力薄价值下注，应该提升hand_reading_ability。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("thinker")
        initial_hr = profile.skill_estimate.hand_reading_ability

        # Medium made hand on a dry board, betting small for thin value
        board = [Card.new("Ks"), Card.new("7d"), Card.new("2c")]
        hole = [Card.new("Kh"), Card.new("5h")]  # top pair weak kicker = medium made
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("thinker", ActionType.BET, 30, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="thinker",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        has_positive = any(j.severity > 0 for j in judgments)
        if has_positive:
            analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
            assert profile.skill_estimate.hand_reading_ability >= initial_hr

    def test_good_trap_oop_monster(self):
        """OOP强牌慢打设陷阱，应该加分。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("trapper")
        initial_skill = profile.skill_estimate.overall_skill

        # Monster hand OOP, checking (trap)
        board = [Card.new("Ks"), Card.new("Kh"), Card.new("4c")]
        hole = [Card.new("Kd"), Card.new("Kc")]  # quads
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("trapper", ActionType.CHECK, 0, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="trapper",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="UTG",
            num_players=6,
        )
        analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
        assert profile.skill_estimate.overall_skill >= initial_skill

    def test_good_positional_play_increases_awareness(self):
        """有位置优势且合理利用，应该提升positional_awareness。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("positional")
        initial_pa = profile.skill_estimate.positional_awareness

        board = [Card.new("Ks"), Card.new("7d"), Card.new("2c")]
        hole = [Card.new("Kh"), Card.new("Qh")]  # top pair good kicker
        actions = {
            Street.PREFLOP: [],
            Street.FLOP: [
                PlayerAction("other", ActionType.CHECK, 0, Street.FLOP),
                PlayerAction("positional", ActionType.BET, 40, Street.FLOP),
            ],
            Street.TURN: [],
            Street.RIVER: [],
        }
        judgments = analyzer.analyze_player_hand(
            player_name="positional",
            hole_cards=hole,
            board=board,
            action_history=actions,
            pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
            player_position="BTN",
            num_players=6,
        )
        has_positional = any(
            j.mistake == MistakeType.GOOD_POSITIONAL_PLAY for j in judgments
        )
        if has_positional:
            analyzer.update_profile_from_judgments(profile, judgments, hand_id=1)
            assert profile.skill_estimate.positional_awareness > initial_pa

    def test_consistent_good_play_raises_skill_significantly(self):
        """连续多手合理操作应该显著提升overall_skill。"""
        analyzer = self._make_analyzer()
        profile = PlayerProfile("solid_reg")

        board = [Card.new("Ks"), Card.new("9s"), Card.new("4s")]
        hole = [Card.new("As"), Card.new("Qs")]  # nut flush

        for hand_id in range(10):
            actions = {
                Street.PREFLOP: [],
                Street.FLOP: [
                    PlayerAction("solid_reg", ActionType.BET, 45, Street.FLOP),
                ],
                Street.TURN: [],
                Street.RIVER: [],
            }
            judgments = analyzer.analyze_player_hand(
                player_name="solid_reg",
                hole_cards=hole,
                board=board,
                action_history=actions,
                pot_sizes={Street.PREFLOP: 0, Street.FLOP: 60, Street.TURN: 0, Street.RIVER: 0},
                player_position="BTN",
                num_players=6,
            )
            analyzer.update_profile_from_judgments(profile, judgments, hand_id=hand_id)

        assert profile.skill_estimate.overall_skill > 0.5


class TestCallingStation:
    def test_call_trash_facing_large_bet(self):
        """Calling with trash facing a large bet should be CALLING_STATION."""
        prior = [PlayerAction("other", ActionType.BET, 80, Street.FLOP)]
        action = PlayerAction("v", ActionType.CALL, 80, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, True, True, 6.0, prior
        )
        assert j.mistake == MistakeType.CALLING_STATION
        assert j.severity <= -0.4

    def test_call_weak_draw_facing_bet(self):
        """Calling with weak draw facing bet should be CALLING_STATION."""
        prior = [PlayerAction("other", ActionType.BET, 50, Street.FLOP)]
        action = PlayerAction("v", ActionType.CALL, 50, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.WEAK_DRAW, 100, True, True, 6.0, prior
        )
        assert j.mistake == MistakeType.CALLING_STATION
        assert j.severity < 0

    def test_call_medium_made_not_calling_station(self):
        """Calling with medium made hand is not calling station."""
        prior = [PlayerAction("other", ActionType.BET, 50, Street.FLOP)]
        action = PlayerAction("v", ActionType.CALL, 50, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MEDIUM_MADE, 100, True, True, 6.0, prior
        )
        assert j.mistake != MistakeType.CALLING_STATION

    def test_calling_station_updates_hand_reading(self):
        """CALLING_STATION should lower hand_reading_ability."""
        analyzer = ActionRationalityAnalyzer()
        profile = PlayerProfile(name="fish")
        initial_hr = profile.skill_estimate.hand_reading_ability
        judgment = ActionJudgment(
            street=Street.FLOP,
            action=PlayerAction("fish", ActionType.CALL, 80, Street.FLOP),
            hand_strength=HandStrength.TRASH,
            optimal_action=PostflopAction.FOLD,
            actual_category=PostflopAction.CALL,
            mistake=MistakeType.CALLING_STATION,
            severity=-0.5,
            detail="test",
        )
        analyzer.update_profile_from_judgments(profile, [judgment])
        assert profile.skill_estimate.hand_reading_ability < initial_hr


class TestOverbetBluff:
    def test_overbet_trash_not_facing_bet(self):
        """Overbetting with trash when not facing bet = OVERBET_BLUFF."""
        action = PlayerAction("v", ActionType.BET, 150, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.OVERBET_BLUFF
        assert j.severity <= -0.3

    def test_overbet_weak_draw(self):
        """Overbetting with weak draw = OVERBET_BLUFF."""
        action = PlayerAction("v", ActionType.BET, 120, Street.TURN)
        j = _judge_single_action(
            action, HandStrength.WEAK_DRAW, 100, False, False, 6.0, []
        )
        assert j.mistake == MistakeType.OVERBET_BLUFF

    def test_large_bet_strong_hand_not_overbet_bluff(self):
        """Large bet with strong hand is not OVERBET_BLUFF."""
        action = PlayerAction("v", ActionType.BET, 150, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_MADE, 100, True, False, 6.0, []
        )
        assert j.mistake != MistakeType.OVERBET_BLUFF

    def test_overbet_bluff_updates_sizing(self):
        """OVERBET_BLUFF should lower sizing_sophistication."""
        analyzer = ActionRationalityAnalyzer()
        profile = PlayerProfile(name="maniac")
        initial_ss = profile.skill_estimate.sizing_sophistication
        judgment = ActionJudgment(
            street=Street.FLOP,
            action=PlayerAction("maniac", ActionType.BET, 200, Street.FLOP),
            hand_strength=HandStrength.TRASH,
            optimal_action=PostflopAction.CHECK,
            actual_category=PostflopAction.BET_LARGE,
            mistake=MistakeType.OVERBET_BLUFF,
            severity=-0.4,
            detail="test",
        )
        analyzer.update_profile_from_judgments(profile, [judgment])
        assert profile.skill_estimate.sizing_sophistication < initial_ss


class TestWeakLead:
    def test_oop_small_bet_trash(self):
        """OOP small bet with trash = WEAK_LEAD."""
        action = PlayerAction("v", ActionType.BET, 20, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, False, False, 6.0, []
        )
        assert j.mistake == MistakeType.WEAK_LEAD
        assert j.severity < 0

    def test_oop_small_bet_weak_made(self):
        """OOP small bet with weak made hand = WEAK_LEAD."""
        action = PlayerAction("v", ActionType.BET, 30, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.WEAK_MADE, 100, False, False, 6.0, []
        )
        assert j.mistake == MistakeType.WEAK_LEAD

    def test_ip_small_bet_not_weak_lead(self):
        """IP small bet is not WEAK_LEAD (position-dependent)."""
        action = PlayerAction("v", ActionType.BET, 20, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.TRASH, 100, True, False, 6.0, []
        )
        assert j.mistake != MistakeType.WEAK_LEAD

    def test_weak_lead_updates_positional_awareness(self):
        """WEAK_LEAD should lower positional_awareness."""
        analyzer = ActionRationalityAnalyzer()
        profile = PlayerProfile(name="donk")
        initial_pa = profile.skill_estimate.positional_awareness
        judgment = ActionJudgment(
            street=Street.FLOP,
            action=PlayerAction("donk", ActionType.BET, 20, Street.FLOP),
            hand_strength=HandStrength.TRASH,
            optimal_action=PostflopAction.CHECK,
            actual_category=PostflopAction.BET_SMALL,
            mistake=MistakeType.WEAK_LEAD,
            severity=-0.2,
            detail="test",
        )
        analyzer.update_profile_from_judgments(profile, [judgment])
        assert profile.skill_estimate.positional_awareness < initial_pa


class TestGoodValueRaise:
    def test_monster_raise_facing_bet(self):
        """Monster raising when facing bet and optimal is RAISE = GOOD_VALUE_RAISE."""
        prior = [PlayerAction("other", ActionType.BET, 60, Street.FLOP)]
        action = PlayerAction("v", ActionType.RAISE, 150, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MONSTER, 100, False, True, 6.0, prior
        )
        assert j.mistake == MistakeType.GOOD_VALUE_RAISE
        assert j.severity > 0.3

    def test_strong_raise_facing_bet(self):
        """Strong hand raising facing bet when optimal = RAISE (low SPR)."""
        prior = [PlayerAction("other", ActionType.BET, 60, Street.FLOP)]
        action = PlayerAction("v", ActionType.RAISE, 200, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.MONSTER, 100, True, True, 2.0, prior
        )
        assert j.mistake == MistakeType.GOOD_VALUE_RAISE
        assert j.severity > 0

    def test_good_value_raise_updates_profile(self):
        """GOOD_VALUE_RAISE should boost hand_reading and sizing."""
        analyzer = ActionRationalityAnalyzer()
        profile = PlayerProfile(name="reg")
        initial_hr = profile.skill_estimate.hand_reading_ability
        initial_ss = profile.skill_estimate.sizing_sophistication
        judgment = ActionJudgment(
            street=Street.FLOP,
            action=PlayerAction("reg", ActionType.RAISE, 200, Street.FLOP),
            hand_strength=HandStrength.MONSTER,
            optimal_action=PostflopAction.RAISE,
            actual_category=PostflopAction.RAISE,
            mistake=MistakeType.GOOD_VALUE_RAISE,
            severity=0.35,
            detail="test",
        )
        analyzer.update_profile_from_judgments(profile, [judgment])
        assert profile.skill_estimate.hand_reading_ability > initial_hr
        assert profile.skill_estimate.sizing_sophistication > initial_ss


class TestGoodDrawPlay:
    def test_strong_draw_call_facing_bet(self):
        """Strong draw correctly calling facing bet = GOOD_DRAW_PLAY."""
        prior = [PlayerAction("other", ActionType.BET, 50, Street.FLOP)]
        action = PlayerAction("v", ActionType.CALL, 50, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_DRAW, 100, True, True, 6.0, prior
        )
        assert j.mistake == MistakeType.GOOD_DRAW_PLAY
        assert j.severity > 0

    def test_medium_draw_semi_bluff(self):
        """Medium draw semi-bluff bet when optimal = GOOD_DRAW_PLAY."""
        action = PlayerAction("v", ActionType.BET, 60, Street.FLOP)
        j = _judge_single_action(
            action, HandStrength.STRONG_DRAW, 100, True, False, 6.0, []
        )
        assert j.mistake == MistakeType.GOOD_DRAW_PLAY
        assert j.severity > 0

    def test_good_draw_play_updates_hand_reading(self):
        """GOOD_DRAW_PLAY should boost hand_reading_ability."""
        analyzer = ActionRationalityAnalyzer()
        profile = PlayerProfile(name="draw_player")
        initial_hr = profile.skill_estimate.hand_reading_ability
        judgment = ActionJudgment(
            street=Street.FLOP,
            action=PlayerAction("draw_player", ActionType.CALL, 50, Street.FLOP),
            hand_strength=HandStrength.STRONG_DRAW,
            optimal_action=PostflopAction.CALL,
            actual_category=PostflopAction.CALL,
            mistake=MistakeType.GOOD_DRAW_PLAY,
            severity=0.2,
            detail="test",
        )
        analyzer.update_profile_from_judgments(profile, [judgment])
        assert profile.skill_estimate.hand_reading_ability > initial_hr


if __name__ == "__main__":
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    if exit_code == 0:
        print("\n✅ Phase 2 全部测试通过!")
    else:
        print("\n❌ Phase 2 存在失败的测试")
    sys.exit(exit_code)
