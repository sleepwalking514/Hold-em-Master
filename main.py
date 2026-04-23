from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.prompt import Prompt, IntPrompt

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
from data.hand_history import export_hand, SessionRecorder, HandRecorder
from data.session_charts import generate_session_charts
from engine.advisor import Advisor
from profiler.profile_manager import (
    load_or_create, save_profile, available_prior_types, create_profile, PRIOR_TEMPLATES,
)
from profiler.player_profile import PlayerProfile
from profiler.action_analyzer import ActionRationalityAnalyzer

STREET_CARD_COUNT = {Street.FLOP: 3, Street.TURN: 1, Street.RIVER: 1}
MAX_ACTIONS_PER_STREET_FACTOR = 12


def _reset_advisor_hand(advisor: Advisor | None) -> None:
    if advisor is not None:
        advisor.reset_hand()


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


def _advice_hint(advice: dict) -> str:
    action = advice.get("action")
    amount = advice.get("amount", 0)
    label = action.value if hasattr(action, "value") else str(action)
    if amount:
        return f"{label} {amount}"
    return label


def _advice_to_action(player: Player, gs: GameState, advice: dict) -> PlayerAction:
    action_type = advice.get("action")
    amount = advice.get("amount", 0)

    if action_type == ActionType.FOLD:
        return PlayerAction(player.name, ActionType.FOLD)

    if action_type == ActionType.CHECK:
        return PlayerAction(player.name, ActionType.CHECK)

    if action_type == ActionType.CALL:
        call_amount = gs.current_bet - player.current_bet
        if call_amount >= player.stack:
            return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)
        return PlayerAction(player.name, ActionType.CALL, amount=gs.current_bet)

    if action_type == ActionType.ALL_IN:
        return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)

    if action_type in (ActionType.BET, ActionType.RAISE):
        if amount >= player.stack + player.current_bet:
            return PlayerAction(player.name, ActionType.ALL_IN, amount=player.stack + player.current_bet)
        at = ActionType.BET if gs.current_bet == 0 else ActionType.RAISE
        return PlayerAction(player.name, at, amount=max(amount, gs.get_min_raise()))

    return PlayerAction(player.name, ActionType.CHECK)


def read_player_action(player: Player, gs: GameState,
                       advice: dict | None = None) -> PlayerAction:
    display_action_prompt(player, gs)
    if advice:
        hint = _advice_hint(advice)
        console.print(f"  [dim](Enter=采纳建议: {hint})[/dim]")
    while True:
        raw = input("  > ").strip().upper()
        if not raw:
            if advice:
                return _advice_to_action(player, gs, advice)
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
        if raw == "P":
            _show_opponent_profiles(gs, hero_name)
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


def _show_opponent_profiles(gs: GameState, hero_name: str) -> None:
    for p in gs.players:
        if p.name != hero_name:
            profile = load_or_create(p.name)
            console.print(f"  [bold]{profile.summary()}[/bold]")


def _ask_prior_type(player_name: str) -> str:
    """为新对手选择先验类型。"""
    types = available_prior_types()
    console.print(f"\n  为 [bold]{player_name}[/bold] 选择先验类型:")
    for i, t in enumerate(types):
        console.print(f"    [{i+1}] {t}")
    console.print(f"    [Enter] 跳过 (未知)")
    raw = input("    > ").strip()
    if not raw:
        return "未知"
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(types):
            return types[idx]
    except ValueError:
        pass
    return "未知"


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


def play_street(gs: GameState, hero_name: str, advisor: Advisor | None = None,
                hand_rec: HandRecorder | None = None) -> bool:
    """Play one betting round. Returns True if hand should continue."""
    action_order = gs.get_action_order()
    if len(action_order) <= 1 and gs.street != Street.PREFLOP:
        return len(gs.players_in_hand) > 1

    action_count = 0
    max_actions = max(24, len(gs.players) * MAX_ACTIONS_PER_STREET_FACTOR)
    while not gs.is_street_over():
        progress_made = False
        for player in gs.get_action_order():
            if player.has_acted:
                continue
            if not player.is_active or player.is_all_in:
                continue

            advice = None
            if advisor and player.name == hero_name and player.hole_cards:
                try:
                    advice = advisor.get_advice(gs, player)
                    console.print(f"\n[bold cyan]{'─' * 40}[/bold cyan]")
                    console.print(f"[bold cyan]{advice['text']}[/bold cyan]")
                    console.print(f"[bold cyan]{'─' * 40}[/bold cyan]")
                except Exception:
                    pass

            action = read_player_action(player, gs, advice)
            gs.apply_action(action)
            progress_made = True
            action_count += 1
            display_message(f"  {action}", style="dim")

            if hand_rec:
                hand_rec.record_action(
                    gs.street, player.name, action,
                    advisor_text=advice["text"] if advice else None,
                    advisor_data=advice if advice else None,
                )

            if gs.is_hand_over():
                return False
            if gs.is_street_over():
                break

            if action_count >= max_actions:
                raise RuntimeError(
                    f"Street {gs.street.name} exceeded {max_actions} actions; "
                    "aborting to avoid an infinite loop"
                )

        if not progress_made:
            raise RuntimeError(
                f"Street {gs.street.name} made no progress; aborting to avoid an infinite loop"
            )

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


