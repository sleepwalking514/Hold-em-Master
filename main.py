from __future__ import annotations

import sys

import click
from rich.console import Console

from env.game_state import GameState, Player
from env.action_space import ActionType, PlayerAction, Street, GameMode
from env.run_it_twice import run_it_twice
from ui.card_parser import parse_cards, validate_no_duplicates, card_to_short, random_cards
from ui.terminal_ui import (
    display_table, display_hero_cards, display_action_prompt,
    display_showdown, display_settlement, display_message, display_error,
    display_run_it_twice, console,
)
from ui.session_manager import setup_session, rebuy_prompt
from data.hand_history import export_hand

STREET_CARD_COUNT = {Street.FLOP: 3, Street.TURN: 1, Street.RIVER: 1}


def read_player_cards(gs: GameState, player_name: str, count: int = 2) -> list[int]:
    label = f"{player_name} 的手牌" if player_name != "__hero__" else "你的手牌"
    while True:
        try:
            raw = input(f"{label} (如 Ah Kd / Enter=随机): ").strip()
            if not raw:
                cards = random_cards(count, gs.used_cards)
                gs.used_cards.update(cards)
                return cards
            cards = parse_cards(raw)
            if len(cards) != count:
                display_error(f"请输入恰好{count}张牌")
                continue
            validate_no_duplicates(cards, gs.used_cards)
            gs.used_cards.update(cards)
            return cards
        except ValueError as e:
            display_error(str(e))


STREET_LABEL = {
    Street.FLOP: "翻牌 (3张)",
    Street.TURN: "转牌 (1张)",
    Street.RIVER: "河牌 (1张)",
}


def read_board_cards(gs: GameState, count: int) -> list[int]:
    label = STREET_LABEL.get(gs.street, f"公共牌 ({count}张)")
    while True:
        try:
            raw = input(f"{label} (Enter=随机): ").strip()
            if not raw:
                cards = random_cards(count, gs.used_cards)
                gs.used_cards.update(cards)
                return cards
            cards = parse_cards(raw)
            if len(cards) != count:
                display_error(f"请输入恰好{count}张牌")
                continue
            validate_no_duplicates(cards, gs.used_cards)
            gs.used_cards.update(cards)
            return cards
        except ValueError as e:
            display_error(str(e))


def read_player_action(player: Player, gs: GameState) -> PlayerAction:
    display_action_prompt(player, gs)
    while True:
        raw = input("  > ").strip().upper()
        if not raw:
            continue

        if raw == "F":
            return PlayerAction(player.name, ActionType.FOLD)

        if raw == "C":
            if gs.current_bet == player.current_bet:
                return PlayerAction(player.name, ActionType.CHECK)
            call_amount = gs.current_bet - player.current_bet
            if call_amount >= player.stack:
                return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)
            return PlayerAction(player.name, ActionType.CALL, amount=gs.current_bet)

        if raw == "A":
            return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)

        if raw == "S":
            display_table(gs)
            continue
        if raw == "H":
            _show_hand_history(gs)
            continue

        try:
            amount = int(raw)
            min_raise = gs.get_min_raise()
            if amount < min_raise and amount < player.stack + player.current_bet:
                display_error(f"最小加注到 {min_raise}")
                continue
            if amount >= player.stack + player.current_bet:
                return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)
            at = ActionType.BET if gs.current_bet == 0 else ActionType.RAISE
            return PlayerAction(player.name, at, amount=amount)
        except ValueError:
            display_error("无效输入，请输入 F/C/A/数字")


def _show_hand_history(gs: GameState) -> None:
    for street, actions in gs.action_history.items():
        if actions:
            display_message(f"  [{street.name}]", style="bold")
            for a in actions:
                display_message(f"    {a}")


def _remaining_board_count(gs: GameState) -> int:
    return 5 - len(gs.board)


def _ask_run_it_twice() -> bool:
    while True:
        raw = input("发一次还是两次? [1] 一次  [2] 两次: ").strip()
        if raw == "1":
            return False
        if raw == "2":
            return True


def _deal_remaining_streets(gs: GameState) -> None:
    dealt = len(gs.board)
    if dealt < 3:
        gs.advance_street()
        cards = read_board_cards(gs, 3 - dealt)
        gs.board.extend(cards)
        dealt = 3
    if dealt < 4:
        gs.advance_street()
        cards = read_board_cards(gs, 1)
        gs.board.extend(cards)
        dealt = 4
    if dealt < 5:
        gs.advance_street()
        cards = read_board_cards(gs, 1)
        gs.board.extend(cards)


def handle_allin_runout(gs: GameState, hero_name: str) -> dict[str, int]:
    remaining = _remaining_board_count(gs)
    if remaining <= 0:
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
        return winnings

    run_twice = _ask_run_it_twice()

    if not run_twice:
        _deal_remaining_streets(gs)
        display_table(gs, hero_name)
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
        return winnings
    else:
        board_1 = random_cards(remaining, gs.used_cards)
        used_for_2 = gs.used_cards | set(board_1)
        board_2 = random_cards(remaining, used_for_2)
        result = run_it_twice(gs, board_1, board_2)
        display_run_it_twice(gs, result)
        for name, amount in result.combined.items():
            p = gs.get_player(name)
            p.stack += amount
        gs.pot = 0
        gs.side_pots = []
        return result.combined


