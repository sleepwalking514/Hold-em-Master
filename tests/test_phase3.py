# No longer needed

# """Phase 3 tests: advanced opponent modeling, exploit engine, simulation."""
# import sys
# from pathlib import Path
# sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# import pytest
# import numpy as np
# from unittest.mock import patch

# from treys import Card, Evaluator
# from profiler.player_profile import PlayerProfile
# from profiler.bayesian_tracker import BayesianStat
# from profiler.pattern_analyzer import PatternAnalyzer, SizingTell, StreetAggressionProfile, TextureResponse
# from profiler.showdown_analyzer import (
#     classify_showdown, retroactive_calibrate, ShowdownType, _has_draw_potential,
# )
# from profiler.hand_range_estimator import (
#     HandRangeMatrix, HandRangeEstimator, load_initial_range,
#     likelihood_bet, likelihood_call, likelihood_check,
# )
# from profiler.style_labeler import classify_style, StyleLabel, get_exploit_priority, _range_score, _get_secondary_trait
# from profiler.anti_misjudgment import AntiMisjudgment, TiltState, AdaptationState
# from engine.exploit_rules import ExploitEngine, ExploitRule, ExploitCategory, EXPLOIT_RULES, ExploitAdjustment
# from engine.multiway_strategy import (
#     compute_fold_equity, analyze_multiway, should_bluff_multiway, multiway_sizing_adjustment,
# )
# from engine.range_equity import equity_vs_range, multiway_equity
# from testing.simulation.label_presets import get_preset, all_labels, LABEL_PRESETS, AIOpponentConfig
# from testing.simulation.sim_dealer import SimDealer
# from testing.simulation.ai_opponent import AIOpponent
# from testing.simulation.sim_game_loop import SimGameLoop, HandResult
# from testing.simulation.monitor import SimMonitor, LabelConsistency, AdvisorEvaluation
# from env.action_space import Street, ActionType


# # ============ Pattern Analyzer Tests ============

# class TestPatternAnalyzer:
#     def test_sizing_tell_detection(self):
#         pa = PatternAnalyzer()
#         for _ in range(15):
#             pa.record_bet("Alice", 0.75, is_value=True)
#             pa.record_bet("Alice", 0.40, is_value=False)
#         analysis = pa.analyze("Alice")
#         assert analysis.sizing_tell.has_tell
#         assert analysis.sizing_tell.value_avg > analysis.sizing_tell.bluff_avg
#         assert analysis.sizing_tell.tell_gap > 0.15

#     def test_no_tell_with_few_samples(self):
#         pa = PatternAnalyzer()
#         pa.record_bet("Bob", 0.6, is_value=True)
#         pa.record_bet("Bob", 0.5, is_value=False)
#         analysis = pa.analyze("Bob")
#         assert not analysis.sizing_tell.has_tell

#     def test_street_aggression_profile(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("Alice", Street.FLOP, True)
#             pa.record_street_action("Alice", Street.TURN, False)
#             pa.record_street_action("Alice", Street.RIVER, False)
#         analysis = pa.analyze("Alice")
#         assert analysis.street_aggression.flop_aggr > 0.8
#         assert analysis.street_aggression.turn_aggr < 0.2
#         assert analysis.street_aggression.barrel_drop_off > 0.5

#     def test_texture_response(self):
#         pa = PatternAnalyzer()
#         for _ in range(10):
#             pa.record_cbet("Alice", True, board_is_wet=False)
#             pa.record_cbet("Alice", False, board_is_wet=True)
#         analysis = pa.analyze("Alice")
#         assert analysis.texture_response.dry_board_cbet > 0.8
#         assert analysis.texture_response.wet_board_cbet < 0.2

#     def test_aggression_pattern_one_and_done(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("Alice", Street.FLOP, True)
#             pa.record_street_action("Alice", Street.TURN, False)
#             pa.record_street_action("Alice", Street.RIVER, False)
#         analysis = pa.analyze("Alice")
#         assert analysis.street_aggression.aggression_pattern == "one_and_done"

#     def test_aggression_pattern_relentless(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("Bob", Street.FLOP, True)
#             pa.record_street_action("Bob", Street.TURN, True)
#             pa.record_street_action("Bob", Street.RIVER, True)
#         analysis = pa.analyze("Bob")
#         assert analysis.street_aggression.aggression_pattern == "relentless"

#     def test_aggression_pattern_river_heavy(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("C", Street.FLOP, False)
#             pa.record_street_action("C", Street.TURN, False)
#             pa.record_street_action("C", Street.RIVER, True)
#         analysis = pa.analyze("C")
#         assert analysis.street_aggression.aggression_pattern == "river_heavy"

#     def test_aggression_pattern_balanced(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("D", Street.FLOP, True)
#             pa.record_street_action("D", Street.TURN, True)
#             pa.record_street_action("D", Street.RIVER, False)
#         analysis = pa.analyze("D")
#         assert analysis.street_aggression.aggression_pattern in ("balanced", "one_and_done")

#     def test_scare_card_reaction(self):
#         pa = PatternAnalyzer()
#         pa.record_cbet("Alice", True, board_is_wet=False)
#         for _ in range(15):
#             pa.record_scare_card_reaction("Alice", True)
#         for _ in range(5):
#             pa.record_scare_card_reaction("Alice", False)
#         analysis = pa.analyze("Alice")
#         assert analysis.texture_response.scare_card_shutdown > 0.5

#     def test_serialization_roundtrip(self):
#         pa = PatternAnalyzer()
#         for _ in range(10):
#             pa.record_bet("X", 0.7, is_value=True)
#             pa.record_bet("X", 0.4, is_value=False)
#             pa.record_street_action("X", Street.FLOP, True)
#             pa.record_cbet("X", True, board_is_wet=False)
#             pa.record_scare_card_reaction("X", True)

