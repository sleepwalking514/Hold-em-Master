from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from treys import Evaluator

from env.action_space import ActionType, PlayerAction, Street
from data.postflop_rules import (
    HandStrength, PostflopAction, classify_hand_strength,
    get_postflop_advice,
)
from profiler.player_profile import PlayerProfile, KeyHand
from profiler.info_weight import calc_skill_delta


EVALUATOR = Evaluator()


class MistakeType(Enum):
    VALUE_OVERSIZE = auto()
    VALUE_UNDERSIZE = auto()
    MISSED_VALUE = auto()
    IRRATIONAL_FOLD = auto()
    BLUFF_INTO_STRENGTH = auto()
    POSITIONAL_WASTE = auto()
    CALLING_STATION = auto()
    OVERBET_BLUFF = auto()
    WEAK_LEAD = auto()
    GOOD_SIZING = auto()
    GOOD_SLOWPLAY = auto()
    GOOD_BLUFF = auto()
    GOOD_THIN_VALUE = auto()
    GOOD_POSITIONAL_PLAY = auto()
    GOOD_FOLD = auto()
    GOOD_TRAP = auto()
    GOOD_VALUE_RAISE = auto()
    GOOD_DRAW_PLAY = auto()


@dataclass
class ActionJudgment:
    street: Street
    action: PlayerAction
    hand_strength: HandStrength
    optimal_action: PostflopAction
    actual_category: PostflopAction
    mistake: Optional[MistakeType]
    severity: float  # -1.0 (terrible) to +1.0 (excellent)
    detail: str


def _action_to_category(action: PlayerAction, pot_size: int) -> PostflopAction:
    at = action.action_type
    if at == ActionType.FOLD:
        return PostflopAction.FOLD
    if at == ActionType.CHECK:
        return PostflopAction.CHECK
    if at == ActionType.CALL:
        return PostflopAction.CALL
    if at in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
        if pot_size <= 0:
            return PostflopAction.BET_MEDIUM
        ratio = action.amount / pot_size
        if ratio <= 0.4:
            return PostflopAction.BET_SMALL
        elif ratio <= 0.8:
            return PostflopAction.BET_MEDIUM
        else:
            return PostflopAction.BET_LARGE
    return PostflopAction.CHECK


def _bet_ratio(action: PlayerAction, pot_size: int) -> float:
    if pot_size <= 0:
        return 1.0
    return action.amount / pot_size


def _is_ip(player_position: str, num_players: int) -> bool:
    late_positions = {"BTN", "CO", "SB"} if num_players <= 3 else {"BTN", "CO"}
    return player_position in late_positions


def _facing_bet(street_actions: list[PlayerAction], player_name: str) -> bool:
    for a in reversed(street_actions):
        if a.player_name == player_name:
            break
        if a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
            return True
    return False


