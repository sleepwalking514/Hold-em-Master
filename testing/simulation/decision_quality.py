"""决策质量分析 - 评估advisor推荐的质量和校准度。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_analysis_common import HandSummary, HeroDecision


@dataclass
class DecisionRecord:
    hand_number: int
    street: str
    action: str
    amount: int
    equity: float
    confidence: float
    hand_strength: int | None
    baseline_action: str
    hero_profit: int
    won: bool


class DecisionQualityTracker:
    def __init__(self, big_blind: int = 10):
        self.big_blind = big_blind
        self.decisions: list[DecisionRecord] = []
        self.total_hands = 0

    def record(self, summary: HandSummary) -> None:
        self.total_hands += 1
        won = summary.hero_profit > 0
        for d in summary.hero_decisions:
            self.decisions.append(DecisionRecord(
                hand_number=summary.hand_number,
                street=d.street,
                action=d.action,
                amount=d.amount,
                equity=d.equity,
                confidence=d.confidence,
                hand_strength=d.hand_strength,
                baseline_action=d.baseline_action,
                hero_profit=summary.hero_profit,
                won=won,
            ))

    def _confidence_calibration(self) -> list[dict[str, Any]]:
        buckets = [
            (0.0, 0.5, "<0.50"),
            (0.5, 0.6, "0.50-0.60"),
            (0.6, 0.7, "0.60-0.70"),
            (0.7, 0.8, "0.70-0.80"),
            (0.8, 1.01, "≥0.80"),
        ]
        results = []
        for lo, hi, label in buckets:
            in_bucket = [d for d in self.decisions if lo <= d.confidence < hi]
            if not in_bucket:
                continue
            win_rate = sum(1 for d in in_bucket if d.won) / len(in_bucket)
            avg_conf = sum(d.confidence for d in in_bucket) / len(in_bucket)
            results.append({
                "label": label,
                "count": len(in_bucket),
                "win_rate": win_rate,
                "avg_confidence": avg_conf,
                "calibration_error": win_rate - avg_conf,
            })
        return results

    def _street_action_stats(self) -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for d in self.decisions:
            if d.street not in stats:
                stats[d.street] = {}
            if d.action not in stats[d.street]:
                stats[d.street][d.action] = {"count": 0, "total_equity": 0.0, "wins": 0}
            s = stats[d.street][d.action]
            s["count"] += 1
            s["total_equity"] += d.equity
            if d.won:
                s["wins"] += 1
        # Compute averages
        for street in stats:
            for action in stats[street]:
                s = stats[street][action]
                s["avg_equity"] = s["total_equity"] / max(s["count"], 1)
                s["win_rate"] = s["wins"] / max(s["count"], 1)
        return stats

    def _potential_mistakes(self) -> list[dict[str, Any]]:
        mistakes = []
        for d in self.decisions:
            if d.street == "preflop":
                continue
            # High equity fold (missed value)
            if d.action == "fold" and d.equity > 0.5:
                mistakes.append({
                    "hand_number": d.hand_number,
                    "street": d.street,
                    "type": "high_equity_fold",
                    "equity": d.equity,
                    "description": f"equity={d.equity:.1%}时fold(可能错失价值)",
                })
            # Low equity call/bet (bad investment)
            if d.action in ("call", "bet", "raise") and d.equity < 0.2 and d.confidence < 0.6:
                mistakes.append({
                    "hand_number": d.hand_number,
                    "street": d.street,
                    "type": "low_equity_invest",
                    "equity": d.equity,
                    "description": f"equity={d.equity:.1%}时{d.action}(投入可能不合理)",
                })
            # High confidence but lost — overconfident decision (skip if equity was genuinely high, that's a cooler not overconfidence)
            if d.confidence >= 0.8 and not d.won and d.action in ("bet", "raise", "all_in") and d.amount > 0 and d.equity < 0.6:
                mistakes.append({
                    "hand_number": d.hand_number,
                    "street": d.street,
                    "type": "overconfident_aggression",
                    "equity": d.equity,
                    "confidence": d.confidence,
                    "description": (f"confidence={d.confidence:.0%}但亏损, "
                                    f"equity={d.equity:.1%}时{d.action} {d.amount}"),
                })
        return mistakes

    def _calibration_warnings(self) -> list[str]:
        """Detect systematic calibration issues across all confidence buckets."""
        cal = self._confidence_calibration()
        if not cal:
            return []
        warnings = []
        overconfident_buckets = [c for c in cal if c["calibration_error"] < -0.2 and c["count"] >= 2]
        if len(overconfident_buckets) >= 3:
            avg_error = sum(c["calibration_error"] for c in overconfident_buckets) / len(overconfident_buckets)
            warnings.append(
                f"系统性过度自信: {len(overconfident_buckets)}个区间均显示严重偏差"
                f"(平均校准误差{avg_error:+.0%})，equity估算可能存在系统性高估"
            )
        high_conf = next((c for c in cal if c["label"] == "≥0.80"), None)
        if high_conf and high_conf["count"] >= 5 and high_conf["win_rate"] < 0.2:
            warnings.append(
                f"高置信决策失效: confidence≥80%的{high_conf['count']}个决策"
                f"实际胜率仅{high_conf['win_rate']:.0%}，"
                f"建议检查equity计算或对手range估计"
            )
        return warnings

    def _gto_deviation_stats(self) -> dict[str, Any]:
        deviations = [d for d in self.decisions if d.baseline_action and d.action != d.baseline_action]
        if not deviations:
            return {"count": 0, "total": len(self.decisions), "profitable": 0}
        profitable = sum(1 for d in deviations if d.won)
        return {
            "count": len(deviations),
            "total": len(self.decisions),
            "rate": len(deviations) / max(len(self.decisions), 1),
            "profitable": profitable,
            "profitable_rate": profitable / max(len(deviations), 1),
        }

    def summary_report(self) -> str:
        n = len(self.decisions)
        if n == 0:
            return "决策质量: 无决策数据"
        avg_conf = sum(d.confidence for d in self.decisions) / n
        mistakes = self._potential_mistakes()
        return f"决策质量: {n}个决策点, 平均confidence={avg_conf:.2f}, 潜在问题={len(mistakes)}"

    def detailed_report(self) -> str:
        lines = [
            "=" * 70,
            "           决策质量分析报告",
            "=" * 70,
            "",
        ]

        n = len(self.decisions)
        if n == 0:
            lines.append("无决策数据。")
            return "\n".join(lines)

        preflop_count = sum(1 for d in self.decisions if d.street == "preflop")
        postflop_count = n - preflop_count
        avg_conf = sum(d.confidence for d in self.decisions) / n

        lines.append(f"总决策点: {n} (翻前: {preflop_count}, 翻后: {postflop_count})")
        lines.append(f"平均 confidence: {avg_conf:.3f}")
        lines.append("")

        # Confidence calibration
        cal = self._confidence_calibration()
        lines.append("【Confidence 校准】")
        lines.append(f"  {'confidence':<12s} {'决策数':>6s} {'实际胜率':>8s} {'校准偏差':>8s}")
        lines.append("  " + "─" * 40)
        for c in cal:
            bias_str = f"{c['calibration_error']:+.0%}"
            note = ""
            if abs(c["calibration_error"]) > 0.1:
                note = " ⚠过度自信" if c["calibration_error"] < -0.1 else " ⚠过度保守"
            lines.append(f"  {c['label']:<12s} {c['count']:>6d} {c['win_rate']:>7.0%} "
                         f"{bias_str:>8s}{note}")
        lines.append("")

        # Calibration warnings
        cal_warnings = self._calibration_warnings()
        if cal_warnings:
            lines.append("【⚠ 校准问题诊断】")
            for w in cal_warnings:
                lines.append(f"  ⚠ {w}")
            lines.append("")

        # Street action distribution
        stats = self._street_action_stats()
        lines.append("【按街行动分布】")
        street_order = ["preflop", "flop", "turn", "river"]
        for street in street_order:
            if street not in stats:
                continue
            parts = []
            for action, s in sorted(stats[street].items(), key=lambda x: -x[1]["count"]):
                parts.append(f"{action}={s['count']}(eq={s['avg_equity']:.0%})")
            lines.append(f"  {street:8s}: {', '.join(parts)}")
        lines.append("")

        # GTO deviations
        dev = self._gto_deviation_stats()
        if dev["count"] > 0:
            lines.append("【GTO偏离统计】(exploit调整导致偏离baseline)")
            lines.append(f"  偏离次数: {dev['count']}/{dev['total']} ({dev['rate']:.0%})")
            lines.append(f"  偏离后盈利: {dev['profitable']}/{dev['count']} ({dev['profitable_rate']:.0%})")
            lines.append("")

        # Potential mistakes
        mistakes = self._potential_mistakes()
        if mistakes:
            lines.append(f"【潜在问题决策】({len(mistakes)}个)")
            for m in mistakes[:10]:
                lines.append(f"  第{m['hand_number']}手 {m['street']}: {m['description']}")
            if len(mistakes) > 10:
                lines.append(f"  ... 还有 {len(mistakes)-10} 个")
        else:
            lines.append("【潜在问题决策】无明显问题")
        lines.append("")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        return {
            "total_decisions": len(self.decisions),
            "confidence_calibration": self._confidence_calibration(),
            "calibration_warnings": self._calibration_warnings(),
            "street_action_stats": self._street_action_stats(),
            "gto_deviations": self._gto_deviation_stats(),
            "potential_mistakes": self._potential_mistakes(),
        }

    def write_outputs(self, session_dir: Path) -> None:
        with open(session_dir / "decision_quality_data.json", "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)
        with open(session_dir / "decision_quality_analysis.txt", "w", encoding="utf-8") as f:
            f.write(self.detailed_report())