#         d = pa.to_dict()
#         pa2 = PatternAnalyzer.from_dict(d)
#         analysis1 = pa.analyze("X")
#         analysis2 = pa2.analyze("X")
#         assert abs(analysis1.sizing_tell.value_avg - analysis2.sizing_tell.value_avg) < 0.01
#         assert abs(analysis1.texture_response.dry_board_cbet - analysis2.texture_response.dry_board_cbet) < 0.01

#     def test_analyze_unknown_player(self):
#         pa = PatternAnalyzer()
#         analysis = pa.analyze("Nobody")
#         assert not analysis.sizing_tell.has_tell
#         assert analysis.street_aggression.flop_aggr == 0.0

#     def test_record_bet_without_value_flag_ignored(self):
#         pa = PatternAnalyzer()
#         pa.record_bet("X", 0.5, is_value=None)
#         analysis = pa.analyze("X")
#         assert not analysis.sizing_tell.has_tell

#     def test_sizing_history_cap_at_60(self):
#         pa = PatternAnalyzer()
#         for i in range(70):
#             pa.record_bet("X", 0.5, is_value=True)
#         assert len(pa._sizing_history["X"]) == 60

#     def test_sizing_tell_gap_property(self):
#         st = SizingTell(value_avg=0.8, bluff_avg=0.4, has_tell=True, confidence=0.9)
#         assert abs(st.tell_gap - 0.4) < 0.01

#     def test_gives_up_turn_rate(self):
#         pa = PatternAnalyzer()
#         for _ in range(20):
#             pa.record_street_action("X", Street.FLOP, True)
#             pa.record_street_action("X", Street.TURN, False)
#         analysis = pa.analyze("X")
#         assert analysis.street_aggression.gives_up_turn_rate > 0.8


# # ============ Showdown Analyzer Tests ============

# class TestShowdownAnalyzer:
#     def _make_action_history(self, streets_with_bets):
#         from env.action_space import PlayerAction
#         history = {}
#         for street, action_type, amount in streets_with_bets:
#             if street not in history:
#                 history[street] = []
#             history[street].append(PlayerAction(
#                 player_name="Villain", action_type=action_type,
#                 amount=amount, street=street,
#             ))
#         return history

#     def test_strong_value_classification(self):
#         hole = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("As"), Card.new("2c"), Card.new("3c")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.BET, 200),
#             (Street.RIVER, ActionType.BET, 300),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 500)
#         assert result.showdown_type == ShowdownType.STRONG_VALUE

#     def test_pure_air_classification(self):
#         hole = [Card.new("7h"), Card.new("2c")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("Qs"), Card.new("Js"), Card.new("9c")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.BET, 200),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 300)
#         assert result.showdown_type == ShowdownType.PURE_AIR
#         assert result.was_bluffing

#     def test_retroactive_calibrate_updates_skill(self):
#         profile = PlayerProfile("Villain")
#         initial_skill = profile.skill_estimate.overall_skill
#         hole = [Card.new("7h"), Card.new("2c")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("Qs"), Card.new("Js"), Card.new("9c")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.BET, 200),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 300)
#         retroactive_calibrate(profile, result, hand_id=1)
#         assert profile.skill_estimate.overall_skill != initial_skill

#     def test_overplayed_medium_hand(self):
#         hole = [Card.new("Jh"), Card.new("Tc")]
#         board = [Card.new("Jd"), Card.new("5s"), Card.new("3c"), Card.new("2h"), Card.new("8d")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 200),
#             (Street.TURN, ActionType.BET, 400),
#             (Street.RIVER, ActionType.BET, 600),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 300)
#         assert result.showdown_type in (ShowdownType.OVERPLAYED, ShowdownType.THIN_VALUE)
#         assert result.total_invested == 1200

#     def test_missed_draw_flush(self):
#         hole = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("2h"), Card.new("5h"), Card.new("9c"), Card.new("Jd"), Card.new("Qs")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.BET, 200),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 400)
#         assert result.showdown_type == ShowdownType.MISSED_DRAW
#         assert not result.was_bluffing or result.showdown_type == ShowdownType.MISSED_DRAW

#     def test_thin_value_passive(self):
#         hole = [Card.new("Qh"), Card.new("Jc")]
#         board = [Card.new("Qd"), Card.new("7s"), Card.new("3c"), Card.new("2h"), Card.new("8d")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.CHECK, 0),
#             (Street.TURN, ActionType.CALL, 50),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 200)
#         assert result.showdown_type in (ShowdownType.THIN_VALUE, ShowdownType.STRONG_VALUE)
#         assert not result.was_bluffing

#     def test_pure_air_passive_no_bluff(self):
#         hole = [Card.new("7h"), Card.new("2c")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("Qs"), Card.new("Js"), Card.new("9c")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.CHECK, 0),
#             (Street.TURN, ActionType.CALL, 50),
#         ])
#         result = classify_showdown(hole, board, history, "Villain", 200)
#         assert result.showdown_type == ShowdownType.PURE_AIR
#         assert not result.was_bluffing

#     def test_draw_potential_straight(self):
#         hole = [Card.new("Th"), Card.new("9h")]
#         board = [Card.new("8d"), Card.new("7s"), Card.new("2c")]
#         assert _has_draw_potential(hole, board)

#     def test_no_draw_potential(self):
#         hole = [Card.new("2h"), Card.new("7c")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("Qs")]
#         assert not _has_draw_potential(hole, board)

#     def test_retroactive_calibrate_overplayed(self):
#         profile = PlayerProfile("V")
#         initial_skill = profile.skill_estimate.overall_skill
#         initial_hr = profile.skill_estimate.hand_reading_ability

