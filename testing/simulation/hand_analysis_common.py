"""Shared data structures and utilities for sim-auto analysis modules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HeroDecision:
    street: str
    action: str
    amount: int
    equity: float
    raw_equity: float
    confidence: float
    hand_strength: int | None = None
    exploit_note: str | None = None
    multiway_note: str | None = None
    baseline_action: str = ""


@dataclass
class HandSummary:
    hand_number: int
    big_blind: int
    hero_position: str
    hero_hole_cards: list[str]
    board: list[str]
    pot_size: int
    hero_invested: int
    hero_profit: int
    streets_played: int
    had_showdown: bool
    hero_folded_preflop: bool
    hero_decisions: list[HeroDecision]
    opponent_actions: dict[str, list[dict]]
    winner: str | None
    interest_score: float = 0.0
    hero_opponent_reads: dict[str, dict] = field(default_factory=dict)
    opponent_ground_truth: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "HandSummary":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HandSummary":
        blinds = data.get("blinds", [5, 10])
        big_blind = blinds[1] if len(blinds) > 1 else 10
        small_blind = blinds[0] if blinds else 5

        players = data.get("players", [])
        hero_player = next((p for p in players if p["name"] == "Hero"), None)
        hero_position = hero_player["position"] if hero_player else "?"
        hero_hole_cards = hero_player.get("hole_cards", []) if hero_player else []

        board = data.get("board", [])
        actions = data.get("actions", [])
        winnings = data.get("winnings", {})

        hero_decisions = _extract_hero_decisions(actions)
        hero_invested = _compute_hero_invested(actions, hero_position, small_blind, big_blind)
        hero_winnings = winnings.get("Hero", 0)
        hero_profit = hero_winnings - hero_invested

        hero_actions = [a for a in actions if a.get("player") == "Hero"]
        hero_folded_preflop = (
            len(hero_actions) > 0
            and hero_actions[0].get("action") == "fold"
            and hero_actions[0].get("street") == "preflop"
        )

        streets_played = _count_streets(board)
        had_showdown = "showdown" in data

        opponent_actions = _group_opponent_actions(actions)

        winner = None
        if winnings:
            winner = max(winnings, key=winnings.get)

        pot_size = hero_invested + sum(
            _compute_player_invested(actions, p["name"], p["position"], small_blind, big_blind)
            for p in players if p["name"] != "Hero"
        )

        summary = cls(
            hand_number=data.get("hand_id", 0),
            big_blind=big_blind,
            hero_position=hero_position,
            hero_hole_cards=hero_hole_cards,
            board=board,
            pot_size=pot_size,
            hero_invested=hero_invested,
            hero_profit=hero_profit,
            streets_played=streets_played,
            had_showdown=had_showdown,
            hero_folded_preflop=hero_folded_preflop,
            hero_decisions=hero_decisions,
            opponent_actions=opponent_actions,
            winner=winner,
            hero_opponent_reads=data.get("hero_opponent_reads", {}),
            opponent_ground_truth=data.get("opponent_ground_truth", {}),
        )
        summary.interest_score = hand_interest_score(summary)
        return summary


def hand_interest_score(summary: HandSummary) -> float:
    if summary.hero_folded_preflop:
        return 0.05

    score = 0.0
    pot_bb = summary.pot_size / max(summary.big_blind, 1)
    score += min(pot_bb / 20.0, 0.25)

    score += (summary.streets_played - 1) * 0.1

    if summary.had_showdown:
        score += 0.1

    if summary.hero_decisions:
        avg_conf = sum(d.confidence for d in summary.hero_decisions) / len(summary.hero_decisions)
        score += (1.0 - avg_conf) * 0.15

    profit_bb = abs(summary.hero_profit) / max(summary.big_blind, 1)
    score += min(profit_bb / 15.0, 0.2)

    return min(score, 1.0)


def _extract_hero_decisions(actions: list[dict]) -> list[HeroDecision]:
    decisions = []
    for a in actions:
        if a.get("player") != "Hero":
            continue
        adv = a.get("advisor")
        if not adv:
            continue
        baseline = adv.get("baseline", {})
        decisions.append(HeroDecision(
            street=a.get("street", "?"),
            action=a.get("action", "?"),
            amount=a.get("amount", 0),
            equity=adv.get("equity", 0.0),
            raw_equity=adv.get("raw_equity", 0.0),
            confidence=adv.get("confidence", 0.5),
            hand_strength=baseline.get("hand_strength"),
            exploit_note=adv.get("exploit_note"),
            multiway_note=adv.get("multiway_note"),
            baseline_action=baseline.get("action", baseline.get("preflop_action", "")),
        ))
    return decisions


def _compute_hero_invested(actions: list[dict], hero_position: str,
                           small_blind: int, big_blind: int) -> int:
    # Preflop: amount = total committed this street (includes blind)
    # Postflop: amount = bet/raise size for that action
    preflop_committed = 0
    if hero_position == "SB":
        preflop_committed = small_blind
    elif hero_position == "BB":
        preflop_committed = big_blind

    postflop_total = 0
    for a in actions:
        if a.get("player") != "Hero":
            continue
        act = a.get("action", "")
        amount = a.get("amount", 0)
        if act in ("call", "raise", "bet", "all_in") and amount > 0:
            if a.get("street") == "preflop":
                preflop_committed = max(preflop_committed, amount)
            else:
                postflop_total += amount
    return preflop_committed + postflop_total


def _compute_player_invested(actions: list[dict], player_name: str,
                             position: str, small_blind: int, big_blind: int) -> int:
    preflop_committed = 0
    if position == "SB":
        preflop_committed = small_blind
    elif position == "BB":
        preflop_committed = big_blind

    postflop_total = 0
    for a in actions:
        if a.get("player") != player_name:
            continue
        act = a.get("action", "")
        amount = a.get("amount", 0)
        if act in ("call", "raise", "bet", "all_in") and amount > 0:
            if a.get("street") == "preflop":
                preflop_committed = max(preflop_committed, amount)
            else:
                postflop_total += amount
    return preflop_committed + postflop_total


def _count_streets(board: list) -> int:
    n = len(board)
    if n == 0:
        return 1
    elif n == 3:
        return 2
    elif n == 4:
        return 3
    else:
        return 4


def _group_opponent_actions(actions: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for a in actions:
        player = a.get("player", "")
        if player == "Hero":
            continue
        if player not in groups:
            groups[player] = []
        groups[player].append({
            "street": a.get("street"),
            "action": a.get("action"),
            "amount": a.get("amount", 0),
        })
    return groups