def play_street(gs: GameState, hero_name: str) -> bool:
    """Play one betting round. Returns True if hand should continue."""
    action_order = gs.get_action_order()
    if len(action_order) <= 1 and gs.street != Street.PREFLOP:
        return len(gs.players_in_hand) > 1

    while not gs.is_street_over():
        for player in gs.get_action_order():
            if player.has_acted:
                continue
            if not player.is_active or player.is_all_in:
                continue

            action = read_player_action(player, gs)
            gs.apply_action(action)
            display_message(f"  {action}", style="dim")

            if gs.is_hand_over():
                return False
            if gs.is_street_over():
                break

    return len(gs.players_in_hand) > 1


def record_showdown_cards(gs: GameState, hero_name: str) -> None:
    opponents = [p for p in gs.players if p.name != hero_name and len(p.hole_cards) == 0]
    if not opponents:
        return
    console.print("\n是否录入对手手牌?")
    for i, p in enumerate(opponents):
        console.print(f"  [{i+1}] {p.name}")
    console.print(f"  [Enter] 跳过")

    while True:
        raw = input("  > ").strip()
        if not raw:
            break
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(opponents):
                p = opponents[idx]
                cards = read_player_cards(gs, p.name)
                p.hole_cards = cards
                display_message(f"  {p.name}: {card_to_short(cards[0])} {card_to_short(cards[1])}")
            else:
                break
        except (ValueError, IndexError):
            break


def deal_hole_cards(gs: GameState, hero_name: str) -> None:
    if gs.game_mode == GameMode.TEST:
        for p in gs.players:
            display_message(f"  发牌: {p.name}", style="dim")
            p.hole_cards = read_player_cards(gs, p.name)
            display_message(f"    {card_to_short(p.hole_cards[0])} {card_to_short(p.hole_cards[1])}")
    else:
        hero = gs.get_player(hero_name)
        hero.hole_cards = read_player_cards(gs, "__hero__")
        display_hero_cards(hero.hole_cards)


def _is_allin_runout_needed(gs: GameState) -> bool:
    in_hand = gs.players_in_hand
    if len(in_hand) <= 1:
        return False
    active_not_allin = [p for p in in_hand if p.is_active and not p.is_all_in]
    return len(active_not_allin) == 0 and len(gs.board) < 5


def _finish_hand(gs: GameState, winnings: dict[str, int], hero_name: str) -> None:
    if gs.game_mode == GameMode.LIVE:
        record_showdown_cards(gs, hero_name)
    path = export_hand(gs, winnings)
    display_message(f"  手牌记录已保存: {path}", style="dim")


def play_hand(gs: GameState, hero_name: str) -> None:
    display_table(gs, hero_name)
    deal_hole_cards(gs, hero_name)

    if not play_street(gs, hero_name):
        display_table(gs, hero_name)
        if _is_allin_runout_needed(gs):
            winnings = handle_allin_runout(gs, hero_name)
        else:
            display_showdown(gs)
            winnings = gs.settle()
            display_settlement(winnings)
        _finish_hand(gs, winnings, hero_name)
        return

    display_table(gs, hero_name)

    streets = [Street.FLOP, Street.TURN, Street.RIVER]
    for street in streets:
        gs.advance_street()
        count = STREET_CARD_COUNT[street]
        board_cards = read_board_cards(gs, count)
        gs.board.extend(board_cards)
        display_table(gs, hero_name)

        if not play_street(gs, hero_name):
            display_table(gs, hero_name)
            if _is_allin_runout_needed(gs):
                winnings = handle_allin_runout(gs, hero_name)
                _finish_hand(gs, winnings, hero_name)
                return
            break

        display_table(gs, hero_name)

        if gs.is_hand_over():
            break

    if _is_allin_runout_needed(gs):
        winnings = handle_allin_runout(gs, hero_name)
    else:
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
    _finish_hand(gs, winnings, hero_name)


def handle_rebuys(gs: GameState, hero_name: str) -> None:
    for p in list(gs.players):
        if p.stack <= 0:
            amount = rebuy_prompt(p)
            if amount is None:
                gs.players.remove(p)
                display_message(f"{p.name} 离场", style="dim")
            else:
                p.stack = amount
                display_message(f"{p.name} 补充筹码到 {amount}")


@click.command()
@click.option("--skip-setup", is_flag=True, help="跳过设置，使用默认6人桌")
@click.option("--test", is_flag=True, help="测试模式：所有玩家手牌可见")
def main(skip_setup: bool, test: bool) -> None:
    mode = GameMode.TEST if test else GameMode.LIVE
    if skip_setup:
        players = [Player(name=n, stack=1000) for n in ["hero", "P2", "P3", "P4", "P5", "P6"]]
        gs = GameState(players=players, game_mode=mode)
        hero_name = "hero"
        gs.assign_positions()
    else:
        gs, hero_name = setup_session(mode)

    mode_label = "测试模式" if mode == GameMode.TEST else "实战模式"
    display_message(f"\n游戏开始! ({mode_label}) 按 Ctrl+C 随时退出\n", style="bold green")

    gs.hand_number = 1
    gs.post_blinds()

    try:
        while True:
            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            play_hand(gs, hero_name)
            handle_rebuys(gs, hero_name)

            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            cont = input("\n按 Enter 继续下一手, Q 退出: ").strip().upper()
            if cont == "Q":
                break

            gs.new_hand()

    except KeyboardInterrupt:
        display_message("\n\n游戏结束!", style="bold yellow")

    display_message("\n最终筹码:", style="bold")
    for p in gs.players:
        display_message(f"  {p.name}: {p.stack}")


if __name__ == "__main__":
    main()