#         hole = [Card.new("Jh"), Card.new("Tc")]
#         board = [Card.new("Jd"), Card.new("5s"), Card.new("3c"), Card.new("2h"), Card.new("8d")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 200),
#             (Street.TURN, ActionType.BET, 400),
#             (Street.RIVER, ActionType.BET, 600),
#         ])
#         result = classify_showdown(hole, board, history, "V", 300)
#         if result.showdown_type == ShowdownType.OVERPLAYED:
#             retroactive_calibrate(profile, result, hand_id=1)
#             assert profile.skill_estimate.overall_skill < initial_skill

#     def test_retroactive_calibrate_thin_value_improves_hr(self):
#         profile = PlayerProfile("V")
#         hole = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("As"), Card.new("2c"), Card.new("3c")]
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.BET, 200),
#             (Street.RIVER, ActionType.BET, 300),
#         ])
#         result = classify_showdown(hole, board, history, "V", 500)
#         retroactive_calibrate(profile, result, hand_id=2)
#         assert len(profile.key_hands) >= 0

#     def test_bet_streets_tracking(self):
#         history = self._make_action_history([
#             (Street.FLOP, ActionType.BET, 100),
#             (Street.TURN, ActionType.CHECK, 0),
#             (Street.RIVER, ActionType.BET, 200),
#         ])
#         hole = [Card.new("7h"), Card.new("2c")]
#         board = [Card.new("Ad"), Card.new("Kd"), Card.new("Qs"), Card.new("Js"), Card.new("9c")]
#         result = classify_showdown(hole, board, history, "Villain", 300)
#         assert Street.FLOP in result.bet_streets
#         assert Street.RIVER in result.bet_streets
#         assert Street.TURN not in result.bet_streets


# # ============ Hand Range Estimator Tests ============

# class TestHandRangeEstimator:
#     def test_initial_range_open_raise(self):
#         matrix = load_initial_range("CO", vpip=0.30, pfr=0.22, action="open_raise")
#         assert matrix.total_weight() > 0

#     def test_initial_range_call(self):
#         matrix = load_initial_range("BTN", vpip=0.35, pfr=0.25, action="call")
#         assert matrix.total_weight() > 0

#     def test_initial_range_3bet(self):
#         matrix = load_initial_range("SB", vpip=0.25, pfr=0.20, action="3bet")
#         assert matrix.total_weight() > 0

#     def test_likelihood_bet_polarized(self):
#         profile = PlayerProfile("Test")
#         for _ in range(20):
#             profile.update_stat("aggression_freq", True)
#         strong = likelihood_bet(0.85, 100, 150, profile)
#         medium = likelihood_bet(0.45, 100, 150, profile)
#         weak = likelihood_bet(0.10, 100, 150, profile)
#         assert strong > medium
#         assert weak > medium * 0.5

#     def test_likelihood_call_sandwich(self):
#         profile = PlayerProfile("Test")
#         strong = likelihood_call(0.90, 50, 100, profile)
#         medium = likelihood_call(0.45, 50, 100, profile)
#         weak = likelihood_call(0.10, 50, 100, profile)
#         assert medium > weak
#         assert medium >= strong * 0.5

#     def test_range_update_narrows(self):
#         profile = PlayerProfile("Opp")
#         for _ in range(20):
#             profile.update_stat("aggression_freq", True)
#         est = HandRangeEstimator(profile)
#         est.init_range("CO", "open_raise")
#         board = [Card.new("Kd"), Card.new("9h"), Card.new("4c")]
#         est.update(board, "bet", bet_size=100, pot_size=150)
#         assert est.range_matrix is not None

#     def test_matrix_set_uniform(self):
#         m = HandRangeMatrix()
#         m.set_uniform(0.5)
#         assert abs(m.get(0, 0) - 0.5) < 0.01
#         assert abs(m.get(12, 12) - 0.5) < 0.01

#     def test_matrix_normalize(self):
#         m = HandRangeMatrix()
#         m.set_uniform(1.0)
#         m.normalize()
#         assert abs(m.total_weight() - 1.0) < 0.01

#     def test_matrix_set_clamps(self):
#         m = HandRangeMatrix()
#         m.set(0, 0, 2.0)
#         assert m.get(0, 0) == 1.0
#         m.set(0, 0, -1.0)
#         assert m.get(0, 0) == 0.0

#     def test_top_hands_returns_sorted(self):
#         m = HandRangeMatrix()
#         m.set(0, 0, 0.9)
#         m.set(0, 1, 0.5)
#         m.set(1, 0, 0.3)
#         top = m.top_hands(3)
#         assert len(top) == 3
#         assert top[0][1] >= top[1][1] >= top[2][1]

#     def test_range_percentage_empty(self):
#         m = HandRangeMatrix()
#         assert m.range_percentage() == 0.0

#     def test_range_percentage_full(self):
#         m = HandRangeMatrix()
#         m.set_uniform(1.0)
#         assert abs(m.range_percentage() - 1.0) < 0.01

#     def test_to_combo_list_with_dead_cards(self):
#         m = HandRangeMatrix()
#         m.set(0, 0, 1.0)  # AA
#         board = [Card.new("Ah"), Card.new("Kd"), Card.new("Qs")]
#         combos = m.to_combo_list(board)
#         for c1, c2, w in combos:
#             assert c1 not in board
#             assert c2 not in board

#     def test_likelihood_check_returns_float(self):
#         profile = PlayerProfile("T")
#         val = likelihood_check(0.5, profile)
#         assert isinstance(val, float)
#         assert val > 0

#     def test_load_initial_range_limp(self):
#         m = load_initial_range("BB", vpip=0.50, pfr=0.10, action="limp")
#         assert m.total_weight() > 0

#     def test_range_estimator_init_and_update(self):
#         profile = PlayerProfile("Opp")
#         for _ in range(20):
#             profile.update_stat("aggression_freq", True)
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", True)

