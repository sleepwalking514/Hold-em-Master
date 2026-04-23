"""Comprehensive chip tracking - log total after every operation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import env.game_state as gs_mod

_orig_settle = gs_mod.GameState.settle
_orig_post_blinds = gs_mod.GameState.post_blinds
_orig_new_hand = gs_mod.GameState.new_hand
_orig_apply_action = gs_mod.GameState.apply_action

all_events = []

def _total(gs):
    return sum(p.stack for p in gs.players) + gs.pot

def _patched_settle(self):
    before = _total(self)
    # Capture side pot state
    if not self.side_pots:
        self.calculate_side_pots()
    sp_info = [(sp.amount, sp.eligible[:]) for sp in self.side_pots]
    sp_sum = sum(sp.amount for sp in self.side_pots)
    in_hand = [(p.name, p.is_active, p.is_all_in, p.total_invested) for p in self.players_in_hand]
    all_invested = [(p.name, p.total_invested, p.is_active, p.is_all_in) for p in self.players]

    result = _orig_settle(self)
    after = _total(self)
    diff = after - before
    all_events.append(("settle", self.hand_number, before, after, diff))
    if diff != 0:
        print(f"\n  *** LEAK in settle() hand #{self.hand_number}: {diff:+d} ***")
        print(f"      pot={self.pot + sum(result.values())}, sp_sum={sp_sum}")
        print(f"      side_pots={sp_info}")
        print(f"      in_hand={in_hand}")
        print(f"      all_invested={all_invested}")
        print(f"      winnings={result}")
    return result

def _patched_post_blinds(self):
    before = _total(self)
    _orig_post_blinds(self)
    after = _total(self)
    diff = after - before
    all_events.append(("post_blinds", self.hand_number, before, after, diff))
    if diff != 0:
        print(f"\n  *** LEAK in post_blinds() hand #{self.hand_number}: {diff:+d} ***")
        print(f"      pot={self.pot}, stacks={[(p.name, p.stack) for p in self.players]}")

def _patched_new_hand(self):
    before = _total(self)
    before_players = [(p.name, p.stack) for p in self.players]
    _orig_new_hand(self)
    after = _total(self)
    after_players = [(p.name, p.stack) for p in self.players]
    removed = set(n for n, _ in before_players) - set(n for n, _ in after_players)
    removed_chips = sum(s for n, s in before_players if n in removed)
    effective_diff = after - (before - removed_chips)
    all_events.append(("new_hand", self.hand_number, before, after, effective_diff, removed, removed_chips))
    if effective_diff != 0:
        print(f"\n  *** LEAK in new_hand() hand #{self.hand_number}: {effective_diff:+d} ***")
        print(f"      before={before_players}, after={after_players}")
        print(f"      removed={removed} (chips={removed_chips})")

def _patched_apply_action(self, action):
    before = _total(self)
    _orig_apply_action(self, action)
    after = _total(self)
    diff = after - before
    all_events.append(("apply_action", self.hand_number, before, after, diff, f"{action.player_name} {action.action_type.name} {action.amount}"))
    if diff != 0:
        print(f"\n  *** LEAK in apply_action() hand #{self.hand_number}: {diff:+d} ***")
        print(f"      action: {action.player_name} {action.action_type.name} {action.amount}")

gs_mod.GameState.settle = _patched_settle
gs_mod.GameState.post_blinds = _patched_post_blinds
gs_mod.GameState.new_hand = _patched_new_hand
gs_mod.GameState.apply_action = _patched_apply_action

from main import run_sim_auto_mode

print("=" * 60)
print("Running sim-auto-solo with 10 hands")
print("=" * 60)

run_sim_auto_mode(max_hands=10, num_ai_opponents=1)

print(f"\n{'=' * 60}")
print("Event log:")
for e in all_events:
    if e[0] in ("settle", "post_blinds") or (len(e) > 4 and e[4] != 0):
        print(f"  {e}")
leaks = [e for e in all_events if len(e) > 4 and e[4] != 0]
print(f"\nTotal leaks: {len(leaks)}")
if leaks:
    total_leaked = sum(e[4] for e in leaks)
    print(f"Total chips leaked: {total_leaked}")
print("=" * 60)
