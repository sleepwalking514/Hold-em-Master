from __future__ import annotations

import bisect
import random
from typing import Optional

from treys import Evaluator, Card, Deck

from env.action_space import ActionType, Street
from env.game_state import GameState, Player
from testing.simulation.label_presets import AIOpponentConfig, get_preset

EVALUATOR = Evaluator()

_IP_POSITIONS = {"BTN", "CO"}
_OOP_POSITIONS = {"SB", "BB", "UTG"}
_ALL_POSITIONS = ["UTG", "MP", "CO", "BTN", "SB", "BB"]

_CALIBRATION_SAMPLES = 10_000
_CALIBRATION_SEED = 77777


class AIOpponent:
    def __init__(self, config: AIOpponentConfig, seed: int | None = None):
        self.config = config
        self._rng = random.Random(seed)
        self._enter_threshold, self._raise_threshold = self._calibrate_thresholds()

    def _calibrate_thresholds(self) -> tuple[float, float]:
        """蒙特卡洛校准：找到能产生目标 VPIP/PFR 的 effective_strength 阈值。"""
        cal_rng = random.Random(_CALIBRATION_SEED)
        samples: list[float] = []
        for _ in range(_CALIBRATION_SAMPLES):
            deck = Deck()
            cards = deck.draw(2)
            strength = self._preflop_strength(cards)
            noise = cal_rng.gauss(0, self.config.tilt_variance)
            pos = cal_rng.choice(_ALL_POSITIONS)
            pos_mod = self._position_modifier(pos)
            eff = max(0.0, min(1.0, strength + noise + pos_mod))
            samples.append(eff)
        samples.sort()
        n = len(samples)

        def find_threshold(target_rate: float) -> float:
            if target_rate <= 0:
                return 1.01
            if target_rate >= 1:
                return -0.01
            lo, hi = 0.0, 1.0
            for _ in range(40):
                mid = (lo + hi) / 2
                idx = bisect.bisect_left(samples, mid)
                rate = (n - idx) / n
                if rate > target_rate:
                    lo = mid
                else:
                    hi = mid
            return (lo + hi) / 2

        return find_threshold(self.config.vpip_target), find_threshold(self.config.pfr_target)

    def decide(
        self, game_state: GameState, player: Player
    ) -> tuple[ActionType, int]:
        if game_state.street == Street.PREFLOP:
            return self._decide_preflop(game_state, player)
        return self._decide_postflop(game_state, player)

    def _position_modifier(self, position: str) -> float:
        if position in _IP_POSITIONS:
            return 0.04
        if position in _OOP_POSITIONS:
            return -0.03
        return 0.0

    def _decide_preflop(
        self, gs: GameState, player: Player
    ) -> tuple[ActionType, int]:
        facing_bet = gs.current_bet > player.current_bet
        call_amount = gs.current_bet - player.current_bet

        hand_strength = self._preflop_strength(player.hole_cards)
        noise = self._rng.gauss(0, self.config.tilt_variance)
        pos_mod = self._position_modifier(player.position)
        effective_strength = max(0.0, min(1.0, hand_strength + noise + pos_mod))

        enter_threshold = self._enter_threshold
        raise_threshold = self._raise_threshold

        if facing_bet:
            pot_odds = call_amount / max(gs.pot + call_amount, 1)
            bet_to_stack = call_amount / max(player.stack, 1)

            if bet_to_stack > 0.5:
                min_strength = 0.55 + bet_to_stack * 0.2
                if effective_strength < min_strength:
                    return ActionType.FOLD, 0

            if call_amount >= player.stack:
                if effective_strength > max(0.7, pot_odds + 0.15):
                    return ActionType.ALL_IN, player.stack + player.current_bet
                return ActionType.FOLD, 0

            if effective_strength < enter_threshold:
                return ActionType.FOLD, 0

            if effective_strength >= raise_threshold and bet_to_stack < 0.3:
                raise_to = min(gs.current_bet * 3, player.stack + player.current_bet)
                if raise_to >= player.stack + player.current_bet:
                    if effective_strength > 0.75:
                        return ActionType.ALL_IN, player.stack + player.current_bet
                    return ActionType.CALL, gs.current_bet
                return ActionType.RAISE, raise_to

            return ActionType.CALL, gs.current_bet

        if effective_strength < enter_threshold:
            return ActionType.CHECK, 0

        if effective_strength >= raise_threshold:
            raise_to = min(gs.pot + gs.big_blind * 3, player.stack + player.current_bet)
            if raise_to >= player.stack + player.current_bet:
                return ActionType.ALL_IN, player.stack + player.current_bet
            return ActionType.RAISE, raise_to

        return ActionType.CHECK, 0

    def _decide_postflop(
        self, gs: GameState, player: Player
    ) -> tuple[ActionType, int]:
        if not player.hole_cards or not gs.board:
            return ActionType.CHECK, 0

        hand_rank = EVALUATOR.evaluate(gs.board, player.hole_cards)
        strength = 1.0 - (hand_rank / 7462.0)
        draw_bonus = self._draw_bonus(player.hole_cards, gs.board)
        noise = self._rng.gauss(0, self.config.tilt_variance)
        pos_mod = self._position_modifier(player.position) * 0.5
        effective = max(0.0, min(1.0, strength + draw_bonus + noise + pos_mod))

        facing_bet = gs.current_bet > player.current_bet
        call_amount = gs.current_bet - player.current_bet

        if facing_bet:
            return self._facing_bet_decision(gs, player, effective, call_amount)
        return self._no_bet_decision(gs, player, effective)

    def _facing_bet_decision(
        self, gs: GameState, player: Player, strength: float, call_amount: int
    ) -> tuple[ActionType, int]:
        pot_odds = call_amount / max(gs.pot + call_amount, 1)
        aggr = self.config.aggression_freq_target
        fold_cbet = self.config.fold_to_cbet
        passivity = self.config.passivity

        if strength > 0.75:
            if self._rng.random() < aggr:
                raise_to = min(gs.current_bet * 2 + gs.pot // 2, player.stack + player.current_bet)
                return ActionType.RAISE, raise_to
            return ActionType.CALL, gs.current_bet

        if strength > pot_odds + 0.05:
            fold_chance = fold_cbet * (1.0 - passivity * 0.3) if strength < 0.4 else 0.0
            if self._rng.random() < fold_chance:
                return ActionType.FOLD, 0
            return ActionType.CALL, gs.current_bet

        if self._rng.random() < fold_cbet:
            return ActionType.FOLD, 0

        if strength > pot_odds * 0.8:
            return ActionType.CALL, gs.current_bet
        return ActionType.FOLD, 0

    def _no_bet_decision(
        self, gs: GameState, player: Player, strength: float
    ) -> tuple[ActionType, int]:
        aggr = self.config.aggression_freq_target
        bluff_freq = self.config.bluff_frequency
        passivity = self.config.passivity

        should_bet = False
        if strength > 0.55:
            should_bet = self._rng.random() < (aggr + 0.2)
        elif strength < 0.25:
            should_bet = self._rng.random() < bluff_freq
        else:
            medium_freq = aggr * 0.5 + passivity * 0.15
            should_bet = self._rng.random() < medium_freq

        if should_bet:
            size = self._bet_size(gs, strength)
            size = max(gs.big_blind, min(size, player.stack))
            if size >= player.stack:
                return ActionType.ALL_IN, player.stack + player.current_bet
            return ActionType.BET, size

        if strength > 0.65 and self._rng.random() < aggr * 0.4:
            return ActionType.CHECK, 0

        return ActionType.CHECK, 0

    def _bet_size(self, gs: GameState, strength: float) -> int:
        label = self.config.label
        pot = max(gs.pot, 1)

        if label in ("Fish", "CallStation"):
            if strength > 0.7:
                ratio = self._rng.uniform(0.35, 0.65)
            elif strength < 0.25:
                ratio = self._rng.uniform(0.25, 0.50)
            else:
                ratio = self._rng.uniform(0.25, 0.45)
        elif label == "Maniac":
            if strength > 0.7:
                ratio = self._rng.uniform(0.75, 1.1)
            elif strength < 0.25:
                ratio = self._rng.uniform(0.55, 0.85)
            else:
                ratio = self._rng.uniform(0.50, 0.75)
        elif label == "Nit":
            if strength > 0.7:
                ratio = self._rng.uniform(0.45, 0.65)
            elif strength < 0.25:
                ratio = self._rng.uniform(0.35, 0.55)
            else:
                ratio = self._rng.uniform(0.30, 0.45)
        elif label == "LAG":
            if strength > 0.7:
                ratio = self._rng.uniform(0.60, 0.95)
            elif strength < 0.25:
                ratio = self._rng.uniform(0.50, 0.80)
            else:
                ratio = self._rng.uniform(0.40, 0.65)
        else:
            if strength > 0.7:
                ratio = self._rng.uniform(0.55, 0.80)
            elif strength < 0.25:
                ratio = self._rng.uniform(0.40, 0.65)
            else:
                ratio = self._rng.uniform(0.35, 0.55)

        return int(pot * ratio)

    def _draw_bonus(self, hole_cards: list[int], board: list[int]) -> float:
        if len(board) >= 5:
            return 0.0

        all_cards = hole_cards + board
        suits = [Card.get_suit_int(c) for c in all_cards]
        ranks = sorted([Card.get_rank_int(c) for c in all_cards])

        bonus = 0.0

        for s in set(suits):
            count = suits.count(s)
            if count == 4:
                bonus = max(bonus, 0.12)
            elif count == 3 and len(board) <= 3:
                bonus = max(bonus, 0.04)

        unique_ranks = sorted(set(ranks))
        for i in range(len(unique_ranks) - 3):
            window = unique_ranks[i:i + 5] if i + 5 <= len(unique_ranks) else unique_ranks[i:]
            if len(window) >= 4 and window[-1] - window[0] <= 4:
                bonus = max(bonus, 0.08)

        return bonus

    def _preflop_strength(self, hole_cards: list[int]) -> float:
        if not hole_cards or len(hole_cards) < 2:
            return 0.5
        r1 = Card.get_rank_int(hole_cards[0])
        r2 = Card.get_rank_int(hole_cards[1])
        s1 = Card.get_suit_int(hole_cards[0])
        s2 = Card.get_suit_int(hole_cards[1])

        high = max(r1, r2)
        low = min(r1, r2)
        suited = s1 == s2

        score = (high + low) / 24.0
        if r1 == r2:
            score += 0.3
        if suited:
            score += 0.05
        if high - low <= 2 and high != low:
            score += 0.03
        if high >= 10:
            score += 0.1

        return min(1.0, score)