def _finish_hand(gs: GameState, winnings: dict[str, int], hero_name: str,
                  advisor: Advisor | None = None,
                  session_rec: SessionRecorder | None = None,
                  hand_rec: HandRecorder | None = None,
                  ai_opponents: dict[str, "AIOpponent"] | None = None) -> None:
    if gs.game_mode == GameMode.LIVE:
        record_showdown_cards(gs, hero_name)
    if advisor:
        _update_opponent_profiles(gs, hero_name, advisor, winnings)

    opponent_labels = None
    hero_reads = None
    if ai_opponents:
        opponent_labels = {}
        for name, ai in ai_opponents.items():
            cfg = ai.config
            opponent_labels[name] = {
                "label": cfg.label,
                "vpip_target": round(cfg.vpip_target, 3),
                "pfr_target": round(cfg.pfr_target, 3),
                "aggression_freq_target": round(cfg.aggression_freq_target, 3),
                "fold_to_cbet": round(cfg.fold_to_cbet, 3),
                "bluff_frequency": round(cfg.bluff_frequency, 3),
                "tilt_variance": round(cfg.tilt_variance, 3),
            }
    if advisor and advisor.profiles:
        hero_reads = {}
        for name, profile in advisor.profiles.items():
            from profiler.style_labeler import classify_style
            style_result = classify_style(profile, num_players=len(gs.players))
            hero_reads[name] = {
                "style": str(style_result),
                "style_primary": style_result.primary,
                "style_secondary": style_result.secondary,
                "style_confidence": round(style_result.confidence, 3),
                "total_hands": profile.total_hands,
                "vpip": round(profile.get_stat("vpip"), 3),
                "pfr": round(profile.get_stat("pfr"), 3),
                "aggression_freq": round(profile.get_stat("aggression_freq"), 3),
                "fold_to_cbet": round(profile.get_stat("fold_to_cbet"), 3),
                "wtsd": round(profile.get_stat("wtsd"), 3),
                "wsd": round(profile.get_stat("wsd"), 3),
                "cbet_flop": round(profile.get_stat("cbet_flop"), 3),
                "three_bet_pct": round(profile.get_stat("three_bet_pct"), 3),
                "steal": round(profile.get_stat("steal"), 3),
            }

    if session_rec:
        path = session_rec.export_hand(gs, winnings, hand_rec, opponent_labels, hero_reads)
        if advisor and advisor.profiles:
            session_rec.record_profile_snapshot(gs.hand_number, advisor.profiles)
    else:
        path = export_hand(gs, winnings)
    display_message(f"  手牌记录已保存: {path}", style="dim")