#         est = HandRangeEstimator(profile)
#         est.init_range("BTN", "open_raise")
#         assert est.range_matrix is not None
#         initial_weight = est.range_matrix.total_weight()

#         board = [Card.new("Kd"), Card.new("9h"), Card.new("4c")]
#         est.update(board, "check")
#         assert est.range_matrix is not None

#     def test_get_weighted_combos(self):
#         profile = PlayerProfile("Opp")
#         for _ in range(20):
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", True)
#         est = HandRangeEstimator(profile)
#         est.init_range("CO", "open_raise")
#         board = [Card.new("Kd"), Card.new("9h"), Card.new("4c")]
#         combos = est.get_weighted_combos(board)
#         assert isinstance(combos, list)


# # ============ Style Labeler Tests ============

# class TestStyleLabeler:
#     def _make_profile(self, vpip_val, aggr_val, n=80):
#         p = PlayerProfile("Test")
#         for _ in range(int(n * vpip_val)):
#             p.update_stat("vpip", True)
#         for _ in range(int(n * (1 - vpip_val))):
#             p.update_stat("vpip", False)
#         for _ in range(int(n * aggr_val)):
#             p.update_stat("aggression_freq", True)
#         for _ in range(int(n * (1 - aggr_val))):
#             p.update_stat("aggression_freq", False)
#         return p

#     def test_tag_classification(self):
#         p = self._make_profile(0.22, 0.45, n=80)
#         label = classify_style(p)
#         assert label.primary in ("TAG", "Regular", "LAG")

#     def test_fish_classification(self):
#         p = self._make_profile(0.55, 0.22)
#         label = classify_style(p)
#         assert label.primary in ("Fish", "CallStation")

#     def test_unknown_with_low_confidence(self):
#         p = PlayerProfile("New")
#         label = classify_style(p)
#         assert "未知" in str(label)

#     def test_exploit_priority(self):
#         p = self._make_profile(0.50, 0.18)
#         label = classify_style(p)
#         priorities = get_exploit_priority(label)
#         assert len(priorities) > 0

#     def test_nit_classification(self):
#         p = self._make_profile(0.10, 0.40)
#         label = classify_style(p)
#         assert label.primary in ("Nit", "TAG", "TightPassive")

#     def test_lag_classification(self):
#         p = self._make_profile(0.35, 0.50)
#         label = classify_style(p)
#         assert label.primary in ("LAG", "Maniac")

#     def test_maniac_classification(self):
#         p = self._make_profile(0.60, 0.55)
#         label = classify_style(p)
#         assert label.primary == "Maniac"

#     def test_callstation_classification(self):
#         p = self._make_profile(0.45, 0.15)
#         label = classify_style(p)
#         assert label.primary in ("CallStation", "Fish")

#     def test_tight_passive_classification(self):
#         p = self._make_profile(0.12, 0.15)
#         label = classify_style(p)
#         assert label.primary in ("TightPassive", "Nit")

#     def test_regular_classification(self):
#         p = self._make_profile(0.25, 0.38)
#         label = classify_style(p)
#         assert label.primary in ("Regular", "TAG")

#     def test_style_label_str_low_confidence(self):
#         label = StyleLabel("TAG", "", 0.1, "test")
#         assert "未知" in str(label)

#     def test_style_label_str_high_confidence(self):
#         label = StyleLabel("TAG", "", 0.8, "test")
#         assert "TAG" in str(label)

#     def test_range_score_in_range(self):
#         assert _range_score(0.20, 0.14, 0.26) > 0.7

#     def test_range_score_out_of_range(self):
#         assert _range_score(0.50, 0.14, 0.26) < 0.3

#     def test_secondary_traits(self):
#         p = self._make_profile(0.30, 0.40, n=80)
#         for _ in range(60):
#             p.update_stat("fold_to_cbet", True)
#         for _ in range(10):
#             p.update_stat("fold_to_cbet", False)
#         trait = _get_secondary_trait(p)
#         assert "易弃牌" in trait

#     def test_exploit_priority_all_styles(self):
#         for style_name in ["Nit", "TAG", "LAG", "Maniac", "CallStation", "Fish", "TightPassive", "Regular"]:
#             label = StyleLabel(style_name, "", 0.8, "")
#             priorities = get_exploit_priority(label)
#             assert isinstance(priorities, dict)

#     def test_exploit_priority_unknown_style(self):
#         label = StyleLabel("Unknown", "", 0.5, "")
#         priorities = get_exploit_priority(label)
#         assert priorities == {}


# # ============ Anti-Misjudgment Tests ============

# class TestAntiMisjudgment:
#     def test_tilt_detection(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Tilter")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(10):
#             am.record_action("Tilter", "aggression_freq", 0.8)
#         am.record_bad_beat("Tilter", 1)
#         am.record_bad_beat("Tilter", 2)
#         tilt = am.detect_tilt("Tilter", profile)
#         assert tilt.is_tilting
#         assert tilt.exploit_multiplier > 1.0

#     def test_no_tilt_normal_play(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Normal")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", True)
#         for _ in range(10):
#             am.record_action("Normal", "aggression_freq", 0.4)
#         tilt = am.detect_tilt("Normal", profile)
#         assert not tilt.is_tilting

#     def test_adaptation_detection(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Adaptor")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(25):
#             am.record_action("Adaptor", "aggression_freq", 0.3)
#         for _ in range(15):
#             am.record_action("Adaptor", "aggression_freq", 0.8, vs_hero=True)
#         adapt = am.detect_adaptation("Adaptor", profile)
#         assert adapt.is_adapting

#     def test_exploit_modifier(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Test")
#         modifier = am.get_exploit_modifier("Test", profile)
#         assert modifier == 1.0

