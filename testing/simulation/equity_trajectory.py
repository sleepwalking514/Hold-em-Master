"""Equity轨迹分析 - 追踪equity跨街变化模式并评估advisor反应。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_analysis_common import HandSummary, HeroDecision


PATTERN_LABELS = {
    "rising": "上升",
    "falling": "下降",
    "cliff": "断崖",
    "stable_high": "稳定高位",
    "stable_low": "稳定低位",
    "volatile": "波动",
}


@dataclass
class TrajectoryRecord:
    hand_number: int
    pattern: str
    equities: list[float]
    actions: list[str]
    hero_profit: int
    hero_position: str
    hero_hole_cards: list[str]
    board: list[str]
    issue: str | None = None  # description of potential problem


class EquityTrajectoryTracker:
    def __init__(self, big_blind: int = 10):
        self.big_blind = big_blind
        self.records: list[TrajectoryRecord] = []
        self.total_hands: int = 0

    def record(self, summary: HandSummary) -> None:
        self.total_hands += 1
        if summary.streets_played < 2 or len(summary.hero_decisions) < 2:
            return

        equities = [d.equity for d in summary.hero_decisions if d.equity > 0]
        if len(equities) < 2:
            return

        actions = [d.action for d in summary.hero_decisions]
        pattern = self._classify_pattern(equities)
        issue = self._detect_issue(pattern, equities, summary.hero_decisions, summary.hero_profit)

        self.records.append(TrajectoryRecord(
            hand_number=summary.hand_number,
            pattern=pattern,
            equities=equities,
            actions=actions,
            hero_profit=summary.hero_profit,
            hero_position=summary.hero_position,
            hero_hole_cards=summary.hero_hole_cards,
            board=summary.board,
            issue=issue,
        ))

    def _classify_pattern(self, equities: list[float]) -> str:
        if len(equities) < 2:
            return "volatile"

        first, last = equities[0], equities[-1]
        diffs = [equities[i + 1] - equities[i] for i in range(len(equities) - 1)]

        # Cliff: any single drop > 0.15
        max_drop = max(-d for d in diffs) if diffs else 0
        if max_drop > 0.15:
            return "cliff"

        # Stable high: all > 0.55
        if all(e > 0.55 for e in equities):
            return "stable_high"

        # Stable low: all < 0.35
        if all(e < 0.35 for e in equities):
            return "stable_low"

        # Rising: overall increase > 0.1
        if last - first > 0.1 and sum(1 for d in diffs if d > 0) >= len(diffs) * 0.6:
            return "rising"

        # Falling: overall decrease > 0.1
        if first - last > 0.1 and sum(1 for d in diffs if d < 0) >= len(diffs) * 0.6:
            return "falling"

        return "volatile"

    def _detect_issue(self, pattern: str, equities: list[float],
                      decisions: list[HeroDecision], profit: int) -> str | None:
        # Falling equity but Hero didn't fold early enough
        if pattern == "falling" and profit < 0:
            aggressive_after_drop = any(
                d.action in ("call", "bet", "raise", "all_in") and d.equity < 0.3
                for d in decisions if d.street != "preflop"
            )
            if aggressive_after_drop:
                return "equity持续下降但未及时退出"

        # Cliff: Hero continued investing after the cliff
        if pattern == "cliff" and profit < 0:
            cliff_idx = None
            for i in range(len(equities) - 1):
                if equities[i] - equities[i + 1] > 0.15:
                    cliff_idx = i + 1
                    break
            if cliff_idx is not None and cliff_idx < len(decisions):
                post_cliff = decisions[cliff_idx:]
                invested_after = any(d.action in ("call", "bet", "raise", "all_in") for d in post_cliff)
                if invested_after:
                    return "equity断崖后仍投入筹码"

        # Stable high but passive (missed value)
        if pattern == "stable_high" and profit >= 0:
            postflop = [d for d in decisions if d.street != "preflop"]
            all_passive = all(d.action in ("check", "call") for d in postflop)
            if all_passive and len(postflop) >= 2:
                return "equity高位但未主动下注(错失价值)"

        # Rising but passive
        if pattern == "rising" and profit >= 0:
            postflop = [d for d in decisions if d.street != "preflop"]
            if postflop and all(d.action in ("check", "call") for d in postflop):
                return "equity上升但未加大投入"

        return None

    def _pattern_stats(self) -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for r in self.records:
            if r.pattern not in stats:
                stats[r.pattern] = {"count": 0, "total_profit": 0, "issues": 0}
            stats[r.pattern]["count"] += 1
            stats[r.pattern]["total_profit"] += r.hero_profit
            if r.issue:
                stats[r.pattern]["issues"] += 1
        for p in stats:
            stats[p]["avg_profit_bb"] = (
                stats[p]["total_profit"] / max(stats[p]["count"], 1) / max(self.big_blind, 1)
            )
        return stats

    def summary_report(self) -> str:
        stats = self._pattern_stats()
        parts = [f"{PATTERN_LABELS.get(p, p)}={s['count']}" for p, s in sorted(stats.items())]
        issues = sum(1 for r in self.records if r.issue)
        return f"Equity轨迹: {len(self.records)}手多街 | 模式: {', '.join(parts)} | 问题手: {issues}"

    def detailed_report(self) -> str:
        lines = [
            "=" * 70,
            "           Equity轨迹分析报告",
            "=" * 70,
            "",
        ]

        lines.append(f"多街手牌数: {len(self.records)}/{self.total_hands} (排除翻前结束)")
        stats = self._pattern_stats()
        dist_parts = [f"{PATTERN_LABELS.get(p, p)}={s['count']}" for p, s in sorted(stats.items())]
        lines.append(f"轨迹模式分布: {', '.join(dist_parts)}")
        lines.append("")

        # Pattern profit stats
        lines.append("【模式盈亏统计】")
        for p, s in sorted(stats.items(), key=lambda x: x[1]["avg_profit_bb"]):
            label = PATTERN_LABELS.get(p, p)
            lines.append(f"  {label:8s}: {s['count']:2d}手, "
                         f"平均 {s['avg_profit_bb']:+.1f}BB/手, "
                         f"问题手={s['issues']}")
        lines.append("")

        # Problem hands
        issue_records = [r for r in self.records if r.issue]
        if issue_records:
            lines.append("【问题轨迹】")
            for r in sorted(issue_records, key=lambda x: x.hero_profit):
                eq_str = " → ".join(f"{e:.1%}" for e in r.equities)
                act_str = " → ".join(r.actions)
                profit_bb = r.hero_profit / max(self.big_blind, 1)
                lines.append(f"  第{r.hand_number}手: {eq_str} ({PATTERN_LABELS.get(r.pattern, r.pattern)})")
                lines.append(f"    位置: {r.hero_position} | 手牌: {' '.join(r.hero_hole_cards)}")
                if r.board:
                    lines.append(f"    公共牌: {' '.join(r.board)}")
                lines.append(f"    行动: {act_str} | 结果: {profit_bb:+.1f}BB")
                lines.append(f"    问题: {r.issue}")
                lines.append("")
        else:
            lines.append("【问题轨迹】无")
            lines.append("")

        # Good examples (stable_high or rising with profit)
        good_records = [r for r in self.records
                        if r.pattern in ("stable_high", "rising") and r.hero_profit > 5 * self.big_blind
                        and not r.issue]
        if good_records:
            lines.append("【优秀轨迹示例】(前3手)")
            for r in sorted(good_records, key=lambda x: -x.hero_profit)[:3]:
                eq_str = " → ".join(f"{e:.1%}" for e in r.equities)
                act_str = " → ".join(r.actions)
                profit_bb = r.hero_profit / max(self.big_blind, 1)
                lines.append(f"  第{r.hand_number}手: {eq_str} ({PATTERN_LABELS.get(r.pattern, r.pattern)})")
                lines.append(f"    行动: {act_str} | 结果: {profit_bb:+.1f}BB")
                lines.append("")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "total_multistreet_hands": len(self.records),
            "pattern_stats": {
                p: {"count": s["count"], "avg_profit_bb": round(s["avg_profit_bb"], 2), "issues": s["issues"]}
                for p, s in self._pattern_stats().items()
            },
            "issue_hands": [
                {
                    "hand_number": r.hand_number,
                    "pattern": r.pattern,
                    "equities": [round(e, 4) for e in r.equities],
                    "actions": r.actions,
                    "hero_profit_bb": round(r.hero_profit / max(self.big_blind, 1), 1),
                    "issue": r.issue,
                }
                for r in self.records if r.issue
            ],
            "all_trajectories": [
                {
                    "hand_number": r.hand_number,
                    "pattern": r.pattern,
                    "equities": [round(e, 4) for e in r.equities],
                    "profit_bb": round(r.hero_profit / max(self.big_blind, 1), 1),
                }
                for r in self.records
            ],
        }

    def write_outputs(self, session_dir: Path) -> None:
        with open(session_dir / "equity_trajectory_data.json", "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)
        with open(session_dir / "equity_trajectory_analysis.txt", "w", encoding="utf-8") as f:
            f.write(self.detailed_report())