def _update_opponent_profiles(gs: GameState, hero_name: str, advisor: Advisor,
                               winnings: dict[str, int] | None = None) -> None:
    preflop_actions = gs.action_history.get(Street.PREFLOP, [])

    # --- 识别翻前关键角色 ---
    # 第一个 raiser（open raiser）
    first_raiser = None
    # 是否存在 3bet（第二次 raise）
    second_raiser = None
    raise_count = 0
    for a in preflop_actions:
        if a.action_type in (ActionType.RAISE, ActionType.BET, ActionType.ALL_IN):
            raise_count += 1
            if raise_count == 1:
                first_raiser = a.player_name
            elif raise_count == 2:
                second_raiser = a.player_name

    # 判断是否为 steal 场景：CO/BTN/SB open，前面无人入池
    steal_positions = {"CO", "BTN", "SB"}
    is_steal = False
    stealer_name = None
    if first_raiser:
        first_raiser_player = gs.get_player(first_raiser) if first_raiser != hero_name else None
        if first_raiser_player and first_raiser_player.position in steal_positions:
            # 检查 first_raiser 之前是否有人 call/raise
            actions_before = []
            for a in preflop_actions:
                if a.player_name == first_raiser:
                    break
                actions_before.append(a)
            no_prior_action = all(
                a.action_type == ActionType.FOLD for a in actions_before
            )
            if no_prior_action:
                is_steal = True
                stealer_name = first_raiser

    # --- 逐 action 更新 stat ---
    for street, actions in gs.action_history.items():
        # 追踪该街是否有人 bet/raise（用于 bet_fold 判断）
        street_bettors: dict[str, int] = {}  # name -> action index
        # 追踪 flop cbet 的人是否在 turn 继续
        flop_cbetter_acted_turn = False

        for i, action in enumerate(actions):
            if action.player_name == hero_name:
                continue
            name = action.player_name
            if name not in advisor.profiles:
                continue
            profile = advisor.profiles[name]
            at = action.action_type
            player = gs.get_player(name)

            # === PREFLOP ===
            if street == Street.PREFLOP:
                if at in (ActionType.CALL, ActionType.RAISE, ActionType.BET, ActionType.ALL_IN):
                    profile.update_stat("vpip", True)
                    if at in (ActionType.RAISE, ActionType.BET, ActionType.ALL_IN):
                        profile.update_stat("pfr", True)
                    else:
                        profile.update_stat("pfr", False)
                elif at == ActionType.FOLD:
                    profile.update_stat("vpip", False)

                # fold_to_3bet: 对手是 first_raiser，面对 3bet 时的反应
                if name == first_raiser and second_raiser:
                    # 找 first_raiser 在 3bet 之后的动作
                    after_3bet = False
                    for a2 in preflop_actions:
                        if a2.player_name == second_raiser and a2.action_type in (ActionType.RAISE, ActionType.ALL_IN):
                            after_3bet = True
                            continue
                        if after_3bet and a2.player_name == name:
                            if a2.action_type == ActionType.FOLD:
                                profile.update_stat("fold_to_3bet", True)
                            else:
                                profile.update_stat("fold_to_3bet", False)
                            break

                # steal: 对手在 steal 位 open
                if name == stealer_name and is_steal:
                    profile.update_stat("steal", True)
                elif (player and player.position in steal_positions
                      and at == ActionType.FOLD and not first_raiser):
                    # 在 steal 位但 fold 了（没人 open 前就 fold，说明放弃 steal 机会）
                    # 只在前面无人 raise 时才算放弃 steal
                    actions_before_this = preflop_actions[:preflop_actions.index(action)]
                    no_raise_before = all(
                        a.action_type in (ActionType.FOLD, ActionType.CHECK)
                        for a in actions_before_this
                    )
                    if no_raise_before:
                        profile.update_stat("steal", False)

                # bb_fold_to_steal / bb_3bet_vs_steal
                if is_steal and player and player.position == "BB":
                    if at == ActionType.FOLD:
                        profile.update_stat("bb_fold_to_steal", True)
                    elif at in (ActionType.RAISE, ActionType.ALL_IN):
                        profile.update_stat("bb_fold_to_steal", False)
                        profile.update_stat("bb_3bet_vs_steal", True)
                    elif at == ActionType.CALL:
                        profile.update_stat("bb_fold_to_steal", False)
                        profile.update_stat("bb_3bet_vs_steal", False)

                # sb_fold_to_steal
                if is_steal and player and player.position == "SB":
                    if at == ActionType.FOLD:
                        profile.update_stat("sb_fold_to_steal", True)
                    else:
                        profile.update_stat("sb_fold_to_steal", False)

                # squeeze: 面对 raise + call，进行 re-raise
                if at in (ActionType.RAISE, ActionType.ALL_IN) and raise_count >= 2:
                    callers_before = sum(
                        1 for a in preflop_actions[:i]
                        if a.action_type == ActionType.CALL
                    )
                    if callers_before >= 1 and name != first_raiser:
                        profile.update_stat("squeeze", True)

            # === 所有街通用：aggression ===
            if at in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
                profile.update_stat("aggression_freq", True)
                street_bettors[name] = i
            elif at in (ActionType.CALL, ActionType.CHECK):
                profile.update_stat("aggression_freq", False)

            # === FLOP ===
            if street == Street.FLOP:
                # cbet_flop
                if name == first_raiser:
                    if at in (ActionType.BET, ActionType.RAISE):
                        profile.update_stat("cbet_flop", True)
                    elif at in (ActionType.CHECK, ActionType.FOLD):
                        profile.update_stat("cbet_flop", False)

                # fold_to_cbet
                if name != first_raiser and first_raiser:
                    # 检查 first_raiser 是否在本街 bet 了
                    raiser_bet_on_flop = any(
                        a.action_type in (ActionType.BET, ActionType.RAISE)
                        and a.player_name == first_raiser
                        for a in actions[:i]
                    )
                    if raiser_bet_on_flop:
                        if at == ActionType.FOLD:
                            profile.update_stat("fold_to_cbet", True)
                        elif at in (ActionType.CALL, ActionType.RAISE):
                            profile.update_stat("fold_to_cbet", False)

            # === TURN ===
            if street == Street.TURN:
                # cbet_turn: flop cbetter 在 turn 继续下注
                flop_actions = gs.action_history.get(Street.FLOP, [])
                flop_cbetter = None
                if first_raiser:
                    for fa in flop_actions:
                        if fa.player_name == first_raiser and fa.action_type in (ActionType.BET, ActionType.RAISE):
                            flop_cbetter = first_raiser
                            break

                if name == flop_cbetter and not flop_cbetter_acted_turn:
                    flop_cbetter_acted_turn = True
                    if at in (ActionType.BET, ActionType.RAISE):
                        profile.update_stat("cbet_turn", True)
                    elif at in (ActionType.CHECK, ActionType.FOLD):
                        profile.update_stat("cbet_turn", False)

            # === RIVER ===
            if street == Street.RIVER:
                # fold_to_river_bet: 面对河牌下注时 fold
                river_bet_exists = any(
                    a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)
                    and a.player_name != name
                    for a in actions[:i]
                )
                if river_bet_exists:
                    if at == ActionType.FOLD:
                        profile.update_stat("fold_to_river_bet", True)
                    elif at in (ActionType.CALL, ActionType.RAISE):
                        profile.update_stat("fold_to_river_bet", False)

            # === bet_fold_freq: 下注/加注后面对 re-raise 时 fold ===
            if at == ActionType.FOLD and street != Street.PREFLOP:
                # 检查该玩家之前在本街是否 bet/raise 过
                player_bet_before = any(
                    a.player_name == name
                    and a.action_type in (ActionType.BET, ActionType.RAISE)
                    for a in actions[:i]
                )
                # 检查是否面对 re-raise
                facing_raise = any(
                    a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                    and a.player_name != name
                    for a in actions[street_bettors.get(name, 0):i]
                ) if name in street_bettors else False
                if player_bet_before and facing_raise:
                    profile.update_stat("bet_fold_freq", True)
            elif at in (ActionType.CALL, ActionType.RAISE) and street != Street.PREFLOP:
                if name in street_bettors:
                    # 之前 bet 过，现在面对 raise 选择 call/re-raise
                    facing_raise = any(
                        a.action_type in (ActionType.RAISE, ActionType.ALL_IN)
                        and a.player_name != name
                        for a in actions[street_bettors[name]:i]
                    )
                    if facing_raise:
                        profile.update_stat("bet_fold_freq", False)

    # === wtsd / wsd ===
    showdown_players = [p for p in gs.players if p.name != hero_name and p.is_active]
    for p in showdown_players:
        if p.name in advisor.profiles:
            advisor.profiles[p.name].update_stat("wtsd", True)
            # wsd: 到摊牌且赢了
            if winnings and winnings.get(p.name, 0) > 0:
                advisor.profiles[p.name].update_stat("wsd", True)
            elif winnings:
                advisor.profiles[p.name].update_stat("wsd", False)
    folded_players = [p for p in gs.players if p.name != hero_name and not p.is_active and not p.is_all_in]
    for p in folded_players:
        if p.name in advisor.profiles:
            advisor.profiles[p.name].update_stat("wtsd", False)

    # === AdvancedActions + StreetTendencies ===
    _update_advanced_actions(gs, hero_name, advisor, first_raiser)

    _analyze_action_rationality(gs, hero_name, advisor)

    for name, profile in advisor.profiles.items():
        profile.total_hands += 1
        if gs.game_mode != GameMode.SIM:
            save_profile(profile)


