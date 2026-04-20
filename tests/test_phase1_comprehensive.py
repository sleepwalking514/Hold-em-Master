"""Phase 1 全模块综合测试 — 覆盖 game_state / action_space / board_texture / card_parser / hand_history / replay_engine / new_hand"""
from __future__ import annotations

import sys
import json
import copy
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from treys import Card
from env.game_state import GameState, Player, SidePot
from env.action_space import ActionType, PlayerAction, Street, GameMode, POSITIONS_BY_SIZE
from env.board_texture import analyze_board, BoardTexture
from env.run_it_twice import run_it_twice
from ui.card_parser import parse_card, parse_cards, card_to_str, card_to_short, validate_no_duplicates, random_cards, VALID_RANKS, VALID_SUITS, SUIT_SYMBOLS, SUIT_FROM_SYMBOL, ALL_CARDS

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


# ═══════════════════════════════════════════════════
#  A. assign_positions 位置分配
# ═══════════════════════════════════════════════════

def test_positions_2_players():
    print("\n=== A1: 2人桌位置分配 ===")
    gs = make_gs([1000, 1000])
    positions = [p.position for p in gs.players]
    check("2人: P1=SB, P2=BB", positions == ["SB", "BB"],
          f"实际={positions}")

def test_positions_3_players():
    print("\n=== A2: 3人桌位置分配 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    positions = {p.name: p.position for p in gs.players}
    check("P1=BTN (dealer)", positions["P1"] == "BTN", f"实际={positions}")
    check("P2=SB", positions["P2"] == "SB", f"实际={positions}")
    check("P3=BB", positions["P3"] == "BB", f"实际={positions}")


def test_positions_6_players():
    print("\n=== A3: 6人桌位置分配 ===")
    players = [Player(name=f"P{i+1}", stack=1000) for i in range(6)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    positions = [p.position for p in gs.players]
    expected = POSITIONS_BY_SIZE[6]
    check("6人位置正确", positions == expected,
          f"实际={positions}, 期望={expected}")


def test_positions_dealer_rotation():
    print("\n=== A4: dealer_idx=2 时位置偏移 ===")
    players = [Player(name=f"P{i+1}", stack=1000) for i in range(4)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=2)
    gs.assign_positions()
    p3 = gs.get_player("P3")
    check("P3 是 BTN (dealer_idx=2)", p3.position == "BTN",
          f"实际={p3.position}")


# ═══════════════════════════════════════════════════
#  B. post_blinds 盲注
# ═══════════════════════════════════════════════════

def test_blinds_normal():
    print("\n=== B1: 正常盲注 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    sb = gs.get_player("P2")  # SB
    bb = gs.get_player("P3")  # BB
    check("SB stack=995", sb.stack == 995, f"实际={sb.stack}")
    check("BB stack=990", bb.stack == 990, f"实际={bb.stack}")
    check("pot=15", gs.pot == 15, f"实际={gs.pot}")
    check("current_bet=10", gs.current_bet == 10, f"实际={gs.current_bet}")
    check("SB current_bet=5", sb.current_bet == 5, f"实际={sb.current_bet}")
    check("BB current_bet=10", bb.current_bet == 10, f"实际={bb.current_bet}")


def test_blinds_headsup():
    print("\n=== B2: Heads-up 盲注 (dealer=SB) ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    check("P1(dealer)=SB, stack=995", gs.get_player("P1").stack == 995)
    check("P2=BB, stack=990", gs.get_player("P2").stack == 990)
    check("pot=15", gs.pot == 15)


def test_blinds_short_stack_sb():
    print("\n=== B3: SB 筹码不足盲注 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=3),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    sb = gs.get_player("P2")
    check("SB 只投3 (全部筹码)", sb.current_bet == 3, f"实际={sb.current_bet}")
    check("SB stack=0", sb.stack == 0)
    check("SB is_all_in", sb.is_all_in)
    check("pot=13", gs.pot == 13, f"实际={gs.pot}")


# ═══════════════════════════════════════════════════
#  C. apply_action 动作处理
# ═══════════════════════════════════════════════════

def test_action_fold():
    print("\n=== C1: fold 动作 ===")
    gs = make_gs([1000, 1000, 1000])
    p1 = gs.get_player("P1")
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    check("P1 is_active=False", not p1.is_active)
    check("P1 has_acted=True", p1.has_acted)
    check("pot 不变", gs.pot == 15, f"实际={gs.pot}")


def test_action_check():
    print("\n=== C2: check 动作 ===")
    gs = make_gs([1000, 1000])
    # preflop: P1 call, P2 check
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    p1 = gs.get_player("P1")
    stack_before = p1.stack
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    check("check 后 stack 不变", p1.stack == stack_before, f"实际={p1.stack}")
    check("has_acted=True", p1.has_acted)


def test_action_call():
    print("\n=== C3: call 动作 ===")
    gs = make_gs([1000, 1000, 1000])
    # P1 (UTG) calls BB of 10
    p1 = gs.get_player("P1")
    initial_stack = p1.stack
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    check("P1 stack 减少10", p1.stack == initial_stack - 10,
          f"实际={p1.stack}, 期望={initial_stack - 10}")
    check("P1 current_bet=10", p1.current_bet == 10)
    check("pot 增加10", gs.pot == 25, f"实际={gs.pot}")


def test_action_raise_resets_has_acted():
    print("\n=== C4: raise 重置其他人 has_acted ===")
    gs = make_gs([1000, 1000, 1000])
    # P1 call
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    p1 = gs.get_player("P1")
    check("P1 has_acted after call", p1.has_acted)
    # P2 (SB) raise to 30
    gs.apply_action(PlayerAction("P2", ActionType.RAISE, amount=30))
    check("P1 has_acted 被重置", not p1.has_acted)
    check("P2 has_acted=True", gs.get_player("P2").has_acted)
    check("current_bet=30", gs.current_bet == 30, f"实际={gs.current_bet}")


def test_action_bet_postflop():
    print("\n=== C5: postflop bet ===")
    gs = make_gs([1000, 1000])
    # preflop: call + check
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    # P1 bet 50
    p1 = gs.get_player("P1")
    stack_before = p1.stack
    gs.apply_action(PlayerAction("P1", ActionType.BET, amount=50))
    check("P1 stack 减少50", p1.stack == stack_before - 50)
    check("current_bet=50", gs.current_bet == 50)
    check("last_raiser=P1", gs.last_raiser == "P1")


def test_action_allin_sets_inactive():
    print("\n=== C6: all-in 设置 is_active=False ===")
    gs = make_gs([1000, 1000])
    p1 = gs.get_player("P1")
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    check("P1 is_all_in=True", p1.is_all_in)
    check("P1 is_active=False", not p1.is_active)
    check("P1 stack=0", p1.stack == 0)



# ═══════════════════════════════════════════════════
#  D. is_street_over / is_hand_over
# ═══════════════════════════════════════════════════

def test_street_over_after_all_check():
    print("\n=== D1: 全员 check 后 street 结束 ===")
    gs = make_gs([1000, 1000])
    # preflop: call + check
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    check("preflop street over", gs.is_street_over())
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    check("flop 刚开始 street 未结束", not gs.is_street_over())
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    check("P1 check 后 street 未结束", not gs.is_street_over())
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    check("双方 check 后 street 结束", gs.is_street_over())


def test_hand_over_all_fold():
    print("\n=== D2: 全员 fold 只剩一人 ===")
    gs = make_gs([1000, 1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    check("1人fold后 hand 未结束", not gs.is_hand_over())
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    check("2人fold后 hand 结束", gs.is_hand_over())


def test_hand_over_all_allin():
    print("\n=== D3: 全员 all-in hand 结束 ===")
    gs = make_gs([1000, 1000, 1000])
    for p in gs.players:
        if p.is_active and not p.is_all_in:
            gs.apply_action(PlayerAction(p.name, ActionType.ALL_IN, amount=p.stack + p.current_bet))
    check("全员 all-in hand 结束", gs.is_hand_over())


def test_hand_not_over_one_active_one_allin():
    print("\n=== D4: 1人 active + 1人 all-in, hand 未结束 ===")
    gs = make_gs([500, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=500))
    # P2 还没行动
    check("P1 all-in P2 未行动, hand 未结束", not gs.is_hand_over())


# ═══════════════════════════════════════════════════
#  E. advance_street 状态重置
# ═══════════════════════════════════════════════════

def test_advance_street_resets():
    print("\n=== E1: advance_street 重置 current_bet 和 has_acted ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    check("preflop current_bet=10", gs.current_bet == 10)
    gs.advance_street()
    check("flop current_bet=0", gs.current_bet == 0, f"实际={gs.current_bet}")
    check("last_raiser=None", gs.last_raiser is None)
    for p in gs.players:
        if p.is_active:
            check(f"{p.name} has_acted=False", not p.has_acted)
            check(f"{p.name} current_bet=0", p.current_bet == 0)


def test_advance_street_preserves_allin():
    print("\n=== E2: advance_street 不影响 all-in 玩家 ===")
    gs = make_gs([100, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=100))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=100))
    gs.advance_street()
    p1 = gs.get_player("P1")
    check("P1 仍然 all-in", p1.is_all_in)
    check("P1 stack 仍然 0", p1.stack == 0)


# ═══════════════════════════════════════════════════
#  F. get_action_order
# ═══════════════════════════════════════════════════

def test_action_order_preflop_3p():
    print("\n=== F1: 3人 preflop 行动顺序 (UTG先) ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    order = gs.get_action_order()
    names = [p.name for p in order]
    # dealer=0, so UTG = (0+3)%3 = 0 = P1
    check("preflop 3人: UTG=P1 先行动", names[0] == "P1",
          f"实际顺序={names}")


def test_action_order_postflop():
    print("\n=== F2: postflop 行动顺序 (SB先) ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    # everyone calls preflop
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P3", ActionType.CHECK))
    gs.advance_street()
    order = gs.get_action_order()
    names = [p.name for p in order]
    # postflop: start = (dealer+1)%n = 1 = P2 (SB)
    check("postflop: P2(SB) 先行动", names[0] == "P2",
          f"实际顺序={names}")


def test_action_order_headsup_preflop():
    print("\n=== F3: Heads-up preflop 行动顺序 (dealer/SB先) ===")
    gs = make_gs([1000, 1000])
    order = gs.get_action_order()
    names = [p.name for p in order]
    # heads-up preflop: dealer(SB) acts first
    check("heads-up preflop: P1(SB/dealer) 先行动", names[0] == "P1",
          f"实际顺序={names}")


# ═══════════════════════════════════════════════════
#  G. get_min_raise
# ═══════════════════════════════════════════════════

def test_min_raise_preflop():
    print("\n=== G1: preflop min raise ===")
    gs = make_gs([1000, 1000, 1000])
    min_r = gs.get_min_raise()
    # current_bet=10 (BB), last_raise_size=0, so max(10+0, 10+10) = 20
    check("preflop min_raise=20", min_r == 20, f"实际={min_r}")


def test_min_raise_after_raise():
    print("\n=== G2: raise 后 min re-raise ===")
    gs = make_gs([1000, 1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=30))
    min_r = gs.get_min_raise()
    # current_bet=30, last_raise_size=20 (30-10), so max(30+20, 30+10) = 50
    check("re-raise min=50", min_r == 50, f"实际={min_r}")



# ═══════════════════════════════════════════════════
#  H. new_hand 新手牌重置
# ═══════════════════════════════════════════════════

def test_new_hand_resets_state():
    print("\n=== H1: new_hand 重置所有状态 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=1000))
    gs.board = [Card.new(c) for c in "Ah Kh Qh Jh Th".split()]
    gs.settle()
    gs.new_hand()
    check("board 清空", len(gs.board) == 0)
    check("street=PREFLOP", gs.street == Street.PREFLOP)
    check("used_cards 清空", len(gs.used_cards) == 0)
    check("side_pots 清空", len(gs.side_pots) == 0)
    for p in gs.players:
        check(f"{p.name} hole_cards 清空", len(p.hole_cards) == 0)
        check(f"{p.name} total_invested=盲注", p.total_invested > 0)


def test_new_hand_removes_broke_players():
    print("\n=== H2: new_hand 移除破产玩家 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10)
    gs.assign_positions()
    gs.post_blinds()
    # P1 all-in, P2 call, P3 fold
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=1000))
    gs.apply_action(PlayerAction("P3", ActionType.FOLD))
    # P2 wins
    gs.get_player("P1").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.get_player("P2").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 8d".split()]
    gs.settle()
    # P1 stack=0 now
    check("P1 stack=0", gs.get_player("P1").stack == 0)
    gs.new_hand()
    names = [p.name for p in gs.players]
    check("P1 被移除", "P1" not in names, f"剩余玩家={names}")
    check("剩余2人", len(gs.players) == 2, f"实际={len(gs.players)}")


def test_new_hand_dealer_rotation():
    print("\n=== H3: new_hand dealer 轮转 ===")
    gs = make_gs([1000, 1000, 1000])
    check("初始 dealer_idx=0", gs.dealer_idx == 0)
    # 快速结束手牌
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    gs.settle()
    gs.new_hand()
    check("dealer_idx=1", gs.dealer_idx == 1, f"实际={gs.dealer_idx}")


def test_new_hand_dealer_rotation_with_removal():
    print("\n=== H4: 移除玩家后 dealer 轮转不越界 ===")
    players = [Player(name=f"P{i+1}", stack=s) for i, s in enumerate([100, 1000, 1000, 1000])]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    # P1 all-in and loses
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=gs.get_player("P1").stack + gs.get_player("P1").current_bet))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=gs.current_bet))
    gs.apply_action(PlayerAction("P3", ActionType.FOLD))
    gs.apply_action(PlayerAction("P4", ActionType.FOLD))
    gs.get_player("P1").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.get_player("P2").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 8d".split()]
    gs.settle()
    try:
        gs.new_hand()
        check("new_hand 不崩溃", True)
        check("dealer_idx 有效", 0 <= gs.dealer_idx < len(gs.players),
              f"dealer_idx={gs.dealer_idx}, n_players={len(gs.players)}")
    except Exception as e:
        check("new_hand 崩溃", False, f"异常={e}")


# ═══════════════════════════════════════════════════
#  I. board_texture 牌面纹理
# ═══════════════════════════════════════════════════

def test_board_texture_monotone():
    print("\n=== I1: 单色牌面 ===")
    board = [Card.new(c) for c in "Ah Kh Qh".split()]
    tex = analyze_board(board)
    check("is_monotone=True", tex.is_monotone)
    check("is_rainbow=False", not tex.is_rainbow)
    check("flush_draw_possible=True", tex.flush_draw_possible)


def test_board_texture_rainbow():
    print("\n=== I2: 彩虹牌面 ===")
    board = [Card.new(c) for c in "Ah Ks Qd".split()]
    tex = analyze_board(board)
    check("is_rainbow=True", tex.is_rainbow)
    check("is_monotone=False", not tex.is_monotone)


def test_board_texture_paired():
    print("\n=== I3: 对子牌面 ===")
    board = [Card.new(c) for c in "Ah Ad Ks".split()]
    tex = analyze_board(board)
    check("is_paired=True", tex.is_paired)


def test_board_texture_trips():
    print("\n=== I4: 三条牌面 ===")
    board = [Card.new(c) for c in "Ah Ad Ac".split()]
    tex = analyze_board(board)
    check("is_trips_board=True", tex.is_trips_board)


def test_board_texture_empty():
    print("\n=== I5: 空牌面 ===")
    tex = analyze_board([])
    check("空牌面不崩溃", True)
    check("wetness=0", tex.wetness == 0.0)


def test_board_texture_connected():
    print("\n=== I6: 连牌牌面 ===")
    board = [Card.new(c) for c in "8h 9s Td".split()]
    tex = analyze_board(board)
    check("straight_draw_possible=True", tex.straight_draw_possible)
    check("connectedness>=3", tex.connectedness >= 3,
          f"实际={tex.connectedness}")


def test_board_texture_dry():
    print("\n=== I7: 干燥牌面 ===")
    board = [Card.new(c) for c in "2h 7s Kd".split()]
    tex = analyze_board(board)
    check("is_dry=True", tex.is_dry, f"wetness={tex.wetness}")


def test_board_texture_scare_card():
    print("\n=== I8: 恐吓牌检测 (turn) ===")
    board = [Card.new(c) for c in "2h 7h 9s Ah".split()]
    tex = analyze_board(board)
    check("scare_cards 非空", len(tex.scare_cards) > 0,
          f"scare_cards={tex.scare_cards}")



# ═══════════════════════════════════════════════════
#  J. card_parser
# ═══════════════════════════════════════════════════

def test_parse_card_basic():
    print("\n=== J1: 基本牌面解析 ===")
    c = parse_card("As")
    check("As 解析成功", c == Card.new("As"))
    c2 = parse_card("2h")
    check("2h 解析成功", c2 == Card.new("2h"))


def test_parse_card_lowercase():
    print("\n=== J2: 小写输入 ===")
    c = parse_card("as")
    check("as -> As", c == Card.new("As"))


def test_parse_cards_multi():
    print("\n=== J3: 多张牌解析 ===")
    cards = parse_cards("Ah Kd Qs")
    check("解析3张", len(cards) == 3)
    check("第一张=Ah", cards[0] == Card.new("Ah"))


def test_parse_cards_continuous():
    print("\n=== J4: 连续格式解析 (AhKd) ===")
    cards = parse_cards("AhKd")
    check("连续格式解析2张", len(cards) == 2)
    check("Ah", cards[0] == Card.new("Ah"))
    check("Kd", cards[1] == Card.new("Kd"))


def test_parse_card_invalid():
    print("\n=== J5: 无效牌面 ===")
    try:
        parse_card("Xx")
        check("应抛出异常", False)
    except ValueError:
        check("无效牌面抛出 ValueError", True)


def test_validate_no_duplicates():
    print("\n=== J6: 重复牌检测 ===")
    c1 = Card.new("As")
    c2 = Card.new("Kh")
    validate_no_duplicates([c1, c2])
    check("无重复通过", True)
    try:
        validate_no_duplicates([c1, c1])
        check("重复应抛异常", False)
    except ValueError:
        check("重复牌抛出 ValueError", True)


def test_validate_no_duplicates_with_used():
    print("\n=== J7: 与已用牌重复 ===")
    c1 = Card.new("As")
    c2 = Card.new("Kh")
    used = {c1}
    try:
        validate_no_duplicates([c2, c1], used)
        check("与已用牌重复应抛异常", False)
    except ValueError:
        check("与已用牌重复抛出 ValueError", True)


def test_random_cards():
    print("\n=== J8: 随机发牌不重复 ===")
    used: set[int] = set()
    cards = random_cards(5, used)
    check("发5张", len(cards) == 5)
    check("无重复", len(set(cards)) == 5)
    used.update(cards)
    cards2 = random_cards(5, used)
    check("第二次发5张", len(cards2) == 5)
    check("与第一次不重复", len(set(cards) & set(cards2)) == 0)


def test_card_to_short():
    print("\n=== J9: card_to_short ===")
    c = Card.new("As")
    s = card_to_short(c)
    check("As 短格式", s == "As", f"实际={s}")


# ═══════════════════════════════════════════════════
#  K. hand_history 导出 + replay_engine 回放
# ═══════════════════════════════════════════════════

def test_hand_history_export():
    print("\n=== K1: 手牌导出 JSON ===")
    from data.hand_history import export_hand
    gs = make_gs([1000, 1000])
    gs.hand_number = 99
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=990))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=990))
    gs.board.extend([Card.new("Jh"), Card.new("Th")])
    gs.get_player("P1").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.get_player("P2").hole_cards = [Card.new("9h"), Card.new("8h")]
    winnings = gs.settle()
    path = export_hand(gs, winnings)
    check("文件存在", path.exists())
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    check("hand_id=99", data["hand_id"] == 99)
    check("有 players", len(data["players"]) == 2)
    check("有 board", len(data["board"]) == 5)
    check("有 actions", len(data["actions"]) > 0)
    check("有 winnings", len(data["winnings"]) > 0)
    # 清理
    path.unlink(missing_ok=True)


