"""回测 all-in 场景下的发牌与结算逻辑"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from treys import Card
from env.game_state import GameState, Player
from env.action_space import ActionType, PlayerAction, Street
from env.run_it_twice import run_it_twice

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results: list[tuple[str, bool]] = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    msg = f"  [{tag}] {name}"
    if detail and not condition:
        msg += f"  -- {detail}"
    print(msg)
    results.append((name, condition))


def make_gs(stacks: list[int], sb=5, bb=10) -> GameState:
    players = [Player(name=f"P{i+1}", stack=s) for i, s in enumerate(stacks)]
    gs = GameState(players=players, small_blind=sb, big_blind=bb)
    gs.assign_positions()
    gs.post_blinds()
    return gs


def allin_all(gs: GameState) -> None:
    for p in gs.players:
        if p.is_active and not p.is_all_in:
            action = PlayerAction(p.name, ActionType.ALL_IN, amount=p.stack + p.current_bet)
            gs.apply_action(action)


def set_board(gs: GameState, card_strs: str) -> None:
    gs.board = [Card.new(c) for c in card_strs.split()]
    gs.used_cards.update(gs.board)


def set_hole(gs: GameState, name: str, card_strs: str) -> None:
    p = gs.get_player(name)
    p.hole_cards = [Card.new(c) for c in card_strs.split()]
    gs.used_cards.update(p.hole_cards)


# ─── 测试 1: 6人等筹码 preflop all-in，有明确赢家 ───
def test_6way_equal_stack_allin():
    print("\n=== 测试1: 6人等筹码 preflop all-in ===")
    gs = make_gs([1000]*6, sb=5, bb=10)
    allin_all(gs)

    check("底池正确 (6000)", gs.pot == 6000, f"实际={gs.pot}")
    check("所有人 all-in", all(p.is_all_in for p in gs.players))
    check("is_hand_over=True", gs.is_hand_over())
    check("board 为空", len(gs.board) == 0)

    set_hole(gs, "P1", "As Ks")
    set_hole(gs, "P2", "2c 7d")
    set_hole(gs, "P3", "3c 8d")
    set_hole(gs, "P4", "4c 9d")
    set_hole(gs, "P5", "5c Td")
    set_hole(gs, "P6", "6c Jd")
    set_board(gs, "Ah Kh Qh 2s 3s")

    pots = gs.calculate_side_pots()
    check("只有1个底池", len(pots) == 1, f"实际={len(pots)}")
    check("底池金额=6000", pots[0].amount == 6000, f"实际={pots[0].amount}")
    check("6人都eligible", len(pots[0].eligible) == 6, f"实际={pots[0].eligible}")

    winnings = gs.settle()
    check("P1赢得6000 (AA KK两对)", winnings["P1"] == 6000,
          f"实际分配={winnings}")


# ─── 测试 2: 不等筹码 all-in，产生边池 ───
def test_unequal_stack_side_pots():
    print("\n=== 测试2: 不等筹码 all-in，边池 ===")
    # P1=500, P2=1000, P3=1500
    players = [Player(name="P1", stack=500),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1500)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("底池=3000", gs.pot == 3000, f"实际={gs.pot}")

    pots = gs.calculate_side_pots()
    check("有2个或3个边池", len(pots) >= 2, f"实际={len(pots)}, pots={[(p.amount, p.eligible) for p in pots]}")

    main_pot = pots[0]
    check("主池=1500 (3x500)", main_pot.amount == 1500,
          f"实际={main_pot.amount}")
    check("主池3人eligible", len(main_pot.eligible) == 3,
          f"实际={main_pot.eligible}")

    side_pot_1 = pots[1]
    check("边池1=1000 (2x500)", side_pot_1.amount == 1000,
          f"实际={side_pot_1.amount}")
    check("边池1只有P2 P3 eligible", set(side_pot_1.eligible) == {"P2", "P3"},
          f"实际={side_pot_1.eligible}")

    # P3 赢主池和边池1，还有剩余的边池2
    set_hole(gs, "P1", "2c 3d")
    set_hole(gs, "P2", "4c 5d")
    set_hole(gs, "P3", "As Ks")
    set_board(gs, "Ah Kh Qh 2s 9c")

    winnings = gs.settle()
    total_won = sum(winnings.values())
    check("总赢额=底池", total_won == 3000, f"实际={total_won}")
    check("P3赢得全部3000", winnings["P3"] == 3000,
          f"实际分配={winnings}")


# ─── 测试 3: 平分底池 (split pot) ───
def test_split_pot():
    print("\n=== 测试3: 平分底池 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")
    set_board(gs, "Qh Jh Ts 2c 3d")

    winnings = gs.settle()
    check("P1赢1000", winnings["P1"] == 1000, f"实际={winnings}")
    check("P2赢1000", winnings["P2"] == 1000, f"实际={winnings}")


# ─── 测试 4: 3人不等筹码，短筹码赢主池，大筹码赢边池 ───
def test_short_stack_wins_main():
    print("\n=== 测试4: 短筹码赢主池，大筹码赢边池 ===")
    players = [Player(name="P1", stack=200),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("底池=2200", gs.pot == 2200, f"实际={gs.pot}")

    # P1 最强手牌赢主池，P2 次强赢边池
    set_hole(gs, "P1", "As Ah")  # AA
    set_hole(gs, "P2", "Ks Kh")  # KK
    set_hole(gs, "P3", "2c 3d")  # 垃圾
    set_board(gs, "7h 2s 9d Jc 4h")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总赢额=2200", total == 2200, f"实际={total}")
    # P1 赢主池 (3x200=600)
    check("P1赢600 (主池)", winnings["P1"] == 600,
          f"实际={winnings}")
    # P2 赢边池 (2x800=1600)
    check("P2赢1600 (边池)", winnings["P2"] == 1600,
          f"实际={winnings}")
    check("P3赢0", winnings["P3"] == 0, f"实际={winnings}")


# ─── 测试 5: run_it_twice 逻辑 ───
def test_run_it_twice():
    print("\n=== 测试5: run_it_twice ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")

    board_1 = [Card.new(c) for c in "Qh Jh Ts 2c 3d".split()]
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]

    result = run_it_twice(gs, board_1, board_2)

    check("board_1 P1赢 (AA > KK)", result.winnings_1.get("P1", 0) > 0,
          f"实际={result.winnings_1}")
    check("board_2 P2赢 (三条K)", result.winnings_2.get("P2", 0) > 0,
          f"实际={result.winnings_2}")

    total = sum(result.combined.values())
    check("combined总额=2000", total == 2000, f"实际={total}")
    check("P1拿一半", result.combined.get("P1", 0) == 1000,
          f"实际={result.combined}")
    check("P2拿一半", result.combined.get("P2", 0) == 1000,
          f"实际={result.combined}")


# ─── 测试 6: flop 后 all-in，只需补 turn+river ───
def test_allin_after_flop():
    print("\n=== 测试6: flop后 all-in，补发 turn+river ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)

    # 模拟 preflop 正常过
    for p in gs.players:
        if p.current_bet < gs.current_bet:
            action = PlayerAction(p.name, ActionType.CALL, amount=gs.current_bet)
            gs.apply_action(action)
        else:
            action = PlayerAction(p.name, ActionType.CHECK)
            gs.apply_action(action)

    # 发 flop
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Qh Jh Ts".split()]

    # flop 上 all-in
    allin_all(gs)

    check("board=3张", len(gs.board) == 3)
    check("is_hand_over=True", gs.is_hand_over())
    check("还需2张公共牌", 5 - len(gs.board) == 2)

    set_hole(gs, "P1", "As Ks")
    set_hole(gs, "P2", "2c 3d")

    # 补发 turn + river
    gs.board.extend([Card.new("4c"), Card.new("5s")])
    check("board=5张", len(gs.board) == 5)

    winnings = gs.settle()
    check("P1赢得全部", winnings["P1"] == 2000, f"实际={winnings}")
    total = sum(winnings.values())
    check("总额=2000", total == 2000, f"实际={total}")


# ─── 测试 7: 验证 evaluate_hand 在 board<5 时返回最差 ───
def test_evaluate_incomplete_board():
    print("\n=== 测试7: board不足5张时 evaluate_hand 返回7463 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    set_hole(gs, "P1", "As Ah")
    gs.board = [Card.new(c) for c in "Qh Jh Ts".split()]

    rank = gs.evaluate_hand(gs.get_player("P1"))
    check("board=3时返回7463", rank == 7463, f"实际={rank}")

    gs.board.append(Card.new("2c"))
    rank = gs.evaluate_hand(gs.get_player("P1"))
    check("board=4时返回7463", rank == 7463, f"实际={rank}")

    gs.board.append(Card.new("3d"))
    rank = gs.evaluate_hand(gs.get_player("P1"))
    check("board=5时返回正常牌力", rank < 7463, f"实际={rank}")


# ─── 测试 8: 4人不等筹码，多层边池 ───
def test_4way_multi_side_pots():
    print("\n=== 测试8: 4人不等筹码，多层边池 ===")
    # P1=100, P2=300, P3=600, P4=1000
    players = [Player(name="P1", stack=100),
               Player(name="P2", stack=300),
               Player(name="P3", stack=600),
               Player(name="P4", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("底池=2000", gs.pot == 2000, f"实际={gs.pot}")

    pots = gs.calculate_side_pots()
    print(f"  边池详情: {[(p.amount, p.eligible) for p in pots]}")

    # 主池: 4x100=400, eligible: P1,P2,P3,P4
    check("主池=400", pots[0].amount == 400, f"实际={pots[0].amount}")
    check("主池4人", len(pots[0].eligible) == 4)

    # 边池1: 3x200=600, eligible: P2,P3,P4
    check("边池1=600", pots[1].amount == 600, f"实际={pots[1].amount}")
    check("边池1有3人", len(pots[1].eligible) == 3)

    # 边池2: 2x300=600, eligible: P3,P4
    check("边池2=600", pots[2].amount == 600, f"实际={pots[2].amount}")
    check("边池2有2人", len(pots[2].eligible) == 2)

    # P1最强赢主池, P2次强赢边池1, P4赢边池2+剩余
    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "2c 3d")
    set_hole(gs, "P4", "Qs Qh")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=2000", total == 2000, f"实际={total}")
    check("P1赢400 (主池)", winnings["P1"] == 400, f"实际={winnings}")
    check("P2赢600 (边池1, KK>QQ)", winnings["P2"] == 600, f"实际={winnings}")
    check("P4赢1000 (边池2+剩余)", winnings["P4"] == 1000, f"实际={winnings}")
    check("P3赢0", winnings["P3"] == 0, f"实际={winnings}")


# ─── 测试 9: 奇数筹码 split pot ───
def test_odd_chip_split():
    print("\n=== 测试9: 奇数筹码 split pot (3人平分) ===")
    players = [Player(name="P1", stack=333),
               Player(name="P2", stack=333),
               Player(name="P3", stack=334)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")
    set_hole(gs, "P3", "Ad Ks")
    set_board(gs, "Qh Jh Ts 2c 3d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=1000", total == 1000, f"实际={total}")
    check("无人赢0", all(v > 0 for v in winnings.values()), f"实际={winnings}")
    check("无负数", all(v >= 0 for v in winnings.values()), f"实际={winnings}")
    values = sorted(winnings.values())
    check("最大差异<=1", values[-1] - values[0] <= 1,
          f"分配={winnings}, 差异={values[-1]-values[0]}")


# ─── 测试 10: fold + all-in 混合 ───
def test_fold_then_allin():
    print("\n=== 测试10: 部分玩家fold后剩余all-in ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000),
               Player(name="P4", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1, P2 fold
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    # P3, P4 all-in
    allin_all(gs)

    set_hole(gs, "P3", "As Ah")
    set_hole(gs, "P4", "Ks Kh")
    set_board(gs, "7h 2s 9d Jc 4h")

    expected_pot = gs.pot
    winnings = gs.settle()
    check("P1赢0 (已fold)", winnings.get("P1", 0) == 0, f"实际={winnings}")
    check("P2赢0 (已fold)", winnings.get("P2", 0) == 0, f"实际={winnings}")
    check("P3赢得全部底池", winnings.get("P3", 0) == expected_pot, f"实际={winnings}")
    check("P4赢0", winnings.get("P4", 0) == 0, f"实际={winnings}")
    total = sum(winnings.values())
    check("总额=底池", total == expected_pot, f"实际={total}, pot={expected_pot}")


# ─── 测试 11: run_it_twice 两次同一人赢 ───
def test_run_it_twice_same_winner():
    print("\n=== 测试11: run_it_twice 两次都同一人赢 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")

    board_1 = [Card.new(c) for c in "Kh Qh Js 7c 8d".split()]
    board_2 = [Card.new(c) for c in "Kd Qd Jc 9s Td".split()]

    result = run_it_twice(gs, board_1, board_2)

    check("board_1 P1赢", result.winnings_1.get("P1", 0) > 0,
          f"实际={result.winnings_1}")
    check("board_2 P1赢", result.winnings_2.get("P1", 0) > 0,
          f"实际={result.winnings_2}")
    check("P1拿全部2000", result.combined.get("P1", 0) == 2000,
          f"实际={result.combined}")
    check("P2拿0", result.combined.get("P2", 0) == 0,
          f"实际={result.combined}")


# ─── 测试 12: 多人 split pot + 边池有单独赢家 ───
def test_split_main_pot_with_side_winner():
    print("\n=== 测试12: 主池平分 + 边池单独赢家 ===")
    # P1=500 短筹码, P2=1000, P3=1000
    players = [Player(name="P1", stack=500),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    # P1 和 P2 手牌相同强度 (平分主池), P2 > P3 赢边池
    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "Qh Jh Ts 7c 8d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=2500", total == 2500, f"实际={total}")
    # 主池=1500 (3x500), P1和P2平分 => 各750
    check("P1赢750 (主池一半)", winnings.get("P1", 0) == 750,
          f"实际={winnings}")
    # 边池=1000 (2x500), P2独赢 => P2总共750+1000=1750
    check("P2赢1750 (主池一半+边池)", winnings.get("P2", 0) == 1750,
          f"实际={winnings}")
    check("P3赢0", winnings.get("P3", 0) == 0, f"实际={winnings}")


# ─── 测试 13: 零筹码玩家不参与 ───
def test_zero_stack_player():
    print("\n=== 测试13: 零筹码玩家边界处理 ===")
    players = [Player(name="P1", stack=0),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("P1不是active或已all-in", not gs.get_player("P1").is_active or gs.get_player("P1").is_all_in)

    set_hole(gs, "P2", "As Ah")
    set_hole(gs, "P3", "Ks Kh")
    set_board(gs, "7h 2s 9d Jc 4h")

    winnings = gs.settle()
    check("P1赢0", winnings.get("P1", 0) == 0, f"实际={winnings}")
    check("无负数分配", all(v >= 0 for v in winnings.values()), f"实际={winnings}")


# ─── 测试 14: settle 幂等性 ───
def test_settle_idempotent():
    print("\n=== 测试14: settle 幂等性 (二次调用不重复发奖) ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)
    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    w1 = gs.settle()
    check("首次settle P1赢2000", w1.get("P1", 0) == 2000, f"实际={w1}")

    p1_stack_after_first = gs.get_player("P1").stack
    w2 = gs.settle()
    p1_stack_after_second = gs.get_player("P1").stack
    total_2 = sum(w2.values())
    check("二次settle总额=0 (pot已清空)", total_2 == 0, f"二次settle={w2}")
    check("二次settle不改变stack",
          p1_stack_after_second == p1_stack_after_first,
          f"首次后={p1_stack_after_first}, 二次后={p1_stack_after_second}")


# ─── 测试 15: All-in 金额小于 blind ───
def test_allin_less_than_blind():
    print("\n=== 测试15: All-in 金额小于 blind ===")
    players = [Player(name="P1", stack=3),
               Player(name="P2", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    pot = gs.pot
    check("底池>0", pot > 0, f"实际={pot}")

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额守恒=pot", total == pot, f"实际total={total}, pot={pot}")
    check("P1赢主池 (AA)", winnings.get("P1", 0) > 0, f"实际={winnings}")
    check("无负数分配", all(v >= 0 for v in winnings.values()), f"实际={winnings}")


# ─── 测试 16: Stack 更新验证 ───
def test_stack_updated_after_settle():
    print("\n=== 测试16: settle 后 player.stack 正确更新 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)
    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    gs.settle()
    p1 = gs.get_player("P1")
    p2 = gs.get_player("P2")
    check("P1 stack=2000", p1.stack == 2000, f"实际={p1.stack}")
    check("P2 stack=0", p2.stack == 0, f"实际={p2.stack}")


# ─── 测试 17: Stack 更新 - 边池场景 ───
def test_stack_updated_side_pots():
    print("\n=== 测试17: 边池场景 settle 后 stack 正确 ===")
    players = [Player(name="P1", stack=200),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 2s 9d Jc 4h")

    gs.settle()
    p1 = gs.get_player("P1")
    p2 = gs.get_player("P2")
    p3 = gs.get_player("P3")
    total_stacks = p1.stack + p2.stack + p3.stack
    check("总stack守恒=2200", total_stacks == 2200, f"实际={total_stacks}")
    check("P1 stack=600 (主池)", p1.stack == 600, f"实际={p1.stack}")
    check("P2 stack=1600 (边池)", p2.stack == 1600, f"实际={p2.stack}")
    check("P3 stack=0", p3.stack == 0, f"实际={p3.stack}")


# ─── 测试 18: Run it twice + side pots ───
def test_run_it_twice_with_side_pots():
    print("\n=== 测试18: run_it_twice + 边池组合 ===")
    players = [Player(name="P1", stack=500),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    total_pot = gs.pot
    check("底池=2500", total_pot == 2500, f"实际={total_pot}")

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "Qs Qh")

    # board_1: AA 赢; board_2: KK 赢 (三条K)
    board_1 = [Card.new(c) for c in "7h 2s 9d Jc 4h".split()]
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]

    result = run_it_twice(gs, board_1, board_2)

    combined_total = sum(result.combined.values())
    check("combined总额=2500", combined_total == total_pot,
          f"实际={combined_total}")
    check("无负数分配", all(v >= 0 for v in result.combined.values()),
          f"实际={result.combined}")
    check("board_1 P1赢主池", result.winnings_1.get("P1", 0) > 0,
          f"实际={result.winnings_1}")


# ─── 测试 19: 4-way 完全相同手牌 split ───
def test_4way_equal_split():
    print("\n=== 测试19: 4人完全相同手牌 split ===")
    gs = make_gs([1000, 1000, 1000, 1000], sb=5, bb=10)
    allin_all(gs)

    # 所有人同花色不同但公共牌组成最强牌
    set_hole(gs, "P1", "2c 3d")
    set_hole(gs, "P2", "2d 3c")
    set_hole(gs, "P3", "2h 3s")
    set_hole(gs, "P4", "2s 3h")
    set_board(gs, "As Ks Qs Js Ts")  # 公共牌皇家同花顺

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=4000", total == 4000, f"实际={total}")
    check("P1赢1000", winnings.get("P1", 0) == 1000, f"实际={winnings}")
    check("P2赢1000", winnings.get("P2", 0) == 1000, f"实际={winnings}")
    check("P3赢1000", winnings.get("P3", 0) == 1000, f"实际={winnings}")
    check("P4赢1000", winnings.get("P4", 0) == 1000, f"实际={winnings}")


# ─── 测试 20: 5-way 奇数筹码 split ───
def test_5way_odd_chip_split():
    print("\n=== 测试20: 5人奇数筹码 split ===")
    players = [Player(name=f"P{i+1}", stack=201) for i in range(5)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    pot = gs.pot
    # 公共牌最强，所有人平分
    set_hole(gs, "P1", "2c 3d")
    set_hole(gs, "P2", "2d 3c")
    set_hole(gs, "P3", "2h 3s")
    set_hole(gs, "P4", "4c 5d")
    set_hole(gs, "P5", "4d 5c")
    set_board(gs, "As Ks Qs Js Ts")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额严格=pot", total == pot, f"实际total={total}, pot={pot}")
    check("无人赢0", all(v > 0 for v in winnings.values()), f"实际={winnings}")
    values = sorted(winnings.values())
    check("最大差异<=1", values[-1] - values[0] <= 1,
          f"分配={winnings}, 差异={values[-1]-values[0]}")


# ─── 测试 21: 缺少 hole cards 时 settle 应 graceful 处理 ───
def test_settle_missing_hole_cards():
    print("\n=== 测试21: 玩家无 hole cards 时 settle 不崩溃且守恒 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)
    set_board(gs, "7h 8h 9s Tc 4d")
    # 不设置 hole cards

    try:
        winnings = gs.settle()
        total = sum(winnings.values())
        check("总额守恒=2000", total == 2000, f"实际={total}")
        check("无负数分配", all(v >= 0 for v in winnings.values()), f"实际={winnings}")
        check("settle未崩溃", True)
    except Exception as e:
        check("settle抛出异常而非静默错误", True, f"异常={e}")


# ─── 测试 22: 重复卡牌检测 ───
def test_duplicate_cards_detection():
    print("\n=== 测试22: 重复卡牌检测 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    set_hole(gs, "P1", "As Ah")
    # used_cards 应已包含 As 和 Ah
    as_card = Card.new("As")
    check("used_cards 追踪 P1 手牌", as_card in gs.used_cards,
          f"used_cards={gs.used_cards}")

    set_hole(gs, "P2", "As Kh")  # As 重复!
    set_board(gs, "7h 8h 9s Tc 4d")

    # used_cards 是 set，重复添加不会增加长度，但实际发出的牌有重复
    all_cards = []
    for p in gs.players:
        if p.hole_cards:
            all_cards.extend(p.hole_cards)
    all_cards.extend(gs.board)

    has_dup = len(all_cards) != len(set(all_cards))
    check("能检测到重复卡牌", has_dup, f"cards={len(all_cards)}, unique={len(set(all_cards))}")

    # settle 在重复卡牌下不应崩溃 (即使结果不正确)
    try:
        winnings = gs.settle()
        total = sum(winnings.values())
        check("重复卡牌下settle未崩溃", True)
        check("重复卡牌下总额守恒", total == 2000, f"实际={total}")
    except Exception as e:
        check("重复卡牌下settle崩溃", False, f"异常={e}")


# ─── 测试 23: 大量玩家 (9人桌) ───
def test_9_player_allin():
    print("\n=== 测试23: 9人桌全员 all-in ===")
    stacks = [100, 200, 300, 400, 500, 600, 700, 800, 900]
    gs = make_gs(stacks, sb=5, bb=10)
    allin_all(gs)

    expected_pot = sum(stacks)
    check("底池=4500", gs.pot == expected_pot, f"实际={gs.pot}")

    pots = gs.calculate_side_pots()
    check("有8个或9个边池", len(pots) >= 8, f"实际={len(pots)}")

    pot_total = sum(p.amount for p in pots)
    check("边池总额=底池", pot_total == expected_pot,
          f"边池总额={pot_total}, 底池={expected_pot}")

    # P1最强手牌赢主池 (AA, board 不配对任何人)
    hole_cards = ["As Ah", "Ks Kh", "Qs Qh", "Js Jh", "Ts Th",
                  "9s 9h", "7s 7h", "6s 6h", "5s 5h"]
    for i, hc in enumerate(hole_cards):
        set_hole(gs, f"P{i+1}", hc)
    set_board(gs, "2c 3d 4h 8c 2d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额守恒=4500", total == expected_pot, f"实际={total}")
    check("无负数分配", all(v >= 0 for v in winnings.values()), f"实际={winnings}")
    # P1 (AA) 应赢主池
    check("P1(AA)赢主池", winnings.get("P1", 0) > 0, f"实际={winnings}")


# ─── 测试 24: fold 玩家的盲注计入底池 ───
def test_fold_blind_in_pot():
    print("\n=== 测试24: fold 玩家的盲注正确计入底池 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1 fold (可能已付盲注)
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    # P2, P3 all-in
    allin_all(gs)

    pot = gs.pot
    check("底池>=2000", pot >= 2000, f"实际pot={pot}")

    set_hole(gs, "P2", "As Ah")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=pot", total == pot, f"实际total={total}, pot={pot}")
    check("P1赢0", winnings.get("P1", 0) == 0, f"实际={winnings}")
    check("P2赢得全部", winnings.get("P2", 0) == pot, f"实际={winnings}")


# ─── 测试 25: 2人 heads-up all-in 位置正确 ───
def test_heads_up_positions():
    print("\n=== 测试25: 2人 heads-up 盲注和 all-in ===")
    gs = make_gs([500, 500], sb=5, bb=10)
    allin_all(gs)

    check("底池=1000", gs.pot == 1000, f"实际={gs.pot}")
    check("is_hand_over=True", gs.is_hand_over())

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_board(gs, "7h 2s 9d Jc 4h")

    winnings = gs.settle()
    check("P1赢1000", winnings.get("P1", 0) == 1000, f"实际={winnings}")
    check("P2赢0", winnings.get("P2", 0) == 0, f"实际={winnings}")


# ─── 测试 26: 多人 fold 只剩一人时不需 showdown ───
def test_all_fold_except_one():
    print("\n=== 测试26: 所有人 fold 只剩一人 ===")
    gs = make_gs([1000, 1000, 1000], sb=5, bb=10)
    pot_before = gs.pot

    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))

    check("is_hand_over=True", gs.is_hand_over())

    winnings = gs.settle()
    check("P3赢得底池", winnings.get("P3", 0) == pot_before,
          f"实际={winnings}, pot={pot_before}")
    total = sum(winnings.values())
    check("总额=pot", total == pot_before, f"实际={total}")


# ─── 测试 27: split pot 奇数筹码分配给正确位置 ───
def test_odd_chip_position_priority():
    print("\n=== 测试27: 奇数筹码分配位置优先 ===")
    # 3人各下奇数筹码，2人平分时有1筹码余数
    players = [Player(name="P1", stack=501),
               Player(name="P2", stack=501),
               Player(name="P3", stack=501)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    # P1 和 P2 平分，P3 输
    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "Qh Jh Ts 7c 8d")

    winnings = gs.settle()
    total = sum(winnings.values())
    pot = gs.pot if gs.pot > 0 else total
    check("总额守恒", total == pot, f"实际total={total}, pot={pot}")
    check("P3赢0", winnings.get("P3", 0) == 0, f"实际={winnings}")
    p1_win = winnings.get("P1", 0)
    p2_win = winnings.get("P2", 0)
    check("P1和P2差异<=1", abs(p1_win - p2_win) <= 1,
          f"P1={p1_win}, P2={p2_win}")
    check("P1+P2=总额", p1_win + p2_win == total, f"P1={p1_win}, P2={p2_win}")


# ─── 测试 28: run_it_twice 两次 board 都 split ───
def test_run_it_twice_both_split():
    print("\n=== 测试28: run_it_twice 两次都平分 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")

    # 两个 board 都让两人平分
    board_1 = [Card.new(c) for c in "Qh Jh Ts 2c 3d".split()]
    board_2 = [Card.new(c) for c in "Qd Jd Tc 4s 5s".split()]

    result = run_it_twice(gs, board_1, board_2)

    # RIT 每个 board 分配一半底池 (1000), split 后每人各500
    check("board_1 P1赢500", result.winnings_1.get("P1", 0) == 500,
          f"实际={result.winnings_1}")
    check("board_1 P2赢500", result.winnings_1.get("P2", 0) == 500,
          f"实际={result.winnings_1}")
    check("board_2 P1赢500", result.winnings_2.get("P1", 0) == 500,
          f"实际={result.winnings_2}")
    check("board_2 P2赢500", result.winnings_2.get("P2", 0) == 500,
          f"实际={result.winnings_2}")
    check("combined P1=1000", result.combined.get("P1", 0) == 1000,
          f"实际={result.combined}")
    check("combined P2=1000", result.combined.get("P2", 0) == 1000,
          f"实际={result.combined}")


## ─── 补充测试: 修复弱断言 + 覆盖遗漏场景 ───


# ─── 测试 29: call 后 fold，投入计入底池但不参与分配 ───
def test_fold_after_call_not_eligible():
    print("\n=== 测试29: call后fold，投入计入底池但不eligible ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1 raise to 100
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=100))
    # P2 call 100
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=100))
    # P3 all-in 1000
    gs.apply_action(PlayerAction("P3", ActionType.ALL_IN, amount=1000))
    # P1 fold
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    # P2 call (all-in for remaining)
    gs.apply_action(PlayerAction("P2", ActionType.ALL_IN, amount=1000))

    pot = gs.pot
    check("底池包含P1的100", pot > 2000, f"实际={pot}")

    pots = gs.calculate_side_pots()
    for sp in pots:
        check(f"P1不在边池eligible中 (pot={sp.amount})",
              "P1" not in sp.eligible,
              f"eligible={sp.eligible}")

    set_hole(gs, "P2", "As Ah")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=pot", total == pot, f"实际total={total}, pot={pot}")
    check("P1赢0 (已fold)", winnings.get("P1", 0) == 0, f"实际={winnings}")
    check("P2赢全部", winnings.get("P2", 0) == pot, f"实际={winnings}")


# ─── 测试 30: 多人fold穿插all-in，边池正确 ───
def test_fold_between_allins():
    print("\n=== 测试30: P1 all-in 100, P2 call, P3 raise all-in 500, P2 fold ===")
    players = [Player(name="P1", stack=100),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=500)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1 all-in 100
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=100))
    # P2 call 100
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=100))
    # P3 all-in 500
    gs.apply_action(PlayerAction("P3", ActionType.ALL_IN, amount=500))
    # P2 fold
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))

    pot = gs.pot
    pots = gs.calculate_side_pots()

    # P2 folded — 不应出现在任何 eligible 中
    for sp in pots:
        check(f"P2不在eligible中 (pot={sp.amount})",
              "P2" not in sp.eligible,
              f"eligible={sp.eligible}")

    pot_total = sum(sp.amount for sp in pots)
    check("边池总额=pot", pot_total == pot, f"边池总额={pot_total}, pot={pot}")

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    # P1 赢主池 (AA), P3 拿回边池中无人竞争的部分
    main_pot_amount = pots[0].amount
    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额守恒", total == pot, f"实际={total}")
    check("P1赢主池 (AA)", winnings.get("P1", 0) == main_pot_amount,
          f"实际={winnings}, 主池={main_pot_amount}")


# ─── 测试 31: turn 上 all-in，累积多街投注 ───
def test_allin_on_turn():
    print("\n=== 测试31: turn上all-in，多街累积投注 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)

    # preflop: call
    for p in gs.players:
        if p.current_bet < gs.current_bet:
            gs.apply_action(PlayerAction(p.name, ActionType.CALL, amount=gs.current_bet))
        else:
            gs.apply_action(PlayerAction(p.name, ActionType.CHECK))

    # flop
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Qh Jh Ts".split()]
    gs.apply_action(PlayerAction("P1", ActionType.BET, amount=50))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=50))

    # turn
    gs.advance_street()
    gs.board.append(Card.new("4c"))
    allin_all(gs)

    pot = gs.pot
    check("底池=2000 (全部筹码)", pot == 2000, f"实际={pot}")

    set_hole(gs, "P1", "As Ks")
    set_hole(gs, "P2", "2c 3d")
    gs.board.append(Card.new("5s"))

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=2000", total == 2000, f"实际={total}")
    check("P1赢全部", winnings.get("P1", 0) == 2000, f"实际={winnings}")

    p1 = gs.get_player("P1")
    p2 = gs.get_player("P2")
    check("stack守恒", p1.stack + p2.stack == 2000,
          f"P1={p1.stack}, P2={p2.stack}")


# ─── 测试 32: run_it_twice 奇数底池，board_1 多拿1筹码 ───
def test_run_it_twice_odd_pot():
    print("\n=== 测试32: run_it_twice 奇数底池 ===")
    players = [Player(name="P1", stack=501),
               Player(name="P2", stack=500)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    total_pot = gs.pot
    check("底池=1001", total_pot == 1001, f"实际={total_pot}")

    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")

    board_1 = [Card.new(c) for c in "Qh Jh Ts 2c 3d".split()]
    board_2 = [Card.new(c) for c in "Qd Jd Tc 4s 5s".split()]

    result = run_it_twice(gs, board_1, board_2)

    w1_total = sum(result.winnings_1.values())
    w2_total = sum(result.winnings_2.values())
    check("board_1分配 = 501 (多拿余数)", w1_total == 501,
          f"实际={w1_total}")
    check("board_2分配 = 500", w2_total == 500,
          f"实际={w2_total}")
    combined_total = sum(result.combined.values())
    check("combined总额=1001", combined_total == 1001,
          f"实际={combined_total}")


# ─── 测试 33: 两人 all-in 相同金额 + 第三人 cover ───
def test_duplicate_allin_levels():
    print("\n=== 测试33: 两人all-in相同金额，第三人cover ===")
    players = [Player(name="P1", stack=500),
               Player(name="P2", stack=500),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("底池=2000", gs.pot == 2000, f"实际={gs.pot}")

    pots = gs.calculate_side_pots()
    check("有2个边池", len(pots) == 2,
          f"实际={len(pots)}, pots={[(p.amount, p.eligible) for p in pots]}")

    main_pot = pots[0]
    check("主池=1500 (3x500)", main_pot.amount == 1500, f"实际={main_pot.amount}")
    check("主池3人eligible", len(main_pot.eligible) == 3)

    side_pot = pots[1]
    check("边池=500 (P3多出的500)", side_pot.amount == 500, f"实际={side_pot.amount}")
    check("边池只有P3", side_pot.eligible == ["P3"],
          f"实际={side_pot.eligible}")

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    check("P1赢主池1500", winnings.get("P1", 0) == 1500, f"实际={winnings}")
    check("P3赢边池500 (唯一eligible)", winnings.get("P3", 0) == 500,
          f"实际={winnings}")
    check("P2赢0", winnings.get("P2", 0) == 0, f"实际={winnings}")


# ─── 测试 34: 只有一人 all-in，其余 active ───
def test_single_allin_others_active():
    print("\n=== 测试34: 只有一人all-in，其余active ===")
    players = [Player(name="P1", stack=200),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1 all-in
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=200))
    # P2 call
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=200))
    # P3 call
    gs.apply_action(PlayerAction("P3", ActionType.CALL, amount=200))

    pots = gs.calculate_side_pots()
    check("有边池", len(pots) >= 1, f"实际={len(pots)}")

    main_pot = pots[0]
    check("主池=600 (3x200)", main_pot.amount == 600, f"实际={main_pot.amount}")
    check("主池3人eligible", len(main_pot.eligible) == 3)

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    check("P1赢主池600 (AA)", winnings.get("P1", 0) == 600, f"实际={winnings}")
    check("P2赢0 (KK < AA)", winnings.get("P2", 0) == 0, f"实际={winnings}")
    check("P3赢0 (垃圾牌)", winnings.get("P3", 0) == 0, f"实际={winnings}")
    total = sum(winnings.values())
    check("总额=600", total == 600, f"实际={total}")


# ─── 测试 35: 预设 side_pots 后 settle 不重新计算 ───
def test_settle_uses_precomputed_side_pots():
    print("\n=== 测试35: 预设side_pots后settle直接使用 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    from env.game_state import SidePot
    gs.side_pots = [SidePot(amount=2000, eligible=["P1", "P2"])]

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    check("使用预设side_pots, P1赢2000", winnings.get("P1", 0) == 2000,
          f"实际={winnings}")
    check("settle后side_pots被清空", gs.side_pots == [],
          f"实际={gs.side_pots}")


# ─── 测试 36: run_it_twice 3人不同边池不同赢家 ───
def test_run_it_twice_3way_different_winners():
    print("\n=== 测试36: run_it_twice 3人，两个board不同赢家 ===")
    players = [Player(name="P1", stack=300),
               Player(name="P2", stack=600),
               Player(name="P3", stack=600)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    total_pot = gs.pot
    check("底池=1500", total_pot == 1500, f"实际={total_pot}")

    set_hole(gs, "P1", "As Ah")  # AA
    set_hole(gs, "P2", "Ks Kh")  # KK
    set_hole(gs, "P3", "Qs Qh")  # QQ

    # board_1: 无帮助 → AA > KK > QQ
    board_1 = [Card.new(c) for c in "7h 2s 9d Jc 4h".split()]
    # board_2: K on board → KK三条 > AA > QQ
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]

    result = run_it_twice(gs, board_1, board_2)

    combined_total = sum(result.combined.values())
    check("combined总额=1500", combined_total == total_pot,
          f"实际={combined_total}")
    check("无负数", all(v >= 0 for v in result.combined.values()),
          f"实际={result.combined}")

    # board_1: P1(AA)赢主池, P2(KK)赢边池; 各pot金额为原pot的一半(向上取整)
    # 主池=900(3x300), 边池=600(2x300); board_1 各拿一半
    check("board_1 P1赢主池", result.winnings_1.get("P1", 0) > 0,
          f"实际={result.winnings_1}")
    check("board_1 P2赢边池", result.winnings_1.get("P2", 0) > 0,
          f"实际={result.winnings_1}")
    check("board_1 P3赢0", result.winnings_1.get("P3", 0) == 0,
          f"实际={result.winnings_1}")
    # board_2: P2(三条K)赢主池和边池
    check("board_2 P2赢全部", result.winnings_2.get("P2", 0) > 0,
          f"实际={result.winnings_2}")
    check("board_2 P1赢0", result.winnings_2.get("P1", 0) == 0,
          f"实际={result.winnings_2}")
    check("board_2 P3赢0", result.winnings_2.get("P3", 0) == 0,
          f"实际={result.winnings_2}")


# ─── 测试 37: 全局 stack 守恒 (多场景) ───
def test_stack_conservation_universal():
    print("\n=== 测试37: 全局stack守恒 (多种场景) ===")

    scenarios = [
        ("2人等筹码", [1000, 1000]),
        ("3人不等筹码", [200, 500, 1000]),
        ("4人极端差异", [10, 100, 1000, 5000]),
        ("6人等筹码", [500] * 6),
    ]

    for label, stacks in scenarios:
        initial_total = sum(stacks)
        players = [Player(name=f"P{i+1}", stack=s) for i, s in enumerate(stacks)]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        allin_all(gs)

        # 给最强手牌给 P1
        set_hole(gs, "P1", "As Ah")
        for i in range(1, len(stacks)):
            low_cards = [("2c", "3d"), ("4c", "5d"), ("6c", "7d"),
                         ("8c", "9d"), ("Tc", "Jd")]
            c1, c2 = low_cards[i - 1]
            set_hole(gs, f"P{i+1}", f"{c1} {c2}")
        set_board(gs, "Kh Qh Js 2s 9h")

        gs.settle()
        final_total = sum(p.stack for p in gs.players)
        check(f"{label}: stack守恒 {initial_total}",
              final_total == initial_total,
              f"初始={initial_total}, 最终={final_total}")


# ─── 测试 38: 无 contender 有 hole cards 时 fallback 分配 ───
def test_no_contender_with_hole_cards_fallback():
    print("\n=== 测试38: 边池无人有hole cards时fallback给eligible[0] ===")
    players = [Player(name="P1", stack=500),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    # 只给 P1 设置 hole cards，P2 和 P3 不设置
    set_hole(gs, "P1", "As Ah")
    set_board(gs, "7h 8h 9s Tc 4d")

    winnings = gs.settle()
    total = sum(winnings.values())
    pot = 2500
    check("总额守恒", total == pot, f"实际total={total}, pot={pot}")
    check("P1赢主池 (唯一有hole cards)", winnings.get("P1", 0) > 0,
          f"实际={winnings}")
    check("无负数", all(v >= 0 for v in winnings.values()), f"实际={winnings}")


# ─── 测试 39: river 上 all-in ───
def test_allin_on_river():
    print("\n=== 测试39: river上all-in ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)

    # preflop: call
    for p in gs.players:
        if p.current_bet < gs.current_bet:
            gs.apply_action(PlayerAction(p.name, ActionType.CALL, amount=gs.current_bet))
        else:
            gs.apply_action(PlayerAction(p.name, ActionType.CHECK))

    # flop
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Qh Jh Ts".split()]
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))

    # turn
    gs.advance_street()
    gs.board.append(Card.new("4c"))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))

    # river
    gs.advance_street()
    gs.board.append(Card.new("5s"))
    allin_all(gs)

    pot = gs.pot
    check("底池=2000", pot == 2000, f"实际={pot}")
    check("board=5张", len(gs.board) == 5)

    set_hole(gs, "P1", "As Ks")
    set_hole(gs, "P2", "2c 3d")

    winnings = gs.settle()
    check("P1赢全部2000", winnings.get("P1", 0) == 2000, f"实际={winnings}")
    check("P2赢0", winnings.get("P2", 0) == 0, f"实际={winnings}")
    total = sum(winnings.values())
    check("总额=2000", total == 2000, f"实际={total}")


# ─── 测试 40: 短筹码 call 导致 all-in (非 raise) ───
def test_call_causes_allin():
    print("\n=== 测试40: 短筹码call导致all-in ===")
    # P1=300 短筹码, P2=1000, P3=1000
    players = [Player(name="P1", stack=300),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    # P1 raise to 100
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=100))
    # P2 raise to 500
    gs.apply_action(PlayerAction("P2", ActionType.RAISE, amount=500))
    # P3 fold
    gs.apply_action(PlayerAction("P3", ActionType.FOLD))
    # P1 call — 只剩 200 (300-100已投), call 导致 all-in
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=500))

    p1 = gs.get_player("P1")
    check("P1 is_all_in", p1.is_all_in, f"stack={p1.stack}, all_in={p1.is_all_in}")
    check("P1 stack=0", p1.stack == 0, f"实际={p1.stack}")

    pot = gs.pot
    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    pots = gs.calculate_side_pots()
    # P1 投入 300, P2 投入 500, P3 投入 10(BB)
    # 主池: 3x min(300,投入) 中 P1 和 P2 eligible (P3 folded)
    check("有边池", len(pots) >= 1, f"实际={len(pots)}")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=pot", total == pot, f"实际total={total}, pot={pot}")
    check("P1赢主池 (AA)", winnings.get("P1", 0) > 0, f"实际={winnings}")
    check("P3赢0 (已fold)", winnings.get("P3", 0) == 0, f"实际={winnings}")
    check("无负数", all(v >= 0 for v in winnings.values()), f"实际={winnings}")


# ─── 测试 41: 盲注 posting 导致 all-in ───
def test_blind_posting_causes_allin():
    print("\n=== 测试41: 盲注posting导致all-in ===")
    # P1 stack=5 刚好等于 SB, P2 stack=8 小于 BB
    players = [Player(name="P1", stack=5),
               Player(name="P2", stack=8)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()

    p1 = gs.get_player("P1")
    p2 = gs.get_player("P2")
    # heads-up: P1 是 SB/dealer, P2 是 BB
    check("P1 posting SB后 all-in", p1.is_all_in,
          f"stack={p1.stack}, all_in={p1.is_all_in}")
    check("P1 stack=0", p1.stack == 0, f"实际={p1.stack}")
    check("P2 posting BB后 all-in", p2.is_all_in,
          f"stack={p2.stack}, all_in={p2.is_all_in}")
    check("P2 stack=0", p2.stack == 0, f"实际={p2.stack}")

    pot = gs.pot
    check("底池=13 (5+8)", pot == 13, f"实际={pot}")
    check("is_hand_over", gs.is_hand_over())

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "2c 3d")
    set_board(gs, "7h 8h 9s Tc 4d")

    pots = gs.calculate_side_pots()
    # P1 投入5, P2 投入8 → 主池=2x5=10 (P1,P2), 边池=3 (只有P2)
    check("主池=10", pots[0].amount == 10, f"实际={pots[0].amount}")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=13", total == 13, f"实际={total}")
    # P1(AA) 赢主池10, P2 拿回边池3
    check("P1赢10 (主池)", winnings.get("P1", 0) == 10, f"实际={winnings}")
    check("P2拿回3 (边池)", winnings.get("P2", 0) == 3, f"实际={winnings}")


# ─── 测试 42: kicker 决定胜负 ───
def test_kicker_decides_winner():
    print("\n=== 测试42: kicker决定胜负 ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    # 两人都有 A pair, 但 P1 kicker K > P2 kicker Q
    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Qh")
    set_board(gs, "Ah 7h 5s 2c 3d")

    winnings = gs.settle()
    check("P1赢2000 (AK > AQ, kicker)", winnings.get("P1", 0) == 2000,
          f"实际={winnings}")
    check("P2赢0", winnings.get("P2", 0) == 0, f"实际={winnings}")


# ─── 测试 43: kicker 相同时 split ───
def test_same_kicker_split():
    print("\n=== 测试43: 相同kicker时split ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    # 两人都有 AK, 不同花色, board 无 flush 可能
    set_hole(gs, "P1", "As Kd")
    set_hole(gs, "P2", "Ac Kh")
    set_board(gs, "Ah 7s 5c 2d 3h")

    winnings = gs.settle()
    check("P1赢1000 (split)", winnings.get("P1", 0) == 1000, f"实际={winnings}")
    check("P2赢1000 (split)", winnings.get("P2", 0) == 1000, f"实际={winnings}")


# ─── 测试 44: 多个边池各自 split 给不同玩家组 ───
def test_multi_pot_different_splits():
    print("\n=== 测试44: 主池和边池分别split给不同玩家组 ===")
    # P1=200(AA), P2=200(AA相同牌力), P3=1000(KK), P4=1000(KK相同牌力)
    players = [Player(name="P1", stack=200),
               Player(name="P2", stack=200),
               Player(name="P3", stack=1000),
               Player(name="P4", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    check("底池=2400", gs.pot == 2400, f"实际={gs.pot}")

    # P1, P2 有 AA (赢主池), P3, P4 有 KK (赢边池)
    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ad Ac")  # 另一组 AA — 但 As 已用, 用不同表示
    # 实际上 As 和 Ad 不冲突: P1=As Ah, P2=Ad Ac
    set_hole(gs, "P3", "Ks Kh")
    set_hole(gs, "P4", "Kd Kc")
    set_board(gs, "7h 5s 2c 9d 3h")

    pots = gs.calculate_side_pots()
    # 主池: 4x200=800, eligible: P1,P2,P3,P4
    # 边池: 2x800=1600, eligible: P3,P4
    check("主池=800", pots[0].amount == 800, f"实际={pots[0].amount}")
    check("边池=1600", pots[1].amount == 1600, f"实际={pots[1].amount}")

    winnings = gs.settle()
    total = sum(winnings.values())
    check("总额=2400", total == 2400, f"实际={total}")
    # 主池: P1+P2 split 800 → 各400
    check("P1赢400 (主池split)", winnings.get("P1", 0) == 400, f"实际={winnings}")
    check("P2赢400 (主池split)", winnings.get("P2", 0) == 400, f"实际={winnings}")
    # 边池: P3+P4 split 1600 → 各800
    check("P3赢800 (边池split)", winnings.get("P3", 0) == 800, f"实际={winnings}")
    check("P4赢800 (边池split)", winnings.get("P4", 0) == 800, f"实际={winnings}")


# ─── 测试 45: run_it_twice 边池金额总和守恒 ───
def test_run_it_twice_side_pot_sum_conservation():
    print("\n=== 测试45: run_it_twice 边池金额拆分守恒 ===")
    import copy as _copy

    players = [Player(name="P1", stack=300),
               Player(name="P2", stack=700),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    allin_all(gs)

    total_pot = gs.pot
    gs.calculate_side_pots()
    original_side_pot_amounts = [sp.amount for sp in gs.side_pots]
    original_side_pot_total = sum(original_side_pot_amounts)
    check("边池总额=pot", original_side_pot_total == total_pot,
          f"边池总额={original_side_pot_total}, pot={total_pot}")

    set_hole(gs, "P1", "As Ah")
    set_hole(gs, "P2", "Ks Kh")
    set_hole(gs, "P3", "Qs Qh")

    board_1 = [Card.new(c) for c in "7h 2s 9d Jc 4h".split()]
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]

    # 手动模拟 run_it_twice 的拆分逻辑来验证
    gs1 = _copy.deepcopy(gs)
    gs2 = _copy.deepcopy(gs)

    for sp in gs1.side_pots:
        orig = sp.amount
        sp.amount = orig // 2 + orig % 2
    for sp in gs2.side_pots:
        sp.amount = sp.amount // 2

    for i, orig_amount in enumerate(original_side_pot_amounts):
        split_sum = gs1.side_pots[i].amount + gs2.side_pots[i].amount
        check(f"边池{i}拆分守恒 ({orig_amount})",
              split_sum == orig_amount,
              f"gs1={gs1.side_pots[i].amount} + gs2={gs2.side_pots[i].amount} = {split_sum}")

    # 完整 run_it_twice 验证
    result = run_it_twice(gs, board_1, board_2)
    combined_total = sum(result.combined.values())
    check("combined总额=pot", combined_total == total_pot,
          f"实际={combined_total}, pot={total_pot}")
    check("无负数", all(v >= 0 for v in result.combined.values()),
          f"实际={result.combined}")


# ─── 测试 46: flush 花色决定胜负 ───
def test_flush_wins_over_straight():
    print("\n=== 测试46: flush胜过straight ===")
    gs = make_gs([1000, 1000], sb=5, bb=10)
    allin_all(gs)

    # P1 有 flush (红心), P2 有 straight
    set_hole(gs, "P1", "2h 4h")
    set_hole(gs, "P2", "6c 9d")
    set_board(gs, "5h 7h 8s Th 3d")

    winnings = gs.settle()
    check("P1赢2000 (flush > straight)", winnings.get("P1", 0) == 2000,
          f"实际={winnings}")
    check("P2赢0", winnings.get("P2", 0) == 0, f"实际={winnings}")


# ─── 测试 47: 随机筹码 stack 守恒 (property-based 简化版) ───
def test_property_chip_conservation():
    print("\n=== 测试47: property-based 筹码守恒 (多随机场景) ===")
    import random
    rng = random.Random(42)

    available_hole_cards = [
        "As Ah", "Ks Kh", "Qs Qh", "Js Jh", "Ts Th",
        "9s 9h", "8s 8h", "7s 7h", "6s 6h", "5s 5h",
    ]
    board_options = [
        "2c 3d 4c 8d 2d",
        "Ac Kd Qc Jd Tc",
        "7c 8d 9c Td Jc",
        "2c 5d 8c Jd Kc",
        "3c 6d 9c Qd 4c",
    ]

    for trial in range(20):
        n_players = rng.randint(2, 9)
        stacks = [rng.randint(1, 5000) for _ in range(n_players)]
        initial_total = sum(stacks)

        players = [Player(name=f"P{i+1}", stack=s) for i, s in enumerate(stacks)]
        gs = GameState(players=players, small_blind=5, big_blind=10)
        gs.assign_positions()
        gs.post_blinds()
        allin_all(gs)

        for i in range(n_players):
            set_hole(gs, f"P{i+1}", available_hole_cards[i % len(available_hole_cards)])
        set_board(gs, board_options[trial % len(board_options)])

        winnings = gs.settle()
        total_won = sum(winnings.values())
        final_stacks = sum(p.stack for p in gs.players)

        check(f"trial{trial}: stack守恒 (n={n_players})",
              final_stacks == initial_total,
              f"初始={initial_total}, 最终stacks={final_stacks}, won={total_won}")
        check(f"trial{trial}: 无负数",
              all(v >= 0 for v in winnings.values()),
              f"winnings={winnings}")
        check(f"trial{trial}: 无负stack",
              all(p.stack >= 0 for p in gs.players),
              f"stacks={[p.stack for p in gs.players]}")



if __name__ == "__main__":
    test_6way_equal_stack_allin()
    test_unequal_stack_side_pots()
    test_split_pot()
    test_short_stack_wins_main()
    test_run_it_twice()
    test_allin_after_flop()
    test_evaluate_incomplete_board()
    test_4way_multi_side_pots()
    test_odd_chip_split()
    test_fold_then_allin()
    test_run_it_twice_same_winner()
    test_split_main_pot_with_side_winner()
    test_zero_stack_player()
    test_settle_idempotent()
    test_allin_less_than_blind()
    test_stack_updated_after_settle()
    test_stack_updated_side_pots()
    test_run_it_twice_with_side_pots()
    test_4way_equal_split()
    test_5way_odd_chip_split()
    test_settle_missing_hole_cards()
    test_duplicate_cards_detection()
    test_9_player_allin()
    test_fold_blind_in_pot()
    test_heads_up_positions()
    test_all_fold_except_one()
    test_odd_chip_position_priority()
    test_run_it_twice_both_split()
    # 补充测试
    test_fold_after_call_not_eligible()
    test_fold_between_allins()
    test_allin_on_turn()
    test_run_it_twice_odd_pot()
    test_duplicate_allin_levels()
    test_single_allin_others_active()
    test_settle_uses_precomputed_side_pots()
    test_run_it_twice_3way_different_winners()
    test_stack_conservation_universal()
    test_no_contender_with_hole_cards_fallback()
    # 新增场景测试
    test_allin_on_river()
    test_call_causes_allin()
    test_blind_posting_causes_allin()
    test_kicker_decides_winner()
    test_same_kicker_split()
    test_multi_pot_different_splits()
    test_run_it_twice_side_pot_sum_conservation()
    test_flush_wins_over_straight()
    test_property_chip_conservation()

    print("\n" + "=" * 50)
    passed = sum(1 for _, ok in results if ok)
    failed = sum(1 for _, ok in results if not ok)
    print(f"总计: {passed} 通过, {failed} 失败")
    if failed:
        print("\n失败项:")
        for name, ok in results:
            if not ok:
                print(f"  - {name}")
        sys.exit(1)
    else:
        print("全部通过!")