#     def test_should_suppress_exploit_when_adapting(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Adaptor")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(25):
#             am.record_action("Adaptor", "aggression_freq", 0.3)
#         for _ in range(15):
#             am.record_action("Adaptor", "aggression_freq", 0.8, vs_hero=True)

#         suppress, reason = am.should_suppress_exploit("Adaptor", profile)
#         assert isinstance(suppress, bool)
#         assert isinstance(reason, str)

#     def test_decay_tilt(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Tilter")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(10):
#             am.record_action("Tilter", "aggression_freq", 0.8)
#         am.record_bad_beat("Tilter", 1)
#         am.record_bad_beat("Tilter", 2)

#         tilt = am.detect_tilt("Tilter", profile)
#         assert tilt.is_tilting

#         for _ in range(20):
#             am.decay_tilt("Tilter")
#         state = am._tilt_states.get("Tilter", TiltState())
#         assert state.tilt_confidence < 0.3 or not state.is_tilting

#     def test_combined_modifier_tilt_and_adapt(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("Both")
#         for _ in range(30):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(10):
#             am.record_action("Both", "aggression_freq", 0.8)
#         am.record_bad_beat("Both", 1)
#         am.record_bad_beat("Both", 2)

#         modifier = am.get_exploit_modifier("Both", profile)
#         assert 0.2 <= modifier <= 2.0

#     def test_tilt_not_triggered_with_few_actions(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("New")
#         am.record_action("New", "aggression_freq", 0.9)
#         tilt = am.detect_tilt("New", profile)
#         assert not tilt.is_tilting

#     def test_adaptation_not_triggered_with_few_vs_hero(self):
#         am = AntiMisjudgment()
#         profile = PlayerProfile("X")
#         for _ in range(30):
#             am.record_action("X", "aggression_freq", 0.5)
#         am.record_action("X", "aggression_freq", 0.9, vs_hero=True)
#         adapt = am.detect_adaptation("X", profile)
#         assert not adapt.is_adapting

#     def test_tilt_exploit_multiplier(self):
#         ts = TiltState(is_tilting=True, tilt_confidence=0.8)
#         assert ts.exploit_multiplier > 1.0
#         ts2 = TiltState(is_tilting=False)
#         assert ts2.exploit_multiplier == 1.0

#     def test_bad_beat_cap_at_10(self):
#         am = AntiMisjudgment()
#         for i in range(15):
#             am.record_bad_beat("X", i)
#         assert len(am._bad_beat_events["X"]) == 10


# # ============ Exploit Rules Tests ============

# class TestExploitRules:
#     def test_rule_count(self):
#         assert len(EXPLOIT_RULES) >= 15

#     def test_exploit_engine_basic(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Fish")
#         for _ in range(50):
#             profile.update_stat("fold_to_cbet", True)
#         for _ in range(10):
#             profile.update_stat("fold_to_cbet", False)
#         adjustments = engine.evaluate_all(profile)
#         assert len(adjustments) > 0

#     def test_exploit_engine_passive_player(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Passive")
#         for _ in range(50):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(10):
#             profile.update_stat("aggression_freq", True)
#         for _ in range(30):
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", False)
#             profile.update_stat("fold_to_cbet", False)
#         action_adj = engine.get_action_adjustments(profile)
#         assert action_adj["value_freq_adj"] != 0 or action_adj["bluff_freq_adj"] != 0

#     def test_conflict_resolution(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Complex")
#         for _ in range(50):
#             profile.update_stat("fold_to_cbet", True)
#             profile.update_stat("fold_to_3bet", True)
#             profile.update_stat("fold_to_river_bet", True)
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", True)
#             profile.update_stat("aggression_freq", True)
#         adjustments = engine.evaluate_all(profile)
#         offense = [a for a in adjustments if a.category.name == "OFFENSE"]
#         if len(offense) > 1:
#             assert offense[1].magnitude <= offense[0].magnitude

#     def test_rule_evaluate_missing_stat(self):
#         rule = EXPLOIT_RULES[0]
#         profile = PlayerProfile("Empty")
#         assert rule.evaluate(profile) == 0.0

#     def test_rule_evaluate_low_confidence(self):
#         rule = ExploitRule("test", ExploitCategory.OFFENSE, "fold_to_cbet", "test", 8.0, 0.3, 0.8)
#         profile = PlayerProfile("Low")
#         profile.update_stat("fold_to_cbet", True)
#         assert rule.evaluate(profile) == 0.0

#     def test_top_exploits_limit(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Fish")
#         for _ in range(50):
#             profile.update_stat("fold_to_cbet", True)
#             profile.update_stat("fold_to_3bet", True)
#             profile.update_stat("aggression_freq", False)
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", False)
#         for _ in range(10):
#             profile.update_stat("fold_to_cbet", False)

#         top = engine.top_exploits(profile, hero_is_ip=True, n=2)
#         assert len(top) <= 2

#     def test_format_exploit_summary(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Fish")
#         for _ in range(50):
#             profile.update_stat("fold_to_cbet", True)
#             profile.update_stat("aggression_freq", False)
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", False)
#         for _ in range(10):
#             profile.update_stat("fold_to_cbet", False)

#         summary = engine.format_exploit_summary(profile)
#         if summary:
#             assert isinstance(summary, str)

#     def test_format_exploit_summary_empty(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("New")
#         summary = engine.format_exploit_summary(profile)
#         assert summary is None

#     def test_get_action_adjustments_keys(self):
#         engine = ExploitEngine()
#         profile = PlayerProfile("Test")
#         for _ in range(50):
#             profile.update_stat("fold_to_cbet", True)
#             profile.update_stat("aggression_freq", False)
#             profile.update_stat("vpip", True)
#             profile.update_stat("pfr", False)
#         adj = engine.get_action_adjustments(profile)
#         assert "value_freq_adj" in adj
#         assert "bluff_freq_adj" in adj
#         assert "sizing_adj" in adj
#         assert "call_freq_adj" in adj