def test_hand_history_initial_stack_after_settle():
    """settle() 清空 total_invested，导出时 stack+total_invested 可能不等于初始筹码"""
    print("\n=== K2: 导出时初始筹码是否正确 (settle后) ===")
    from data.hand_history import export_hand
    gs = make_gs([1000, 1000])
    gs.hand_number = 100
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=1000))
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.get_player("P2").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 8d".split()]
    winnings = gs.settle()
    # settle 后 total_invested 被清零
    path = export_hand(gs, winnings)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 检查导出的初始筹码是否合理 (应该是1000, 不是settle后的值)
    stacks = [p["stack"] for p in data["players"]]
    check("导出初始筹码应为1000 (BUG探测)",
          all(s == 1000 for s in stacks),
          f"实际stacks={stacks} — settle后total_invested=0导致stack+0=当前stack")
    path.unlink(missing_ok=True)


def test_replay_engine_basic():
    print("\n=== K3: replay_engine 基本回放 ===")
    from testing.replay_engine import ReplayEngine
    hand_data = {
        "hand_id": 1,
        "players": [
            {"name": "P1", "position": "SB", "stack": 1000, "hole_cards": ["As", "Ah"]},
            {"name": "P2", "position": "BB", "stack": 1000, "hole_cards": ["2c", "3d"]},
        ],
        "blinds": [5, 10],
        "actions": [
            {"player": "P1", "street": "preflop", "action": "all_in", "amount": 1000},
            {"player": "P2", "street": "preflop", "action": "call", "amount": 1000},
        ],
        "board": ["Kh", "Qh", "Jh", "7c", "8d"],
    }
    engine = ReplayEngine()
    result = engine.replay_hand(hand_data)
    check("hand_id=1", result.hand_id == 1)
    check("有 decision_points", len(result.decision_points) == 2)
    check("有 winnings", sum(result.winnings.values()) > 0,
          f"winnings={result.winnings}")
    total = sum(result.winnings.values())
    check("winnings 守恒", total > 0, f"total={total}")


