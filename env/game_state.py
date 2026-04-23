from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

from treys import Card, Evaluator

from env.action_space import ActionType, PlayerAction, Street, GameMode, POSITIONS_BY_SIZE

EVALUATOR = Evaluator()


@dataclass
class Player:
    name: str
    stack: int
    position: str = ""
    hole_cards: list[int] = field(default_factory=list)
    is_active: bool = True
    is_all_in: bool = False
    current_bet: int = 0
    street_invested: int = 0
    total_invested: int = 0
    has_acted: bool = False
    initial_stack: int = 0

    def reset_for_new_street(self) -> None:
        self.current_bet = 0
        self.street_invested = 0
        self.has_acted = False

    def reset_for_new_hand(self) -> None:
        self.hole_cards = []
        self.is_active = True
        self.is_all_in = False
        self.current_bet = 0
        self.street_invested = 0
        self.total_invested = 0
        self.has_acted = False
        self.initial_stack = self.stack


@dataclass
class SidePot:
    amount: int
    eligible: list[str]


class GameState:
    def __init__(self, players: list[Player], small_blind: int = 5, big_blind: int = 10,
                 dealer_idx: int = 0, game_mode: GameMode = GameMode.LIVE) -> None:
        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.dealer_idx = dealer_idx
        self.game_mode = game_mode
        self.board: list[int] = []
        self.street = Street.PREFLOP
        self.pot = 0
        self.side_pots: list[SidePot] = []
        self.action_history: dict[Street, list[PlayerAction]] = {s: [] for s in Street}
        self.current_bet = 0
        self.last_raiser: Optional[str] = None
        self.last_raise_size = 0
        self.hand_number = 0
        self.used_cards: set[int] = set()
        self._action_idx = 0

    # --- player lookup ---

    def get_player(self, name: str) -> Player:
        for p in self.players:
            if p.name == name:
                return p
        raise ValueError(f"Player {name} not found")

    @property
    def active_players(self) -> list[Player]:
        return [p for p in self.players if p.is_active]

    @property
    def players_in_hand(self) -> list[Player]:
        return [p for p in self.players if p.is_active or p.is_all_in]

    # --- positions ---

    def assign_positions(self) -> None:
        n = len(self.players)
        positions = POSITIONS_BY_SIZE.get(n, POSITIONS_BY_SIZE[9][:n])
        for i, p in enumerate(self.players):
            p.position = positions[(i - self.dealer_idx) % n]

    # --- blinds ---

    def post_blinds(self) -> None:
        for p in self.players:
            if p.initial_stack == 0:
                p.initial_stack = p.stack

        n = len(self.players)
        if n == 2:
            sb_idx = self.dealer_idx
            bb_idx = (self.dealer_idx + 1) % n
        else:
            sb_idx = (self.dealer_idx + 1) % n
            bb_idx = (self.dealer_idx + 2) % n

        sb_player = self.players[sb_idx]
        bb_player = self.players[bb_idx]

        sb_amount = min(self.small_blind, sb_player.stack)
        sb_player.stack -= sb_amount
        sb_player.current_bet = sb_amount
        sb_player.street_invested = sb_amount
        sb_player.total_invested = sb_amount
        if sb_player.stack == 0:
            sb_player.is_all_in = True

        bb_amount = min(self.big_blind, bb_player.stack)
        bb_player.stack -= bb_amount
        bb_player.current_bet = bb_amount
        bb_player.street_invested = bb_amount
        bb_player.total_invested = bb_amount
        if bb_player.stack == 0:
            bb_player.is_all_in = True

        self.pot = sb_amount + bb_amount
        self.current_bet = bb_amount

    # --- action processing ---

    def apply_action(self, action: PlayerAction) -> None:
        player = self.get_player(action.player_name)
        at = action.action_type

        if at == ActionType.FOLD:
            player.is_active = False
            player.has_acted = True

        elif at == ActionType.CHECK:
            player.has_acted = True

        elif at == ActionType.CALL:
            call_amount = min(self.current_bet - player.current_bet, player.stack)
            player.stack -= call_amount
            player.current_bet += call_amount
            player.street_invested += call_amount
            player.total_invested += call_amount
            self.pot += call_amount
            if player.stack == 0:
                player.is_all_in = True
                action.is_all_in = True
            player.has_acted = True

        elif at in (ActionType.BET, ActionType.RAISE):
            raise_to = action.amount
            cost = raise_to - player.current_bet
            actual_cost = min(cost, player.stack)
            actual_raise_to = player.current_bet + actual_cost

            # Guard against malformed AI/user actions that do not move the state
            # forward. Treat them as the passive action the player is actually
            # able to take instead of resetting the street forever.
            if actual_raise_to <= self.current_bet:
                if self.current_bet > player.current_bet:
                    call_amount = min(self.current_bet - player.current_bet, player.stack)
                    player.stack -= call_amount
                    player.current_bet += call_amount
                    player.street_invested += call_amount
                    player.total_invested += call_amount
                    self.pot += call_amount
                    if player.stack == 0:
                        player.is_all_in = True
                        action.is_all_in = True
                    action.action_type = ActionType.CALL
                    action.amount = self.current_bet
                    player.has_acted = True
                else:
                    action.action_type = ActionType.CHECK
                    action.amount = 0
                    player.has_acted = True
                action.street = self.street
                self.action_history[self.street].append(action)
                return

            raise_size = actual_raise_to - self.current_bet
            player.stack -= actual_cost
            player.current_bet = actual_raise_to
            player.street_invested += actual_cost
            player.total_invested += actual_cost
            self.pot += actual_cost
            self.last_raise_size = raise_size
            self.last_raiser = player.name
            self.current_bet = actual_raise_to
            if player.stack == 0:
                player.is_all_in = True
                action.is_all_in = True
            for p in self.active_players:
                if p.name != player.name and not p.is_all_in:
                    p.has_acted = False
            player.has_acted = True

        elif at == ActionType.ALL_IN:
            all_in_amount = player.stack
            total_bet = player.current_bet + all_in_amount
            if total_bet > self.current_bet:
                self.last_raise_size = total_bet - self.current_bet
                self.last_raiser = player.name
                self.current_bet = total_bet
                for p in self.active_players:
                    if p.name != player.name and not p.is_all_in:
                        p.has_acted = False
            player.stack -= all_in_amount
            player.current_bet = total_bet
            player.street_invested += all_in_amount
            player.total_invested += all_in_amount
            self.pot += all_in_amount
            player.is_all_in = True
            player.is_active = False
            action.is_all_in = True
            player.has_acted = True

        action.street = self.street
        self.action_history[self.street].append(action)

    # --- street management ---

    def is_street_over(self) -> bool:
        active = [p for p in self.players if p.is_active and not p.is_all_in]
        if len(active) <= 1 and all(p.has_acted for p in active):
            return True
        if not active:
            return True
        return all(
            p.has_acted and p.current_bet == self.current_bet
            for p in active
        )

    def is_hand_over(self) -> bool:
        in_hand = self.players_in_hand
        if len(in_hand) <= 1:
            return True
        active_not_allin = [p for p in in_hand if p.is_active and not p.is_all_in]
        if len(active_not_allin) == 0:
            return True
        if len(active_not_allin) == 1 and len(in_hand) == 1:
            return True
        return False

    def advance_street(self) -> None:
        order = [Street.PREFLOP, Street.FLOP, Street.TURN, Street.RIVER]
        idx = order.index(self.street)
        if idx < 3:
            self.street = order[idx + 1]
            self.current_bet = 0
            self.last_raiser = None
            self.last_raise_size = 0
            for p in self.players:
                p.current_bet = 0
                if p.is_active:
                    p.reset_for_new_street()

    # --- side pots ---

    def calculate_side_pots(self) -> list[SidePot]:
        contributions: list[tuple[int, str]] = []
        for p in self.players:
            if p.total_invested > 0:
                contributions.append((p.total_invested, p.name))

        all_in_levels = sorted(set(
            p.total_invested for p in self.players if p.is_all_in and p.total_invested > 0
        ))

        if not all_in_levels:
            eligible = [p.name for p in self.players_in_hand]
            self.side_pots = [SidePot(amount=self.pot, eligible=eligible)]
            return self.side_pots

        pots: list[SidePot] = []
        prev_level = 0
        for level in all_in_levels:
            pot_amount = 0
            eligible = []
            for invested, name in contributions:
                contribution = min(invested, level) - min(invested, prev_level)
                pot_amount += contribution
                if invested >= level:
                    p = self.get_player(name)
                    if p.is_active or p.is_all_in:
                        eligible.append(name)
            if pot_amount > 0:
                pots.append(SidePot(amount=pot_amount, eligible=eligible))
            prev_level = level

        remaining = 0
        eligible = []
        for invested, name in contributions:
            leftover = invested - min(invested, prev_level)
            remaining += leftover
            if leftover > 0 or invested > prev_level:
                p = self.get_player(name)
                if p.is_active or p.is_all_in:
                    eligible.append(name)
        if remaining > 0:
            pots.append(SidePot(amount=remaining, eligible=eligible))

        self.side_pots = pots
        return pots

    # --- showdown & settlement ---

    def evaluate_hand(self, player: Player) -> int:
        if len(player.hole_cards) != 2 or len(self.board) < 5:
            return 7463
        return EVALUATOR.evaluate(self.board, player.hole_cards)

    def settle(self) -> dict[str, int]:
        winnings: dict[str, int] = {p.name: 0 for p in self.players}
        in_hand = self.players_in_hand

        if len(in_hand) == 1:
            winner = in_hand[0]
            winnings[winner.name] = self.pot
            winner.stack += self.pot
            self.pot = 0
            self.side_pots = []
            for p in self.players:
                p.total_invested = 0
            return winnings

        if not self.side_pots:
            self.calculate_side_pots()

        for side_pot in self.side_pots:
            contenders = [
                self.get_player(name) for name in side_pot.eligible
                if self.get_player(name) in in_hand and len(self.get_player(name).hole_cards) == 2
            ]
            if not contenders:
                if side_pot.eligible:
                    p = self.get_player(side_pot.eligible[0])
                    winnings[p.name] += side_pot.amount
                    p.stack += side_pot.amount
                continue

            best_rank = min(self.evaluate_hand(p) for p in contenders)
            winners = [p for p in contenders if self.evaluate_hand(p) == best_rank]
            share = side_pot.amount // len(winners)
            remainder = side_pot.amount % len(winners)
            for i, w in enumerate(winners):
                amount = share + (1 if i < remainder else 0)
                winnings[w.name] += amount
                w.stack += amount

        self.pot = 0
        self.side_pots = []
        for p in self.players:
            p.total_invested = 0
        return winnings

    # --- new hand ---

    def new_hand(self) -> None:
        self.hand_number += 1
        self.board = []
        self.street = Street.PREFLOP
        self.pot = 0
        self.side_pots = []
        self.action_history = {s: [] for s in Street}
        self.current_bet = 0
        self.last_raiser = None
        self.last_raise_size = 0
        self.used_cards = set()
        self._action_idx = 0

        self.players = [p for p in self.players if p.stack > 0]
        for p in self.players:
            p.reset_for_new_hand()

        self.dealer_idx = (self.dealer_idx + 1) % len(self.players)
        self.assign_positions()
        self.post_blinds()

    # --- action order ---

    def get_action_order(self) -> list[Player]:
        n = len(self.players)
        if self.street == Street.PREFLOP:
            if n == 2:
                start = self.dealer_idx
            else:
                start = (self.dealer_idx + 3) % n
        else:
            start = (self.dealer_idx + 1) % n

        order = []
        for i in range(n):
            p = self.players[(start + i) % n]
            if p.is_active and not p.is_all_in:
                order.append(p)
        return order

    def get_min_raise(self) -> int:
        return max(self.current_bet + self.last_raise_size, self.current_bet + self.big_blind)