def _update_advanced_actions(
    gs: GameState, hero_name: str, advisor: Advisor, preflop_raiser: str | None,
) -> None:
    """更新 AdvancedActions 和 StreetTendencies。"""
    preflop_actions = gs.action_history.get(Street.PREFLOP, [])

    # --- Limp / Limp-raise 检测 ---
    limpers: set[str] = set()
    for a in preflop_actions:
        if a.player_name == hero_name:
            continue
        if a.action_type == ActionType.CALL and a.amount <= gs.big_blind:
            limpers.add(a.player_name)
        elif a.action_type in (ActionType.RAISE, ActionType.ALL_IN) and a.player_name in limpers:
            # limp-raise: 先 limp 后 raise
            if a.player_name in advisor.profiles:
                advisor.profiles[a.player_name].advanced_actions.limp_raise_freq.update(True)

    for name in limpers:
        if name in advisor.profiles:
            advisor.profiles[name].advanced_actions.limp_freq.update(True)
    # 非 limper 的入池玩家
    for a in preflop_actions:
        if a.player_name == hero_name or a.player_name in limpers:
            continue
        if a.player_name in advisor.profiles and a.action_type in (ActionType.RAISE, ActionType.BET):
            advisor.profiles[a.player_name].advanced_actions.limp_freq.update(False)

    # --- Postflop: check-raise, donk bet, probe bet, raise cbet ---
    for street in (Street.FLOP, Street.TURN, Street.RIVER):
        actions = gs.action_history.get(street, [])
        if not actions:
            continue

        checkers: set[str] = set()
        first_bettor: str | None = None
        first_bet_seen = False

        for i, a in enumerate(actions):
            if a.player_name == hero_name:
                if a.action_type == ActionType.CHECK:
                    checkers.add(a.player_name)
                if a.action_type in (ActionType.BET, ActionType.RAISE) and not first_bet_seen:
                    first_bettor = a.player_name
                    first_bet_seen = True
                continue

            name = a.player_name
            if name not in advisor.profiles:
                continue
            profile = advisor.profiles[name]
            at = a.action_type

            if at == ActionType.CHECK:
                checkers.add(name)
                continue

            if at in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
                if not first_bet_seen:
                    first_bettor = name
                    first_bet_seen = True

                    # donk_bet: 非翻前 raiser 在翻后第一个下注
                    if street == Street.FLOP and name != preflop_raiser and preflop_raiser:
                        profile.advanced_actions.donk_bet_freq.update(True)

                    # probe_bet: 翻前 raiser 在上一街 check through 后，本街第一个下注
                    if street in (Street.TURN, Street.RIVER):
                        prev_street = Street.FLOP if street == Street.TURN else Street.TURN
                        prev_actions = gs.action_history.get(prev_street, [])
                        raiser_checked_prev = any(
                            pa.player_name == preflop_raiser and pa.action_type == ActionType.CHECK
                            for pa in prev_actions
                        ) if preflop_raiser else False
                        if raiser_checked_prev and name != preflop_raiser:
                            profile.advanced_actions.probe_bet_freq.update(True)

                elif name in checkers:
                    # check-raise
                    profile.advanced_actions.check_raise_freq.update(True)

                # raise_cbet: 面对 cbet 时 raise
                if (street == Street.FLOP and first_bettor == preflop_raiser
                        and name != preflop_raiser
                        and at in (ActionType.RAISE, ActionType.ALL_IN)):
                    profile.advanced_actions.raise_cbet_freq.update(True)

            elif at == ActionType.CALL:
                # 有机会 check-raise 但没有（先 check 后 call）
                if name in checkers and first_bet_seen:
                    profile.advanced_actions.check_raise_freq.update(False)
                # 面对 cbet 没有 raise
                if (street == Street.FLOP and first_bettor == preflop_raiser
                        and name != preflop_raiser):
                    profile.advanced_actions.raise_cbet_freq.update(False)

        # --- StreetTendencies: 各街激进度 ---
        for a in actions:
            if a.player_name == hero_name:
                continue
            if a.player_name not in advisor.profiles:
                continue
            profile = advisor.profiles[a.player_name]
            tendencies = profile.street_tendencies
            is_aggressive = a.action_type in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN)
            is_passive = a.action_type in (ActionType.CALL, ActionType.CHECK)

            if street == Street.FLOP:
                if is_aggressive:
                    tendencies.flop_aggression.update(True)
                elif is_passive:
                    tendencies.flop_aggression.update(False)
            elif street == Street.TURN:
                if is_aggressive:
                    tendencies.turn_aggression.update(True)
                elif is_passive:
                    tendencies.turn_aggression.update(False)
                # gives_up_turn: 翻牌下注但转牌放弃
                if a.player_name == first_bettor:
                    pass  # first_bettor 是本街的，需要看上一街
                flop_actions = gs.action_history.get(Street.FLOP, [])
                bet_on_flop = any(
                    fa.player_name == a.player_name
                    and fa.action_type in (ActionType.BET, ActionType.RAISE)
                    for fa in flop_actions
                )
                if bet_on_flop:
                    if a.action_type in (ActionType.CHECK, ActionType.FOLD):
                        tendencies.gives_up_turn.update(True)
                    elif is_aggressive:
                        tendencies.gives_up_turn.update(False)
                        tendencies.double_barrel_freq.update(True)
            elif street == Street.RIVER:
                if is_aggressive:
                    tendencies.river_aggression.update(True)
                elif is_passive:
                    tendencies.river_aggression.update(False)
                # triple_barrel: turn 下注且 river 继续
                turn_actions = gs.action_history.get(Street.TURN, [])
                bet_on_turn = any(
                    ta.player_name == a.player_name
                    and ta.action_type in (ActionType.BET, ActionType.RAISE)
                    for ta in turn_actions
                )
                if bet_on_turn and is_aggressive:
                    tendencies.triple_barrel_freq.update(True)
                elif bet_on_turn and a.action_type in (ActionType.CHECK, ActionType.FOLD):
                    tendencies.triple_barrel_freq.update(False)


def _analyze_action_rationality(gs: GameState, hero_name: str, advisor: Advisor) -> None:
    """在showdown后，对有底牌信息的对手进行行动合理性分析。"""
    analyzer = ActionRationalityAnalyzer()
    pot_sizes = _estimate_pot_sizes(gs)

    for player in gs.players:
        if player.name == hero_name:
            continue
        if not player.hole_cards:
            continue
        if player.name not in advisor.profiles:
            continue

        profile = advisor.profiles[player.name]
        num_active = len([p for p in gs.players if p.is_active or p.is_all_in])
        flop_pot = pot_sizes.get(Street.FLOP, gs.big_blind * 2)
        eff_stack = player.initial_stack - player.current_bet if hasattr(player, 'initial_stack') else player.stack
        spr = eff_stack / flop_pot if flop_pot > 0 else 6.0

        judgments = analyzer.analyze_player_hand(
            player_name=player.name,
            hole_cards=player.hole_cards,
            board=gs.board,
            action_history=gs.action_history,
            pot_sizes=pot_sizes,
            player_position=player.position,
            num_players=num_active,
            spr=spr,
        )

        if judgments:
            analyzer.update_profile_from_judgments(
                profile, judgments, hand_id=gs.hand_number
            )


def _estimate_pot_sizes(gs: GameState) -> dict[Street, int]:
    """根据action_history估算每条街开始时的底池大小。

    amount字段是"总下注到"的金额，需要跟踪每个玩家在该街的已投入来计算增量。
    """
    pot = 0
    sizes: dict[Street, int] = {}
    for street in (Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER):
        sizes[street] = pot
        player_invested: dict[str, int] = {}
        for action in gs.action_history.get(street, []):
            if action.amount > 0:
                prev = player_invested.get(action.player_name, 0)
                increment = action.amount - prev
                pot += max(increment, 0)
                player_invested[action.player_name] = action.amount
    return sizes