#     def test_exploit_categories_exist(self):
#         cats = set(r.category for r in EXPLOIT_RULES)
#         assert ExploitCategory.OFFENSE in cats
#         assert ExploitCategory.DEFENSE in cats

#     def test_position_rules_exist(self):
#         pos_rules = [r for r in EXPLOIT_RULES if r.category == ExploitCategory.POSITION]
#         assert len(pos_rules) >= 1


# # ============ Multiway Strategy Tests ============

# class TestMultiwayStrategy:
#     def test_fold_equity_multiplication(self):
#         p1 = PlayerProfile("P1")
#         p2 = PlayerProfile("P2")
#         for _ in range(30):
#             p1.update_stat("fold_to_cbet", True)
#             p2.update_stat("fold_to_cbet", True)
#         for _ in range(20):
#             p1.update_stat("fold_to_cbet", False)
#             p2.update_stat("fold_to_cbet", False)
#         fe = compute_fold_equity([("P1", p1), ("P2", p2)])
#         p1_fold = p1.get_stat("fold_to_cbet")
#         p2_fold = p2.get_stat("fold_to_cbet")
#         expected = p1_fold * p2_fold
#         assert abs(fe - expected) < 0.01

#     def test_multiway_analysis(self):
#         p1 = PlayerProfile("P1")
#         p2 = PlayerProfile("P2")
#         for _ in range(30):
#             p1.update_stat("fold_to_cbet", True)
#             p1.update_stat("aggression_freq", False)
#             p2.update_stat("fold_to_cbet", False)
#             p2.update_stat("aggression_freq", True)
#         analysis = analyze_multiway([("P1", p1), ("P2", p2)], 0.6, 200)
#         assert analysis.num_opponents == 2
#         assert analysis.most_dangerous is not None
#         assert analysis.most_exploitable is not None

#     def test_should_bluff_multiway(self):
#         ok, _ = should_bluff_multiway(0.5, 200, 100, 2)
#         assert ok
#         no, _ = should_bluff_multiway(0.1, 200, 100, 3)
#         assert not no

#     def test_fold_equity_empty_opponents(self):
#         assert compute_fold_equity([]) == 0.0

#     def test_fold_equity_river_bet_type(self):
#         p1 = PlayerProfile("P1")
#         for _ in range(30):
#             p1.update_stat("fold_to_river_bet", True)
#         for _ in range(10):
#             p1.update_stat("fold_to_river_bet", False)
#         fe = compute_fold_equity([("P1", p1)], bet_type="river")
#         assert fe > 0.5

#     def test_fold_equity_3bet_type(self):
#         p1 = PlayerProfile("P1")
#         for _ in range(30):
#             p1.update_stat("fold_to_3bet", True)
#         for _ in range(10):
#             p1.update_stat("fold_to_3bet", False)
#         fe = compute_fold_equity([("P1", p1)], bet_type="3bet")
#         assert fe > 0.5

#     def test_analyze_multiway_empty(self):
#         analysis = analyze_multiway([], 0.5, 200)
#         assert analysis.num_opponents == 0
#         assert analysis.most_dangerous is None

#     def test_analyze_multiway_strong_equity(self):
#         p1 = PlayerProfile("P1")
#         for _ in range(30):
#             p1.update_stat("fold_to_cbet", True)
#             p1.update_stat("aggression_freq", False)
#         analysis = analyze_multiway([("P1", p1)], 0.7, 200)
#         assert "价值" in analysis.strategy_note

#     def test_analyze_multiway_weak_equity(self):
#         p1 = PlayerProfile("P1")
#         for _ in range(30):
#             p1.update_stat("fold_to_cbet", False)
#             p1.update_stat("aggression_freq", True)
#         analysis = analyze_multiway([("P1", p1)], 0.2, 200)
#         assert "过牌" in analysis.strategy_note or "弃牌" in analysis.strategy_note

#     def test_sizing_adjustment_value(self):
#         size = multiway_sizing_adjustment(100, 3, is_value=True)
#         assert size > 100

#     def test_sizing_adjustment_bluff(self):
#         size = multiway_sizing_adjustment(100, 3, is_value=False)
#         assert size < 100

#     def test_sizing_adjustment_headsup(self):
#         size = multiway_sizing_adjustment(100, 1, is_value=True)
#         assert size == 100

#     def test_should_bluff_boundary(self):
#         ok, _ = should_bluff_multiway(0.5, 100, 100, 2)
#         assert ok
#         no, _ = should_bluff_multiway(0.49, 100, 100, 2)
#         assert not no

#     def test_should_bluff_3plus_low_fe(self):
#         no, reason = should_bluff_multiway(0.2, 200, 100, 3)
#         assert not no
#         assert "3+" in reason


# # ============ Range Equity Tests ============

# class TestRangeEquity:
#     def test_equity_vs_range_basic(self):
#         hero = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("7s"), Card.new("2c")]
#         m = HandRangeMatrix()
#         m.set_uniform(0.1)
#         eq = equity_vs_range(hero, board, m, num_simulations=500)
#         assert 0.0 <= eq <= 1.0
#         assert eq > 0.5

#     def test_equity_vs_range_empty_range(self):
#         hero = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("7s"), Card.new("2c")]
#         m = HandRangeMatrix()
#         eq = equity_vs_range(hero, board, m, num_simulations=200)
#         assert 0.0 <= eq <= 1.0

#     def test_multiway_equity_basic(self):
#         hero = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("7s"), Card.new("2c")]
#         m1 = HandRangeMatrix()
#         m1.set_uniform(0.1)
#         m2 = HandRangeMatrix()
#         m2.set_uniform(0.1)
#         eq = multiway_equity(hero, board, [m1, m2], num_simulations=300)
#         assert 0.0 <= eq <= 1.0

