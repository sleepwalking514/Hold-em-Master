from __future__ import annotations

import math
import numpy as np
from typing import Optional

from treys import Card, Evaluator

from data.preflop_ranges import (
    RANKS, RANK_INDEX, POSITION_OPEN_TIERS, HAND_TIERS, _hand_tier,
)
from profiler.player_profile import PlayerProfile


EVALUATOR = Evaluator()
MATRIX_SIZE = 13


def _sigmoid(x: float, center: float, steepness: float) -> float:
    z = steepness * (x - center)
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _gaussian_peak(x: float, center: float, width: float) -> float:
    return math.exp(-((x - center) ** 2) / (2 * width ** 2))


class HandRangeMatrix:
    """13x13 hand range matrix. Upper triangle = suited, lower = offsuit, diagonal = pairs."""

    def __init__(self):
        self.matrix = np.zeros((MATRIX_SIZE, MATRIX_SIZE), dtype=np.float64)

    def set_uniform(self, value: float = 1.0) -> None:
        self.matrix[:] = value

    def get(self, rank1_idx: int, rank2_idx: int) -> float:
        return self.matrix[rank1_idx, rank2_idx]

    def set(self, rank1_idx: int, rank2_idx: int, value: float) -> None:
        self.matrix[rank1_idx, rank2_idx] = max(0.0, min(1.0, value))

    def normalize(self) -> None:
        total = self.matrix.sum()
        if total > 0:
            self.matrix /= total

    def total_weight(self) -> float:
        return float(self.matrix.sum())

    def top_hands(self, n: int = 10) -> list[tuple[str, float]]:
        results = []
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                if self.matrix[i, j] > 0.001:
                    hand = _idx_to_hand(i, j)
                    results.append((hand, float(self.matrix[i, j])))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:n]

    def range_percentage(self) -> float:
        total_combos = 0.0
        weighted = 0.0
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                if i == j:
                    combos = 6
                elif i < j:
                    combos = 4
                else:
                    combos = 12
                total_combos += combos
                weighted += combos * self.matrix[i, j]
        return weighted / total_combos if total_combos > 0 else 0.0

    def to_combo_list(self, board: list[int] | None = None) -> list[tuple[int, int, float]]:
        from ui.card_parser import ALL_CARDS
        suits = [1, 2, 4, 8]
        dead = set(board) if board else set()
        combos = []
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                w = self.matrix[i, j]
                if w < 0.01:
                    continue
                if i == j:
                    for si in range(4):
                        for sj in range(si + 1, 4):
                            c1 = Card.new(RANKS[i] + "shdc"[si])
                            c2 = Card.new(RANKS[i] + "shdc"[sj])
                            if c1 not in dead and c2 not in dead:
                                combos.append((c1, c2, w))
                elif i < j:
                    for s in range(4):
                        c1 = Card.new(RANKS[i] + "shdc"[s])
                        c2 = Card.new(RANKS[j] + "shdc"[s])
                        if c1 not in dead and c2 not in dead:
                            combos.append((c1, c2, w))
                else:
                    for si in range(4):
                        for sj in range(4):
                            if si == sj:
                                continue
                            c1 = Card.new(RANKS[i] + "shdc"[si])
                            c2 = Card.new(RANKS[j] + "shdc"[sj])
                            if c1 not in dead and c2 not in dead:
                                combos.append((c1, c2, w))
        return combos

    def copy(self) -> HandRangeMatrix:
        m = HandRangeMatrix()
        m.matrix = self.matrix.copy()
        return m


def _idx_to_hand(i: int, j: int) -> str:
    if i == j:
        return RANKS[i] + RANKS[j]
    elif i < j:
        return RANKS[j] + RANKS[i] + "s"
    else:
        return RANKS[i] + RANKS[j] + "o"


def load_initial_range(
    position: str, vpip: float, pfr: float, action: str
) -> HandRangeMatrix:
    matrix = HandRangeMatrix()

    if action == "open_raise":
        cutoff_pct = pfr
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                hand = _idx_to_hand(i, j)
                tier = _hand_tier(hand)
                hand_pct = tier / 10.0
                if hand_pct <= cutoff_pct:
                    matrix.set(i, j, 1.0)
                elif hand_pct <= cutoff_pct + 0.05:
                    matrix.set(i, j, 1.0 - (hand_pct - cutoff_pct) / 0.05)
    elif action == "call":
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                hand = _idx_to_hand(i, j)
                tier = _hand_tier(hand)
                hand_pct = tier / 10.0
                if pfr < hand_pct <= vpip:
                    matrix.set(i, j, 1.0)
                elif vpip < hand_pct <= vpip + 0.05:
                    matrix.set(i, j, 0.5)
    elif action == "3bet":
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                hand = _idx_to_hand(i, j)
                tier = _hand_tier(hand)
                if tier <= 2:
                    matrix.set(i, j, 1.0)
                elif tier == 3:
                    matrix.set(i, j, 0.4)
                elif i < j and tier >= 7:
                    matrix.set(i, j, 0.2)
    elif action == "limp":
        for i in range(MATRIX_SIZE):
            for j in range(MATRIX_SIZE):
                hand = _idx_to_hand(i, j)
                tier = _hand_tier(hand)
                hand_pct = tier / 10.0
                if 0.1 < hand_pct <= vpip:
                    matrix.set(i, j, 0.8)

    matrix.normalize()
    return matrix


