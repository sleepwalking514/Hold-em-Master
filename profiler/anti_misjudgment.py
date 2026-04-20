from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections import deque
from typing import Optional

from profiler.player_profile import PlayerProfile


@dataclass
class TiltState:
    is_tilting: bool = False
    tilt_confidence: float = 0.0
    trigger_event: str = ""
    hands_since_trigger: int = 0

    @property
    def exploit_multiplier(self) -> float:
        if not self.is_tilting:
            return 1.0
        return 1.0 + self.tilt_confidence * 0.5


@dataclass
class AdaptationState:
    is_adapting: bool = False
    adaptation_confidence: float = 0.0
    direction: str = ""
    exploit_reduction: float = 0.0


class AntiMisjudgment:
    def __init__(self):
        self._recent_actions: dict[str, deque] = {}
        self._recent_vs_hero: dict[str, deque] = {}
        self._tilt_states: dict[str, TiltState] = {}
        self._bad_beat_events: dict[str, list[int]] = {}
        self._adaptation_states: dict[str, AdaptationState] = {}

    def record_action(
        self, player_name: str, stat_key: str, value: float, vs_hero: bool = False
    ) -> None:
        if player_name not in self._recent_actions:
            self._recent_actions[player_name] = deque(maxlen=50)
        self._recent_actions[player_name].append((stat_key, value))

        if vs_hero:
            if player_name not in self._recent_vs_hero:
                self._recent_vs_hero[player_name] = deque(maxlen=20)
            self._recent_vs_hero[player_name].append((stat_key, value))

    def record_bad_beat(self, player_name: str, hand_id: int) -> None:
        if player_name not in self._bad_beat_events:
            self._bad_beat_events[player_name] = []
        self._bad_beat_events[player_name].append(hand_id)
        if len(self._bad_beat_events[player_name]) > 10:
            self._bad_beat_events[player_name].pop(0)

    def detect_tilt(self, player_name: str, profile: PlayerProfile) -> TiltState:
        state = self._tilt_states.get(player_name, TiltState())
        recent = self._recent_actions.get(player_name, deque())

        if len(recent) < 5:
            return state

        recent_aggr_values = [v for k, v in recent if k == "aggression_freq"]
        if not recent_aggr_values:
            return state

        long_term_aggr = profile.get_stat("aggression_freq")
        recent_avg = sum(recent_aggr_values[-5:]) / min(5, len(recent_aggr_values))

        deviation = recent_avg - long_term_aggr
        std_estimate = max(0.1, long_term_aggr * 0.3)
        sigma = deviation / std_estimate

        bad_beats = self._bad_beat_events.get(player_name, [])
        recent_bad_beats = len(bad_beats[-3:]) if bad_beats else 0

        tilt_score = 0.0
        if sigma > 2.0:
            tilt_score += 0.4
        if sigma > 3.0:
            tilt_score += 0.3
        if recent_bad_beats >= 1:
            tilt_score += 0.2 * recent_bad_beats

        tilt_score = min(1.0, tilt_score)

        if tilt_score > 0.4:
            state = TiltState(
                is_tilting=True,
                tilt_confidence=tilt_score,
                trigger_event=f"aggr偏离{sigma:.1f}σ" + (f"+{recent_bad_beats}次bad beat" if recent_bad_beats else ""),
                hands_since_trigger=0,
            )
        elif state.is_tilting:
            state.hands_since_trigger += 1
            if state.hands_since_trigger >= 5:
                state.tilt_confidence *= 0.5
            if state.tilt_confidence < 0.2:
                state = TiltState()

        self._tilt_states[player_name] = state
        return state

    def detect_adaptation(
        self, player_name: str, profile: PlayerProfile
    ) -> AdaptationState:
        vs_hero = self._recent_vs_hero.get(player_name, deque())
        all_actions = self._recent_actions.get(player_name, deque())

        if len(vs_hero) < 10 or len(all_actions) < 20:
            return AdaptationState()

        hero_aggr = [v for k, v in vs_hero if k == "aggression_freq"]
        all_aggr = [v for k, v in all_actions if k == "aggression_freq"]

        if len(hero_aggr) < 5 or len(all_aggr) < 10:
            return AdaptationState()

        hero_avg = sum(hero_aggr) / len(hero_aggr)
        all_avg = sum(all_aggr) / len(all_aggr)

        deviation = hero_avg - all_avg
        std_estimate = max(0.08, all_avg * 0.25)
        sigma = abs(deviation) / std_estimate

        state = AdaptationState()
        if sigma > 1.5:
            state.is_adapting = True
            state.adaptation_confidence = min(1.0, (sigma - 1.5) / 2.0)
            state.direction = "更激进" if deviation > 0 else "更被动"

            if sigma > 2.0:
                state.exploit_reduction = 0.5
            elif sigma > 2.5:
                state.exploit_reduction = 0.8
            if sigma > 3.0 and profile.skill_estimate.overall_skill > 0.6:
                state.exploit_reduction = -0.3

        self._adaptation_states[player_name] = state
        return state

    def get_exploit_modifier(self, player_name: str, profile: PlayerProfile) -> float:
        tilt = self.detect_tilt(player_name, profile)
        adapt = self.detect_adaptation(player_name, profile)

        modifier = 1.0
        if tilt.is_tilting:
            modifier *= tilt.exploit_multiplier
        if adapt.is_adapting:
            modifier *= (1.0 - adapt.exploit_reduction)

        return max(0.2, min(2.0, modifier))

    def should_suppress_exploit(self, player_name: str, profile: PlayerProfile) -> tuple[bool, str]:
        adapt = self.detect_adaptation(player_name, profile)
        if adapt.is_adapting and adapt.exploit_reduction >= 0.5:
            return True, f"对手正在调整({adapt.direction})，回归Solid基线"
        return False, ""

    def decay_tilt(self, player_name: str) -> None:
        state = self._tilt_states.get(player_name)
        if state and state.is_tilting:
            state.hands_since_trigger += 1
            if state.hands_since_trigger % 5 == 0:
                state.tilt_confidence *= 0.5
            if state.tilt_confidence < 0.15:
                self._tilt_states[player_name] = TiltState()
