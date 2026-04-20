from __future__ import annotations

EVENT_INFO_WEIGHT: dict[str, float] = {
    # 高信息量事件（罕见，信息熵高）
    "pure_air_overbet": 0.15,
    "pure_air_normal_bet": 0.08,
    "limp_raise": 0.06,
    "check_raise": 0.06,
    "squeeze": 0.06,
    "overplayed_hand": 0.07,
    # 中等信息量事件
    "missed_draw_bluff": 0.05,
    "donk_bet": 0.05,
    "thin_value_correct": 0.04,
    "probe_bet": 0.04,
    "steal_attempt": 0.03,
    "position_misplay": 0.03,
    "bet_fold": 0.04,
    "fold_to_3bet": 0.04,
    # 低信息量事件（常见，信息熵低）
    "normal_bet": 0.01,
    "normal_call": 0.008,
    "normal_fold": 0.005,
    "normal_check": 0.003,
}

SKILL_EVENT_WEIGHT: dict[str, float] = {
    # 高信号事件
    "pure_air_overbet": 0.80,
    "pure_air_normal_bet": 0.40,
    "overplayed_hand": 0.35,
    "limp_raise": 0.30,
    "missed_draw_bluff": 0.30,
    "check_raise": 0.25,
    "thin_value_correct": 0.25,
    "squeeze": 0.25,
    # 中等信号事件
    "donk_bet": 0.20,
    "position_misplay": 0.20,
    "probe_bet": 0.18,
    "bet_fold": 0.15,
    "fold_to_3bet": 0.15,
    "steal_attempt": 0.12,
    # 低信号事件
    "normal_bet": 0.08,
    "normal_call": 0.06,
    "normal_fold": 0.05,
    "normal_check": 0.03,
}


def calc_update_delta(
    event_type: str, direction: float, current_confidence: float
) -> float:
    base_info = EVENT_INFO_WEIGHT.get(event_type, 0.01)
    dampening = 1.0 / (1.0 + current_confidence * 10)
    return direction * base_info * dampening


def calc_skill_delta(
    event_type: str, direction: float, current_skill: float
) -> float:
    """Skill estimation update — larger steps, gentler dampening."""
    base_info = SKILL_EVENT_WEIGHT.get(event_type, 0.08)
    dampening = 1.0 / (1.0 + max(current_skill - 0.5, 0) * 3)
    return direction * base_info * dampening