#     def test_multiway_equity_empty_ranges(self):
#         hero = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("7s"), Card.new("2c")]
#         eq = multiway_equity(hero, board, [], num_simulations=200)
#         assert 0.0 <= eq <= 1.0

#     def test_equity_vs_range_full_board(self):
#         hero = [Card.new("Ah"), Card.new("Kh")]
#         board = [Card.new("Ad"), Card.new("7s"), Card.new("2c"), Card.new("Jd"), Card.new("3h")]
#         m = HandRangeMatrix()
#         m.set_uniform(0.1)
#         eq = equity_vs_range(hero, board, m, num_simulations=300)
#         assert 0.0 <= eq <= 1.0


# # ============ Simulation Tests ============

# class TestSimulation:
#     def test_label_presets(self):
#         labels = all_labels()
#         assert "TAG" in labels
#         assert "Fish" in labels
#         assert len(labels) == 6

#     def test_sim_dealer(self):
#         dealer = SimDealer(seed=42)
#         dealer.new_hand()
#         hands = dealer.deal_hole_cards(4)
#         assert len(hands) == 4
#         assert all(len(h) == 2 for h in hands)
#         flop = dealer.deal_flop()
#         assert len(flop) == 3
#         all_cards = set()
#         for h in hands:
#             all_cards.update(h)
#         all_cards.update(flop)
#         assert len(all_cards) == 4 * 2 + 3

#     def test_ai_opponent_decides(self):
#         from env.game_state import GameState, Player
#         config = get_preset("TAG")
#         ai = AIOpponent(config, seed=42)
#         players = [Player(name="Hero", stack=1000), Player(name="Villain", stack=1000)]
#         gs = GameState(players=players, big_blind=10, small_blind=5)
#         gs.street = Street.PREFLOP
#         gs.current_bet = 10
#         player = gs.players[1]
#         player.hole_cards = [Card.new("Ah"), Card.new("Kh")]
#         action, amount = ai.decide(gs, player)
#         assert action in (ActionType.FOLD, ActionType.CALL, ActionType.RAISE,
#                          ActionType.CHECK, ActionType.ALL_IN)

#     def test_seed_determinism(self):
#         dealer1 = SimDealer(seed=123)
#         dealer1.new_hand()
#         h1 = dealer1.deal_hole_cards(2)

#         dealer2 = SimDealer(seed=123)
#         dealer2.new_hand()
#         h2 = dealer2.deal_hole_cards(2)

#         assert h1 == h2

#     def test_dealer_remaining_count(self):
#         dealer = SimDealer(seed=42)
#         dealer.new_hand()
#         assert dealer.remaining == 52
#         dealer.deal_hole_cards(2)
#         assert dealer.remaining == 48
#         dealer.deal_flop()
#         assert dealer.remaining == 44  # 3 cards + 1 burn

#     def test_dealer_dealt_cards_property(self):
#         dealer = SimDealer(seed=42)
#         dealer.new_hand()
#         hands = dealer.deal_hole_cards(2)
#         dealt = dealer.dealt_cards
#         assert len(dealt) == 4
#         for h in hands:
#             for c in h:
#                 assert c in dealt

#     def test_ai_opponent_postflop_no_board(self):
#         from env.game_state import GameState, Player
#         config = get_preset("Fish")
#         ai = AIOpponent(config, seed=42)
#         players = [Player(name="Hero", stack=1000), Player(name="V", stack=1000)]
#         gs = GameState(players=players, big_blind=10, small_blind=5)
#         gs.street = Street.FLOP
#         gs.board = []
#         player = gs.players[1]
#         player.hole_cards = [Card.new("Ah"), Card.new("Kh")]
#         action, amount = ai.decide(gs, player)
#         assert action == ActionType.CHECK

#     def test_ai_opponent_facing_bet_postflop(self):
#         from env.game_state import GameState, Player
#         config = get_preset("TAG")
#         ai = AIOpponent(config, seed=42)
#         players = [Player(name="Hero", stack=1000), Player(name="V", stack=1000)]
#         gs = GameState(players=players, big_blind=10, small_blind=5)
#         gs.street = Street.FLOP
#         gs.board = [Card.new("Kd"), Card.new("9h"), Card.new("4c")]
#         gs.current_bet = 30
#         gs.pot = 80
#         player = gs.players[1]
#         player.hole_cards = [Card.new("Ah"), Card.new("Kh")]
#         player.current_bet = 0
#         action, amount = ai.decide(gs, player)
#         assert action in (ActionType.FOLD, ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN)

#     def test_ai_opponent_preflop_no_cards(self):
#         from env.game_state import GameState, Player
#         config = get_preset("Fish")
#         ai = AIOpponent(config, seed=42)
#         players = [Player(name="Hero", stack=1000), Player(name="V", stack=1000)]
#         gs = GameState(players=players, big_blind=10, small_blind=5)
#         gs.street = Street.PREFLOP
#         gs.current_bet = 10
#         player = gs.players[1]
#         player.hole_cards = []
#         action, amount = ai.decide(gs, player)
#         assert action in (ActionType.FOLD, ActionType.CALL, ActionType.CHECK, ActionType.RAISE, ActionType.ALL_IN)


# class TestMonitorRobust:
#     def test_monitor_empty_report(self):
#         mon = SimMonitor()
#         report = mon.summary_report()
#         assert "0手" in report

#     def test_monitor_evaluate_empty(self):
#         mon = SimMonitor()
#         ev = mon.evaluate_advisor()
#         assert ev.total_hands == 0
#         assert ev.hero_profit == 0

#     def test_monitor_label_consistency_unknown(self):
#         mon = SimMonitor()
#         result = mon.check_label_consistency("Nobody")
#         assert result is None

