from __future__ import annotations

from env.action_space import ActionType
from data.postflop_rules import HandStrength


ACTION_NAMES = {
    ActionType.FOLD: "弃牌",
    ActionType.CHECK: "过牌",
    ActionType.CALL: "跟注",
    ActionType.BET: "下注",
    ActionType.RAISE: "加注",
    ActionType.ALL_IN: "全下",
}

STRENGTH_NAMES = {
    HandStrength.TRASH: "空气牌",
    HandStrength.WEAK_DRAW: "弱听牌",
    HandStrength.MEDIUM_DRAW: "中等听牌",
    HandStrength.STRONG_DRAW: "强听牌",
    HandStrength.WEAK_MADE: "弱成牌",
    HandStrength.MEDIUM_MADE: "中等成牌",
    HandStrength.STRONG_MADE: "强成牌",
    HandStrength.MONSTER: "坚果牌",
}


def format_advice(
    action: ActionType,
    amount: int,
    confidence: float,
    reasons: list[str],
    alternatives: list[tuple[ActionType, float]] | None = None,
) -> str:
    action_str = ACTION_NAMES.get(action, action.value)
    if amount > 0 and action in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
        header = f"建议: {action_str} {amount} (置信度: {confidence:.0%})"
    else:
        header = f"建议: {action_str} (置信度: {confidence:.0%})"

    lines = [header, "理由:"]
    for r in reasons:
        lines.append(f"  - {r}")

    if alternatives:
        alt_parts = []
        for alt_action, alt_pct in alternatives:
            alt_name = ACTION_NAMES.get(alt_action, alt_action.value)
            alt_parts.append(f"{alt_name}({alt_pct:.0%})")
        lines.append(f"备选: {' / '.join(alt_parts)}")

    return "\n".join(lines)


def build_reasons(
    baseline_info: dict,
    equity: float | None = None,
    pot_odds_val: float | None = None,
    opponent_summary: str | None = None,
    exploit_note: str | None = None,
) -> list[str]:
    reasons = []

    if "hand" in baseline_info:
        reasons.append(f"手牌 {baseline_info['hand']}")
    if "reasoning" in baseline_info:
        reasons.append(baseline_info["reasoning"])

    if equity is not None:
        reasons.append(f"胜率: {equity:.0%}")
    if pot_odds_val is not None:
        reasons.append(f"底池赔率: {pot_odds_val:.0%}")

    if opponent_summary:
        reasons.append(f"对手画像: {opponent_summary}")
    if exploit_note:
        reasons.append(f"Exploit: {exploit_note}")

    return reasons
