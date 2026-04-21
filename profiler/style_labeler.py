from __future__ import annotations

from dataclasses import dataclass
from profiler.player_profile import PlayerProfile


@dataclass
class StyleLabel:
    primary: str
    secondary: str
    confidence: float
    description: str

    def __str__(self) -> str:
        if self.confidence < 0.3:
            return f"未知 (置信度{self.confidence:.0%})"
        return f"{self.primary} (置信度{self.confidence:.0%})"


STYLE_DEFINITIONS = {
    "Nit": {"vpip": (0.0, 0.14), "aggr": (0.30, 1.0), "desc": "极紧，只玩超强牌"},
    "TAG": {"vpip": (0.14, 0.26), "aggr": (0.38, 1.0), "desc": "紧凶，选择性强但下注激进"},
    "LAG": {"vpip": (0.26, 0.42), "aggr": (0.40, 1.0), "desc": "松凶，范围宽且激进"},
    "Maniac": {"vpip": (0.42, 1.0), "aggr": (0.45, 1.0), "desc": "疯子，几乎什么牌都打且极度激进"},
    "CallStation": {"vpip": (0.35, 1.0), "aggr": (0.0, 0.28), "desc": "跟注站，很少弃牌但被动"},
    "Fish": {"vpip": (0.38, 1.0), "aggr": (0.15, 0.38), "desc": "松鱼，玩太多牌且不够激进"},
    "TightPassive": {"vpip": (0.0, 0.22), "aggr": (0.0, 0.32), "desc": "紧弱，选牌紧但不敢下注"},
    "Regular": {"vpip": (0.20, 0.30), "aggr": (0.32, 0.45), "desc": "常规玩家，中规中矩"},
}


def classify_style(profile: PlayerProfile, num_players: int = 6) -> StyleLabel:
    vpip = profile.get_stat("vpip")
    aggr = profile.get_stat("aggression_freq")
    pfr = profile.get_stat("pfr")
    wtsd = profile.get_stat("wtsd")

    vpip_conf = profile.get_confidence("vpip")
    aggr_conf = profile.get_confidence("aggression_freq")
    avg_conf = (vpip_conf + aggr_conf) / 2

    if avg_conf < 0.40:
        return StyleLabel("未知", "", avg_conf, "样本不足，无法判断风格")

    # HU/short-handed: shift thresholds up since everyone plays wider
    if num_players <= 2:
        vpip_shift = 0.20
        aggr_shift = 0.08
    elif num_players <= 4:
        vpip_shift = 0.08
        aggr_shift = 0.03
    else:
        vpip_shift = 0.0
        aggr_shift = 0.0

    adjusted_defs = {}
    for style, criteria in STYLE_DEFINITIONS.items():
        vlo, vhi = criteria["vpip"]
        alo, ahi = criteria["aggr"]
        adjusted_defs[style] = {
            "vpip": (min(vlo + vpip_shift, 0.95), min(vhi + vpip_shift, 1.0)),
            "aggr": (min(alo + aggr_shift, 0.95), min(ahi + aggr_shift, 1.0)),
            "desc": criteria["desc"],
        }

    best_match = "Regular"
    best_score = 0.0

    pfr_vpip_ratio = pfr / vpip if vpip > 0.05 else 0.0

    for style, criteria in adjusted_defs.items():
        vpip_lo, vpip_hi = criteria["vpip"]
        aggr_lo, aggr_hi = criteria["aggr"]

        vpip_score = _range_score(vpip, vpip_lo, vpip_hi)
        aggr_score = _range_score(aggr, aggr_lo, aggr_hi)
        score = vpip_score * 0.4 + aggr_score * 0.4

        if style == "TAG" and pfr_vpip_ratio < 0.50:
            score *= 0.5
        elif style == "LAG" and pfr_vpip_ratio < 0.45:
            score *= 0.6
        elif style == "Maniac" and pfr_vpip_ratio < 0.40:
            score *= 0.7
        elif style in ("CallStation", "Fish") and pfr_vpip_ratio > 0.60:
            score *= 0.5

        pfr_bonus = 0.0
        if style in ("TAG", "LAG", "Maniac") and pfr_vpip_ratio > 0.55:
            pfr_bonus = 0.2
        elif style in ("CallStation", "Fish", "TightPassive") and pfr_vpip_ratio < 0.30:
            pfr_bonus = 0.2
        score += pfr_bonus

        if score > best_score:
            best_score = score
            best_match = style

    secondary = _get_secondary_trait(profile)
    desc = STYLE_DEFINITIONS.get(best_match, {}).get("desc", "")

    return StyleLabel(
        primary=best_match,
        secondary=secondary,
        confidence=avg_conf * best_score,
        description=desc,
    )


def _range_score(value: float, lo: float, hi: float) -> float:
    if lo <= value <= hi:
        center = (lo + hi) / 2
        half_width = (hi - lo) / 2
        if half_width == 0:
            return 1.0
        dist = abs(value - center) / half_width
        return 1.0 - dist * 0.3
    if value < lo:
        return max(0.0, 1.0 - (lo - value) * 5)
    return max(0.0, 1.0 - (value - hi) * 5)


def _get_secondary_trait(profile: PlayerProfile) -> str:
    traits = []
    fold_cbet = profile.get_stat("fold_to_cbet")
    if fold_cbet > 0.65:
        traits.append("易弃牌")
    elif fold_cbet < 0.35:
        traits.append("抗cbet")

    wtsd = profile.get_stat("wtsd")
    if wtsd > 0.35:
        traits.append("爱摊牌")
    elif wtsd < 0.20:
        traits.append("少摊牌")

    skill = profile.skill_estimate.overall_skill
    if skill > 0.7:
        traits.append("高水平")
    elif skill < 0.3:
        traits.append("低水平")

    return "/".join(traits[:2]) if traits else ""


def get_exploit_priority(label: StyleLabel) -> dict[str, float]:
    priorities = {
        "Nit": {"steal": 0.8, "fold_pressure": 0.7, "thin_value": 0.3},
        "TAG": {"position": 0.5, "timing": 0.4, "thin_value": 0.3},
        "LAG": {"trap": 0.6, "call_down": 0.5, "pot_control": 0.4},
        "Maniac": {"call_down": 0.8, "trap": 0.7, "value_heavy": 0.6},
        "CallStation": {"value_heavy": 0.9, "no_bluff": 0.8, "thin_value": 0.7},
        "Fish": {"value_heavy": 0.7, "isolate": 0.6, "simple_play": 0.5},
        "TightPassive": {"steal": 0.7, "bluff": 0.6, "fold_pressure": 0.5},
        "Regular": {"position": 0.4, "balance": 0.3},
    }
    return priorities.get(label.primary, {})