#     def test_monitor_record_and_evaluate(self):
#         mon = SimMonitor()
#         config = get_preset("Fish")
#         profile = PlayerProfile("Fish1")
#         for _ in range(30):
#             profile.update_stat("vpip", True)
#             profile.update_stat("aggression_freq", False)
#         mon.register_player("Fish1", config, profile)

#         for i in range(10):
#             mon.record_hand(HandResult(
#                 hand_id=i, winner="Hero", pot_size=50,
#                 hero_profit=25, showdown=(i % 2 == 0),
#             ))
#         ev = mon.evaluate_advisor()
#         assert ev.total_hands == 10
#         assert ev.hero_profit == 250

#     def test_monitor_label_consistency_score(self):
#         mon = SimMonitor()
#         config = get_preset("TAG")
#         profile = PlayerProfile("TAG1")
#         for _ in range(50):
#             profile.update_stat("vpip", True)
#         for _ in range(150):
#             profile.update_stat("vpip", False)
#         for _ in range(40):
#             profile.update_stat("aggression_freq", True)
#         for _ in range(60):
#             profile.update_stat("aggression_freq", False)
#         for _ in range(20):
#             profile.update_stat("pfr", True)
#         for _ in range(80):
#             profile.update_stat("pfr", False)
#         mon.register_player("TAG1", config, profile)
#         lc = mon.check_label_consistency("TAG1")
#         assert lc is not None
#         assert 0.0 <= lc.score <= 1.0

#     def test_label_consistency_is_consistent_property(self):
#         lc = LabelConsistency("X", "TAG", 0.22, 0.22, 0.18, 0.18, 0.42, 0.42, 1.0)
#         assert lc.is_consistent
#         lc2 = LabelConsistency("X", "TAG", 0.22, 0.22, 0.18, 0.18, 0.42, 0.42, 0.5)
#         assert not lc2.is_consistent

#     def test_summary_report_with_players(self):
#         mon = SimMonitor()
#         config = get_preset("Fish")
#         profile = PlayerProfile("Fish1")
#         for _ in range(30):
#             profile.update_stat("vpip", True)
#             profile.update_stat("aggression_freq", False)
#             profile.update_stat("pfr", False)
#         mon.register_player("Fish1", config, profile)
#         mon.record_hand(HandResult(hand_id=1, winner="Hero", pot_size=50, hero_profit=25, showdown=True))
#         report = mon.summary_report()
#         assert "Fish1" in report
#         assert "Fish" in report


# class TestLabelPresets:
#     def test_all_presets_have_required_fields(self):
#         for label, config in LABEL_PRESETS.items():
#             assert 0.0 <= config.vpip_target <= 1.0
#             assert 0.0 <= config.pfr_target <= 1.0
#             assert 0.0 <= config.aggression_freq_target <= 1.0
#             assert 0.0 <= config.fold_to_cbet <= 1.0
#             assert 0.0 <= config.bluff_frequency <= 1.0
#             assert config.tilt_variance >= 0

#     def test_passivity_property(self):
#         config = get_preset("CallStation")
#         assert config.passivity > 0.7

#     def test_get_preset_fallback(self):
#         config = get_preset("NonExistent")
#         assert config.label == "TAG"


# class TestSimGameLoop:
#     def test_run_batch(self):
#         loop = SimGameLoop(
#             player_configs=[("Hero", "TAG"), ("V1", "Fish")],
#             hero_name="Hero", starting_stack=1000, big_blind=10, seed=42,
#         )
#         results = loop.run_batch(5, hero_auto=True)
#         assert len(results) == 5
#         for r in results:
#             assert isinstance(r, HandResult)
#             assert r.hand_id > 0

#     def test_run_hand_returns_result(self):
#         loop = SimGameLoop(
#             player_configs=[("Hero", "TAG"), ("V1", "Nit")],
#             hero_name="Hero", starting_stack=1000, big_blind=10, seed=99,
#         )
#         result = loop.run_hand(hero_auto=True)
#         assert isinstance(result, HandResult)
#         assert result.winner != "" or result.pot_size == 0

#     def test_multiway_game(self):
#         loop = SimGameLoop(
#             player_configs=[("Hero", "TAG"), ("V1", "Fish"), ("V2", "Maniac")],
#             hero_name="Hero", starting_stack=1000, big_blind=10, seed=42,
#         )
#         results = loop.run_batch(3, hero_auto=True)
#         assert len(results) == 3


# # ============ Integration Test ============

# class TestAdvisorIntegration:
#     def test_advisor_with_new_modules(self):
#         from engine.advisor import Advisor
#         from env.game_state import GameState, Player

#         advisor = Advisor()
#         profile = PlayerProfile("Villain")
#         for _ in range(40):
#             profile.update_stat("vpip", True)
#             profile.update_stat("aggression_freq", False)
#             profile.update_stat("fold_to_cbet", True)
#             profile.update_stat("pfr", False)
#         advisor.set_profiles({"Villain": profile})

#         players = [
#             Player(name="Hero", stack=1000),
#             Player(name="Villain", stack=1000),
#         ]
#         gs = GameState(players=players, big_blind=10, small_blind=5)
#         gs.players[0].hole_cards = [Card.new("Ah"), Card.new("Kh")]
#         gs.board = [Card.new("Kd"), Card.new("9h"), Card.new("4c")]
#         gs.street = Street.FLOP
#         gs.pot = 50
#         gs.current_bet = 0

#         advice = advisor.get_advice(gs, gs.players[0])
#         assert "action" in advice
#         assert "equity" in advice
#         assert advice["action"] in (ActionType.BET, ActionType.CHECK, ActionType.RAISE)


# if __name__ == "__main__":
#     pytest.main([__file__, "-v"])