def _judge_single_action(
    action: PlayerAction,
    hand_strength: HandStrength,
    pot_size: int,
    is_ip: bool,
    facing_bet: bool,
    spr: float,
    prior_actions_on_street: list[PlayerAction],
) -> ActionJudgment:
    advice = get_postflop_advice(hand_strength, is_ip, facing_bet, spr)
    optimal = advice["action"]
    actual = _action_to_category(action, pot_size)

    mistake = None
    severity = 0.0
    detail = ""

    # Irrational fold: folding when not facing a bet (free card available)
    if actual == PostflopAction.FOLD and not facing_bet:
        mistake = MistakeType.IRRATIONAL_FOLD
        severity = -0.9
        detail = "弃牌但无人下注，放弃免费看牌机会"

    # Strong hand but fold
    elif (actual == PostflopAction.FOLD
          and hand_strength.value >= HandStrength.MEDIUM_MADE.value):
        mistake = MistakeType.IRRATIONAL_FOLD
        severity = -0.7
        detail = f"持有{hand_strength.name}却弃牌"

    # Monster/strong hand but only check through all streets (missed value)
    elif (actual == PostflopAction.CHECK
          and hand_strength.value >= HandStrength.STRONG_MADE.value
          and optimal in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE)):
        mistake = MistakeType.MISSED_VALUE
        severity = -0.4
        detail = f"持有{hand_strength.name}却过牌，错失价值"

    # Value oversize: strong hand but bet too large, scaring opponents
    elif (hand_strength.value >= HandStrength.STRONG_MADE.value
          and actual == PostflopAction.BET_LARGE
          and optimal in (PostflopAction.BET_SMALL, PostflopAction.BET_MEDIUM)):
        ratio = _bet_ratio(action, pot_size)
        if ratio > 1.2:
            mistake = MistakeType.VALUE_OVERSIZE
            severity = -0.5
            detail = f"价值手下注过大({ratio:.0%}pot)，容易吓跑对手"
        else:
            mistake = MistakeType.VALUE_OVERSIZE
            severity = -0.25
            detail = f"价值手下注偏大({ratio:.0%}pot)"

    # Value undersize: strong hand but bet too small
    elif (hand_strength.value >= HandStrength.STRONG_MADE.value
          and actual == PostflopAction.BET_SMALL
          and optimal in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE)):
        mistake = MistakeType.VALUE_UNDERSIZE
        severity = -0.3
        detail = "价值手下注过小，未能最大化收益"

    # Bluffing with trash when facing a bet
    elif (hand_strength.value <= HandStrength.WEAK_DRAW.value
          and actual in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE)
          and facing_bet
          and action.action_type in (ActionType.RAISE, ActionType.ALL_IN)):
        mistake = MistakeType.BLUFF_INTO_STRENGTH
        severity = -0.3
        detail = "对手已下注，用弱牌加注/大额下注"

    # Positional waste: has position but plays passively with playable hand
    elif (is_ip
          and hand_strength.value >= HandStrength.MEDIUM_MADE.value
          and actual == PostflopAction.CHECK
          and not facing_bet
          and optimal != PostflopAction.CHECK):
        mistake = MistakeType.POSITIONAL_WASTE
        severity = -0.2
        detail = "有位置优势却未利用，被动过牌"

    # Calling station: calling with trash/weak when should fold
    elif (actual == PostflopAction.CALL and facing_bet
          and hand_strength.value <= HandStrength.WEAK_DRAW.value
          and optimal == PostflopAction.FOLD):
        ratio = _bet_ratio(
            next((a for a in reversed(prior_actions_on_street)
                  if a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)),
                 action),
            pot_size,
        )
        if ratio >= 0.7:
            mistake = MistakeType.CALLING_STATION
            severity = -0.5
            detail = f"弱牌跟注大额下注({ratio:.0%}pot)，典型跟注站行为"
        else:
            mistake = MistakeType.CALLING_STATION
            severity = -0.3
            detail = "弱牌跟注应弃牌，缺乏弃牌纪律"

    # Overbet bluff: huge bet with trash when not facing bet
    elif (not facing_bet
          and hand_strength.value <= HandStrength.WEAK_DRAW.value
          and actual == PostflopAction.BET_LARGE):
        ratio = _bet_ratio(action, pot_size)
        if ratio > 1.0:
            mistake = MistakeType.OVERBET_BLUFF
            severity = -0.4
            detail = f"用空气牌超额下注({ratio:.0%}pot)，诈唬尺寸不合理"
        else:
            mistake = MistakeType.OVERBET_BLUFF
            severity = -0.25
            detail = "弱牌大额下注，诈唬频率/尺寸失衡"

    # Weak lead: OOP small bet with trash/weak (donk bet tell)
    elif (not is_ip and not facing_bet
          and hand_strength.value <= HandStrength.WEAK_MADE.value
          and actual == PostflopAction.BET_SMALL
          and optimal == PostflopAction.CHECK):
        mistake = MistakeType.WEAK_LEAD
        severity = -0.2
        detail = "OOP弱牌小额领先下注，暴露牌力信息"

    # Positive signals
    # Note: _action_to_category maps RAISE to BET_* based on sizing,
    # so we also check when optimal is RAISE and player raised (any size)
    elif actual == optimal or (
        optimal == PostflopAction.RAISE and facing_bet
        and actual in (PostflopAction.BET_SMALL, PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE)
        and action.action_type in (ActionType.RAISE, ActionType.ALL_IN)
    ):
        if hand_strength.value >= HandStrength.STRONG_MADE.value:
            if facing_bet and action.action_type in (ActionType.RAISE, ActionType.ALL_IN):
                mistake = MistakeType.GOOD_VALUE_RAISE
                severity = 0.35
                detail = "强牌面对下注正确加注榨取价值"
            elif actual in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE):
                mistake = MistakeType.GOOD_SIZING
                severity = 0.3
                detail = "价值手合理下注尺寸"
            elif actual == PostflopAction.CHECK and not is_ip:
                mistake = MistakeType.GOOD_TRAP
                severity = 0.25
                detail = "OOP强牌慢打设陷阱"
        elif hand_strength.value == HandStrength.MEDIUM_MADE.value:
            if actual in (PostflopAction.BET_SMALL, PostflopAction.BET_MEDIUM):
                mistake = MistakeType.GOOD_THIN_VALUE
                severity = 0.2
                detail = "中等牌力薄价值下注"
            elif actual == PostflopAction.CALL and facing_bet:
                mistake = MistakeType.GOOD_THIN_VALUE
                severity = 0.15
                detail = "中等牌力合理跟注"
        elif hand_strength.value in (HandStrength.STRONG_DRAW.value,
                                     HandStrength.MEDIUM_DRAW.value):
            if actual == PostflopAction.CALL and facing_bet:
                mistake = MistakeType.GOOD_DRAW_PLAY
                severity = 0.2
                detail = "听牌正确跟注，赔率合理"
            elif actual in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE):
                mistake = MistakeType.GOOD_DRAW_PLAY
                severity = 0.25
                detail = "听牌半诈唬下注，兼具弃牌收益和成牌价值"
        elif hand_strength.value <= HandStrength.WEAK_DRAW.value:
            if actual in (PostflopAction.BET_MEDIUM, PostflopAction.BET_LARGE):
                mistake = MistakeType.GOOD_BLUFF
                severity = 0.2
                detail = "合理的诈唬选择"
            elif actual == PostflopAction.FOLD and facing_bet:
                mistake = MistakeType.GOOD_FOLD
                severity = 0.1
                detail = "弱牌面对下注果断弃牌"

    # Good positional play: IP with medium+ hand, correctly betting
    elif (is_ip and not facing_bet
          and hand_strength.value >= HandStrength.MEDIUM_MADE.value
          and actual in (PostflopAction.BET_SMALL, PostflopAction.BET_MEDIUM)
          and optimal in (PostflopAction.BET_SMALL, PostflopAction.BET_MEDIUM,
                          PostflopAction.BET_LARGE)):
        mistake = MistakeType.GOOD_POSITIONAL_PLAY
        severity = 0.2
        detail = "利用位置优势主动下注"

    # Correct fold: trash/weak facing bet, folding is disciplined
    elif (actual == PostflopAction.FOLD and facing_bet
          and hand_strength.value <= HandStrength.WEAK_DRAW.value
          and optimal == PostflopAction.FOLD):
        mistake = MistakeType.GOOD_FOLD
        severity = 0.1
        detail = "弱牌面对下注纪律性弃牌"

    return ActionJudgment(
        street=action.street,
        action=action,
        hand_strength=hand_strength,
        optimal_action=optimal,
        actual_category=actual,
        mistake=mistake,
        severity=severity,
        detail=detail,
    )