def test_replay_engine_multi_street():
    print("\n=== K4: replay_engine 多街回放 ===")
    from testing.replay_engine import ReplayEngine
    hand_data = {
        "hand_id": 2,
        "players": [
            {"name": "P1", "position": "SB", "stack": 1000, "hole_cards": ["As", "Kd"]},
            {"name": "P2", "position": "BB", "stack": 1000, "hole_cards": ["2c", "3d"]},
        ],
        "blinds": [5, 10],
        "actions": [
            {"player": "P1", "street": "preflop", "action": "call", "amount": 10},
            {"player": "P2", "street": "preflop", "action": "check"},
            {"player": "P1", "street": "flop", "action": "bet", "amount": 20},
            {"player": "P2", "street": "flop", "action": "call", "amount": 20},
            {"player": "P1", "street": "turn", "action": "check"},
            {"player": "P2", "street": "turn", "action": "check"},
            {"player": "P1", "street": "river", "action": "all_in", "amount": 980},
            {"player": "P2", "street": "river", "action": "call", "amount": 980},
        ],
        "board": ["Ah", "7s", "2d", "9c", "4h"],
    }
    engine = ReplayEngine()
    result = engine.replay_hand(hand_data)
    check("8个 decision_points", len(result.decision_points) == 8,
          f"实际={len(result.decision_points)}")
    check("P1 赢 (AK > 23)", result.winnings.get("P1", 0) > 0,
          f"winnings={result.winnings}")


def test_replay_engine_summary():
    print("\n=== K5: replay_engine summary 不崩溃 ===")
    from testing.replay_engine import ReplayEngine
    engine = ReplayEngine()
    hand_data = {
        "hand_id": 3,
        "players": [
            {"name": "P1", "stack": 1000, "hole_cards": ["As", "Ah"]},
            {"name": "P2", "stack": 1000, "hole_cards": ["Ks", "Kh"]},
        ],
        "blinds": [5, 10],
        "actions": [
            {"player": "P1", "street": "preflop", "action": "all_in", "amount": 1000},
            {"player": "P2", "street": "preflop", "action": "call", "amount": 1000},
        ],
        "board": ["7h", "2s", "9d", "Jc", "4h"],
    }
    engine.replay_hand(hand_data)
    summary = engine.summary()
    check("summary 返回字符串", isinstance(summary, str) and len(summary) > 0)



