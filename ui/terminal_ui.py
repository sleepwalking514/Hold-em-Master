from __future__ import annotations

from itertools import combinations

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from treys import Card, Evaluator

from env.game_state import GameState, Player
from env.action_space import Street, GameMode

console = Console()
_EVALUATOR = Evaluator()

SUIT_COLORS = {
    1: "green",   # spades
    2: "red",     # hearts
    4: "blue",    # diamonds
    8: "green",   # clubs
}


def _pretty_card(card: int) -> Text:
    s = Card.int_to_pretty_str(card).strip()
    suit_int = Card.get_suit_int(card)
    color = SUIT_COLORS.get(suit_int, "white")
    return Text(s, style=f"bold {color}")


def _cards_text(cards: list[int]) -> Text:
    if not cards:
        return Text("--", style="dim")
    result = Text()
    for i, c in enumerate(cards):
        if i > 0:
            result.append(" ")
        result.append_text(_pretty_card(c))
    return result


def display_table(gs: GameState, hero_name: str | None = None) -> None:
    street_names = {
        Street.PREFLOP: "Preflop",
        Street.FLOP: "Flop",
        Street.TURN: "Turn",
        Street.RIVER: "River",
    }

    header = Text()
    header.append(f"═══ 第 #{gs.hand_number} 手 ═══  ", style="bold yellow")
    header.append(f"庄位: {gs.players[gs.dealer_idx].name}  ")
    header.append(f"盲注: {gs.small_blind}/{gs.big_blind}  ")
    header.append(f"底池: {gs.pot}", style="bold cyan")
    console.print(header)

    console.print(f"\n── {street_names[gs.street]} ──", style="bold")

    if gs.board:
        board_text = Text("公共牌: ")
        board_text.append_text(_cards_text(gs.board))
        console.print(board_text)

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("位置", style="cyan", width=6)
    table.add_column("玩家", width=10)
    table.add_column("筹码", justify="right", width=8)
    table.add_column("本轮下注", justify="right", width=8)
    if gs.game_mode == GameMode.TEST:
        table.add_column("手牌", width=14)
    table.add_column("状态", width=8)

    for p in gs.players:
        status = ""
        style = ""
        if not p.is_active and not p.is_all_in:
            status = "fold"
            style = "dim"
        elif p.is_all_in:
            status = "ALL-IN"
            style = "bold red"
        elif p.name == hero_name:
            style = "bold green"

        bet_str = str(p.current_bet) if (p.is_active or p.is_all_in) else ""
        row: list = [p.position, p.name, str(p.stack), bet_str]
        if gs.game_mode == GameMode.TEST:
            row.append(_cards_text(p.hole_cards) if p.hole_cards else Text("", style="dim"))
        row.append(Text(status, style=style) if status else Text(""))
        table.add_row(*row, style=style)

    console.print(table)
    console.print()


def display_hero_cards(cards: list[int]) -> None:
    text = Text("你的手牌: ")
    text.append_text(_cards_text(cards))
    console.print(text, style="bold")


def display_action_prompt(player: Player, gs: GameState) -> None:
    call_amount = gs.current_bet - player.current_bet
    info = Text()
    info.append(f"\n当前行动: ", style="")
    info.append(f"{player.name}", style="bold")
    info.append(f" ({player.position}) 筹码: {player.stack}")
    if gs.game_mode == GameMode.TEST and player.hole_cards:
        info.append("  手牌: ")
        info.append_text(_cards_text(player.hole_cards))
    console.print(info)
    options = Text()
    options.append("[F]", style="bold") ; options.append(" Fold  ")
    if call_amount == 0:
        options.append("[C]", style="bold") ; options.append(" Check  ")
    elif call_amount >= player.stack:
        options.append("[C]", style="bold") ; options.append(f" Call All-in({player.stack})  ")
    else:
        options.append("[C]", style="bold") ; options.append(f" Call {call_amount}  ")
    min_raise = gs.get_min_raise()
    max_bet = player.stack + player.current_bet
    if call_amount >= player.stack:
        pass
    elif min_raise >= max_bet:
        options.append("[A]", style="bold") ; options.append(f" All-in({player.stack})")
    else:
        options.append(f"[数字]", style="bold") ; options.append(f" Raise(最小{min_raise})  ")
        options.append("[A]", style="bold") ; options.append(f" All-in({player.stack})")
    console.print(options)


def _best_five(board: list[int], hole_cards: list[int]) -> tuple[list[int], int]:
    all_seven = board + hole_cards
    best_rank = 7463
    best_combo: list[int] = all_seven[:5]
    for combo in combinations(all_seven, 5):
        rank = _EVALUATOR.evaluate(list(combo[:3]), list(combo[3:]))
        if rank < best_rank:
            best_rank = rank
            best_combo = list(combo)
    return best_combo, best_rank


def display_showdown(gs: GameState) -> None:
    in_hand = gs.players_in_hand
    if len(in_hand) <= 1 or len(gs.board) < 5:
        return
    console.print("\n── 摊牌 ──", style="bold yellow")
    board_text = Text("  公共牌: ")
    board_text.append_text(_cards_text(gs.board))
    console.print(board_text)
    for p in in_hand:
        if len(p.hole_cards) == 2:
            best, rank = _best_five(gs.board, p.hole_cards)
            rank_class = _EVALUATOR.get_rank_class(rank)
            rank_str = _EVALUATOR.class_to_string(rank_class)
            text = Text(f"  {p.name}: ")
            text.append_text(_cards_text(p.hole_cards))
            text.append(f"  → {rank_str}  ", style="bold")
            text.append_text(_cards_text(best))
            console.print(text)
        else:
            console.print(f"  {p.name}: [未知]", style="dim")


def display_settlement(winnings: dict[str, int]) -> None:
    console.print("\n── 结算 ──", style="bold yellow")
    for name, amount in winnings.items():
        if amount > 0:
            console.print(f"  {name} 赢得 {amount}", style="bold green")


def display_message(msg: str, style: str = "") -> None:
    console.print(msg, style=style)


def display_error(msg: str) -> None:
    console.print(f"[bold red]错误: {msg}[/bold red]")
