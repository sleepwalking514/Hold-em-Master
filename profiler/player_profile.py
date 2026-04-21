from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from profiler.bayesian_tracker import BayesianStat
from profiler.info_weight import calc_skill_delta


STAT_NAMES = [
    "vpip", "pfr", "three_bet_pct", "aggression_freq", "wtsd", "wsd",
    "cbet_flop", "cbet_turn", "fold_to_cbet", "fold_to_3bet",
    "bet_fold_freq", "fold_to_river_bet", "squeeze", "steal",
    "bb_fold_to_steal", "bb_3bet_vs_steal", "sb_fold_to_steal",
]

DEFAULT_PRIORS = {
    "vpip": (2, 4),
    "pfr": (1, 4),
    "three_bet_pct": (1, 6),
    "aggression_freq": (2, 3),
    "wtsd": (1, 3),
    "wsd": (2, 2),
    "cbet_flop": (2, 2),
    "cbet_turn": (1, 3),
    "fold_to_cbet": (2, 2),
    "fold_to_3bet": (2, 2),
    "bet_fold_freq": (1, 3),
    "fold_to_river_bet": (2, 2),
    "squeeze": (1, 6),
    "steal": (1, 3),
    "bb_fold_to_steal": (2, 2),
    "bb_3bet_vs_steal": (1, 4),
    "sb_fold_to_steal": (2, 2),
}


@dataclass
class BetSizingPattern:
    value_bet_ratios: list[float] = field(default_factory=list)
    bluff_bet_ratios: list[float] = field(default_factory=list)
    overbet_count: int = 0
    total_bets: int = 0

    @property
    def avg_value_sizing(self) -> float:
        return sum(self.value_bet_ratios) / len(self.value_bet_ratios) if self.value_bet_ratios else 0.65

    @property
    def avg_bluff_sizing(self) -> float:
        return sum(self.bluff_bet_ratios) / len(self.bluff_bet_ratios) if self.bluff_bet_ratios else 0.5

    @property
    def overbet_frequency(self) -> float:
        return self.overbet_count / self.total_bets if self.total_bets > 0 else 0.0

    def record_bet(self, ratio: float, is_value: bool = True) -> None:
        self.total_bets += 1
        if ratio > 1.0:
            self.overbet_count += 1
        window = self.value_bet_ratios if is_value else self.bluff_bet_ratios
        window.append(ratio)
        if len(window) > 30:
            window.pop(0)

    def to_dict(self) -> dict:
        return {
            "value_bet_ratios": self.value_bet_ratios,
            "bluff_bet_ratios": self.bluff_bet_ratios,
            "overbet_count": self.overbet_count,
            "total_bets": self.total_bets,
        }

    @classmethod
    def from_dict(cls, d: dict) -> BetSizingPattern:
        return cls(
            value_bet_ratios=d.get("value_bet_ratios", []),
            bluff_bet_ratios=d.get("bluff_bet_ratios", []),
            overbet_count=d.get("overbet_count", 0),
            total_bets=d.get("total_bets", 0),
        )


@dataclass
class StreetTendencies:
    flop_aggression: BayesianStat = field(default_factory=lambda: BayesianStat(3, 4))
    turn_aggression: BayesianStat = field(default_factory=lambda: BayesianStat(3, 4))
    river_aggression: BayesianStat = field(default_factory=lambda: BayesianStat(2, 4))
    gives_up_turn: BayesianStat = field(default_factory=lambda: BayesianStat(3, 4))
    double_barrel_freq: BayesianStat = field(default_factory=lambda: BayesianStat(2, 4))
    triple_barrel_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 4))

    def to_dict(self) -> dict:
        return {k: getattr(self, k).to_dict() for k in [
            "flop_aggression", "turn_aggression", "river_aggression",
            "gives_up_turn", "double_barrel_freq", "triple_barrel_freq",
        ]}

    @classmethod
    def from_dict(cls, d: dict) -> StreetTendencies:
        st = cls()
        for k in ["flop_aggression", "turn_aggression", "river_aggression",
                   "gives_up_turn", "double_barrel_freq", "triple_barrel_freq"]:
            if k in d:
                setattr(st, k, BayesianStat.from_dict(d[k]))
        return st


@dataclass
class AdvancedActions:
    check_raise_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 6))
    donk_bet_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 6))
    limp_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 5))
    limp_raise_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 7))
    probe_bet_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 5))
    raise_cbet_freq: BayesianStat = field(default_factory=lambda: BayesianStat(1, 6))

    def to_dict(self) -> dict:
        return {k: getattr(self, k).to_dict() for k in [
            "check_raise_freq", "donk_bet_freq", "limp_freq",
            "limp_raise_freq", "probe_bet_freq", "raise_cbet_freq",
        ]}

    @classmethod
    def from_dict(cls, d: dict) -> AdvancedActions:
        aa = cls()
        for k in ["check_raise_freq", "donk_bet_freq", "limp_freq",
                   "limp_raise_freq", "probe_bet_freq", "raise_cbet_freq"]:
            if k in d:
                setattr(aa, k, BayesianStat.from_dict(d[k]))
        return aa