def play_hand(gs: GameState, hero_name: str, advisor: Advisor | None = None,
              session_rec: SessionRecorder | None = None) -> None:
    _reset_advisor_hand(advisor)
    hand_rec = HandRecorder()
    display_table(gs, hero_name)
    deal_hole_cards(gs, hero_name)

    if not play_street(gs, hero_name, advisor, hand_rec):
        display_table(gs, hero_name)
        if _is_allin_runout_needed(gs):
            winnings = handle_allin_runout(gs, hero_name)
        else:
            display_showdown(gs)
            winnings = gs.settle()
            display_settlement(winnings)
        _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec)
        return

    display_table(gs, hero_name)

    streets = [Street.FLOP, Street.TURN, Street.RIVER]
    for street in streets:
        gs.advance_street()
        count = STREET_CARD_COUNT[street]
        board_cards = read_board_cards(gs, count)
        gs.board.extend(board_cards)
        hand_rec.record_board(street.name, gs.board[:])
        display_table(gs, hero_name)

        if not play_street(gs, hero_name, advisor, hand_rec):
            display_table(gs, hero_name)
            if _is_allin_runout_needed(gs):
                winnings = handle_allin_runout(gs, hero_name)
                _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec)
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
    _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec)


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


# ============ Sim Mode ============

_SIM_AI_OPPONENTS: dict[str, "AIOpponent"] = {}
_SIM_MODE_ACTIVE = False

STYLE_ALIASES = {
    "TAG": "紧凶TAG", "LAG": "松凶LAG", "Nit": "极紧Nit",
    "Fish": "跟注站", "Maniac": "疯子Maniac", "CallStation": "跟注站",
    "紧弱": "紧弱", "岩石": "岩石",
}


def _pick_style_interactive(player_name: str) -> str:
    """让用户为一个AI对手选择风格。"""
    from testing.simulation.label_presets import all_labels
    sim_labels = all_labels()
    console.print(f"\n  为 [bold]{player_name}[/bold] 选择风格:")
    for i, label in enumerate(sim_labels):
        console.print(f"    [{i+1}] {label}")
    console.print(f"    [R] 随机")
    while True:
        raw = input("    > ").strip().upper()
        if raw == "R":
            import random
            return random.choice(sim_labels)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(sim_labels):
                return sim_labels[idx]
        except ValueError:
            pass
        display_error("无效选择")


def quick_sim_session(num_ai_opponents: int = 5) -> tuple[GameState, str, dict[str, "AIOpponent"]]:
    """快速启动：默认5个随机风格AI对手。"""
    import random as _rng
    from testing.simulation.label_presets import get_preset, all_labels
    from testing.simulation.ai_opponent import AIOpponent

    labels = all_labels()
    hero_name = "Hero"
    players = [Player(name=hero_name, stack=1000)]
    ai_opponents: dict[str, AIOpponent] = {}

    for i in range(num_ai_opponents):
        name = f"AI_{i+1}"
        label = _rng.choice(labels)
        ai_opponents[name] = AIOpponent(get_preset(label))
        players.append(Player(name=name, stack=1000))
        prior_key = STYLE_ALIASES.get(label, "未知")
        display_message(f"  {name}: {label} (先验={prior_key})", style="dim")

    gs = GameState(players=players, small_blind=5, big_blind=10, game_mode=GameMode.SIM)
    gs.assign_positions()
    return gs, hero_name, ai_opponents


def setup_sim_session() -> tuple[GameState, str, dict[str, "AIOpponent"]]:
    """交互式设置模拟对战。"""
    from testing.simulation.label_presets import get_preset
    from testing.simulation.ai_opponent import AIOpponent

    console.print("\n[bold yellow]═══ AI对战模式 ═══[/bold yellow]\n")

    num_opp = IntPrompt.ask("AI对手数量", default=5, choices=[str(i) for i in range(1, 9)])
    stack = IntPrompt.ask("初始筹码", default=1000)
    bb = IntPrompt.ask("大盲注", default=10)
    sb = bb // 2

    hero_name = Prompt.ask("你的名称", default="Hero")
    players = [Player(name=hero_name, stack=stack)]
    ai_opponents: dict[str, AIOpponent] = {}

    for i in range(num_opp):
        name = f"AI_{i+1}"
        label = _pick_style_interactive(name)
        config = get_preset(label)
        ai_opponents[name] = AIOpponent(config)
        players.append(Player(name=name, stack=stack))
        prior_key = STYLE_ALIASES.get(label, "未知")
        console.print(f"    → {name}: {label} (先验={prior_key})", style="dim")

    gs = GameState(players=players, small_blind=sb, big_blind=bb, game_mode=GameMode.SIM)
    gs.assign_positions()
    return gs, hero_name, ai_opponents


def sim_deal_hole_cards(gs: GameState, hero_name: str) -> None:
    """Sim模式发牌：hero与AI都自动随机。

    AI底牌不加入gs.used_cards，避免advisor的equity计算排除这些牌（信息泄露）。
    用gs._sim_all_dealt追踪所有已发牌防重复。
    """
    gs._sim_all_dealt = set(gs.used_cards)
    for p in gs.players:
        if p.name == hero_name:
            p.hole_cards = random_cards(2, gs._sim_all_dealt)
            display_hero_cards(p.hole_cards)
            gs._sim_all_dealt.update(p.hole_cards)
        else:
            p.hole_cards = random_cards(2, gs._sim_all_dealt)
            gs._sim_all_dealt.update(p.hole_cards)


