from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from profiler.player_profile import PlayerProfile
from profiler.hand_range_estimator import HandRangeMatrix
from data.exploit_config import BASELINE


@dataclass
class MultiwayAnalysis:
    fold_equity: float
    num_opponents: int
    threat_levels: dict[str, float]
    most_exploitable: Optional[str]
    most_dangerous: Optional[str]
    strategy_note: str


def compute_fold_equity(
    opponent_profiles: list[tuple[str, PlayerProfile]],
    street: str = "flop",
    bet_type: str = "cbet",
) -> float:
    if not opponent_profiles:
        return 0.0

    fold_probs = []
    for name, profile in opponent_profiles:
        if bet_type == "cbet":
            fold_prob = profile.get_stat("fold_to_cbet")
        elif bet_type == "river":
            fold_prob = profile.get_stat("fold_to_river_bet")
        elif bet_type == "3bet":
            fold_prob = profile.get_stat("fold_to_3bet")
        else:
            fold_prob = profile.get_stat("fold_to_cbet")
        fold_probs.append(fold_prob)

    combined = 1.0
    for fp in fold_probs:
        combined *= fp
    return combined


def analyze_multiway(
    opponent_profiles: list[tuple[str, PlayerProfile]],
    hero_equity: float,
    pot_size: int,
    street: str = "flop",
) -> MultiwayAnalysis:
    if not opponent_profiles:
        return MultiwayAnalysis(
            fold_equity=0.0, num_opponents=0,
            threat_levels={}, most_exploitable=None,
            most_dangerous=None, strategy_note="无对手信息",
        )

    fold_eq = compute_fold_equity(opponent_profiles, street)
    threat_levels = {}
    exploit_scores = {}

    for name, profile in opponent_profiles:
        aggr = profile.get_stat("aggression_freq")
        vpip = profile.get_stat("vpip")
        skill = profile.skill_estimate.overall_skill
        threat = aggr * 0.4 + skill * 0.4 + (1 - profile.get_stat("fold_to_cbet")) * 0.2
        threat_levels[name] = threat

        fold_cbet = profile.get_stat("fold_to_cbet")
        fold_3bet = profile.get_stat("fold_to_3bet")
        passivity = 1.0 - aggr
        exploit_scores[name] = (
            max(0, fold_cbet - BASELINE["fold_to_cbet"]) * 0.4
            + passivity * 0.3
            + max(0, vpip - 0.30) * 0.3
        )

    most_dangerous = max(threat_levels, key=threat_levels.get) if threat_levels else None
    most_exploitable = max(exploit_scores, key=exploit_scores.get) if exploit_scores else None

    n = len(opponent_profiles)
    if hero_equity > 0.6:
        note = "强牌多人底池→价值下注为主，不减尺寸"
    elif hero_equity > 0.4:
        note = "中等牌力多人底池→控池，避免膨胀底池"
    elif fold_eq > 0.4:
        note = f"弃牌收益{fold_eq:.0%}→可考虑bluff，但需谨慎"
    else:
        note = "牌力不足且弃牌收益低→倾向过牌/弃牌，等待更好机会"

    return MultiwayAnalysis(
        fold_equity=fold_eq,
        num_opponents=n,
        threat_levels=threat_levels,
        most_exploitable=most_exploitable,
        most_dangerous=most_dangerous,
        strategy_note=note,
    )


def multiway_sizing_adjustment(
    base_size: float, num_opponents: int, is_value: bool
) -> float:
    if is_value:
        return base_size * (1.0 + 0.1 * (num_opponents - 1))
    else:
        return base_size * max(0.5, 1.0 - 0.15 * (num_opponents - 1))


def should_bluff_multiway(
    fold_equity: float, pot_size: int, bet_size: int, num_opponents: int
) -> tuple[bool, str]:
    required_fe = bet_size / (pot_size + bet_size)

    if fold_equity >= required_fe:
        return True, f"弃牌收益{fold_equity:.0%} >= 所需{required_fe:.0%}"

    if num_opponents >= 3 and fold_equity < 0.3:
        return False, f"3+人底池弃牌收益过低({fold_equity:.0%})，放弃bluff"

    return False, f"弃牌收益{fold_equity:.0%} < 所需{required_fe:.0%}"
