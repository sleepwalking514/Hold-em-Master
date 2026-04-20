from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AIOpponentConfig:
    label: str
    vpip_target: float
    pfr_target: float
    aggression_freq_target: float
    fold_to_cbet: float
    bluff_frequency: float
    tilt_variance: float = 0.05

    @property
    def passivity(self) -> float:
        return 1.0 - self.aggression_freq_target


LABEL_PRESETS: dict[str, AIOpponentConfig] = {
    "TAG": AIOpponentConfig(
        label="TAG", vpip_target=0.22, pfr_target=0.18,
        aggression_freq_target=0.42, fold_to_cbet=0.48,
        bluff_frequency=0.25, tilt_variance=0.03,
    ),
    "LAG": AIOpponentConfig(
        label="LAG", vpip_target=0.35, pfr_target=0.28,
        aggression_freq_target=0.50, fold_to_cbet=0.40,
        bluff_frequency=0.35, tilt_variance=0.05,
    ),
    "Nit": AIOpponentConfig(
        label="Nit", vpip_target=0.12, pfr_target=0.10,
        aggression_freq_target=0.35, fold_to_cbet=0.55,
        bluff_frequency=0.10, tilt_variance=0.02,
    ),
    "Fish": AIOpponentConfig(
        label="Fish", vpip_target=0.55, pfr_target=0.12,
        aggression_freq_target=0.22, fold_to_cbet=0.35,
        bluff_frequency=0.15, tilt_variance=0.10,
    ),
    "Maniac": AIOpponentConfig(
        label="Maniac", vpip_target=0.65, pfr_target=0.45,
        aggression_freq_target=0.60, fold_to_cbet=0.25,
        bluff_frequency=0.50, tilt_variance=0.08,
    ),
    "CallStation": AIOpponentConfig(
        label="CallStation", vpip_target=0.50, pfr_target=0.08,
        aggression_freq_target=0.18, fold_to_cbet=0.20,
        bluff_frequency=0.08, tilt_variance=0.06,
    ),
}


def get_preset(label: str) -> AIOpponentConfig:
    return LABEL_PRESETS.get(label, LABEL_PRESETS["TAG"])


def all_labels() -> list[str]:
    return list(LABEL_PRESETS.keys())
