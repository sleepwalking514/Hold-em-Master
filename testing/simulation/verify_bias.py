"""验证问题一：Hero学到的对手画像偏松的根因分析。

分离两个因素：
  Factor A — AI对手的实际VPIP/PFR是否偏离config target
  Factor B — 贝叶斯学习是否在Factor A基础上引入额外偏差
"""
from __future__ import annotations

import random
import statistics
from collections import defaultdict

from treys import Card, Deck

from testing.simulation.label_presets import LABEL_PRESETS, AIOpponentConfig
from testing.simulation.ai_opponent import AIOpponent
from profiler.bayesian_tracker import BayesianStat


# ── Factor A: AI 实际行为 vs config target ──────────────────────────

def measure_actual_vpip_pfr(
    config: AIOpponentConfig,
    n_hands: int = 20_000,
    seed: int = 42,
) -> dict[str, float]:
    """蒙特卡洛测量AI在各位置的实际VPIP和PFR。"""
    rng = random.Random(seed)
    ai = AIOpponent(config, seed=seed)

    positions = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
    vpip_by_pos = defaultdict(list)
    pfr_by_pos = defaultdict(list)
    vpip_all = []
    pfr_all = []

    from env.game_state import GameState, Player
    from env.action_space import ActionType, Street

    for _ in range(n_hands):
        pos = rng.choice(positions)
        deck = Deck()
        cards = deck.draw(2)

        dummy_players = [
            Player(name="Hero", stack=1000),
            Player(name="AI", stack=1000),
        ]
        dummy_players[1].hole_cards = cards
        dummy_players[1].position = pos
        gs = GameState(players=dummy_players, small_blind=5, big_blind=10)
        gs.street = Street.PREFLOP
        gs.pot = 15
        gs.current_bet = 10

        action, amount = ai.decide(gs, dummy_players[1])
        entered = action != ActionType.FOLD and action != ActionType.CHECK
        raised = action in (ActionType.RAISE, ActionType.ALL_IN)

        vpip_all.append(entered)
        pfr_all.append(raised)
        vpip_by_pos[pos].append(entered)
        pfr_by_pos[pos].append(raised)

    result = {
        "actual_vpip": sum(vpip_all) / len(vpip_all),
        "actual_pfr": sum(pfr_all) / len(pfr_all),
        "target_vpip": config.vpip_target,
        "target_pfr": config.pfr_target,
    }
    for pos in positions:
        if vpip_by_pos[pos]:
            result[f"vpip_{pos}"] = sum(vpip_by_pos[pos]) / len(vpip_by_pos[pos])
            result[f"pfr_{pos}"] = sum(pfr_by_pos[pos]) / len(pfr_by_pos[pos])
    return result


# ── Factor B: 贝叶斯学习偏差 ──────────────────────────────────────

def measure_learning_bias(
    true_rate: float,
    prior_alpha: float = 2.0,
    prior_beta: float = 3.0,
    n_observations: int = 60,
    n_trials: int = 5000,
    seed: int = 42,
) -> dict[str, float]:
    """模拟贝叶斯学习过程，测量后验均值相对真实值的偏差。"""
    rng = random.Random(seed)
    posterior_means = []
    data_means = []

    for _ in range(n_trials):
        stat = BayesianStat(prior_alpha, prior_beta)
        successes = 0
        for _ in range(n_observations):
            success = rng.random() < true_rate
            stat.update(success)
            if success:
                successes += 1
        posterior_means.append(stat.mean)
        data_means.append(successes / n_observations if n_observations > 0 else 0)

    return {
        "true_rate": true_rate,
        "prior_mean": prior_alpha / (prior_alpha + prior_beta),
        "avg_posterior": statistics.mean(posterior_means),
        "avg_data_mean": statistics.mean(data_means),
        "posterior_bias": statistics.mean(posterior_means) - true_rate,
        "data_bias": statistics.mean(data_means) - true_rate,
        "posterior_std": statistics.stdev(posterior_means),
    }


# ── 主测试 ────────────────────────────────────────────────────────

PRIOR_MAP = {
    "TAG": (2, 4),
    "LAG": (3, 3),
    "Nit": (1, 5),
    "Fish": (4, 2),
    "Maniac": (4, 2),
    "CallStation": (4, 2),
}


def run_all():
    print("=" * 72)
    print("  Factor A: AI对手实际行为 vs Config Target")
    print("=" * 72)
    print()

    factor_a_results = {}
    for label, config in LABEL_PRESETS.items():
        r = measure_actual_vpip_pfr(config, n_hands=20_000)
        factor_a_results[label] = r
        vpip_diff = r["actual_vpip"] - r["target_vpip"]
        pfr_diff = r["actual_pfr"] - r["target_pfr"]
        print(f"  {label:12s}  VPIP: target={r['target_vpip']:.1%}  actual={r['actual_vpip']:.1%}  "
              f"Δ={vpip_diff:+.1%}  |  PFR: target={r['target_pfr']:.1%}  actual={r['actual_pfr']:.1%}  "
              f"Δ={pfr_diff:+.1%}")

    print()
    print("  各位置VPIP分布 (验证位置修正效果):")
    for label in LABEL_PRESETS:
        r = factor_a_results[label]
        parts = [f"{label:12s}"]
        for pos in ["UTG", "MP", "CO", "BTN", "SB", "BB"]:
            key = f"vpip_{pos}"
            if key in r:
                parts.append(f"{pos}={r[key]:.0%}")
        print(f"  {'  '.join(parts)}")

    print()
    print("=" * 72)
    print("  Factor B: 贝叶斯学习引入的额外偏差 (60手观测)")
    print("=" * 72)
    print()
    print(f"  {'Label':12s}  {'真实VPIP':>8}  {'先验均值':>8}  {'后验均值':>8}  "
          f"{'后验偏差':>8}  {'纯数据偏差':>10}")

    for label, config in LABEL_PRESETS.items():
        actual_vpip = factor_a_results[label]["actual_vpip"]
        pa, pb = PRIOR_MAP.get(label, (2, 3))
        r = measure_learning_bias(
            true_rate=actual_vpip,
            prior_alpha=pa,
            prior_beta=pb,
            n_observations=60,
        )
        print(f"  {label:12s}  {actual_vpip:>8.1%}  {r['prior_mean']:>8.1%}  "
              f"{r['avg_posterior']:>8.1%}  {r['posterior_bias']:>+8.1%}  "
              f"{r['data_bias']:>+10.1%}")

    print()
    print("=" * 72)
    print("  综合偏差 = Factor A (AI行为偏差) + Factor B (学习偏差)")
    print("=" * 72)
    print()
    print(f"  {'Label':12s}  {'Config':>7}  {'AI实际':>7}  {'Hero学到':>8}  "
          f"{'总偏差':>7}  {'A贡献':>7}  {'B贡献':>7}")

    for label, config in LABEL_PRESETS.items():
        actual = factor_a_results[label]["actual_vpip"]
        pa, pb = PRIOR_MAP.get(label, (2, 3))
        r = measure_learning_bias(true_rate=actual, prior_alpha=pa, prior_beta=pb, n_observations=60)
        hero_learned = r["avg_posterior"]
        total_bias = hero_learned - config.vpip_target
        factor_a = actual - config.vpip_target
        factor_b = hero_learned - actual
        print(f"  {label:12s}  {config.vpip_target:>7.1%}  {actual:>7.1%}  "
              f"{hero_learned:>8.1%}  {total_bias:>+7.1%}  {factor_a:>+7.1%}  {factor_b:>+7.1%}")

    print()


if __name__ == "__main__":
    run_all()
