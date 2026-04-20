from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from treys import Evaluator, Card

from env.action_space import ActionType, PlayerAction, Street
from env.board_texture import analyze_board
from profiler.player_profile import PlayerProfile, KeyHand
from profiler.info_weight import calc_skill_delta


EVALUATOR = Evaluator()


class ShowdownType(Enum):
    PURE_AIR = auto()
    MISSED_DRAW = auto()
    THIN_VALUE = auto()
    STRONG_VALUE = auto()
    OVERPLAYED = auto()


@dataclass
class ShowdownResult:
    showdown_type: ShowdownType
    hand_strength_rank: int
    was_bluffing: bool
    bet_streets: list[Street]
    total_invested: int
    skill_signal: str
    detail: str


def _has_draw_potential(hole_cards: list[int], board: list[int]) -> bool:
    all_cards = hole_cards + board
    suits = [Card.get_suit_int(c) for c in all_cards]
    ranks = sorted([Card.get_rank_int(c) for c in all_cards])

    suit_counts: dict[int, int] = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1
    if any(c >= 4 for c in suit_counts.values()):
        hero_suits = [Card.get_suit_int(c) for c in hole_cards]
        for s, count in suit_counts.items():
            if count >= 4 and s in hero_suits:
                return True

    unique = sorted(set(ranks))
    for i in range(len(unique) - 3):
        window = unique[i:i+5] if i+5 <= len(unique) else unique[i:]
        if len(window) >= 4 and window[-1] - window[0] <= 4:
            hero_ranks = [Card.get_rank_int(c) for c in hole_cards]
            if any(r in window for r in hero_ranks):
                return True

    return False


def classify_showdown(
    hole_cards: list[int],
    board: list[int],
    action_history: dict[Street, list[PlayerAction]],
    player_name: str,
    pot_size: int,
) -> ShowdownResult:
    rank = EVALUATOR.evaluate(hole_cards, board)
    bet_streets = []
    total_invested = 0

    for street, actions in action_history.items():
        for a in actions:
            if a.player_name != player_name:
                continue
            if a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
                bet_streets.append(street)
                total_invested += a.amount
            elif a.action_type == ActionType.CALL:
                total_invested += a.amount

    was_aggressive = len(bet_streets) >= 2
    had_draw = _has_draw_potential(hole_cards, board[:3]) if len(board) >= 3 else False

    if rank <= 2000:
        if was_aggressive and total_invested > pot_size * 0.8:
            sd_type = ShowdownType.STRONG_VALUE
            signal = "neutral"
            detail = "强牌积极下注，正常价值行为"
        else:
            sd_type = ShowdownType.STRONG_VALUE
            signal = "neutral"
            detail = "强牌"
    elif rank <= 4000:
        if was_aggressive and total_invested > pot_size * 1.2:
            sd_type = ShowdownType.OVERPLAYED
            signal = "low"
            detail = f"中等牌力(rank={rank})过度投入，高估手牌强度"
        else:
            sd_type = ShowdownType.THIN_VALUE
            signal = "medium_high"
            detail = "中等牌力薄价值下注，判断力不错"
    elif rank <= 5500:
        if was_aggressive:
            sd_type = ShowdownType.OVERPLAYED
            signal = "low"
            detail = f"弱牌(rank={rank})却积极下注，牌力判断差"
        else:
            sd_type = ShowdownType.THIN_VALUE
            signal = "neutral"
            detail = "弱成牌被动到摊牌"
    else:
        if had_draw:
            sd_type = ShowdownType.MISSED_DRAW
            signal = "medium"
            detail = "听牌未中，理解半诈唬概念"
        else:
            sd_type = ShowdownType.PURE_AIR
            if was_aggressive:
                signal = "variable"
                detail = "纯空气牌积极下注，非理性激进或高级诈唬"
            else:
                signal = "low"
                detail = "纯空气牌到摊牌，缺乏弃牌意识"

    return ShowdownResult(
        showdown_type=sd_type,
        hand_strength_rank=rank,
        was_bluffing=rank > 5500 and was_aggressive,
        bet_streets=bet_streets,
        total_invested=total_invested,
        skill_signal=signal,
        detail=detail,
    )


def retroactive_calibrate(
    profile: PlayerProfile,
    showdown: ShowdownResult,
    hand_id: int,
    board: str = "",
) -> None:
    sd_type = showdown.showdown_type
    skill = profile.skill_estimate
    conf = skill.overall_skill

    event_map = {
        ShowdownType.PURE_AIR: ("pure_air_normal_bet", -1.0),
        ShowdownType.MISSED_DRAW: ("missed_draw_bluff", 0.3),
        ShowdownType.THIN_VALUE: ("thin_value_correct", 0.5),
        ShowdownType.STRONG_VALUE: ("normal_bet", 0.1),
        ShowdownType.OVERPLAYED: ("overplayed_hand", -0.7),
    }

    event, direction = event_map.get(sd_type, ("normal_bet", 0.0))

    if showdown.was_bluffing and sd_type == ShowdownType.PURE_AIR:
        if showdown.total_invested > 0:
            event = "pure_air_overbet"
            direction = -1.0

    delta = calc_skill_delta(event, direction, conf)
    skill.overall_skill = max(0.0, min(1.0, skill.overall_skill + delta))

    if sd_type == ShowdownType.OVERPLAYED:
        skill.hand_reading_ability = max(0.0, min(1.0, skill.hand_reading_ability + delta))
    elif sd_type == ShowdownType.THIN_VALUE:
        skill.hand_reading_ability = max(0.0, min(1.0, skill.hand_reading_ability + delta * 0.5))

    if showdown.was_bluffing:
        profile.bet_sizing.record_bet(
            showdown.total_invested / max(1, len(showdown.bet_streets)),
            is_value=False,
        )

    if abs(direction) >= 0.5 or showdown.was_bluffing:
        profile.add_key_hand(KeyHand(
            hand_id=hand_id,
            situation=sd_type.name.lower(),
            details=showdown.detail,
            board=board,
            showdown_type=sd_type.name.lower(),
            skill_signal=showdown.skill_signal,
        ))
