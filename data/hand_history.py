from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from treys import Evaluator, Card

from env.game_state import GameState, Player
from env.action_space import PlayerAction, Street, ActionType
from ui.card_parser import card_to_short

_EVALUATOR = Evaluator()

HISTORY_DIR = Path(__file__).parent / "hands"


def _card_strs(cards: list[int]) -> list[str]:
    return [card_to_short(c) for c in cards]


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class DecisionEvent:
    street: Street
    player: str
    action: PlayerAction
    advisor_text: str | None = None
    advisor_data: dict[str, Any] | None = None


@dataclass
class HandRecorder:
    """Accumulates events during a single hand for rich export."""
    events: list[DecisionEvent] = field(default_factory=list)
    board_log: dict[str, list[str]] = field(default_factory=dict)
    cli_lines: list[str] = field(default_factory=list)

    def record_action(self, street: Street, player: str, action: PlayerAction,
                      advisor_text: str | None = None,
                      advisor_data: dict[str, Any] | None = None) -> None:
        self.events.append(DecisionEvent(
            street=street, player=player, action=action,
            advisor_text=advisor_text, advisor_data=advisor_data,
        ))

    def record_board(self, street: str, cards: list[int]) -> None:
        self.board_log[street] = _card_strs(cards)

    def record_cli(self, line: str) -> None:
        self.cli_lines.append(line)


class SessionRecorder:
    """Manages a per-session folder under data/hands/."""

    PROFILE_SNAPSHOT_INTERVAL = 10

    def __init__(self, num_players: int, small_blind: int, big_blind: int,
                 player_names: list[str] | None = None) -> None:
        ts = _ts()
        folder_name = f"session_{ts}_{num_players}p_{small_blind}_{big_blind}"
        self.session_dir = HISTORY_DIR / folder_name
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._write_session_info(num_players, small_blind, big_blind, player_names or [])
        self._profile_snapshots: list[dict[str, Any]] = []

    def _write_session_info(self, num_players: int, sb: int, bb: int,
                            names: list[str]) -> None:
        info = (
            f"Session started: {datetime.now().isoformat()}\n"
            f"Players: {num_players}  Blinds: {sb}/{bb}\n"
            f"Names: {', '.join(names)}\n"
        )
        (self.session_dir / "session_info.txt").write_text(info, encoding="utf-8")

    def export_hand(self, gs: GameState, winnings: dict[str, int],
                    recorder: HandRecorder | None = None,
                    opponent_labels: dict[str, dict[str, Any]] | None = None,
                    hero_reads: dict[str, dict[str, Any]] | None = None) -> Path:
        hand_num = gs.hand_number
        txt_path = self.session_dir / f"hand_{hand_num:03d}.txt"
        json_path = self.session_dir / f"hand_{hand_num:03d}.json"

        txt = _build_hand_log(gs, winnings, recorder, opponent_labels, hero_reads)
        txt_path.write_text(txt, encoding="utf-8")

        data = _build_hand_json(gs, winnings, recorder, opponent_labels, hero_reads)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return txt_path

    def record_profile_snapshot(self, hand_num: int,
                                profiles: dict[str, Any]) -> None:
        """Record opponent profile snapshot every N hands."""
        if hand_num % self.PROFILE_SNAPSHOT_INTERVAL != 0:
            return
        snapshot: dict[str, Any] = {
            "hand_number": hand_num,
            "timestamp": datetime.now().isoformat(),
            "profiles": {},
        }
        for name, profile in profiles.items():
            snapshot["profiles"][name] = {
                "style": profile.style_label,
                "total_hands": profile.total_hands,
                "vpip": round(profile.get_stat("vpip"), 3),
                "pfr": round(profile.get_stat("pfr"), 3),
                "three_bet_pct": round(profile.get_stat("three_bet_pct"), 3),
                "aggression_freq": round(profile.get_stat("aggression_freq"), 3),
                "wtsd": round(profile.get_stat("wtsd"), 3),
                "wsd": round(profile.get_stat("wsd"), 3),
                "cbet_flop": round(profile.get_stat("cbet_flop"), 3),
                "fold_to_cbet": round(profile.get_stat("fold_to_cbet"), 3),
                "steal": round(profile.get_stat("steal"), 3),
                "fold_to_3bet": round(profile.get_stat("fold_to_3bet"), 3),
                "skill_estimate": profile.skill_estimate.to_dict(),
            }
        self._profile_snapshots.append(snapshot)
        self._flush_profile_snapshots()

    def _flush_profile_snapshots(self) -> None:
        path = self.session_dir / "profile_snapshots.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._profile_snapshots, f, indent=2, ensure_ascii=False)