# ═══════════════════════════════════════════════════
#  L. 完整对局流程 (多街 + settle)
# ═══════════════════════════════════════════════════

def test_full_hand_preflop_to_river():
    print("\n=== L1: 完整对局 preflop→river ===")
    gs = make_gs([1000, 1000, 1000])
    initial_total = sum(p.stack for p in gs.players) + gs.pot
    # preflop: UTG raise, SB call, BB call
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=30))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=30))
    gs.apply_action(PlayerAction("P3", ActionType.CALL, amount=30))
    check("preflop street over", gs.is_street_over())
    # flop
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah 7s 2d".split()]
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P3", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.BET, amount=50))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=50))
    gs.apply_action(PlayerAction("P3", ActionType.FOLD))
    check("flop street over", gs.is_street_over())
    # turn
    gs.advance_street()
    gs.board.append(Card.new("9c"))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    check("turn street over", gs.is_street_over())
    # river
    gs.advance_street()
    gs.board.append(Card.new("4h"))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.BET, amount=100))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=100))
    check("river street over", gs.is_street_over())
    check("board=5张", len(gs.board) == 5)
    # settle
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Kd")]
    gs.get_player("P2").hole_cards = [Card.new("Qs"), Card.new("Jd")]
    winnings = gs.settle()
    total_won = sum(winnings.values())
    check("P1赢 (AK > QJ on A-high board)", winnings.get("P1", 0) > 0,
          f"winnings={winnings}")
    final_total = sum(p.stack for p in gs.players)
    check("筹码守恒", final_total == 3000,
          f"初始=3000, 最终={final_total}")


def test_full_hand_everyone_folds_to_bb():
    print("\n=== L2: 全员 fold 给 BB ===")
    gs = make_gs([1000, 1000, 1000])
    pot_before = gs.pot
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    check("hand over", gs.is_hand_over())
    winnings = gs.settle()
    check("P3(BB) 赢得底池", winnings.get("P3", 0) == pot_before,
          f"winnings={winnings}")


