"""慢性失血分析 - 检测持续小亏损模式和盲注消耗。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_analysis_common import HandSummary


@dataclass
class LosingStreak:
    start_hand: int
    end_hand: int
    total_loss: int
    hand_count: int
    causes: dict[str, int]  # e.g. {"blind_fold": 3, "postflop_fold": 2}


class BleedPatternTracker:
    def __init__(self, big_blind: int = 10, catastrophic_threshold_bb: float = 15.0):
        self.big_blind = big_blind
        self.catastrophic_threshold_bb = catastrophic_threshold_bb
        self.hands: list[HandSummary] = []

    def record(self, summary: HandSummary) -> None:
        self.hands.append(summary)

    def _is_catastrophic(self, s: HandSummary) -> bool:
        return (-s.hero_profit / max(self.big_blind, 1)) >= self.catastrophic_threshold_bb

    def _detect_losing_streaks(self, window: int = 10, threshold: int = 7) -> list[LosingStreak]:
        streaks = []
        profits = [h.hero_profit for h in self.hands]
        n = len(profits)
        i = 0
        while i <= n - window:
            losses_in_window = sum(1 for p in profits[i:i + window] if p <= 0)
            if losses_in_window >= threshold:
                # Extend the streak
                end = i + window
                while end < n and profits[end] <= 0:
                    end += 1
                # Analyze causes
                causes: dict[str, int] = {}
                total_loss = 0
                for h in self.hands[i:end]:
                    if h.hero_profit <= 0:
                        total_loss += h.hero_profit
                        if h.hero_folded_preflop:
                            if h.hero_position in ("SB", "BB"):
                                causes["blind_fold"] = causes.get("blind_fold", 0) + 1
                            else:
                                causes["preflop_fold"] = causes.get("preflop_fold", 0) + 1
                        elif h.hero_profit < 0:
                            causes["postflop_loss"] = causes.get("postflop_loss", 0) + 1
                        else:
                            causes["break_even"] = causes.get("break_even", 0) + 1

                streaks.append(LosingStreak(
                    start_hand=self.hands[i].hand_number,
                    end_hand=self.hands[end - 1].hand_number,
                    total_loss=total_loss,
                    hand_count=end - i,
                    causes=causes,
                ))
                i = end
            else:
                i += 1
        return streaks

    def _blind_stats(self) -> dict[str, Any]:
        sb_hands = [h for h in self.hands if h.hero_position == "SB"]
        bb_hands = [h for h in self.hands if h.hero_position == "BB"]

        sb_folds = sum(1 for h in sb_hands if h.hero_folded_preflop)
        bb_folds = sum(1 for h in bb_hands if h.hero_folded_preflop)
        sb_profit = sum(h.hero_profit for h in sb_hands)
        bb_profit = sum(h.hero_profit for h in bb_hands)

        return {
            "sb_hands": len(sb_hands),
            "sb_fold_rate": sb_folds / max(len(sb_hands), 1),
            "sb_net_profit": sb_profit,
            "bb_hands": len(bb_hands),
            "bb_fold_rate": bb_folds / max(len(bb_hands), 1),
            "bb_net_profit": bb_profit,
            "blind_total_loss": sb_profit + bb_profit if (sb_profit + bb_profit) < 0 else 0,
        }

    def _steal_stats(self) -> dict[str, Any]:
        steal_positions = ("BTN", "CO")
        steal_attempts = 0
        steal_success = 0
        steal_profit = 0

        for h in self.hands:
            if h.hero_position not in steal_positions:
                continue
            if not h.hero_decisions:
                continue
            first = h.hero_decisions[0]
            if first.street == "preflop" and first.action == "raise":
                steal_attempts += 1
                # Success = everyone folds (Hero wins without showdown, preflop only)
                if h.streets_played == 1 and h.hero_profit > 0:
                    steal_success += 1
                steal_profit += h.hero_profit

        return {
            "attempts": steal_attempts,
            "success": steal_success,
            "success_rate": steal_success / max(steal_attempts, 1),
            "net_profit": steal_profit,
        }

    def _dead_money_stats(self) -> dict[str, Any]:
        dead_money = 0
        dead_money_hands = 0
        fold_street_dist: dict[str, int] = {"preflop": 0, "flop": 0, "turn": 0, "river": 0}

        for h in self.hands:
            if h.hero_invested > 0 and h.hero_profit < 0 and not h.had_showdown:
                dead_money += -h.hero_profit
                dead_money_hands += 1
            # Track which street Hero folded on
            for d in h.hero_decisions:
                if d.action == "fold":
                    fold_street_dist[d.street] = fold_street_dist.get(d.street, 0) + 1
                    break

        return {
            "total": dead_money,
            "hands": dead_money_hands,
            "avg_per_hand": dead_money / max(dead_money_hands, 1),
            "fold_street_distribution": fold_street_dist,
        }

    def _bleed_rate(self) -> float:
        non_catastrophic = [h.hero_profit for h in self.hands if not self._is_catastrophic(h)]
        if not non_catastrophic:
            return 0.0
        losses_only = [p for p in non_catastrophic if p < 0]
        return sum(losses_only) / max(len(non_catastrophic), 1) / max(self.big_blind, 1)

    def summary_report(self) -> str:
        rate = self._bleed_rate()
        streaks = self._detect_losing_streaks()
        longest = max((s.hand_count for s in streaks), default=0)
        return f"失血速率: {rate:.2f} bb/hand | 最长连亏: {longest}手 | 连亏段: {len(streaks)}个"

    def detailed_report(self) -> str:
        lines = [
            "=" * 70,
            "           慢性失血分析报告",
            "=" * 70,
            "",
        ]

        total = len(self.hands)
        rate = self._bleed_rate()
        blind_stats = self._blind_stats()
        steal_stats = self._steal_stats()
        dead_money = self._dead_money_stats()
        streaks = self._detect_losing_streaks()

        lines.append(f"总手数: {total}")
        lines.append(f"失血速率: {rate:.2f} bb/hand (排除巨亏手)")
        lines.append(f"死钱总计: -{dead_money['total']} chips "
                     f"(Hero投入后弃牌的累计损失, {dead_money['hands']}手)")
        longest = max(streaks, key=lambda s: s.hand_count) if streaks else None
        if longest:
            lines.append(f"最长连亏: {longest.hand_count}手 "
                         f"(第{longest.start_hand}-{longest.end_hand}手, "
                         f"累计 {longest.total_loss} chips)")
        lines.append("")

        # Blind defense
        lines.append("【盲注消耗】")
        sb_fold_pct = blind_stats["sb_fold_rate"] * 100
        bb_fold_pct = blind_stats["bb_fold_rate"] * 100
        lines.append(f"  SB 手数: {blind_stats['sb_hands']}, "
                     f"弃牌率: {sb_fold_pct:.0f}% "
                     f"{'(偏高, 6人桌建议<65%)' if sb_fold_pct > 65 else '(正常)'}")
        lines.append(f"  BB 手数: {blind_stats['bb_hands']}, "
                     f"弃牌率: {bb_fold_pct:.0f}% "
                     f"{'(偏高, 建议<55%)' if bb_fold_pct > 55 else '(正常)'}")
        lines.append(f"  SB 净盈亏: {blind_stats['sb_net_profit']:+d} chips")
        lines.append(f"  BB 净盈亏: {blind_stats['bb_net_profit']:+d} chips")
        total_profit = sum(h.hero_profit for h in self.hands)
        blind_loss = blind_stats["sb_net_profit"] + blind_stats["bb_net_profit"]
        if total_profit < 0 and blind_loss < 0:
            pct = blind_loss / total_profit * 100
            lines.append(f"  盲注位亏损占总亏损: {pct:.0f}%")
        lines.append("")

        # Steal efficiency
        lines.append("【偷盲效率】")
        lines.append(f"  BTN/CO open: {steal_stats['attempts']}次, "
                     f"成功偷盲: {steal_stats['success']}次 "
                     f"({steal_stats['success_rate']*100:.1f}%)")
        lines.append(f"  偷盲净收益: {steal_stats['net_profit']:+d} chips")
        lines.append("")

        # Fold street distribution
        lines.append("【弃牌街分布】")
        dist = dead_money["fold_street_distribution"]
        lines.append(f"  翻前弃牌: {dist.get('preflop', 0)}次")
        lines.append(f"  翻后弃牌: flop={dist.get('flop', 0)}, "
                     f"turn={dist.get('turn', 0)}, river={dist.get('river', 0)}")
        if dead_money["hands"] > 0:
            avg_bb = dead_money["avg_per_hand"] / max(self.big_blind, 1)
            lines.append(f"  翻后弃牌平均已投入: {avg_bb:.1f}BB")
        lines.append("")

        # Losing streaks detail
        if streaks:
            lines.append("【连亏段详情】")
            for s in sorted(streaks, key=lambda x: x.total_loss):
                lines.append(f"  第{s.start_hand}-{s.end_hand}手: "
                             f"累计 {s.total_loss} chips ({s.hand_count}手)")
                cause_parts = []
                for cause, count in sorted(s.causes.items(), key=lambda x: -x[1]):
                    label = {"blind_fold": "盲注弃牌", "preflop_fold": "翻前弃牌",
                             "postflop_loss": "翻后亏损", "break_even": "持平"}.get(cause, cause)
                    cause_parts.append(f"{label}={count}")
                lines.append(f"    主因: {', '.join(cause_parts)}")
            lines.append("")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "bleed_rate_bb": round(self._bleed_rate(), 3),
            "blind_stats": self._blind_stats(),
            "steal_stats": self._steal_stats(),
            "dead_money": self._dead_money_stats(),
            "losing_streaks": [
                {
                    "start_hand": s.start_hand,
                    "end_hand": s.end_hand,
                    "total_loss": s.total_loss,
                    "hand_count": s.hand_count,
                    "causes": s.causes,
                }
                for s in self._detect_losing_streaks()
            ],
        }

    def write_outputs(self, session_dir: Path) -> None:
        with open(session_dir / "bleed_pattern_data.json", "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)
        with open(session_dir / "bleed_pattern_analysis.txt", "w", encoding="utf-8") as f:
            f.write(self.detailed_report())