def sim_play_street(
    gs: GameState, hero_name: str, advisor: Advisor | None,
    ai_opponents: dict[str, "AIOpponent"],
    hand_rec: HandRecorder | None = None,
) -> bool:
    """Sim模式下的一条街：AI自动行动，hero手动。"""
    action_order = gs.get_action_order()
    if len(action_order) <= 1 and gs.street != Street.PREFLOP:
        return len(gs.players_in_hand) > 1

    action_count = 0
    max_actions = max(24, len(gs.players) * MAX_ACTIONS_PER_STREET_FACTOR)
    while not gs.is_street_over():
        progress_made = False
        for player in gs.get_action_order():
            if player.has_acted:
                continue
            if not player.is_active or player.is_all_in:
                continue

            advice = None
            if player.name == hero_name:
                if advisor and player.hole_cards:
                    try:
                        advice = advisor.get_advice(gs, player)
                        console.print(f"\n[bold cyan]{'─' * 40}[/bold cyan]")
                        console.print(f"[bold cyan]{advice['text']}[/bold cyan]")
                        console.print(f"[bold cyan]{'─' * 40}[/bold cyan]")
                    except Exception:
                        pass
                action = read_player_action(player, gs, advice)
            elif player.name in ai_opponents:
                ai = ai_opponents[player.name]
                action_type, amount = ai.decide(gs, player)
                action = PlayerAction(
                    player_name=player.name,
                    action_type=action_type,
                    amount=amount,
                )
            else:
                action = PlayerAction(player.name, ActionType.FOLD)

            gs.apply_action(action)
            progress_made = True
            action_count += 1
            display_message(f"  {action}", style="dim")

            if hand_rec:
                hand_rec.record_action(
                    gs.street, player.name, action,
                    advisor_text=advice["text"] if advice else None,
                    advisor_data=advice if advice else None,
                )

            if gs.is_hand_over():
                return False
            if gs.is_street_over():
                break

            if action_count >= max_actions:
                raise RuntimeError(
                    f"Street {gs.street.name} exceeded {max_actions} actions; "
                    "aborting to avoid an infinite loop"
                )

        if not progress_made:
            raise RuntimeError(
                f"Street {gs.street.name} made no progress; aborting to avoid an infinite loop"
            )

    return len(gs.players_in_hand) > 1


def sim_handle_allin_runout(gs: GameState, hero_name: str) -> dict[str, int]:
    """Sim模式的allin runout，用_sim_all_dealt防牌冲突。"""
    remaining = _remaining_board_count(gs)
    if remaining <= 0:
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
        return winnings

    dealt_set = getattr(gs, "_sim_all_dealt", gs.used_cards)
    board_cards = random_cards(remaining, dealt_set)
    dealt_set.update(board_cards)
    gs.used_cards.update(board_cards)

    dealt = len(gs.board)
    if dealt < 3:
        gs.advance_street()
        take = 3 - dealt
        gs.board.extend(board_cards[:take])
        board_cards = board_cards[take:]
        dealt = 3
    if dealt < 4 and board_cards:
        gs.advance_street()
        gs.board.append(board_cards[0])
        board_cards = board_cards[1:]
        dealt = 4
    if dealt < 5 and board_cards:
        gs.advance_street()
        gs.board.append(board_cards[0])

    display_table(gs, hero_name)
    display_showdown(gs)
    winnings = gs.settle()
    display_settlement(winnings)
    return winnings


def sim_play_hand(
    gs: GameState, hero_name: str, advisor: Advisor | None,
    ai_opponents: dict[str, "AIOpponent"],
    session_rec: SessionRecorder | None = None,
) -> None:
    """Sim模式的一手牌完整流程。"""
    _reset_advisor_hand(advisor)
    hand_rec = HandRecorder()
    display_table(gs, hero_name)
    sim_deal_hole_cards(gs, hero_name)

    if not sim_play_street(gs, hero_name, advisor, ai_opponents, hand_rec):
        display_table(gs, hero_name)
        if _is_allin_runout_needed(gs):
            winnings = sim_handle_allin_runout(gs, hero_name)
        else:
            display_showdown(gs)
            winnings = gs.settle()
            display_settlement(winnings)
        _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)
        return

    display_table(gs, hero_name)

    streets = [Street.FLOP, Street.TURN, Street.RIVER]
    for street in streets:
        gs.advance_street()
        count = STREET_CARD_COUNT[street]
        board_cards = random_cards(count, gs._sim_all_dealt)
        gs._sim_all_dealt.update(board_cards)
        gs.used_cards.update(board_cards)
        gs.board.extend(board_cards)
        hand_rec.record_board(street.name, gs.board[:])
        board_str = " ".join(card_to_short(c) for c in board_cards)
        display_message(f"  {street.name}: {board_str}", style="bold")
        display_table(gs, hero_name)

        if not sim_play_street(gs, hero_name, advisor, ai_opponents, hand_rec):
            display_table(gs, hero_name)
            if _is_allin_runout_needed(gs):
                winnings = sim_handle_allin_runout(gs, hero_name)
                _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)
                return
            break

        display_table(gs, hero_name)

        if gs.is_hand_over():
            break

    if _is_allin_runout_needed(gs):
        winnings = sim_handle_allin_runout(gs, hero_name)
    else:
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
    _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)


def run_sim_mode(skip_setup: bool = False) -> None:
    """AI对战模式主循环。"""
    from testing.simulation.learning_convergence import LearningConvergenceTracker

    if skip_setup:
        gs, hero_name, ai_opponents = quick_sim_session()
    else:
        gs, hero_name, ai_opponents = setup_sim_session()

    advisor = Advisor()
    profiles = {}
    for p in gs.players:
        if p.name != hero_name:
            ai = ai_opponents.get(p.name)
            prior_key = STYLE_ALIASES.get(ai.config.label, "未知") if ai else "未知"
            profiles[p.name] = create_profile(p.name, prior_key)
    advisor.set_profiles(profiles)

    convergence_tracker = LearningConvergenceTracker()
    for name, ai in ai_opponents.items():
        convergence_tracker.register(name, ai.config)

    display_message(f"\n对战开始! (AI对战模式 + AI顾问) 按 Ctrl+C 随时退出\n", style="bold green")

    gs.hand_number = 1
    gs.post_blinds()

    session_rec = SessionRecorder(
        num_players=len(gs.players),
        small_blind=gs.small_blind,
        big_blind=gs.big_blind,
        player_names=[p.name for p in gs.players],
    )

    try:
        while True:
            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            sim_play_hand(gs, hero_name, advisor, ai_opponents, session_rec)

            if gs.hand_number % 5 == 0:
                convergence_tracker.record(gs.hand_number, advisor.profiles)

            for p in list(gs.players):
                if p.stack <= 0 and p.name != hero_name:
                    gs.players.remove(p)
                    ai_opponents.pop(p.name, None)
                    display_message(f"{p.name} 筹码归零，离场", style="dim")
            if hero_name in [p.name for p in gs.players if p.stack <= 0]:
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

    display_message("\n" + convergence_tracker.summary_report())

    if session_rec and session_rec.session_dir:
        import json as _json
        conv_path = session_rec.session_dir / "convergence_data.json"
        with open(conv_path, "w", encoding="utf-8") as f:
            _json.dump(convergence_tracker.to_json(), f, indent=2, ensure_ascii=False)

        analysis_path = session_rec.session_dir / "convergence_analysis.txt"
        with open(analysis_path, "w", encoding="utf-8") as f:
            f.write(convergence_tracker.detailed_report(advisor.profiles))
        display_message(f"  收敛分析报告: {analysis_path}", style="dim")

    _generate_end_charts(session_rec)


