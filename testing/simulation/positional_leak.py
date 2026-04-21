"""位置漏洞分析 - 按位置统计Hero表现并检测GTO偏离。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_analysis_common import HandSummary


# 6-max GTO baseline ranges (approximate VPIP)
GTO_BASELINES_6MAX = {
    "UTG": {"vpip": 0.20, "pfr": 0.17},
    "MP": {"vpip": 0.23, "pfr": 0.20},
    "CO": {"vpip": 0.28, "pfr": 0.24},
    "BTN": {"vpip": 0.42, "pfr": 0.36},
    "SB": {"vpip": 0.36, "pfr": 0.28},
    "BB": {"vpip": 0.40, "pfr": 0.12},
}


@dataclass
class PositionStats:
    position: str
    hands: int = 0
    vpip_count: int = 0
    pfr_count: int = 0
    total_profit: int = 0
    showdown_count: int = 0
    showdown_wins: int = 0
    cbet_opportunities: int = 0
    cbet_count: int = 0
    postflop_folds: int = 0
    postflop_hands: int = 0

    @property
    def vpip(self) -> float:
        return self.vpip_count / max(self.hands, 1)

    @property
    def pfr(self) -> float:
        return self.pfr_count / max(self.hands, 1)

    @property
    def bb_per_hand(self) -> float:
        return 0.0  # set externally with big_blind

    @property
    def wtsd(self) -> float:
        return self.showdown_count / max(self.hands, 1)

    @property
    def wsd(self) -> float:
        return self.showdown_wins / max(self.showdown_count, 1)

    @property
    def cbet_rate(self) -> float:
        return self.cbet_count / max(self.cbet_opportunities, 1)


class PositionalLeakTracker:
    def __init__(self, big_blind: int = 10):
        self.big_blind = big_blind
        self.stats: dict[str, PositionStats] = {}
        self.total_hands = 0

    def record(self, summary: HandSummary) -> None:
        self.total_hands += 1
        pos = summary.hero_position
        if pos not in self.stats:
            self.stats[pos] = PositionStats(position=pos)
        s = self.stats[pos]
        s.hands += 1
        s.total_profit += summary.hero_profit

        if summary.had_showdown:
            s.showdown_count += 1
            if summary.hero_profit > 0:
                s.showdown_wins += 1

        if not summary.hero_decisions:
            return

        # VPIP: voluntarily put money in preflop (not counting BB check)
        first = summary.hero_decisions[0]
        if first.street == "preflop" and first.action in ("call", "raise", "all_in"):
            s.vpip_count += 1
            if first.action in ("raise", "all_in"):
                s.pfr_count += 1

        # Postflop stats
        if summary.streets_played >= 2:
            s.postflop_hands += 1
            postflop = [d for d in summary.hero_decisions if d.street != "preflop"]
            if any(d.action == "fold" for d in postflop):
                s.postflop_folds += 1

            # C-bet detection: Hero was preflop raiser and first to act on flop
            was_pfr = first.action in ("raise", "all_in")
            if was_pfr:
                flop_decisions = [d for d in postflop if d.street == "flop"]
                if flop_decisions:
                    s.cbet_opportunities += 1
                    if flop_decisions[0].action in ("bet", "raise"):
                        s.cbet_count += 1

    def _detect_leaks(self) -> list[str]:
        leaks = []
        for pos, s in self.stats.items():
            if s.hands < 3:
                continue
            baseline = GTO_BASELINES_6MAX.get(pos)
            if not baseline:
                continue

            bb_per_hand = s.total_profit / max(s.hands, 1) / max(self.big_blind, 1)

            if pos == "BTN" and s.vpip < 0.35:
                leaks.append(f"BTN VPIP={s.vpip:.0%} (建议≥35%): 位置优势未充分利用")
            if pos == "CO" and s.vpip < 0.22:
                leaks.append(f"CO VPIP={s.vpip:.0%} (建议≥22%): CO位过紧")
            if pos == "UTG" and s.vpip > 0.28:
                leaks.append(f"UTG VPIP={s.vpip:.0%} (建议≤28%): 前位过松")
            if pos == "SB" and s.vpip > 0 and s.hands >= 5:
                sb_fold_rate = 1.0 - s.vpip
                if sb_fold_rate > 0.75:
                    leaks.append(f"SB 弃牌率={sb_fold_rate:.0%} (建议<75%): SB过度弃牌")
            if pos == "BB" and s.hands >= 5:
                bb_fold_rate = 1.0 - s.vpip
                if bb_fold_rate > 0.60:
                    leaks.append(f"BB 弃牌率={bb_fold_rate:.0%} (建议<60%): BB面对偷盲过弱")

            if bb_per_hand < -2.0 and pos not in ("SB", "BB"):
                leaks.append(f"{pos} bb/hand={bb_per_hand:.1f}: 该位置亏损严重")

        return leaks

    def summary_report(self) -> str:
        leaks = self._detect_leaks()
        return f"位置分析: {len(self.stats)}个位置 | 检测到漏洞: {len(leaks)}个"

    def detailed_report(self) -> str:
        lines = [
            "=" * 70,
            "           位置漏洞分析报告",
            "=" * 70,
            "",
        ]

        # Position table
        pos_order = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
        lines.append(f"{'位置':<6s} {'手数':>4s} {'VPIP':>6s} {'PFR':>6s} "
                     f"{'bb/hand':>8s} {'到摊率':>6s} {'摊牌胜率':>8s} {'Cbet':>6s}")
        lines.append("─" * 60)

        for pos in pos_order:
            s = self.stats.get(pos)
            if not s:
                continue
            bb_per_hand = s.total_profit / max(s.hands, 1) / max(self.big_blind, 1)
            cbet_str = f"{s.cbet_rate:.0%}" if s.cbet_opportunities > 0 else "N/A"
            wsd_str = f"{s.wsd:.0%}" if s.showdown_count > 0 else "N/A"
            lines.append(
                f"{pos:<6s} {s.hands:>4d} {s.vpip:>5.0%} {s.pfr:>5.0%} "
                f"{bb_per_hand:>+7.1f} {s.wtsd:>5.0%} {wsd_str:>8s} {cbet_str:>6s}"
            )
        lines.append("")

        # Leaks
        leaks = self._detect_leaks()
        if leaks:
            lines.append("【检测到的漏洞】")
            for leak in leaks:
                lines.append(f"  ⚠ {leak}")
        else:
            lines.append("【检测到的漏洞】无明显位置漏洞")
        lines.append("")

        # GTO comparison
        lines.append("【与GTO基线对比】")
        for pos in pos_order:
            s = self.stats.get(pos)
            baseline = GTO_BASELINES_6MAX.get(pos)
            if not s or not baseline or s.hands < 3:
                continue
            vpip_diff = s.vpip - baseline["vpip"]
            pfr_diff = s.pfr - baseline["pfr"]
            if abs(vpip_diff) > 0.08 or abs(pfr_diff) > 0.08:
                lines.append(f"  {pos}: VPIP {vpip_diff:+.0%} vs GTO, PFR {pfr_diff:+.0%} vs GTO")
        lines.append("")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        result = {}
        for pos, s in self.stats.items():
            bb_per_hand = s.total_profit / max(s.hands, 1) / max(self.big_blind, 1)
            result[pos] = {
                "hands": s.hands,
                "vpip": round(s.vpip, 3),
                "pfr": round(s.pfr, 3),
                "bb_per_hand": round(bb_per_hand, 2),
                "wtsd": round(s.wtsd, 3),
                "wsd": round(s.wsd, 3),
                "cbet_rate": round(s.cbet_rate, 3),
                "total_profit": s.total_profit,
            }
        return {
            "position_stats": result,
            "leaks": self._detect_leaks(),
        }

    def write_outputs(self, session_dir: Path) -> None:
        with open(session_dir / "positional_leak_data.json", "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)
        with open(session_dir / "positional_leak_analysis.txt", "w", encoding="utf-8") as f:
            f.write(self.detailed_report())
