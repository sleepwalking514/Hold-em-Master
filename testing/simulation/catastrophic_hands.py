"""巨亏手分析 - 识别和诊断单手大额亏损。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_analysis_common import HandSummary, HeroDecision


@dataclass
class CatastrophicHand:
    hand_number: int
    loss_bb: float
    loss_chips: int
    diagnosis: str  # overplay / bad_calldown / cooler / failed_bluff / trapped
    hero_position: str
    hero_hole_cards: list[str]
    board: list[str]
    equity_trajectory: list[float]
    critical_street: str
    critical_street_equity_drop: float
    spr: float | None
    decisions_summary: list[dict]


class CatastrophicHandTracker:
    def __init__(self, big_blind: int = 10, threshold_bb: float = 15.0):
        self.big_blind = big_blind
        self.threshold_bb = threshold_bb
        self.catastrophic_hands: list[CatastrophicHand] = []
        self.all_profits: list[int] = []

    def record(self, summary: HandSummary) -> None:
        self.all_profits.append(summary.hero_profit)
        loss_bb = -summary.hero_profit / max(self.big_blind, 1)
        if loss_bb >= self.threshold_bb:
            self.catastrophic_hands.append(self._analyze(summary, loss_bb))

    def _analyze(self, s: HandSummary, loss_bb: float) -> CatastrophicHand:
        equities = [d.equity for d in s.hero_decisions if d.equity > 0]
        diagnosis = self._diagnose(s, equities)
        critical_street, drop = self._find_critical_street(s.hero_decisions)
        spr = self._extract_spr(s.hero_decisions)

        return CatastrophicHand(
            hand_number=s.hand_number,
            loss_bb=loss_bb,
            loss_chips=-s.hero_profit,
            diagnosis=diagnosis,
            hero_position=s.hero_position,
            hero_hole_cards=s.hero_hole_cards,
            board=s.board,
            equity_trajectory=equities,
            critical_street=critical_street,
            critical_street_equity_drop=drop,
            spr=spr,
            decisions_summary=[
                {"street": d.street, "action": d.action, "amount": d.amount,
                 "equity": round(d.equity, 3), "confidence": d.confidence}
                for d in s.hero_decisions
            ],
        )

    def _diagnose(self, s: HandSummary, equities: list[float]) -> str:
        if not equities:
            return "overplay"

        final_equity = equities[-1]
        max_equity = max(equities)

        # cooler: equity stayed high throughout (Hero had a strong hand but ran into better)
        if all(e > 0.5 for e in equities):
            return "cooler"

        # cooler variant: equity was rising/high at decision point (>= 0.6 at end)
        # Hero made reasonable decisions based on available info but lost
        if final_equity >= 0.6:
            return "cooler"

        # standard_play: Hero followed baseline advice, equity was reasonable (>= 0.35),
        # and the loss was due to normal variance rather than a mistake
        all_followed_baseline = all(
            d.action == d.baseline_action or not d.baseline_action
            for d in s.hero_decisions
        )
        if all_followed_baseline and final_equity >= 0.35:
            return "standard_gone_wrong"

        # preflop_allin: short-stack shove or standard 4-bet push
        preflop_decisions = [d for d in s.hero_decisions if d.street == "preflop"]
        if preflop_decisions and preflop_decisions[-1].action == "all_in":
            postflop_decisions = [d for d in s.hero_decisions if d.street != "preflop"]
            if not postflop_decisions:
                if preflop_decisions[-1].equity >= 0.35:
                    return "standard_gone_wrong"

        # bad_calldown: equity steadily declining but Hero kept calling
        if len(equities) >= 3:
            declining = all(equities[i] >= equities[i + 1] - 0.02 for i in range(len(equities) - 1))
            if declining and equities[-1] < 0.3 and equities[0] > 0.45:
                return "bad_calldown"

        # failed_bluff: weak hand strength but aggressive action
        postflop_decisions = [d for d in s.hero_decisions if d.street != "preflop"]
        for d in reversed(postflop_decisions):
            if d.hand_strength is not None and d.hand_strength <= 2 and d.action in ("bet", "raise", "all_in"):
                return "failed_bluff"

        # trapped: opponent was passive then suddenly aggressive
        for opp_name, opp_acts in s.opponent_actions.items():
            streets_seen: dict[str, list[str]] = {}
            for a in opp_acts:
                st = a["street"]
                if st not in streets_seen:
                    streets_seen[st] = []
                streets_seen[st].append(a["action"])
            for st, acts in streets_seen.items():
                if "check" in acts and ("raise" in acts or "all_in" in acts):
                    return "trapped"

        # overplay: invested heavily with weak equity
        if final_equity < 0.35:
            return "overplay"

        # overplay: equity was moderate but Hero over-invested relative to strength
        big_bets = [d for d in s.hero_decisions
                    if d.action in ("bet", "raise", "all_in")
                    and d.amount > 0 and d.equity < 0.45]
        if big_bets:
            return "overplay"

        return "overplay"

    def _find_critical_street(self, decisions: list[HeroDecision]) -> tuple[str, float]:
        max_drop = 0.0
        critical = "preflop"
        prev_eq = None
        for d in decisions:
            if d.equity <= 0:
                continue
            if prev_eq is not None:
                drop = prev_eq - d.equity
                if drop > max_drop:
                    max_drop = drop
                    critical = d.street
            prev_eq = d.equity
        return critical, max_drop

    def _extract_spr(self, decisions: list[HeroDecision]) -> float | None:
        for d in decisions:
            if d.street != "preflop" and d.hand_strength is not None:
                # SPR is embedded in baseline reasoning but not directly accessible
                # We'll return None for now; could parse from baseline text
                return None
        return None

    def summary_report(self) -> str:
        total = len(self.all_profits)
        n_cat = len(self.catastrophic_hands)
        if n_cat == 0:
            return f"巨亏手: 0/{total} (无超过{self.threshold_bb}BB的单手亏损)"
        total_loss = sum(h.loss_chips for h in self.catastrophic_hands)
        return (
            f"巨亏手: {n_cat}/{total} ({n_cat/total*100:.1f}%), "
            f"总巨亏: -{total_loss} chips (-{total_loss/self.big_blind:.1f}BB)"
        )

    def detailed_report(self) -> str:
        lines = [
            "=" * 70,
            "           巨亏手深度分析报告",
            "=" * 70,
            "",
        ]
        total = len(self.all_profits)
        n_cat = len(self.catastrophic_hands)

        if n_cat == 0:
            lines.append(f"巨亏手数: 0/{total} (无超过{self.threshold_bb}BB的单手亏损)")
            lines.append("本次模拟未出现严重亏损手，策略表现稳定。")
            return "\n".join(lines)

        total_loss = sum(h.loss_chips for h in self.catastrophic_hands)
        diag_counts: dict[str, int] = {}
        for h in self.catastrophic_hands:
            diag_counts[h.diagnosis] = diag_counts.get(h.diagnosis, 0) + 1

        lines.append(f"巨亏手数: {n_cat}/{total} ({n_cat/total*100:.1f}%)")
        lines.append(f"总巨亏: -{total_loss} chips (-{total_loss/self.big_blind:.1f}BB)")
        lines.append(f"阈值: >{self.threshold_bb}BB")
        diag_str = ", ".join(f"{k}={v}" for k, v in sorted(diag_counts.items()))
        lines.append(f"分类统计: {diag_str}")
        lines.append("")

        diag_labels = {
            "overplay": "高估手牌",
            "bad_calldown": "错误跟注",
            "cooler": "不可避免(Cooler)",
            "standard_gone_wrong": "标准打法(运气不佳)",
            "failed_bluff": "失败诈唬",
            "trapped": "被套(Trapped)",
        }

        for h in sorted(self.catastrophic_hands, key=lambda x: -x.loss_bb):
            lines.append(f"── 第 {h.hand_number} 手 (亏损: -{h.loss_chips} chips, -{h.loss_bb:.1f}BB) ──")
            lines.append(f"  类型: {diag_labels.get(h.diagnosis, h.diagnosis)}")
            lines.append(f"  位置: {h.hero_position} | 手牌: {' '.join(h.hero_hole_cards)}")
            if h.board:
                lines.append(f"  公共牌: {' '.join(h.board)}")
            if h.equity_trajectory:
                eq_str = " → ".join(f"{e:.1%}" for e in h.equity_trajectory)
                lines.append(f"  Equity轨迹: {eq_str}")
            if h.critical_street_equity_drop > 0.05:
                lines.append(f"  关键街: {h.critical_street} (equity下降 {h.critical_street_equity_drop:.1%})")
            lines.append(f"  决策序列:")
            for dec in h.decisions_summary:
                lines.append(f"    {dec['street']:8s} {dec['action']:6s} "
                             f"amount={dec['amount']:4d} equity={dec['equity']:.1%} conf={dec['confidence']}")
            lines.append("")

        # Recommendations
        lines.append("─" * 70)
        lines.append("【改进建议】")
        if diag_counts.get("bad_calldown", 0) > 0:
            lines.append("  • 错误跟注: 当equity跨街持续下降时应更早弃牌，尤其在面对加注时")
        if diag_counts.get("overplay", 0) > 0:
            overplay_hands = [h for h in self.catastrophic_hands if h.diagnosis == "overplay"]
            avg_eq = sum(h.equity_trajectory[-1] for h in overplay_hands if h.equity_trajectory) / max(len(overplay_hands), 1)
            lines.append(f"  • 高估手牌: 这些手牌在关键决策点equity偏低(平均{avg_eq:.0%})，"
                         f"应减少投入或选择弃牌")
        if diag_counts.get("failed_bluff", 0) > 0:
            lines.append("  • 失败诈唬: 选择诈唬对象时需考虑对手fold_to_bet频率")
        if diag_counts.get("trapped", 0) > 0:
            lines.append("  • 被套: 注意对手check后突然加注的模式，可能是慢打强牌")
        if diag_counts.get("cooler", 0) > 0:
            lines.append(f"  • Cooler({diag_counts['cooler']}手): 决策本身合理，"
                         f"属于正常方差范围，无需调整策略")
        if diag_counts.get("standard_gone_wrong", 0) > 0:
            lines.append(f"  • 标准打法({diag_counts['standard_gone_wrong']}手): "
                         f"遵循了baseline建议但结果不佳，属于正常波动")

        return "\n".join(lines)

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "hand_number": h.hand_number,
                "loss_bb": round(h.loss_bb, 1),
                "loss_chips": h.loss_chips,
                "diagnosis": h.diagnosis,
                "hero_position": h.hero_position,
                "hero_hole_cards": h.hero_hole_cards,
                "board": h.board,
                "equity_trajectory": [round(e, 4) for e in h.equity_trajectory],
                "critical_street": h.critical_street,
                "critical_street_equity_drop": round(h.critical_street_equity_drop, 4),
                "decisions": h.decisions_summary,
            }
            for h in self.catastrophic_hands
        ]

    def write_outputs(self, session_dir: Path) -> None:
        with open(session_dir / "catastrophic_hands_data.json", "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False)
        with open(session_dir / "catastrophic_hands_analysis.txt", "w", encoding="utf-8") as f:
            f.write(self.detailed_report())