def _build_hand_log(gs: GameState, winnings: dict[str, int],
                    recorder: HandRecorder | None,
                    opponent_labels: dict[str, dict[str, Any]] | None = None,
                    hero_reads: dict[str, dict[str, Any]] | None = None) -> str:
    lines: list[str] = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"{'=' * 50}")
    lines.append(f"Hand #{gs.hand_number} | {ts}")
    lines.append(f"Blinds: {gs.small_blind}/{gs.big_blind}")
    lines.append(f"{'=' * 50}")

    lines.append("\nPlayers:")
    for p in gs.players:
        cards = " ".join(_card_strs(p.hole_cards)) if p.hole_cards else "??"
        init_stack = p.initial_stack if p.initial_stack > 0 else p.stack
        lines.append(f"  {p.position:<4} {p.name:<12} stack={init_stack:<6} cards=[{cards}]")

    advisor_map: dict[tuple[str, str, int], DecisionEvent] = {}
    if recorder:
        counters: dict[tuple[str, str], int] = {}
        for ev in recorder.events:
            key_base = (ev.street.name, ev.player)
            idx = counters.get(key_base, 0)
            counters[key_base] = idx + 1
            advisor_map[(ev.street.name, ev.player, idx)] = ev

    action_counters: dict[tuple[str, str], int] = {}
    for street in Street:
        actions = gs.action_history.get(street, [])
        if not actions:
            continue

        lines.append(f"\n--- {street.name} ---")

        if recorder and street.name in recorder.board_log:
            board_cards = recorder.board_log[street.name]
            lines.append(f"Board: [{' '.join(board_cards)}]")

        pot_at_street = _estimate_pot_at_street(gs, street)
        if pot_at_street > 0:
            lines.append(f"Pot: {pot_at_street}")

        for action in actions:
            key_base = (street.name, action.player_name)
            idx = action_counters.get(key_base, 0)
            action_counters[key_base] = idx + 1
            ev = advisor_map.get((street.name, action.player_name, idx))

            if ev and ev.advisor_text:
                lines.append(f"")
                lines.append(f"  [ADVISOR for {action.player_name}]")
                for adv_line in ev.advisor_text.strip().split("\n"):
                    lines.append(f"    {adv_line}")
                if ev.advisor_data:
                    eq = ev.advisor_data.get("equity")
                    raw_eq = ev.advisor_data.get("raw_equity")
                    rng_eq = ev.advisor_data.get("range_equity")
                    conf = ev.advisor_data.get("confidence")
                    parts = []
                    if eq is not None:
                        parts.append(f"eff_equity={eq:.3f}")
                    if raw_eq is not None:
                        parts.append(f"raw_equity={raw_eq:.3f}")
                    if rng_eq is not None:
                        parts.append(f"range_equity={rng_eq:.3f}")
                    if conf is not None:
                        parts.append(f"confidence={conf:.2f}")
                    if parts:
                        lines.append(f"    [{', '.join(parts)}]")

            amt = f" {action.amount}" if action.amount else ""
            lines.append(f"  >> {action.player_name}: {action.action_type.value}{amt}")

    lines.append(f"\n--- RESULT ---")
    board_str = " ".join(_card_strs(gs.board)) if gs.board else "(no board)"
    lines.append(f"Board: [{board_str}]")
    for name, amount in winnings.items():
        if amount != 0:
            sign = "+" if amount > 0 else ""
            lines.append(f"  {name}: {sign}{amount}")

    showdown_info = _build_showdown_info(gs, winnings)
    if showdown_info:
        lines.append(f"\n--- SHOWDOWN ---")
        for si in showdown_info:
            w = "WIN" if si["won"] else "LOSE"
            lines.append(
                f"  {si['player']}: [{' '.join(si['hole_cards'])}] "
                f"{si['hand_class']} (rank={si['hand_rank']}) → {w} ({si['net']:+d})"
            )

    advisor_eval = _evaluate_advisor_decisions(gs, winnings, recorder)
    if advisor_eval:
        lines.append(f"\n--- ADVISOR EVALUATION ---")
        for ae in advisor_eval:
            tag = "FOLLOWED" if ae["followed"] else "DEVIATED"
            eq_str = f" eq={ae['equity_at_decision']:.1%}" if ae.get("equity_at_decision") else ""
            lines.append(
                f"  [{ae['street']}] 建议={ae['advised_action']}"
                f" 实际={ae['actual_action']} [{tag}]{eq_str}"
            )
        last = advisor_eval[-1]
        if "hand_outcome" in last:
            followed_str = "全部采纳" if last.get("all_advice_followed") else "有偏离"
            lines.append(
                f"  结果: {last['hand_outcome']} ({last['hand_result_net']:+d}) | {followed_str}"
            )

    if opponent_labels:
        lines.append(f"\n--- OPPONENT GROUND TRUTH ---")
        for name, info in opponent_labels.items():
            label = info.get("label", "?")
            vpip = info.get("vpip_target", 0)
            pfr = info.get("pfr_target", 0)
            aggr = info.get("aggression_freq_target", 0)
            ftc = info.get("fold_to_cbet", 0)
            bluff = info.get("bluff_frequency", 0)
            tilt = info.get("tilt_variance", 0)
            lines.append(
                f"  {name}: [{label}] VPIP={vpip:.0%} PFR={pfr:.0%} "
                f"AF={aggr:.0%} FoldCbet={ftc:.0%} Bluff={bluff:.0%} Tilt={tilt:.2f}"
            )

    if hero_reads:
        lines.append(f"\n--- HERO OPPONENT READS (本手结束时) ---")
        for name, info in hero_reads.items():
            style = info.get("style", "未知")
            hands = info.get("total_hands", 0)
            vpip = info.get("vpip", 0)
            pfr = info.get("pfr", 0)
            aggr = info.get("aggression_freq", 0)
            ftc = info.get("fold_to_cbet", 0)
            wtsd = info.get("wtsd", 0)
            conf = info.get("style_confidence", 0)
            lines.append(
                f"  {name}: [{style}] (置信度{conf:.0%}, {hands}手) "
                f"VPIP={vpip:.1%} PFR={pfr:.1%} AF={aggr:.1%} "
                f"FoldCbet={ftc:.1%} WTSD={wtsd:.1%}"
            )

    lines.append(f"\nFinal stacks:")
    for p in gs.players:
        lines.append(f"  {p.name}: {p.stack}")

    if recorder and recorder.cli_lines:
        lines.append(f"\n--- CLI OUTPUT ---")
        lines.extend(recorder.cli_lines)

    lines.append("")
    return "\n".join(lines)


