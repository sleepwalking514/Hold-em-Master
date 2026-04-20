from __future__ import annotations

import random
from typing import Optional

from treys import Evaluator

from env.action_space import ActionType, Street
from env.game_state import GameState, Player
from testing.simulation.label_presets import AIOpponentConfig, get_preset

EVALUATOR = Evaluator()


class AIOpponent:
    def __init__(self, config: AIOpponentConfig, seed: int | None = None):
        self.config = config
        self._rng = random.Random(seed)

    def decide(
        self, game_state: GameState, player: Player
    ) -> tuple[ActionType, int]:
        if game_state.street == Street.PREFLOP:
            return self._decide_preflop(game_state, player)
        return self._decide_postflop(game_state, player)

    def _decide_preflop(
        self, gs: GameState, player: Player
    ) -> tuple[ActionType, int]:
        facing_bet = gs.current_bet > player.current_bet
        call_amount = gs.current_bet - player.current_bet

        hand_strength = self._preflop_strength(player.hole_cards)
        noise = self._rng.gauss(0, self.config.tilt_variance)
        effective_strength = max(0.0, min(1.0, hand_strength + noise))

        enter_threshold = 1.0 - self.config.vpip_target
        raise_threshold = 1.0 - self.config.pfr_target

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

        return ActionType.CALL, gs.current_bet

    def _decide_postflop(
        self, gs: GameState, player: Player
    ) -> tuple[ActionType, int]:
        if not player.hole_cards or not gs.board:
            return ActionType.CHECK, 0

        hand_rank = EVALUATOR.evaluate(player.hole_cards, gs.board)
        strength = 1.0 - (hand_rank / 7462.0)
        noise = self._rng.gauss(0, self.config.tilt_variance)
        effective = max(0.0, min(1.0, strength + noise))

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

        if strength > 0.75:
            if self._rng.random() < aggr:
                raise_to = min(gs.current_bet * 2 + gs.pot // 2, player.stack + player.current_bet)
                return ActionType.RAISE, raise_to
            return ActionType.CALL, gs.current_bet

        if strength > pot_odds + 0.05:
            if self._rng.random() < fold_cbet and strength < 0.4:
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

        should_bet = False
        if strength > 0.55:
            should_bet = self._rng.random() < (aggr + 0.2)
        elif strength < 0.25:
            should_bet = self._rng.random() < bluff_freq
        else:
            should_bet = self._rng.random() < aggr * 0.5

        if should_bet:
            if strength > 0.7:
                size = int(gs.pot * self._rng.uniform(0.6, 0.9))
            elif strength < 0.25:
                size = int(gs.pot * self._rng.uniform(0.4, 0.7))
            else:
                size = int(gs.pot * self._rng.uniform(0.3, 0.5))
            size = max(gs.big_blind, min(size, player.stack))
            if size >= player.stack:
                return ActionType.ALL_IN, player.stack + player.current_bet
            return ActionType.BET, size
        return ActionType.CHECK, 0

    def _preflop_strength(self, hole_cards: list[int]) -> float:
        if not hole_cards or len(hole_cards) < 2:
            return 0.5
        from treys import Card
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
