from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from treys import Card

from env.game_state import GameState, Player
from env.action_space import ActionType, PlayerAction, Street
from engine.advisor import Advisor
from profiler.player_profile import PlayerProfile
from testing.simulation.ai_opponent import AIOpponent
from testing.simulation.sim_dealer import SimDealer
from testing.simulation.label_presets import AIOpponentConfig, get_preset


@dataclass
class SimPlayer:
    name: str
    config: AIOpponentConfig
    ai: AIOpponent
    stack: int = 1000
    is_hero: bool = False


@dataclass
class HandResult:
    hand_id: int
    winner: str
    pot_size: int
    hero_profit: int
    showdown: bool
    hero_cards: list[int] = field(default_factory=list)
    board: list[int] = field(default_factory=list)
    all_hole_cards: dict[str, list[int]] = field(default_factory=dict)


class SimGameLoop:
    def __init__(
        self,
        player_configs: list[tuple[str, str]],
        hero_name: str = "Hero",
        starting_stack: int = 1000,
        big_blind: int = 10,
        seed: int | None = None,
    ):
        self.big_blind = big_blind
        self.hero_name = hero_name
        self.dealer = SimDealer(seed)
        self.advisor = Advisor()
        self.hand_count = 0
        self.results: list[HandResult] = []

        self.players: list[SimPlayer] = []
        for name, label in player_configs:
            config = get_preset(label)
            ai = AIOpponent(config, seed=(seed + hash(name)) if seed else None)
            is_hero = (name == hero_name)
            self.players.append(SimPlayer(
                name=name, config=config, ai=ai,
                stack=starting_stack, is_hero=is_hero,
            ))

        profiles = {}
        for sp in self.players:
            if not sp.is_hero:
                profiles[sp.name] = PlayerProfile(sp.name, "未知")
        self.advisor.set_profiles(profiles)

    def run_hand(self, hero_auto: bool = True) -> HandResult:
        self.hand_count += 1
        self.dealer.new_hand()
        self.advisor.reset_hand()

        active = [p for p in self.players if p.stack > self.big_blind]
        if len(active) < 2:
            return HandResult(self.hand_count, "", 0, 0, False)

        num = len(active)
        hands = self.dealer.deal_hole_cards(num)
        hole_cards_map = {}
        for i, sp in enumerate(active):
            hole_cards_map[sp.name] = hands[i]

        gs = GameState(
            players=[Player(name=sp.name, stack=sp.stack) for sp in active],
            big_blind=self.big_blind,
            small_blind=self.big_blind // 2,
        )
        for i, sp in enumerate(active):
            gs.players[i].hole_cards = hands[i]

        gs.post_blinds()
        gs.street = Street.PREFLOP

        showdown = self._play_street(gs, active, hole_cards_map, hero_auto)

        if showdown and len(gs.players_in_hand) > 1:
            board = []
            flop = self.dealer.deal_flop()
            board.extend(flop)
            gs.board = board
            gs.street = Street.FLOP
            gs.current_bet = 0
            for p in gs.players:
                p.current_bet = 0

            still_in = self._play_street(gs, active, hole_cards_map, hero_auto)

            if still_in and len(gs.players_in_hand) > 1:
                turn = self.dealer.deal_turn()
                board.append(turn)
                gs.board = board
                gs.street = Street.TURN
                gs.current_bet = 0
                for p in gs.players:
                    p.current_bet = 0

                still_in = self._play_street(gs, active, hole_cards_map, hero_auto)

                if still_in and len(gs.players_in_hand) > 1:
                    river = self.dealer.deal_river()
                    board.append(river)
                    gs.board = board
                    gs.street = Street.RIVER
                    gs.current_bet = 0
                    for p in gs.players:
                        p.current_bet = 0

                    self._play_street(gs, active, hole_cards_map, hero_auto)

        winner, pot = self._resolve_winner(gs, hole_cards_map)
        hero_profit = 0
        hero_sp = next((p for p in active if p.is_hero), None)
        if hero_sp and winner == hero_sp.name:
            hero_profit = pot - (hero_sp.stack - gs.players[active.index(hero_sp)].stack)

        for i, sp in enumerate(active):
            sp.stack = gs.players[i].stack

        result = HandResult(
            hand_id=self.hand_count,
            winner=winner,
            pot_size=pot,
            hero_profit=hero_profit,
            showdown=len(gs.players_in_hand) > 1,
            hero_cards=hole_cards_map.get(self.hero_name, []),
            board=gs.board,
            all_hole_cards=hole_cards_map,
        )
        self.results.append(result)
        return result

    def run_batch(self, num_hands: int, hero_auto: bool = True) -> list[HandResult]:
        results = []
        for _ in range(num_hands):
            results.append(self.run_hand(hero_auto))
        return results

    def _play_street(
        self, gs: GameState, active: list[SimPlayer],
        hole_cards_map: dict, hero_auto: bool,
    ) -> bool:
        max_actions = len(active) * 4
        action_count = 0
        acted = set()
        last_raiser = None

        while action_count < max_actions:
            for i, sp in enumerate(active):
                player = gs.players[i]
                if not player.is_active or player.is_all_in:
                    continue
                if sp.name in acted and sp.name != last_raiser:
                    if gs.current_bet <= player.current_bet:
                        continue

                if sp.is_hero:
                    if hero_auto:
                        advice = self.advisor.get_advice(gs, player)
                        action_type = advice["action"]
                        amount = advice["amount"]
                    else:
                        action_type = ActionType.CHECK
                        amount = 0
                else:
                    action_type, amount = sp.ai.decide(gs, player)

                self._apply_action(gs, player, action_type, amount)
                acted.add(sp.name)
                if action_type in (ActionType.RAISE, ActionType.BET):
                    last_raiser = sp.name
                    acted = {sp.name}
                action_count += 1

                if len(gs.players_in_hand) <= 1:
                    return False

            if all(
                not p.is_active or p.is_all_in or p.current_bet >= gs.current_bet
                for p in gs.players
            ):
                break

        return len(gs.players_in_hand) > 1

    def _apply_action(
        self, gs: GameState, player: Player, action_type: ActionType, amount: int
    ) -> None:
        if action_type == ActionType.FOLD:
            player.is_active = False
        elif action_type == ActionType.CHECK:
            pass
        elif action_type == ActionType.CALL:
            call_amt = min(gs.current_bet - player.current_bet, player.stack)
            player.stack -= call_amt
            player.current_bet += call_amt
            gs.pot += call_amt
        elif action_type in (ActionType.BET, ActionType.RAISE):
            bet_amt = min(amount - player.current_bet, player.stack)
            if bet_amt <= 0:
                return
            player.stack -= bet_amt
            gs.pot += bet_amt
            player.current_bet += bet_amt
            gs.current_bet = player.current_bet
            if player.stack == 0:
                player.is_all_in = True
        elif action_type == ActionType.ALL_IN:
            all_in_amt = player.stack
            player.current_bet += all_in_amt
            gs.pot += all_in_amt
            player.stack = 0
            player.is_all_in = True
            if player.current_bet > gs.current_bet:
                gs.current_bet = player.current_bet

    def _resolve_winner(
        self, gs: GameState, hole_cards_map: dict
    ) -> tuple[str, int]:
        in_hand = [p for p in gs.players if p.is_active or p.is_all_in]
        if len(in_hand) == 1:
            winner = in_hand[0]
            winner.stack += gs.pot
            return winner.name, gs.pot

        if not gs.board or len(gs.board) < 5:
            while len(gs.board) < 5:
                if len(gs.board) == 0:
                    gs.board.extend(self.dealer.deal_flop())
                elif len(gs.board) == 3:
                    gs.board.append(self.dealer.deal_turn())
                else:
                    gs.board.append(self.dealer.deal_river())

        from treys import Evaluator
        ev = Evaluator()
        best_rank = 7463
        best_player = in_hand[0]

        for p in in_hand:
            cards = hole_cards_map.get(p.name, [])
            if cards and len(cards) == 2:
                rank = ev.evaluate(cards, gs.board)
                if rank < best_rank:
                    best_rank = rank
                    best_player = p

        best_player.stack += gs.pot
        return best_player.name, gs.pot