def _estimate_pot_at_street(gs: GameState, target_street: Street) -> int:
    """Rough pot estimate at the start of a street from action history."""
    total = gs.small_blind + gs.big_blind
    for street in Street:
        if street == target_street:
            break
        for action in gs.action_history.get(street, []):
            if action.amount and action.amount > 0:
                total = max(total, action.amount)
    return total


def _sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items() if k != "text" and v is not None}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    if hasattr(obj, "value"):
        return obj.value
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _build_showdown_info(gs: GameState, winnings: dict[str, int]) -> list[dict[str, Any]]:
    """Build showdown detail for each player still in hand at the end."""
    in_hand = gs.players_in_hand
    if len(in_hand) <= 1 or len(gs.board) < 5:
        return []

    results: list[dict[str, Any]] = []
    for p in in_hand:
        if not p.hole_cards or len(p.hole_cards) != 2:
            continue
        rank = _EVALUATOR.evaluate(p.hole_cards, gs.board)
        rank_class = _EVALUATOR.get_rank_class(rank)
        hand_class = _EVALUATOR.class_to_string(rank_class)
        results.append({
            "player": p.name,
            "hole_cards": _card_strs(p.hole_cards),
            "hand_rank": rank,
            "hand_class": hand_class,
            "won": winnings.get(p.name, 0) > 0,
            "net": winnings.get(p.name, 0),
        })
    results.sort(key=lambda x: x["hand_rank"])
    return results


