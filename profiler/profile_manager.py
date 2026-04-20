from __future__ import annotations

import json
import os
from pathlib import Path

from profiler.player_profile import PlayerProfile, DEFAULT_PRIORS
from profiler.bayesian_tracker import BayesianStat

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"
PRIORS_DIR = PROFILES_DIR / "priors"

PRIOR_TEMPLATES: dict[str, dict[str, tuple[float, float]]] = {
    "极紧Nit": {
        "vpip": (1, 8), "pfr": (1, 8), "three_bet_pct": (1, 9),
        "aggression_freq": (3, 3), "wtsd": (1, 5), "cbet_flop": (5, 2),
        "fold_to_cbet": (3, 4), "fold_to_3bet": (5, 2), "steal": (1, 6),
    },
    "岩石": {
        "vpip": (2, 8), "pfr": (2, 7), "three_bet_pct": (1, 7),
        "aggression_freq": (3, 3), "wtsd": (2, 5), "cbet_flop": (5, 2),
        "fold_to_cbet": (3, 3), "fold_to_3bet": (4, 2), "steal": (1, 5),
    },
    "紧凶TAG": {
        "vpip": (3, 7), "pfr": (3, 7), "three_bet_pct": (1, 6),
        "aggression_freq": (4, 3), "wtsd": (2, 5), "cbet_flop": (5, 2),
        "fold_to_cbet": (3, 3), "fold_to_3bet": (3, 3), "steal": (3, 4),
    },
    "松凶LAG": {
        "vpip": (5, 5), "pfr": (4, 6), "three_bet_pct": (2, 5),
        "aggression_freq": (5, 2), "wtsd": (2, 5), "cbet_flop": (5, 2),
        "fold_to_cbet": (3, 4), "fold_to_3bet": (3, 4), "steal": (4, 3),
    },
    "疯子Maniac": {
        "vpip": (7, 3), "pfr": (5, 5), "three_bet_pct": (3, 5),
        "aggression_freq": (6, 2), "wtsd": (3, 4), "cbet_flop": (6, 2),
        "fold_to_cbet": (2, 5), "fold_to_3bet": (2, 5), "steal": (5, 2),
    },
    "跟注站": {
        "vpip": (6, 4), "pfr": (1, 8), "three_bet_pct": (1, 7),
        "aggression_freq": (2, 5), "wtsd": (5, 2), "cbet_flop": (2, 5),
        "fold_to_cbet": (2, 5), "fold_to_3bet": (3, 4), "steal": (1, 5),
    },
    "紧弱": {
        "vpip": (2, 7), "pfr": (1, 8), "three_bet_pct": (1, 7),
        "aggression_freq": (2, 5), "wtsd": (2, 5), "cbet_flop": (3, 4),
        "fold_to_cbet": (4, 3), "fold_to_3bet": (5, 2), "steal": (1, 5),
    },
}


def create_profile(name: str, prior_type: str = "未知") -> PlayerProfile:
    profile = PlayerProfile(name, prior_type)
    if prior_type in PRIOR_TEMPLATES:
        template = PRIOR_TEMPLATES[prior_type]
        for stat_name, (a, b) in template.items():
            if stat_name in profile.stats:
                profile.stats[stat_name] = BayesianStat(a, b)
    return profile


def save_profile(profile: PlayerProfile) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{profile.name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
    return path


def load_profile(name: str) -> PlayerProfile | None:
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return PlayerProfile.from_dict(data)


def load_or_create(name: str, prior_type: str = "未知") -> PlayerProfile:
    profile = load_profile(name)
    if profile is not None:
        return profile
    return create_profile(name, prior_type)


def list_profiles() -> list[str]:
    if not PROFILES_DIR.exists():
        return []
    return [p.stem for p in PROFILES_DIR.glob("*.json") if p.stem != "__init__"]


def delete_profile(name: str) -> bool:
    path = PROFILES_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def available_prior_types() -> list[str]:
    return list(PRIOR_TEMPLATES.keys()) + ["未知"]
