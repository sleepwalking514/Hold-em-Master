from __future__ import annotations

from treys import Card

from env.game_state import GameState, Player, EVALUATOR
from env.action_space import Street, ActionType
from env.board_texture import analyze_board
from data.preflop_ranges import (
    get_preflop_advice, cards_to_hand, RANKS, RANK_INDEX, PreflopAction,
)
from data.postflop_rules import (
    classify_hand_strength, hand_strength_ratio,
    get_postflop_advice, HandStrength, PostflopAction,
)
from engine.pot_odds import spr_from_state, effective_stack_bb


def _card_rank_char(card: int) -> str:
    return Card.STR_RANKS[Card.get_rank_int(card)]


def _cards_suited(c1: int, c2: int) -> bool:
    return Card.get_suit_int(c1) == Card.get_suit_int(c2)


def _hero_position_is_ip(game_state: GameState, hero_name: str) -> bool:
    order = game_state.get_action_order()
    names = [p.name for p in order]
    if hero_name not in names:
        return True
    return names.index(hero_name) == len(names) - 1


def get_baseline_advice(
    game_state: GameState,
    hero: Player,
) -> dict:
    if game_state.street == Street.PREFLOP:
        return _preflop_baseline(game_state, hero)
    return _postflop_baseline(game_state, hero)


def _preflop_baseline(game_state: GameState, hero: Player) -> dict:
    r1 = _card_rank_char(hero.hole_cards[0])
    r2 = _card_rank_char(hero.hole_cards[1])
    suited = _cards_suited(hero.hole_cards[0], hero.hole_cards[1])
    hand = cards_to_hand(r1, r2, suited)

    opponents = [p for p in game_state.players_in_hand if p.name != hero.name]
    if not opponents:
        eff_bb = hero.stack / game_state.big_blind
    else:
        opp_effs = sorted(
            [effective_stack_bb(hero, v, game_state.big_blind) for v in opponents],
            reverse=True,
        )
        # Use the largest effective stack (main threat) rather than the smallest
        # Short stacks don't dictate our strategy — the deep opponents do
        eff_bb = opp_effs[0]

    facing_raise = game_state.current_bet > game_state.big_blind
    facing_3bet = False
    preflop_actions = game_state.action_history.get(Street.PREFLOP, [])
    raise_count = sum(
        1 for a in preflop_actions
        if a.action_type in (ActionType.RAISE, ActionType.BET)
    )
    if raise_count >= 2:
        facing_3bet = True

    action, confidence = get_preflop_advice(
        hand, hero.position, eff_bb, facing_raise, facing_3bet,
        num_players=len(game_state.players),
    )

    action_map = {
        PreflopAction.FOLD: ActionType.FOLD,
        PreflopAction.OPEN: ActionType.RAISE,
        PreflopAction.CALL: ActionType.CALL,
        PreflopAction.CHECK: ActionType.CHECK,
        PreflopAction.THREE_BET: ActionType.RAISE,
        PreflopAction.FOUR_BET: ActionType.RAISE,
        PreflopAction.PUSH: ActionType.ALL_IN,
    }

    return {
        "action": action_map.get(action, ActionType.FOLD),
        "confidence": confidence,
        "hand": hand,
        "preflop_action": action,
        "reasoning": f"Solid基线: {hand} 在{hero.position}位 → {action}",
    }


def _postflop_baseline(game_state: GameState, hero: Player) -> dict:
    rank = EVALUATOR.evaluate(game_state.board, hero.hole_cards)
    strength = classify_hand_strength(rank, len(game_state.board), hero.hole_cards, game_state.board)
    strength_ratio = hand_strength_ratio(rank)
    is_ip = _hero_position_is_ip(game_state, hero.name)
    texture = analyze_board(game_state.board)
    current_spr = spr_from_state(game_state, hero.name)
    facing_bet = game_state.current_bet > 0

    advice = get_postflop_advice(
        strength, is_ip, facing_bet, current_spr, texture.is_wet,
        mix=False,
    )

    postflop_to_action = {
        PostflopAction.CHECK: ActionType.CHECK,
        PostflopAction.BET_SMALL: ActionType.BET,
        PostflopAction.BET_MEDIUM: ActionType.BET,
        PostflopAction.BET_LARGE: ActionType.BET,
        PostflopAction.CALL: ActionType.CALL,
        PostflopAction.RAISE: ActionType.RAISE,
        PostflopAction.FOLD: ActionType.FOLD,
    }

    action_type = postflop_to_action.get(advice["action"], ActionType.CHECK)
    if facing_bet and action_type == ActionType.CHECK:
        action_type = ActionType.FOLD

    return {
        "action": action_type,
        "postflop_action": advice["action"],
        "confidence": advice["freq"],
        "hand_strength": strength,
        "strength_ratio": strength_ratio,
        "is_ip": is_ip,
        "spr": current_spr,
        "board_wet": texture.is_wet,
        "reasoning": (
            f"Solid基线: 牌力{strength.name} "
            f"({'有位置' if is_ip else '无位置'}, "
            f"SPR={current_spr:.1f}) → {advice['action'].value}"
        ),
    }