def _evaluate_advisor_decisions(
    gs: GameState,
    winnings: dict[str, int],
    recorder: HandRecorder | None,
) -> list[dict[str, Any]]:
    """Post-hoc evaluation of each advisor recommendation in this hand."""
    if not recorder:
        return []

    hero_net = 0
    hero_name = None
    for ev in recorder.events:
        if ev.advisor_data:
            hero_name = ev.player
            break
    if not hero_name:
        return []
    hero_net = winnings.get(hero_name, 0)

    evaluations: list[dict[str, Any]] = []
    for ev in recorder.events:
        if not ev.advisor_data:
            continue
        advised_action = ev.advisor_data.get("action")
        if hasattr(advised_action, "value"):
            advised_action = advised_action.value
        actual_action = ev.action.action_type.value if hasattr(ev.action, "action_type") else str(ev.action)
        followed = (advised_action == actual_action)

        advised_amount = ev.advisor_data.get("amount", 0)
        actual_amount = ev.action.amount if hasattr(ev.action, "amount") else 0

        entry: dict[str, Any] = {
            "street": ev.street.name.lower(),
            "advised_action": advised_action,
            "advised_amount": advised_amount,
            "actual_action": actual_action,
            "actual_amount": actual_amount,
            "followed": followed,
            "confidence": ev.advisor_data.get("confidence"),
            "equity_at_decision": ev.advisor_data.get("equity"),
        }

        if not followed and advised_amount and actual_amount:
            entry["amount_diff"] = actual_amount - advised_amount

        evaluations.append(entry)

    if evaluations:
        evaluations[-1]["hand_result_net"] = hero_net
        outcome = "win" if hero_net > 0 else ("lose" if hero_net < 0 else "push")
        evaluations[-1]["hand_outcome"] = outcome
        all_followed = all(e["followed"] for e in evaluations)
        evaluations[-1]["all_advice_followed"] = all_followed

    return evaluations



def _build_hand_json(gs: GameState, winnings: dict[str, int],
                     recorder: HandRecorder | None,
                     opponent_labels: dict[str, dict[str, Any]] | None = None,
                     hero_reads: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    hand: dict[str, Any] = {
        "hand_id": gs.hand_number,
        "timestamp": datetime.now().isoformat(),
        "blinds": [gs.small_blind, gs.big_blind],
        "players": [],
        "board": _card_strs(gs.board),
        "actions": [],
        "winnings": {k: v for k, v in winnings.items() if v != 0},
    }

    for p in gs.players:
        pd: dict[str, Any] = {
            "name": p.name,
            "position": p.position,
            "stack": p.initial_stack if p.initial_stack > 0 else p.stack,
        }
        if p.hole_cards:
            pd["hole_cards"] = _card_strs(p.hole_cards)
        hand["players"].append(pd)

    decision_idx = 0
    decisions = recorder.events if recorder else []

    for street in Street:
        for action in gs.action_history.get(street, []):
            ad: dict[str, Any] = {
                "street": street.name.lower(),
                "player": action.player_name,
                "action": action.action_type.value,
            }
            if action.amount:
                ad["amount"] = action.amount

            if decision_idx < len(decisions):
                ev = decisions[decision_idx]
                if ev.street == street and ev.player == action.player_name:
                    if ev.advisor_data:
                        ad["advisor"] = _sanitize_for_json(ev.advisor_data)
                    decision_idx += 1

            hand["actions"].append(ad)

    showdown_info = _build_showdown_info(gs, winnings)
    if showdown_info:
        hand["showdown"] = showdown_info

    advisor_eval = _evaluate_advisor_decisions(gs, winnings, recorder)
    if advisor_eval:
        hand["advisor_evaluation"] = advisor_eval

    if opponent_labels:
        hand["opponent_ground_truth"] = opponent_labels

    if hero_reads:
        hand["hero_opponent_reads"] = hero_reads

    return hand


def export_hand(gs: GameState, winnings: dict[str, int]) -> Path:
    """Legacy standalone export (no session folder)."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    hand = _build_hand_json(gs, winnings, None)
    ts = _ts()
    path = HISTORY_DIR / f"hand_{gs.hand_number}_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hand, f, indent=2, ensure_ascii=False)
    return path