@dataclass
class SkillEstimate:
    overall_skill: float = 0.5
    positional_awareness: float = 0.5
    sizing_sophistication: float = 0.5
    hand_reading_ability: float = 0.5

    def update(self, event_type: str, direction: float, confidence: float) -> None:
        delta = calc_skill_delta(event_type, direction, confidence)
        self.overall_skill = max(0.0, min(1.0, self.overall_skill + delta))

    def to_dict(self) -> dict:
        return {
            "overall_skill": self.overall_skill,
            "positional_awareness": self.positional_awareness,
            "sizing_sophistication": self.sizing_sophistication,
            "hand_reading_ability": self.hand_reading_ability,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SkillEstimate:
        return cls(**{k: d.get(k, 0.5) for k in [
            "overall_skill", "positional_awareness",
            "sizing_sophistication", "hand_reading_ability",
        ]})


@dataclass
class KeyHand:
    hand_id: int
    situation: str
    details: str
    board: str = ""
    showdown_type: str = ""
    skill_signal: str = "neutral"
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "hand_id": self.hand_id,
            "situation": self.situation,
            "details": self.details,
            "board": self.board,
            "showdown_type": self.showdown_type,
            "skill_signal": self.skill_signal,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> KeyHand:
        return cls(**d)


class PlayerProfile:
    def __init__(self, name: str, prior_type: str = "未知"):
        self.name = name
        self.prior_type = prior_type
        self.total_hands = 0
        self.stats: dict[str, BayesianStat] = {}
        for stat_name in STAT_NAMES:
            a, b = DEFAULT_PRIORS.get(stat_name, (2, 3))
            self.stats[stat_name] = BayesianStat(a, b)
        self.street_tendencies = StreetTendencies()
        self.advanced_actions = AdvancedActions()
        self.bet_sizing = BetSizingPattern()
        self.skill_estimate = SkillEstimate()
        self.key_hands: list[KeyHand] = []

    def get_stat(self, name: str) -> float:
        if name in self.stats:
            return self.stats[name].mean
        return 0.0

    def get_confidence(self, name: str) -> float:
        if name in self.stats:
            return self.stats[name].confidence
        return 0.0

    def update_stat(self, name: str, success: bool) -> None:
        if name in self.stats:
            self.stats[name].update(success)

    def add_key_hand(self, hand: KeyHand) -> None:
        self.key_hands.append(hand)
        if len(self.key_hands) > 50:
            self.key_hands.pop(0)

    @property
    def style_label(self) -> str:
        vpip_conf = self.get_confidence("vpip")
        aggr_conf = self.get_confidence("aggression_freq")
        if (vpip_conf + aggr_conf) / 2 < 0.30:
            return "未知"
        vpip = self.get_stat("vpip")
        aggr = self.get_stat("aggression_freq")
        if vpip < 0.18:
            return "紧凶TAG" if aggr > 0.40 else "紧弱"
        elif vpip < 0.28:
            return "紧凶TAG" if aggr > 0.35 else "中等"
        elif vpip < 0.40:
            return "松凶LAG" if aggr > 0.40 else "跟注站"
        else:
            return "疯子Maniac" if aggr > 0.45 else "松鱼"

    def summary(self) -> str:
        return (
            f"{self.name} [{self.style_label}] "
            f"VPIP:{self.get_stat('vpip'):.0%} "
            f"PFR:{self.get_stat('pfr'):.0%} "
            f"AF:{self.get_stat('aggression_freq'):.0%} "
            f"({self.total_hands}手)"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "prior_type": self.prior_type,
            "total_hands": self.total_hands,
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
            "street_tendencies": self.street_tendencies.to_dict(),
            "advanced_actions": self.advanced_actions.to_dict(),
            "bet_sizing": self.bet_sizing.to_dict(),
            "skill_estimate": self.skill_estimate.to_dict(),
            "key_hands": [h.to_dict() for h in self.key_hands],
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlayerProfile:
        profile = cls(d["name"], d.get("prior_type", "未知"))
        profile.total_hands = d.get("total_hands", 0)
        for k, v in d.get("stats", {}).items():
            if k in profile.stats:
                profile.stats[k] = BayesianStat.from_dict(v)
        if "street_tendencies" in d:
            profile.street_tendencies = StreetTendencies.from_dict(d["street_tendencies"])
        if "advanced_actions" in d:
            profile.advanced_actions = AdvancedActions.from_dict(d["advanced_actions"])
        if "bet_sizing" in d:
            profile.bet_sizing = BetSizingPattern.from_dict(d["bet_sizing"])
        if "skill_estimate" in d:
            profile.skill_estimate = SkillEstimate.from_dict(d["skill_estimate"])
        profile.key_hands = [KeyHand.from_dict(h) for h in d.get("key_hands", [])]
        return profile


def check_profile_consistency(profile: PlayerProfile) -> list[tuple[str, str]]:
    corrections = []
    if profile.get_stat("pfr") > profile.get_stat("vpip"):
        corrections.append(("pfr", "cap_at_vpip"))
    vpip = profile.get_stat("vpip")
    wtsd = profile.get_stat("wtsd")
    if vpip > 0 and wtsd < vpip * 0.4 and profile.get_confidence("wtsd") > 0.3:
        corrections.append(("wtsd", "flag_anomaly"))
    if vpip < 0.15 and profile.get_stat("aggression_freq") > 0.55:
        corrections.append(("aggression_freq", "reduce_confidence"))
    return corrections