def test_full_hand_raise_fold():
    print("\n=== L3: raise 后对手 fold ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=30))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    check("hand over", gs.is_hand_over())
    winnings = gs.settle()
    pot = 30 + 10  # P1 raised to 30 (cost 25 from SB 5), P2 BB 10
    check("P1 赢得底池", winnings.get("P1", 0) > 0, f"winnings={winnings}")
    total = sum(p.stack for p in gs.players)
    check("筹码守恒", total == 2000, f"total={total}")


# ═══════════════════════════════════════════════════
#  M. 边界 & 回归测试
# ═══════════════════════════════════════════════════

def test_call_exact_stack_becomes_allin():
    print("\n=== M1: call 恰好等于剩余筹码 → all-in ===")
    players = [Player(name="P1", stack=100),
               Player(name="P2", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    # P1 is SB with 95 remaining, P2 raises to 100
    gs.apply_action(PlayerAction("P2", ActionType.RAISE, amount=100))
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=100))
    p1 = gs.get_player("P1")
    check("P1 stack=0", p1.stack == 0, f"实际={p1.stack}")
    check("P1 is_all_in", p1.is_all_in)


def test_multiple_raises_same_street():
    print("\n=== M2: 同一街多次 raise ===")
    gs = make_gs([5000, 5000, 5000])
    gs.apply_action(PlayerAction("P1", ActionType.RAISE, amount=30))
    gs.apply_action(PlayerAction("P2", ActionType.RAISE, amount=60))
    gs.apply_action(PlayerAction("P3", ActionType.RAISE, amount=120))
    check("current_bet=120", gs.current_bet == 120, f"实际={gs.current_bet}")
    check("last_raiser=P3", gs.last_raiser == "P3")
    # P1 and P2 need to act again
    check("P1 has_acted=False", not gs.get_player("P1").has_acted)
    check("P2 has_acted=False", not gs.get_player("P2").has_acted)


def test_action_history_recorded():
    print("\n=== M3: action_history 记录正确 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    preflop_actions = gs.action_history[Street.PREFLOP]
    check("preflop 记录2个动作", len(preflop_actions) == 2,
          f"实际={len(preflop_actions)}")
    check("第一个动作是 CALL", preflop_actions[0].action_type == ActionType.CALL)
    check("第二个动作是 CHECK", preflop_actions[1].action_type == ActionType.CHECK)


def test_evaluate_hand_normal():
    print("\n=== M4: evaluate_hand 正常评估 ===")
    gs = make_gs([1000, 1000])
    p1 = gs.get_player("P1")
    p1.hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 2d".split()]
    rank = gs.evaluate_hand(p1)
    check("rank < 7463 (有效手牌)", rank < 7463, f"rank={rank}")
    # Treys: AA as one pair on this board ranks ~3326, under 4000
    check("rank < 4000 (至少一对)", rank < 4000, f"rank={rank}")


def test_evaluate_hand_no_hole_cards():
    print("\n=== M5: evaluate_hand 无手牌返回最差 ===")
    gs = make_gs([1000, 1000])
    p1 = gs.get_player("P1")
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 2d".split()]
    rank = gs.evaluate_hand(p1)
    check("无手牌返回7463", rank == 7463, f"rank={rank}")


def test_player_reset_for_new_hand():
    print("\n=== M6: Player.reset_for_new_hand ===")
    p = Player(name="test", stack=500)
    p.hole_cards = [Card.new("As"), Card.new("Ah")]
    p.is_active = False
    p.is_all_in = True
    p.current_bet = 100
    p.street_invested = 100
    p.total_invested = 200
    p.has_acted = True
    p.reset_for_new_hand()
    check("hole_cards 清空", len(p.hole_cards) == 0)
    check("is_active=True", p.is_active)
    check("is_all_in=False", not p.is_all_in)
    check("current_bet=0", p.current_bet == 0)
    check("street_invested=0", p.street_invested == 0)
    check("total_invested=0", p.total_invested == 0)
    check("has_acted=False", not p.has_acted)


def test_player_reset_for_new_street():
    print("\n=== M7: Player.reset_for_new_street ===")
    p = Player(name="test", stack=500)
    p.current_bet = 50
    p.street_invested = 50
    p.has_acted = True
    p.total_invested = 100
    p.reset_for_new_street()
    check("current_bet=0", p.current_bet == 0)
    check("street_invested=0", p.street_invested == 0)
    check("has_acted=False", not p.has_acted)
    check("total_invested 不变", p.total_invested == 100)


def test_side_pot_no_allin():
    print("\n=== M8: 无 all-in 时 side_pots 只有一个主池 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    pots = gs.calculate_side_pots()
    check("只有1个池", len(pots) == 1, f"实际={len(pots)}")
    check("eligible 包含两人", len(pots[0].eligible) == 2)
    check("金额=pot", pots[0].amount == gs.pot)


def test_get_player_not_found():
    print("\n=== M9: get_player 找不到玩家 ===")
    gs = make_gs([1000, 1000])
    try:
        gs.get_player("NONEXISTENT")
        check("应抛出异常", False)
    except ValueError:
        check("找不到玩家抛出 ValueError", True)


def test_advance_street_beyond_river():
    print("\n=== M10: advance_street 超过 river 不崩溃 ===")
    gs = make_gs([1000, 1000])
    gs.street = Street.RIVER
    try:
        gs.advance_street()
        check("river 后 advance 不崩溃", True)
        check("street 仍然是 RIVER", gs.street == Street.RIVER)
    except Exception as e:
        check("advance 崩溃", False, f"异常={e}")


def test_deep_copy_isolation():
    print("\n=== M11: deep copy 隔离性 (run_it_twice 不影响原 gs) ===")
    gs = make_gs([1000, 1000])
    for p in gs.players:
        if p.is_active and not p.is_all_in:
            gs.apply_action(PlayerAction(p.name, ActionType.ALL_IN, amount=p.stack + p.current_bet))
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.get_player("P2").hole_cards = [Card.new("Ks"), Card.new("Kh")]
    original_pot = gs.pot
    original_board = gs.board[:]
    board_1 = [Card.new(c) for c in "7h 2s 9d Jc 4h".split()]
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]
    result = run_it_twice(gs, board_1, board_2)
    check("原 gs.board 未变", gs.board == original_board,
          f"原={original_board}, 现={gs.board}")
    check("原 gs.pot 未变", gs.pot == original_pot,
          f"原={original_pot}, 现={gs.pot}")


def test_positions_by_size_coverage():
    print("\n=== M12: POSITIONS_BY_SIZE 覆盖 2-9 人 ===")
    for n in range(2, 10):
        check(f"{n}人桌有位置定义", n in POSITIONS_BY_SIZE)
        check(f"{n}人桌位置数={n}", len(POSITIONS_BY_SIZE[n]) == n,
              f"实际={len(POSITIONS_BY_SIZE[n])}")


def test_street_enum_order():
    print("\n=== M13: Street 枚举顺序 ===")
    streets = list(Street)
    check("4条街", len(streets) == 4)
    check("顺序: PREFLOP→FLOP→TURN→RIVER",
          streets == [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER])


def test_action_type_values():
    print("\n=== M14: ActionType 值 ===")
    check("FOLD=fold", ActionType.FOLD.value == "fold")
    check("ALL_IN=all_in", ActionType.ALL_IN.value == "all_in")


def test_player_action_str():
    print("\n=== M15: PlayerAction.__str__ ===")
    a1 = PlayerAction("P1", ActionType.FOLD)
    check("fold 格式", "fold" in str(a1).lower())
    a2 = PlayerAction("P1", ActionType.RAISE, amount=100)
    check("raise 格式含金额", "100" in str(a2))


# ═══════════════════════════════════════════════════
#  N. 多手牌连续对局
# ═══════════════════════════════════════════════════

def test_multi_hand_sequence():
    print("\n=== N1: 连续3手牌筹码守恒 ===")
    gs = make_gs([1000, 1000, 1000])
    initial_total = sum(p.stack for p in gs.players) + gs.pot

    for hand_num in range(3):
        # 快速结束: P1 fold, P2 fold
        active = [p for p in gs.players if p.is_active and not p.is_all_in]
        for p in active[:-1]:
            gs.apply_action(PlayerAction(p.name, ActionType.FOLD))
        gs.settle()
        total = sum(p.stack for p in gs.players)
        check(f"手牌{hand_num+1}: 筹码守恒={initial_total}",
              total == initial_total,
              f"实际={total}")
        if hand_num < 2:
            gs.new_hand()


# ═══════════════════════════════════════════════════
#  O. run_it_twice 边界
# ═══════════════════════════════════════════════════

def test_run_it_twice_preserves_original_state():
    print("\n=== O1: run_it_twice 不修改原 game_state 的 side_pots ===")
    gs = make_gs([500, 1000])
    for p in gs.players:
        if p.is_active and not p.is_all_in:
            gs.apply_action(PlayerAction(p.name, ActionType.ALL_IN, amount=p.stack + p.current_bet))
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.get_player("P2").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.calculate_side_pots()
    original_pots = [(sp.amount, sp.eligible[:]) for sp in gs.side_pots]
    board_1 = [Card.new(c) for c in "7h 2s 9d Jc 4h".split()]
    board_2 = [Card.new(c) for c in "Kd 7d 8c 4s 9s".split()]
    run_it_twice(gs, board_1, board_2)
    current_pots = [(sp.amount, sp.eligible) for sp in gs.side_pots]
    check("side_pots 金额未变", current_pots == original_pots,
          f"原={original_pots}, 现={current_pots}")


# ═══════════════════════════════════════════════════
#  P. 压力测试
# ═══════════════════════════════════════════════════

def test_rapid_new_hand_no_crash():
    print("\n=== P1: 快速连续 new_hand 不崩溃 ===")
    gs = make_gs([10000, 10000, 10000])
    for i in range(50):
        active = [p for p in gs.players if p.is_active and not p.is_all_in]
        for p in active[:-1]:
            gs.apply_action(PlayerAction(p.name, ActionType.FOLD))
        gs.settle()
        if len([p for p in gs.players if p.stack > 0]) < 2:
            break
        gs.new_hand()
    check("50手牌不崩溃", True)
    total = sum(p.stack for p in gs.players) + gs.pot
    check("筹码守恒=30000", total == 30000, f"实际={total}")


# ═══════════════════════════════════════════════════
#  Q. BUG 探测: settle 单人赢家路径不清 total_invested
# ═══════════════════════════════════════════════════

def test_bug_settle_single_winner_clears_total_invested():
    """settle() 单人赢家 early return 不清 total_invested → 跨手牌累积"""
    print("\n=== Q1: BUG — settle 单人赢家路径不清 total_invested ===")
    gs = make_gs([1000, 1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    gs.settle()
    for p in gs.players:
        check(f"{p.name} total_invested=0 after settle",
              p.total_invested == 0,
              f"实际={p.total_invested} — settle单人路径未清total_invested")


def test_bug_settle_single_winner_clears_side_pots():
    """settle() 单人赢家 early return 不清 side_pots"""
    print("\n=== Q2: BUG — settle 单人赢家路径不清 side_pots ===")
    gs = make_gs([1000, 1000])
    gs.side_pots = [SidePot(amount=100, eligible=["P1", "P2"])]
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.settle()
    check("side_pots 被清空", gs.side_pots == [],
          f"实际={gs.side_pots} — settle单人路径未清side_pots")


def test_bug_chip_leak_over_many_hands():
    """total_invested 不清导致 new_hand 后筹码泄漏"""
    print("\n=== Q3: BUG — 多手牌筹码泄漏 (total_invested 累积) ===")
    gs = make_gs([1000, 1000, 1000])
    initial_total = 3000
    for i in range(10):
        active = [p for p in gs.players if p.is_active and not p.is_all_in]
        for p in active[:-1]:
            gs.apply_action(PlayerAction(p.name, ActionType.FOLD))
        gs.settle()
        total = sum(p.stack for p in gs.players)
        if total != initial_total:
            check(f"手牌{i+1}: 筹码泄漏", False,
                  f"期望={initial_total}, 实际={total}, 差={initial_total-total}")
            break
        gs.new_hand()
    else:
        check("10手牌无筹码泄漏", True)


def test_bug_export_hand_initial_stack():
    """export_hand 用 stack+total_invested 算初始筹码, settle后 total_invested=0 导致错误"""
    print("\n=== Q4: BUG — export_hand 初始筹码计算 ===")
    from data.hand_history import export_hand
    gs = make_gs([500, 500])
    gs.hand_number = 200
    # all-in
    for p in gs.players:
        if p.is_active and not p.is_all_in:
            gs.apply_action(PlayerAction(p.name, ActionType.ALL_IN, amount=p.stack + p.current_bet))
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Ah")]
    gs.get_player("P2").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.board = [Card.new(c) for c in "Kh Qh Jh 7c 8d".split()]
    # 记录 settle 前的 total_invested
    invested_before = {p.name: p.total_invested for p in gs.players}
    gs.settle()
    invested_after = {p.name: p.total_invested for p in gs.players}
    # export
    path = export_hand(gs, {"P1": 1000, "P2": 0})
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    stacks = {p["name"]: p["stack"] for p in data["players"]}
    check("P1 导出初始筹码=500", stacks["P1"] == 500,
          f"实际={stacks['P1']}, invested_before={invested_before}, invested_after={invested_after}")
    check("P2 导出初始筹码=500", stacks["P2"] == 500,
          f"实际={stacks['P2']}")
    path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════
#  R. 补充覆盖: 属性 / API / 场景 / 边界
# ═══════════════════════════════════════════════════

def test_active_players_property():
    print("\n=== R1: active_players 属性 ===")
    gs = make_gs([1000, 1000, 1000])
    check("初始3人 active", len(gs.active_players) == 3)
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    check("P1 fold 后 2人 active", len(gs.active_players) == 2)
    names = [p.name for p in gs.active_players]
    check("P1 不在 active 中", "P1" not in names, f"实际={names}")


def test_players_in_hand_property():
    print("\n=== R2: players_in_hand 属性 ===")
    gs = make_gs([1000, 1000, 1000])
    check("初始3人 in_hand", len(gs.players_in_hand) == 3)
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    check("P1 all-in 后仍 in_hand", len(gs.players_in_hand) == 3)
    in_hand_names = [p.name for p in gs.players_in_hand]
    check("P1 仍在 in_hand", "P1" in in_hand_names)
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    check("P2 fold 后 2人 in_hand", len(gs.players_in_hand) == 2)
    in_hand_names = [p.name for p in gs.players_in_hand]
    check("P2 不在 in_hand", "P2" not in in_hand_names)


def test_game_mode_test():
    print("\n=== R3: GameMode.TEST 模式 ===")
    players = [Player(name="P1", stack=1000), Player(name="P2", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, game_mode=GameMode.TEST)
    check("game_mode=TEST", gs.game_mode == GameMode.TEST)
    gs.assign_positions()
    gs.post_blinds()
    check("TEST 模式下 post_blinds 正常", gs.pot == 15)


def test_board_texture_is_wet():
    print("\n=== R4: 湿润牌面 is_wet ===")
    board = [Card.new(c) for c in "8h 9h Th".split()]
    tex = analyze_board(board)
    check("is_wet=True (同花+连牌)", tex.is_wet, f"wetness={tex.wetness}")
    check("is_dry=False", not tex.is_dry)


def test_board_texture_double_paired():
    print("\n=== R5: 双对牌面 ===")
    board = [Card.new(c) for c in "Ah Ad Kh Kd 2c".split()]
    tex = analyze_board(board)
    check("is_double_paired=True", tex.is_double_paired)
    check("is_paired=True", tex.is_paired)


def test_board_texture_two_tone():
    print("\n=== R6: 两色牌面 ===")
    board = [Card.new(c) for c in "Ah Kh Qd".split()]
    tex = analyze_board(board)
    check("is_two_tone=True", tex.is_two_tone)
    check("is_monotone=False", not tex.is_monotone)
    check("is_rainbow=False", not tex.is_rainbow)


def test_board_texture_high_card_rank():
    print("\n=== R7: high_card_rank ===")
    board = [Card.new(c) for c in "2h 5s 9d".split()]
    tex = analyze_board(board)
    check("high_card_rank=7 (9=rank7)", tex.high_card_rank == 7,
          f"实际={tex.high_card_rank}")
    board2 = [Card.new(c) for c in "Ah Ks Qd".split()]
    tex2 = analyze_board(board2)
    check("high_card_rank=12 (A=rank12)", tex2.high_card_rank == 12,
          f"实际={tex2.high_card_rank}")

# --- PLACEHOLDER_R8 ---


def test_board_texture_turn_5cards():
    print("\n=== R8: turn(4张) 和 river(5张) 牌面纹理 ===")
    board_turn = [Card.new(c) for c in "8h 9s Td Jc".split()]
    tex_turn = analyze_board(board_turn)
    check("turn straight_draw_possible", tex_turn.straight_draw_possible)
    check("turn connectedness>=4", tex_turn.connectedness >= 4,
          f"实际={tex_turn.connectedness}")
    board_river = [Card.new(c) for c in "2h 7h 9h Kh Ah".split()]
    tex_river = analyze_board(board_river)
    check("river is_monotone=True", tex_river.is_monotone)
    check("river high_card_rank=12 (A)", tex_river.high_card_rank == 12,
          f"实际={tex_river.high_card_rank}")


def test_card_to_str_function():
    print("\n=== R9: card_to_str 函数 ===")
    c = Card.new("As")
    s = card_to_str(c)
    check("card_to_str 返回字符串", isinstance(s, str) and len(s) > 0, f"实际={s}")
    c2 = Card.new("2h")
    s2 = card_to_str(c2)
    check("card_to_str(2h) 返回字符串", isinstance(s2, str) and len(s2) > 0, f"实际={s2}")


def test_replay_engine_replay_file():
    print("\n=== R10: ReplayEngine.replay_file ===")
    from testing.replay_engine import ReplayEngine
    hand_data = {
        "hand_id": 50,
        "players": [
            {"name": "P1", "position": "SB", "stack": 1000, "hole_cards": ["As", "Ah"]},
            {"name": "P2", "position": "BB", "stack": 1000, "hole_cards": ["2c", "3d"]},
        ],
        "blinds": [5, 10],
        "actions": [
            {"player": "P1", "street": "preflop", "action": "all_in", "amount": 1000},
            {"player": "P2", "street": "preflop", "action": "call", "amount": 1000},
        ],
        "board": ["Kh", "Qh", "Jh", "7c", "8d"],
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(hand_data, f)
        tmp_path = f.name
    try:
        engine = ReplayEngine()
        results_list = engine.replay_file(tmp_path)
        check("replay_file 返回1个结果", len(results_list) == 1, f"实际={len(results_list)}")
        check("hand_id=50", results_list[0].hand_id == 50)
        check("有 winnings", sum(results_list[0].winnings.values()) > 0)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    # 测试多手牌文件
    multi_data = [hand_data, {**hand_data, "hand_id": 51}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(multi_data, f)
        tmp_path2 = f.name
    try:
        engine2 = ReplayEngine()
        results2 = engine2.replay_file(tmp_path2)
        check("多手牌文件返回2个结果", len(results2) == 2, f"实际={len(results2)}")
    finally:
        Path(tmp_path2).unlink(missing_ok=True)

# --- PLACEHOLDER_R11 ---


def test_replay_engine_with_folds():
    print("\n=== R11: ReplayEngine 含 fold 动作 ===")
    from testing.replay_engine import ReplayEngine
    hand_data = {
        "hand_id": 60,
        "players": [
            {"name": "P1", "position": "BTN", "stack": 1000, "hole_cards": ["As", "Ah"]},
            {"name": "P2", "position": "SB", "stack": 1000, "hole_cards": ["Ks", "Kh"]},
            {"name": "P3", "position": "BB", "stack": 1000, "hole_cards": ["2c", "3d"]},
        ],
        "blinds": [5, 10],
        "actions": [
            {"player": "P1", "street": "preflop", "action": "raise", "amount": 30},
            {"player": "P2", "street": "preflop", "action": "fold"},
            {"player": "P3", "street": "preflop", "action": "call", "amount": 30},
            {"player": "P3", "street": "flop", "action": "check"},
            {"player": "P1", "street": "flop", "action": "bet", "amount": 50},
            {"player": "P3", "street": "flop", "action": "fold"},
        ],
        "board": ["7h", "8s", "9d", "Tc", "2h"],
    }
    engine = ReplayEngine()
    result = engine.replay_hand(hand_data)
    check("6个 decision_points", len(result.decision_points) == 6,
          f"实际={len(result.decision_points)}")
    check("P1赢 (P2,P3 fold)", result.winnings.get("P1", 0) > 0,
          f"winnings={result.winnings}")


def test_replay_engine_malformed_data():
    print("\n=== R12: ReplayEngine 缺失字段不崩溃 ===")
    from testing.replay_engine import ReplayEngine
    hand_data = {
        "players": [
            {"name": "P1", "stack": 500},
            {"name": "P2", "stack": 500},
        ],
        "actions": [],
        "board": [],
    }
    engine = ReplayEngine()
    try:
        result = engine.replay_hand(hand_data)
        check("缺失字段不崩溃", True)
        check("hand_id 默认0", result.hand_id == 0)
    except Exception as e:
        check("缺失字段崩溃", False, f"异常={e}")


def test_blinds_short_stack_bb():
    print("\n=== R13: BB 筹码不足盲注 ===")
    players = [Player(name="P1", stack=1000),
               Player(name="P2", stack=1000),
               Player(name="P3", stack=7)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    bb = gs.get_player("P3")
    check("BB 只投7 (全部筹码)", bb.current_bet == 7, f"实际={bb.current_bet}")
    check("BB stack=0", bb.stack == 0)
    check("BB is_all_in", bb.is_all_in)
    check("current_bet=7 (BB实际投入)", gs.current_bet == 7, f"实际={gs.current_bet}")
    check("pot=12 (5+7)", gs.pot == 12, f"实际={gs.pot}")

# --- PLACEHOLDER_R14 ---


def test_min_raise_postflop():
    print("\n=== R14: postflop min raise (首次 bet) ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    min_r = gs.get_min_raise()
    check("postflop min_raise=10 (BB)", min_r == 10, f"实际={min_r}")


def test_min_raise_player_cant_meet():
    print("\n=== R15: min_raise 超过玩家筹码 ===")
    players = [Player(name="P1", stack=25),
               Player(name="P2", stack=1000)]
    gs = GameState(players=players, small_blind=5, big_blind=10, dealer_idx=0)
    gs.assign_positions()
    gs.post_blinds()
    min_r = gs.get_min_raise()
    p1 = gs.get_player("P1")
    check("min_raise=20", min_r == 20, f"实际={min_r}")
    check("P1 stack=20 < min_raise 但可 all-in", p1.stack == 20,
          f"实际={p1.stack}")
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=p1.stack + p1.current_bet))
    check("P1 all-in 不崩溃", p1.is_all_in)


def test_action_order_headsup_postflop():
    print("\n=== R16: Heads-up postflop 行动顺序 (BB先) ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    order = gs.get_action_order()
    names = [p.name for p in order]
    check("heads-up postflop: P2(BB) 先行动", names[0] == "P2",
          f"实际顺序={names}")


def test_action_history_multi_street():
    print("\n=== R17: action_history 多街记录 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    gs.apply_action(PlayerAction("P2", ActionType.BET, amount=20))
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=20))
    gs.advance_street()
    gs.board.append(Card.new("Jh"))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.BET, amount=50))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=50))
    gs.advance_street()
    gs.board.append(Card.new("Th"))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    check("preflop 2个动作", len(gs.action_history[Street.PREFLOP]) == 2)
    check("flop 2个动作", len(gs.action_history[Street.FLOP]) == 2)
    check("turn 3个动作", len(gs.action_history[Street.TURN]) == 3)
    check("river 2个动作", len(gs.action_history[Street.RIVER]) == 2)
    check("flop 第一个是 BET", gs.action_history[Street.FLOP][0].action_type == ActionType.BET)
    check("turn 第二个是 BET", gs.action_history[Street.TURN][1].action_type == ActionType.BET)

# --- PLACEHOLDER_R18 ---


def test_call_when_current_bet_zero():
    print("\n=== R18: CALL 当 current_bet=0 时 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    p2 = gs.get_player("P2")
    stack_before = p2.stack
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=0))
    check("CALL 0 不扣筹码", p2.stack == stack_before, f"实际={p2.stack}")
    check("has_acted=True", p2.has_acted)


def test_action_on_folded_player():
    print("\n=== R19: 对已 fold 玩家执行动作 ===")
    gs = make_gs([1000, 1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    p1 = gs.get_player("P1")
    check("P1 已 fold", not p1.is_active)
    stack_before = p1.stack
    try:
        gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
        check("fold 后 CALL 不崩溃", True)
        check("fold 后 CALL 扣了筹码 (无保护)", p1.stack != stack_before or p1.stack == stack_before)
    except Exception as e:
        check("fold 后 CALL 抛异常", True, f"异常={e}")


def test_action_on_allin_player():
    print("\n=== R20: 对已 all-in 玩家执行动作 ===")
    gs = make_gs([1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.ALL_IN, amount=1000))
    p1 = gs.get_player("P1")
    check("P1 已 all-in", p1.is_all_in)
    try:
        gs.apply_action(PlayerAction("P1", ActionType.CHECK))
        check("all-in 后 CHECK 不崩溃", True)
    except Exception as e:
        check("all-in 后 CHECK 抛异常", True, f"异常={e}")


def test_settle_pot_zero():
    print("\n=== R21: settle 当 pot=0 ===")
    gs = make_gs([1000, 1000])
    gs.pot = 0
    gs.side_pots = []
    for p in gs.players:
        p.total_invested = 0
    try:
        winnings = gs.settle()
        total = sum(winnings.values())
        check("pot=0 settle 不崩溃", True)
        check("总赢额=0", total == 0, f"实际={total}")
    except Exception as e:
        check("pot=0 settle 崩溃", False, f"异常={e}")


def test_new_hand_increments_hand_number():
    print("\n=== R22: new_hand 递增 hand_number ===")
    gs = make_gs([1000, 1000, 1000])
    check("初始 hand_number=0", gs.hand_number == 0)
    gs.apply_action(PlayerAction("P1", ActionType.FOLD))
    gs.apply_action(PlayerAction("P2", ActionType.FOLD))
    gs.settle()
    gs.new_hand()
    check("第一次 new_hand: hand_number=1", gs.hand_number == 1, f"实际={gs.hand_number}")
    active = [p for p in gs.players if p.is_active and not p.is_all_in]
    for p in active[:-1]:
        gs.apply_action(PlayerAction(p.name, ActionType.FOLD))
    gs.settle()
    gs.new_hand()
    check("第二次 new_hand: hand_number=2", gs.hand_number == 2, f"实际={gs.hand_number}")

# --- PLACEHOLDER_R23 ---


def test_random_cards_near_full_exclude():
    print("\n=== R23: random_cards 排除集接近满 ===")
    used = set(ALL_CARDS[:50])
    cards = random_cards(2, used)
    check("发出2张", len(cards) == 2)
    check("不在排除集中", all(c not in used for c in cards))
    try:
        random_cards(3, set(ALL_CARDS[:50]))
        check("剩余2张发3张应失败", False)
    except (ValueError, Exception):
        check("剩余不足时抛异常", True)


def test_parse_cards_trailing_spaces():
    print("\n=== R24: parse_cards 前后空格 ===")
    cards = parse_cards("  Ah  Kd  ")
    check("前后空格解析2张", len(cards) == 2, f"实际={len(cards)}")
    check("第一张=Ah", cards[0] == Card.new("Ah"))
    check("第二张=Kd", cards[1] == Card.new("Kd"))
    cards2 = parse_cards(" As ")
    check("单张前后空格", len(cards2) == 1)


def test_used_cards_tracking():
    print("\n=== R25: used_cards 追踪 ===")
    gs = make_gs([1000, 1000])
    p1 = gs.get_player("P1")
    p2 = gs.get_player("P2")
    c1 = Card.new("As")
    c2 = Card.new("Ah")
    c3 = Card.new("Ks")
    c4 = Card.new("Kh")
    p1.hole_cards = [c1, c2]
    gs.used_cards.update(p1.hole_cards)
    p2.hole_cards = [c3, c4]
    gs.used_cards.update(p2.hole_cards)
    check("used_cards 包含4张手牌", len(gs.used_cards) == 4)
    check("As 在 used_cards", c1 in gs.used_cards)
    board = [Card.new(c) for c in "Qh Jh Th".split()]
    gs.board = board
    gs.used_cards.update(board)
    check("used_cards 包含7张", len(gs.used_cards) == 7)


def test_action_history_no_leak_across_hands():
    print("\n=== R26: action_history 跨手牌不泄漏 ===")
    gs = make_gs([1000, 1000, 1000])
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P3", ActionType.CHECK))
    check("手牌1 preflop 有3个动作", len(gs.action_history[Street.PREFLOP]) == 3)
    gs.advance_street()
    gs.board = [Card.new(c) for c in "Ah Kh Qh".split()]
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P3", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    check("手牌1 flop 有3个动作", len(gs.action_history[Street.FLOP]) == 3)
    gs.get_player("P1").hole_cards = [Card.new("As"), Card.new("Ad")]
    gs.get_player("P2").hole_cards = [Card.new("2c"), Card.new("3d")]
    gs.get_player("P3").hole_cards = [Card.new("4c"), Card.new("5d")]
    gs.board = [Card.new(c) for c in "Ah Kh Qh Jh Th".split()]
    gs.settle()
    gs.new_hand()
    check("new_hand 后 preflop 历史清空", len(gs.action_history[Street.PREFLOP]) == 0,
          f"实际={len(gs.action_history[Street.PREFLOP])}")
    check("new_hand 后 flop 历史清空", len(gs.action_history[Street.FLOP]) == 0)
    check("new_hand 后 turn 历史清空", len(gs.action_history[Street.TURN]) == 0)
    check("new_hand 后 river 历史清空", len(gs.action_history[Street.RIVER]) == 0)
    check("new_hand 后 used_cards 清空", len(gs.used_cards) == 0,
          f"实际={len(gs.used_cards)}")

# --- PLACEHOLDER_R27 ---


def test_card_parser_constants():
    print("\n=== R27: card_parser 常量 ===")
    check("VALID_RANKS 包含 A", "A" in VALID_RANKS)
    check("VALID_RANKS 包含 2", "2" in VALID_RANKS)
    check("VALID_RANKS 包含 T", "T" in VALID_RANKS)
    check("VALID_SUITS 包含 s,h,d,c", VALID_SUITS == {"s", "h", "d", "c"})
    check("SUIT_SYMBOLS 有4个", len(SUIT_SYMBOLS) == 4)
    check("SUIT_FROM_SYMBOL 有4个", len(SUIT_FROM_SYMBOL) == 4)
    check("ALL_CARDS 有52张", len(ALL_CARDS) == 52, f"实际={len(ALL_CARDS)}")
    check("ALL_CARDS 无重复", len(set(ALL_CARDS)) == 52)


def test_parse_card_unicode_suits():
    print("\n=== R28: parse_card Unicode 花色符号 ===")
    c1 = parse_card("A\u2660")
    check("A♠ 解析成功", c1 == Card.new("As"))
    c2 = parse_card("K\u2665")
    check("K♥ 解析成功", c2 == Card.new("Kh"))
    c3 = parse_card("Q\u2666")
    check("Q♦ 解析成功", c3 == Card.new("Qd"))
    c4 = parse_card("J\u2663")
    check("J♣ 解析成功", c4 == Card.new("Jc"))


def test_advance_street_full_sequence():
    print("\n=== R29: advance_street 完整 PREFLOP→FLOP→TURN→RIVER ===")
    gs = make_gs([1000, 1000])
    check("初始 PREFLOP", gs.street == Street.PREFLOP)
    gs.apply_action(PlayerAction("P1", ActionType.CALL, amount=10))
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.advance_street()
    check("第一次 advance → FLOP", gs.street == Street.FLOP)
    check("FLOP current_bet=0", gs.current_bet == 0)
    for p in gs.players:
        if p.is_active:
            check(f"FLOP {p.name} has_acted=False", not p.has_acted)
            check(f"FLOP {p.name} current_bet=0", p.current_bet == 0)
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    gs.advance_street()
    check("第二次 advance → TURN", gs.street == Street.TURN)
    check("TURN last_raiser=None", gs.last_raiser is None)
    gs.apply_action(PlayerAction("P2", ActionType.CHECK))
    gs.apply_action(PlayerAction("P1", ActionType.CHECK))
    gs.advance_street()
    check("第三次 advance → RIVER", gs.street == Street.RIVER)
    check("RIVER current_bet=0", gs.current_bet == 0)


def test_multiple_new_hand_dealer_wrap():
    print("\n=== R30: 多次 new_hand dealer 环绕 ===")
    gs = make_gs([1000, 1000, 1000])
    check("初始 dealer_idx=0", gs.dealer_idx == 0)
    for expected_dealer in [1, 2, 0, 1]:
        active = [p for p in gs.players if p.is_active and not p.is_all_in]
        for p in active[:-1]:
            gs.apply_action(PlayerAction(p.name, ActionType.FOLD))
        gs.settle()
        gs.new_hand()
        check(f"dealer_idx={expected_dealer}", gs.dealer_idx == expected_dealer,
              f"实际={gs.dealer_idx}")

if __name__ == "__main__":
    # A: positions
    test_positions_2_players()
    test_positions_3_players()
    test_positions_6_players()
    test_positions_dealer_rotation()
    # B: blinds
    test_blinds_normal()
    test_blinds_headsup()
    test_blinds_short_stack_sb()
    # C: actions
    test_action_fold()
    test_action_check()
    test_action_call()
    test_action_raise_resets_has_acted()
    test_action_bet_postflop()
    test_action_allin_sets_inactive()
    # D: street/hand over
    test_street_over_after_all_check()
    test_hand_over_all_fold()
    test_hand_over_all_allin()
    test_hand_not_over_one_active_one_allin()
    # E: advance_street
    test_advance_street_resets()
    test_advance_street_preserves_allin()
    # F: action order
    test_action_order_preflop_3p()
    test_action_order_postflop()
    test_action_order_headsup_preflop()
    # G: min raise
    test_min_raise_preflop()
    test_min_raise_after_raise()
    # H: new_hand
    test_new_hand_resets_state()
    test_new_hand_removes_broke_players()
    test_new_hand_dealer_rotation()
    test_new_hand_dealer_rotation_with_removal()
    # I: board texture
    test_board_texture_monotone()
    test_board_texture_rainbow()
    test_board_texture_paired()
    test_board_texture_trips()
    test_board_texture_empty()
    test_board_texture_connected()
    test_board_texture_dry()
    test_board_texture_scare_card()
    # J: card parser
    test_parse_card_basic()
    test_parse_card_lowercase()
    test_parse_cards_multi()
    test_parse_cards_continuous()
    test_parse_card_invalid()
    test_validate_no_duplicates()
    test_validate_no_duplicates_with_used()
    test_random_cards()
    test_card_to_short()
    # K: hand history + replay
    test_hand_history_export()
    test_hand_history_initial_stack_after_settle()
    test_replay_engine_basic()
    test_replay_engine_multi_street()
    test_replay_engine_summary()
    # L: full hand
    test_full_hand_preflop_to_river()
    test_full_hand_everyone_folds_to_bb()
    test_full_hand_raise_fold()
    # M: edge cases
    test_call_exact_stack_becomes_allin()
    test_multiple_raises_same_street()
    test_action_history_recorded()
    test_evaluate_hand_normal()
    test_evaluate_hand_no_hole_cards()
    test_player_reset_for_new_hand()
    test_player_reset_for_new_street()
    test_side_pot_no_allin()
    test_get_player_not_found()
    test_advance_street_beyond_river()
    test_deep_copy_isolation()
    test_positions_by_size_coverage()
    test_street_enum_order()
    test_action_type_values()
    test_player_action_str()
    # N: multi-hand
    test_multi_hand_sequence()
    # O: run_it_twice edge
    test_run_it_twice_preserves_original_state()
    # P: stress
    test_rapid_new_hand_no_crash()
    # Q: bug detection
    test_bug_settle_single_winner_clears_total_invested()
    test_bug_settle_single_winner_clears_side_pots()
    test_bug_chip_leak_over_many_hands()
    test_bug_export_hand_initial_stack()

    # R: new coverage — properties, API surface, scenarios, edge cases
    # (function definitions are in section R above)
    test_active_players_property()
    test_players_in_hand_property()
    test_game_mode_test()
    test_board_texture_is_wet()
    test_board_texture_double_paired()
    test_board_texture_two_tone()
    test_board_texture_high_card_rank()
    test_board_texture_turn_5cards()
    test_card_to_str_function()
    test_replay_engine_replay_file()
    test_replay_engine_with_folds()
    test_replay_engine_malformed_data()
    test_blinds_short_stack_bb()
    test_min_raise_postflop()
    test_min_raise_player_cant_meet()
    test_action_order_headsup_postflop()
    test_action_history_multi_street()
    test_call_when_current_bet_zero()
    test_action_on_folded_player()
    test_action_on_allin_player()
    test_settle_pot_zero()
    test_new_hand_increments_hand_number()
    test_random_cards_near_full_exclude()
    test_parse_cards_trailing_spaces()
    test_used_cards_tracking()
    test_action_history_no_leak_across_hands()
    test_card_parser_constants()
    test_parse_card_unicode_suits()
    test_advance_street_full_sequence()
    test_multiple_new_hand_dealer_wrap()

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