def sim_auto_deal_hole_cards(gs: GameState) -> None:
    gs._sim_all_dealt = set(gs.used_cards)
    for p in gs.players:
        p.hole_cards = random_cards(2, gs._sim_all_dealt)
        gs._sim_all_dealt.update(p.hole_cards)


def sim_auto_play_street(
    gs: GameState, hero_name: str, advisor: Advisor | None,
    ai_opponents: dict[str, "AIOpponent"],
    hand_rec: HandRecorder | None = None,
) -> bool:
    action_order = gs.get_action_order()
    if len(action_order) <= 1 and gs.street != Street.PREFLOP:
        return len(gs.players_in_hand) > 1

    action_count = 0
    max_actions = max(24, len(gs.players) * MAX_ACTIONS_PER_STREET_FACTOR)
    while not gs.is_street_over():
        progress_made = False
        for player in gs.get_action_order():
            if player.has_acted:
                continue
            if not player.is_active or player.is_all_in:
                continue

            advice = None
            if player.name == hero_name:
                if advisor and player.hole_cards:
                    try:
                        advice = advisor.get_advice(gs, player)
                    except Exception:
                        pass
                if advice:
                    action = _advice_to_action(player, gs, advice)
                else:
                    action = PlayerAction(player.name, ActionType.CHECK
                                          if gs.current_bet == player.current_bet
                                          else ActionType.CALL,
                                          amount=gs.current_bet)
            elif player.name in ai_opponents:
                ai = ai_opponents[player.name]
                action_type, amount = ai.decide(gs, player)
                action = PlayerAction(
                    player_name=player.name,
                    action_type=action_type,
                    amount=amount,
                )
            else:
                action = PlayerAction(player.name, ActionType.FOLD)

            gs.apply_action(action)
            progress_made = True
            action_count += 1
            display_message(f"  {action}", style="dim")

            if hand_rec:
                hand_rec.record_action(
                    gs.street, player.name, action,
                    advisor_text=advice["text"] if advice else None,
                    advisor_data=advice if advice else None,
                )

            if gs.is_hand_over():
                return False
            if gs.is_street_over():
                break

            if action_count >= max_actions:
                raise RuntimeError(
                    f"Street {gs.street.name} exceeded {max_actions} actions; "
                    "aborting to avoid an infinite loop"
                )

        if not progress_made:
            raise RuntimeError(
                f"Street {gs.street.name} made no progress; aborting to avoid an infinite loop"
            )

    return len(gs.players_in_hand) > 1


def sim_auto_play_hand(
    gs: GameState, hero_name: str, advisor: Advisor | None,
    ai_opponents: dict[str, "AIOpponent"],
    session_rec: SessionRecorder | None = None,
) -> None:
    _reset_advisor_hand(advisor)
    hand_rec = HandRecorder()
    display_table(gs, hero_name)
    sim_auto_deal_hole_cards(gs)
    display_hero_cards(next(p for p in gs.players if p.name == hero_name).hole_cards)

    if not sim_auto_play_street(gs, hero_name, advisor, ai_opponents, hand_rec):
        display_table(gs, hero_name)
        if _is_allin_runout_needed(gs):
            winnings = sim_handle_allin_runout(gs, hero_name)
        else:
            display_showdown(gs)
            winnings = gs.settle()
            display_settlement(winnings)
        _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)
        return

    display_table(gs, hero_name)

    streets = [Street.FLOP, Street.TURN, Street.RIVER]
    for street in streets:
        gs.advance_street()
        count = STREET_CARD_COUNT[street]
        board_cards = random_cards(count, gs._sim_all_dealt)
        gs._sim_all_dealt.update(board_cards)
        gs.used_cards.update(board_cards)
        gs.board.extend(board_cards)
        hand_rec.record_board(street.name, gs.board[:])
        board_str = " ".join(card_to_short(c) for c in board_cards)
        display_message(f"  {street.name}: {board_str}", style="bold")
        display_table(gs, hero_name)

        if not sim_auto_play_street(gs, hero_name, advisor, ai_opponents, hand_rec):
            display_table(gs, hero_name)
            if _is_allin_runout_needed(gs):
                winnings = sim_handle_allin_runout(gs, hero_name)
                _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)
                return
            break

        display_table(gs, hero_name)

        if gs.is_hand_over():
            break

    if _is_allin_runout_needed(gs):
        winnings = sim_handle_allin_runout(gs, hero_name)
    else:
        display_showdown(gs)
        winnings = gs.settle()
        display_settlement(winnings)
    _finish_hand(gs, winnings, hero_name, advisor, session_rec, hand_rec, ai_opponents)