def likelihood_bet(
    equity: float, bet_size: float, pot_size: float, profile: PlayerProfile,
    wetness: float = 0.5,
) -> float:
    sizing_ratio = bet_size / max(pot_size, 1)
    aggr = profile.get_stat("aggression_freq")

    value_center = 0.65 - wetness * 0.10
    bluff_center = 0.15 + wetness * 0.10

    value = _sigmoid(equity, center=value_center, steepness=10)
    bluff = (1 - _sigmoid(equity, center=bluff_center, steepness=10)) * aggr
    pot_control_dip = _gaussian_peak(equity, center=0.40, width=0.15)
    L = value + bluff - pot_control_dip * 0.3

    if sizing_ratio > 0.75:
        pol = sizing_ratio - 0.5
        L += _sigmoid(equity, 0.80, 12) * pol
        L += (1 - _sigmoid(equity, 0.10, 12)) * pol * 0.3
        L -= _gaussian_peak(equity, 0.40, 0.12) * pol

    return max(0.05, min(0.95, L))


def likelihood_call(
    equity: float, bet_size: float, pot_size: float, profile: PlayerProfile
) -> float:
    pot_odds_val = bet_size / max(pot_size + bet_size, 1)
    call_core = _gaussian_peak(equity, center=0.45, width=0.20)
    aggr = profile.get_stat("aggression_freq")
    trap = _sigmoid(equity, 0.85, 8) * (1 - aggr) * 0.3
    fold_mask = _sigmoid(equity, center=pot_odds_val * 0.8, steepness=15)
    return max(0.05, min(0.95, (call_core + trap) * fold_mask))


def likelihood_check(equity: float, profile: PlayerProfile) -> float:
    aggr = profile.get_stat("aggression_freq")
    cr_freq = profile.advanced_actions.check_raise_freq.mean

    weak = 1 - _sigmoid(equity, 0.25, 8)
    medium = _gaussian_peak(equity, 0.45, 0.18)
    trap = _sigmoid(equity, 0.80, 8) * cr_freq
    discount = 1.0 - aggr * 0.5
    return max(0.05, min(0.95, (weak * 0.4 + medium + trap) * discount))


def _combo_equity(card1: int, card2: int, board: list[int]) -> float:
    if len(board) < 3:
        return 0.5
    rank = EVALUATOR.evaluate([card1, card2], board)
    return 1.0 - (rank / 7462.0)


class HandRangeEstimator:
    """Tracks and updates opponent hand range through a hand."""

    def __init__(self, profile: PlayerProfile):
        self.profile = profile
        self.range_matrix: Optional[HandRangeMatrix] = None
        self._history: list[tuple[str, HandRangeMatrix]] = []

    def init_range(self, position: str, action: str) -> HandRangeMatrix:
        vpip = self.profile.get_stat("vpip")
        pfr = self.profile.get_stat("pfr")
        self.range_matrix = load_initial_range(position, vpip, pfr, action)
        self._history.append(("init", self.range_matrix.copy()))
        return self.range_matrix

    def update(
        self,
        board: list[int],
        action: str,
        bet_size: float = 0,
        pot_size: float = 0,
    ) -> HandRangeMatrix:
        if self.range_matrix is None:
            self.range_matrix = HandRangeMatrix()
            self.range_matrix.set_uniform(1.0)
            self.range_matrix.normalize()

        if action == "fold":
            self.range_matrix.matrix[:] = 0.0
            return self.range_matrix

        from env.board_texture import analyze_board
        wetness = analyze_board(board).wetness if board else 0.5

        combos = self.range_matrix.to_combo_list(board)
        new_matrix = HandRangeMatrix()

        for c1, c2, weight in combos:
            if weight < 0.001:
                continue
            eq = _combo_equity(c1, c2, board)
            if action in ("bet", "raise"):
                L = likelihood_bet(eq, bet_size, pot_size, self.profile, wetness)
            elif action == "call":
                L = likelihood_call(eq, bet_size, pot_size, self.profile)
            elif action == "check":
                L = likelihood_check(eq, self.profile)
            else:
                L = 0.5

            r1 = Card.get_rank_int(c1)
            r2 = Card.get_rank_int(c2)
            s1 = Card.get_suit_int(c1)
            s2 = Card.get_suit_int(c2)
            if r1 == r2:
                i, j = r1, r2
            elif s1 == s2:
                i, j = min(r1, r2), max(r1, r2)
            else:
                i, j = max(r1, r2), min(r1, r2)

            current = new_matrix.get(i, j)
            new_matrix.set(i, j, max(current, weight * L))

        new_matrix.normalize()
        self.range_matrix = new_matrix
        self._history.append((action, new_matrix.copy()))
        return self.range_matrix

    def get_weighted_combos(self, board: list[int]) -> list[tuple[int, int]]:
        if self.range_matrix is None:
            return []
        combos = self.range_matrix.to_combo_list(board)
        result = []
        for c1, c2, w in combos:
            if w > 0.05:
                result.append((c1, c2))
        return result

    def range_strength_buckets(self, board: list[int]) -> dict[str, float]:
        if self.range_matrix is None:
            return {}
        combos = self.range_matrix.to_combo_list(board)
        if not combos:
            return {}

        buckets = {"超强": 0.0, "强": 0.0, "中等": 0.0, "投机": 0.0, "弱": 0.0}
        total = sum(w for _, _, w in combos)
        if total == 0:
            return buckets

        for c1, c2, w in combos:
            eq = _combo_equity(c1, c2, board)
            if eq >= 0.80:
                buckets["超强"] += w
            elif eq >= 0.60:
                buckets["强"] += w
            elif eq >= 0.40:
                buckets["中等"] += w
            elif eq >= 0.25:
                buckets["投机"] += w
            else:
                buckets["弱"] += w

        for k in buckets:
            buckets[k] /= total
        return buckets
