from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from profiler.player_profile import PlayerProfile
from testing.simulation.label_presets import AIOpponentConfig
from testing.simulation.sim_game_loop import HandResult


@dataclass
class LabelConsistency:
    player_name: str
    target_label: str
    vpip_target: float
    vpip_actual: float
    pfr_target: float
    pfr_actual: float
    aggr_target: float
    aggr_actual: float
    score: float

    @property
    def is_consistent(self) -> bool:
        return self.score >= 0.7


@dataclass
class AdvisorEvaluation:
    total_hands: int = 0
    hero_profit: int = 0
    win_rate_bb_100: float = 0.0
    showdown_wins: int = 0
    showdown_total: int = 0


class SimMonitor:
    def __init__(self):
        self._hand_results: list[HandResult] = []
        self._profiles: dict[str, PlayerProfile] = {}
        self._configs: dict[str, AIOpponentConfig] = {}

    def register_player(self, name: str, config: AIOpponentConfig, profile: PlayerProfile) -> None:
        self._configs[name] = config
        self._profiles[name] = profile

    def record_hand(self, result: HandResult) -> None:
        self._hand_results.append(result)

    def check_label_consistency(self, player_name: str) -> LabelConsistency | None:
        config = self._configs.get(player_name)
        profile = self._profiles.get(player_name)
        if not config or not profile:
            return None

        vpip_actual = profile.get_stat("vpip")
        pfr_actual = profile.get_stat("pfr")
        aggr_actual = profile.get_stat("aggression_freq")

        vpip_err = abs(vpip_actual - config.vpip_target)
        pfr_err = abs(pfr_actual - config.pfr_target)
        aggr_err = abs(aggr_actual - config.aggression_freq_target)

        score = max(0.0, 1.0 - (vpip_err + pfr_err + aggr_err))

        return LabelConsistency(
            player_name=player_name,
            target_label=config.label,
            vpip_target=config.vpip_target,
            vpip_actual=vpip_actual,
            pfr_target=config.pfr_target,
            pfr_actual=pfr_actual,
            aggr_target=config.aggression_freq_target,
            aggr_actual=aggr_actual,
            score=score,
        )

    def evaluate_advisor(self, big_blind: int = 10) -> AdvisorEvaluation:
        if not self._hand_results:
            return AdvisorEvaluation()

        total = len(self._hand_results)
        profit = sum(r.hero_profit for r in self._hand_results)
        showdown_hands = [r for r in self._hand_results if r.showdown]
        showdown_wins = sum(1 for r in showdown_hands if r.hero_profit > 0)

        bb_100 = (profit / big_blind) / max(total, 1) * 100

        return AdvisorEvaluation(
            total_hands=total,
            hero_profit=profit,
            win_rate_bb_100=bb_100,
            showdown_wins=showdown_wins,
            showdown_total=len(showdown_hands),
        )

    def summary_report(self, big_blind: int = 10) -> str:
        eval_result = self.evaluate_advisor(big_blind)
        lines = [
            f"=== 模拟测试报告 ({eval_result.total_hands}手) ===",
            f"Hero盈亏: {eval_result.hero_profit:+d} ({eval_result.win_rate_bb_100:+.1f} bb/100)",
            f"摊牌胜率: {eval_result.showdown_wins}/{eval_result.showdown_total}",
            "",
            "--- 对手画像一致性 ---",
        ]

        for name in self._configs:
            lc = self.check_label_consistency(name)
            if lc:
                status = "✓" if lc.is_consistent else "✗"
                lines.append(
                    f"  {status} {name}[{lc.target_label}]: "
                    f"VPIP {lc.vpip_actual:.0%}(目标{lc.vpip_target:.0%}) "
                    f"AGG {lc.aggr_actual:.0%}(目标{lc.aggr_target:.0%}) "
                    f"得分{lc.score:.0%}"
                )

        return "\n".join(lines)
