from __future__ import annotations

import json
import os
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt, IntPrompt

from env.game_state import GameState, Player
from env.action_space import GameMode, POSITIONS_BY_SIZE

console = Console()
PROFILES_DIR = Path(__file__).parent.parent / "profiles"


def setup_session(mode: GameMode = GameMode.LIVE) -> tuple[GameState, str]:
    mode_label = "测试模式" if mode == GameMode.TEST else "实战模式"
    console.print(f"\n[bold yellow]═══ 德扑AI顾问 ({mode_label}) ═══[/bold yellow]\n")

    num_players = IntPrompt.ask("玩家人数", default=6, choices=[str(i) for i in range(2, 10)])

    players: list[Player] = []
    console.print(f"\n输入 {num_players} 位玩家信息:")
    for i in range(num_players):
        name = Prompt.ask(f"  玩家{i+1} 名称", default=f"Player{i+1}")
        stack = IntPrompt.ask(f"  {name} 初始筹码", default=1000)
        players.append(Player(name=name, stack=stack))

    hero_name = Prompt.ask("\n你是哪位玩家", choices=[p.name for p in players], default=players[0].name)

    sb = IntPrompt.ask("小盲注", default=5)
    bb = IntPrompt.ask("大盲注", default=10)

    gs = GameState(players=players, small_blind=sb, big_blind=bb, dealer_idx=0, game_mode=mode)
    gs.assign_positions()

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    for p in players:
        _load_or_create_profile(p.name)

    return gs, hero_name


def _load_or_create_profile(name: str) -> dict:
    path = PROFILES_DIR / f"{name}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            console.print(f"  已加载 {name} 的档案", style="dim")
            return json.load(f)

    profile = {
        "name": name,
        "hands_played": 0,
        "vpip_count": 0,
        "pfr_count": 0,
        "aggression_actions": 0,
        "passive_actions": 0,
        "observations": 0,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    console.print(f"  已创建 {name} 的新档案", style="dim")
    return profile


def rebuy_prompt(player: Player) -> int | None:
    console.print(f"\n[bold]{player.name}[/bold] 筹码归零!")
    choice = Prompt.ask(
        "  [Enter] 补充1000 / [数字] 自定义 / [Q] 离场",
        default="1000",
    )
    if choice.upper() == "Q":
        return None
    try:
        amount = int(choice)
        return max(1, amount)
    except ValueError:
        return 1000