def run_sim_auto_mode(max_hands: int = 60, num_ai_opponents: int = 5) -> None:
    gs, hero_name, ai_opponents = quick_sim_session(num_ai_opponents=num_ai_opponents)

    advisor = Advisor()
    profiles = {}
    for p in gs.players:
        if p.name != hero_name:
            ai = ai_opponents.get(p.name)
            prior_key = STYLE_ALIASES.get(ai.config.label, "未知") if ai else "未知"
            profiles[p.name] = create_profile(p.name, prior_key)
    advisor.set_profiles(profiles)

    from testing.simulation.learning_convergence import LearningConvergenceTracker
    convergence_tracker = LearningConvergenceTracker()
    for name, ai in ai_opponents.items():
        convergence_tracker.register(name, ai.config)

    from testing.simulation.hand_analysis_common import HandSummary
    from testing.simulation.catastrophic_hands import CatastrophicHandTracker
    from testing.simulation.bleed_pattern import BleedPatternTracker
    from testing.simulation.equity_trajectory import EquityTrajectoryTracker
    from testing.simulation.positional_leak import PositionalLeakTracker
    from testing.simulation.exploit_effectiveness import ExploitEffectivenessTracker
    from testing.simulation.decision_quality import DecisionQualityTracker

    analysis_trackers = [
        CatastrophicHandTracker(big_blind=gs.big_blind),
        BleedPatternTracker(big_blind=gs.big_blind),
        EquityTrajectoryTracker(big_blind=gs.big_blind),
        PositionalLeakTracker(big_blind=gs.big_blind),
        ExploitEffectivenessTracker(big_blind=gs.big_blind),
        DecisionQualityTracker(big_blind=gs.big_blind),
    ]

    display_message(
        f"\n全自动模拟开始! 共 {max_hands} 手 按 Ctrl+C 提前终止\n",
        style="bold green",
    )

    gs.hand_number = 1
    gs.post_blinds()

    session_rec = SessionRecorder(
        num_players=len(gs.players),
        small_blind=gs.small_blind,
        big_blind=gs.big_blind,
        player_names=[p.name for p in gs.players],
    )

    try:
        for hand_idx in range(max_hands):
            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            display_message(
                f"\n{'═' * 20} 第 {hand_idx + 1}/{max_hands} 手 {'═' * 20}",
                style="bold yellow",
            )

            sim_auto_play_hand(gs, hero_name, advisor, ai_opponents, session_rec)

            # Feed hand data to analysis trackers
            if session_rec and session_rec.session_dir:
                hand_path = session_rec.session_dir / f"hand_{gs.hand_number:03d}.json"
                if hand_path.exists():
                    hand_summary = HandSummary.from_json(hand_path)
                    for tracker in analysis_trackers:
                        tracker.record(hand_summary)

            if gs.hand_number % 5 == 0:
                convergence_tracker.record(gs.hand_number, advisor.profiles)

            for p in list(gs.players):
                if p.stack <= 0 and p.name != hero_name:
                    gs.players.remove(p)
                    ai_opponents.pop(p.name, None)
                    display_message(f"{p.name} 筹码归零，离场", style="dim")

            if hero_name in [p.name for p in gs.players if p.stack <= 0]:
                display_message("Hero 筹码归零，模拟结束", style="bold red")
                break

            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            gs.new_hand()

    except KeyboardInterrupt:
        display_message("\n\n模拟提前终止!", style="bold yellow")

    display_message(f"\n模拟完成 (共 {gs.hand_number} 手)", style="bold")
    display_message("最终筹码:", style="bold")
    for p in gs.players:
        display_message(f"  {p.name}: {p.stack}")

    display_message("\n" + convergence_tracker.summary_report())

    if session_rec and session_rec.session_dir:
        import json as _json
        analysis_dir = session_rec.session_dir / "analysis"
        analysis_dir.mkdir(exist_ok=True)

        conv_path = analysis_dir / "convergence_data.json"
        with open(conv_path, "w", encoding="utf-8") as f:
            _json.dump(convergence_tracker.to_json(), f, indent=2, ensure_ascii=False)

        analysis_path = analysis_dir / "convergence_analysis.txt"
        with open(analysis_path, "w", encoding="utf-8") as f:
            f.write(convergence_tracker.detailed_report(advisor.profiles))
        display_message(f"  收敛分析报告: {analysis_path}", style="dim")

        for tracker in analysis_trackers:
            tracker.write_outputs(analysis_dir)
        display_message(f"  策略分析报告已生成 → analysis/ ({len(analysis_trackers)}个模块)", style="dim")

    _generate_end_charts(session_rec)


def _generate_end_charts(session_rec: SessionRecorder | None) -> None:
    pass


@click.command()
@click.option("--skip-setup", is_flag=True, help="跳过设置，使用默认6人桌")
@click.option("--test", is_flag=True, help="测试模式：所有玩家手牌可见")
@click.option("--no-advisor", is_flag=True, help="禁用AI顾问")
@click.option("--sim", is_flag=True, help="AI对战模式：与AI对手对战")
@click.option("--sim-auto", is_flag=True, help="全自动模拟：无需任何输入，批量生成数据")
@click.option("--sim-auto-solo", is_flag=True, help="全自动1v1模拟：Hero 对 1 个随机AI")
@click.option("--max-hands", type=int, default=60, help="全自动模式最大手数 (默认60)")
def main(skip_setup: bool, test: bool, no_advisor: bool, sim: bool,
         sim_auto: bool, sim_auto_solo: bool, max_hands: int) -> None:
    if sim_auto_solo:
        run_sim_auto_mode(max_hands, num_ai_opponents=1)
        return
    if sim_auto:
        run_sim_auto_mode(max_hands)
        return
    if sim:
        run_sim_mode(skip_setup)
        return

    mode = GameMode.TEST if test else GameMode.LIVE
    if skip_setup:
        players = [Player(name=n, stack=1000) for n in ["hero", "P2", "P3", "P4", "P5", "P6"]]
        gs = GameState(players=players, game_mode=mode)
        hero_name = "hero"
        gs.assign_positions()
    else:
        gs, hero_name = setup_session(mode)

    advisor = None
    if not no_advisor:
        advisor = Advisor()
        profiles = {}
        for p in gs.players:
            if p.name != hero_name:
                existing = load_or_create(p.name)
                if existing.total_hands == 0 and existing.prior_type == "未知":
                    prior = _ask_prior_type(p.name)
                    if prior != "未知":
                        existing = create_profile(p.name, prior)
                profiles[p.name] = existing
        advisor.set_profiles(profiles)

    mode_label = "测试模式" if mode == GameMode.TEST else "实战模式"
    advisor_label = " + AI顾问" if advisor else ""
    display_message(f"\n游戏开始! ({mode_label}{advisor_label}) 按 Ctrl+C 随时退出\n", style="bold green")

    gs.hand_number = 1
    gs.post_blinds()

    session_rec = SessionRecorder(
        num_players=len(gs.players),
        small_blind=gs.small_blind,
        big_blind=gs.big_blind,
        player_names=[p.name for p in gs.players],
    )

    try:
        while True:
            if len(gs.players) < 2:
                display_message("玩家不足，游戏结束", style="bold red")
                break

            play_hand(gs, hero_name, advisor, session_rec)
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

    _generate_end_charts(session_rec)


if __name__ == "__main__":
    main()