class ActionRationalityAnalyzer:
    """在showdown时回溯评估对手行动的合理性，更新技能评估。"""

    def __init__(self):
        self._evaluator = EVALUATOR

    def analyze_player_hand(
        self,
        player_name: str,
        hole_cards: list[int],
        board: list[int],
        action_history: dict[Street, list[PlayerAction]],
        pot_sizes: dict[Street, int],
        player_position: str,
        num_players: int,
        spr: float = 6.0,
    ) -> list[ActionJudgment]:
        judgments: list[ActionJudgment] = []
        ip = _is_ip(player_position, num_players)

        street_boards = {
            Street.FLOP: board[:3] if len(board) >= 3 else [],
            Street.TURN: board[:4] if len(board) >= 4 else [],
            Street.RIVER: board[:5] if len(board) >= 5 else [],
        }

        for street in (Street.FLOP, Street.TURN, Street.RIVER):
            current_board = street_boards.get(street, [])
            if not current_board:
                continue

            rank = self._evaluator.evaluate(hole_cards, current_board)
            strength = classify_hand_strength(rank, len(current_board), hole_cards, current_board)
            pot = pot_sizes.get(street, 0)

            street_actions = action_history.get(street, [])
            prior: list[PlayerAction] = []
            for action in street_actions:
                if action.player_name != player_name:
                    prior.append(action)
                    continue

                fb = _facing_bet(prior, player_name)
                judgment = _judge_single_action(
                    action, strength, pot, ip, fb, spr, prior,
                )
                judgments.append(judgment)
                prior.append(action)

        return judgments

    def update_profile_from_judgments(
        self,
        profile: PlayerProfile,
        judgments: list[ActionJudgment],
        hand_id: int = 0,
    ) -> None:
        if not judgments:
            return

        skill = profile.skill_estimate
        mistakes = [j for j in judgments if j.mistake and j.severity < 0]
        good_plays = [j for j in judgments if j.mistake and j.severity > 0]

        for j in judgments:
            if j.severity == 0.0:
                continue

            confidence = skill.overall_skill
            direction = j.severity

            if j.mistake in (MistakeType.VALUE_OVERSIZE, MistakeType.VALUE_UNDERSIZE):
                event = "overplayed_hand"
                delta = calc_skill_delta(event, direction, confidence)
                skill.sizing_sophistication = _clamp(
                    skill.sizing_sophistication + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.IRRATIONAL_FOLD:
                event = "position_misplay"
                delta = calc_skill_delta(event, direction * 2, confidence)
                skill.overall_skill = _clamp(skill.overall_skill + delta)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta * 0.7
                )

            elif j.mistake == MistakeType.MISSED_VALUE:
                event = "thin_value_correct"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.BLUFF_INTO_STRENGTH:
                event = "pure_air_normal_bet"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.POSITIONAL_WASTE:
                event = "position_misplay"
                delta = calc_skill_delta(event, direction, confidence)
                skill.positional_awareness = _clamp(
                    skill.positional_awareness + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.3)

            elif j.mistake == MistakeType.CALLING_STATION:
                event = "normal_fold"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.7)

            elif j.mistake == MistakeType.OVERBET_BLUFF:
                event = "overplayed_hand"
                delta = calc_skill_delta(event, direction, confidence)
                skill.sizing_sophistication = _clamp(
                    skill.sizing_sophistication + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.WEAK_LEAD:
                event = "position_misplay"
                delta = calc_skill_delta(event, direction, confidence)
                skill.positional_awareness = _clamp(
                    skill.positional_awareness + delta
                )
                skill.sizing_sophistication = _clamp(
                    skill.sizing_sophistication + delta * 0.5
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.3)

            elif j.mistake in (MistakeType.GOOD_SIZING, MistakeType.GOOD_BLUFF,
                               MistakeType.GOOD_SLOWPLAY, MistakeType.GOOD_TRAP):
                event = "thin_value_correct"
                delta = calc_skill_delta(event, direction, confidence)
                skill.overall_skill = _clamp(skill.overall_skill + delta)
                skill.sizing_sophistication = _clamp(
                    skill.sizing_sophistication + delta * 0.7
                )

            elif j.mistake == MistakeType.GOOD_THIN_VALUE:
                event = "thin_value_correct"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.GOOD_POSITIONAL_PLAY:
                event = "normal_bet"
                delta = calc_skill_delta(event, direction, confidence)
                skill.positional_awareness = _clamp(
                    skill.positional_awareness + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.GOOD_FOLD:
                event = "normal_fold"
                delta = calc_skill_delta(event, direction, confidence)
                skill.overall_skill = _clamp(skill.overall_skill + delta)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta * 0.5
                )

            elif j.mistake == MistakeType.GOOD_VALUE_RAISE:
                event = "thin_value_correct"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.sizing_sophistication = _clamp(
                    skill.sizing_sophistication + delta * 0.7
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

            elif j.mistake == MistakeType.GOOD_DRAW_PLAY:
                event = "thin_value_correct"
                delta = calc_skill_delta(event, direction, confidence)
                skill.hand_reading_ability = _clamp(
                    skill.hand_reading_ability + delta
                )
                skill.overall_skill = _clamp(skill.overall_skill + delta * 0.5)

        worst = min(judgments, key=lambda j: j.severity)
        if worst.severity <= -0.5:
            profile.add_key_hand(KeyHand(
                hand_id=hand_id,
                situation=worst.mistake.name if worst.mistake else "unknown",
                details=worst.detail,
                skill_signal="negative",
            ))

        best = max(judgments, key=lambda j: j.severity)
        if best.severity >= 0.3:
            profile.add_key_hand(KeyHand(
                hand_id=hand_id,
                situation=best.mistake.name if best.mistake else "good_play",
                details=best.detail,
                skill_signal="positive",
            ))


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))
