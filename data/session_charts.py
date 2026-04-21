"""Session-end charts: opponent learning curves + advisor quality."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _load_snapshots(session_dir: Path) -> list[dict]:
    path = session_dir / "profile_snapshots.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_hand_jsons(session_dir: Path) -> list[dict]:
    hands: list[dict] = []
    for p in sorted(session_dir.glob("hand_*.json")):
        with open(p, encoding="utf-8") as f:
            hands.append(json.load(f))
    return hands


def _plot_profile_learning(snapshots: list[dict], out_path: Path) -> None:
    """Plot key stats over time for each opponent."""
    if not snapshots:
        return

    players = list(snapshots[0]["profiles"].keys())
    stats_to_plot = ["vpip", "pfr", "aggression_freq", "cbet_flop", "fold_to_cbet", "steal"]
    stat_labels = ["VPIP", "PFR", "AF", "Cbet Flop", "Fold to Cbet", "Steal"]

    n_stats = len(stats_to_plot)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes = axes.flatten()

    hand_nums = [s["hand_number"] for s in snapshots]

    for i, (stat, label) in enumerate(zip(stats_to_plot, stat_labels)):
        ax = axes[i]
        for player in players:
            values = [s["profiles"].get(player, {}).get(stat, 0) for s in snapshots]
            ax.plot(hand_nums, values, marker=".", markersize=3, label=player)
        ax.set_title(label)
        ax.set_xlabel("Hand #")
        ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.3)

    fig.suptitle("对手画像学习曲线", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_advisor_quality(hands: list[dict], out_path: Path) -> None:
    """Plot advisor follow rate and cumulative P&L."""
    follow_counts: list[int] = []
    total_counts: list[int] = []
    hero_pnl: list[int] = []
    hand_ids: list[int] = []
    cumulative_pnl = 0

    for h in hands:
        evals = h.get("advisor_evaluation")
        if not evals:
            continue
        hand_ids.append(h["hand_id"])
        followed = sum(1 for e in evals if e.get("followed"))
        follow_counts.append(followed)
        total_counts.append(len(evals))
        last = evals[-1]
        net = last.get("hand_result_net", 0)
        cumulative_pnl += net
        hero_pnl.append(cumulative_pnl)

    if not hand_ids:
        return

    window = min(20, max(1, len(hand_ids) // 5))
    rolling_rate: list[float] = []
    for i in range(len(follow_counts)):
        start = max(0, i - window + 1)
        f = sum(follow_counts[start:i+1])
        t = sum(total_counts[start:i+1])
        rolling_rate.append(f / t if t else 0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)

    ax1.plot(hand_ids, rolling_rate, color="steelblue", linewidth=1.5)
    ax1.set_ylabel("采纳率")
    ax1.set_title(f"Advisor 建议采纳率 (滚动{window}手)")
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax1.set_ylim(-0.05, 1.05)
    ax1.grid(True, alpha=0.3)

    colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in hero_pnl]
    ax2.fill_between(hand_ids, hero_pnl, alpha=0.3,
                     where=[p >= 0 for p in hero_pnl], color="#2ecc71")
    ax2.fill_between(hand_ids, hero_pnl, alpha=0.3,
                     where=[p < 0 for p in hero_pnl], color="#e74c3c")
    ax2.plot(hand_ids, hero_pnl, color="black", linewidth=1)
    ax2.axhline(0, color="gray", linewidth=0.5, linestyle="--")
    ax2.set_ylabel("累计盈亏")
    ax2.set_xlabel("Hand #")
    ax2.set_title("Hero 累计盈亏曲线")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_skill_estimate(snapshots: list[dict], out_path: Path) -> None:
    """Plot opponent skill estimate evolution."""
    if not snapshots:
        return

    players = list(snapshots[0]["profiles"].keys())
    hand_nums = [s["hand_number"] for s in snapshots]

    fig, ax = plt.subplots(figsize=(10, 5))
    for player in players:
        values = [
            s["profiles"].get(player, {}).get("skill_estimate", {}).get("overall_skill", 0.5)
            for s in snapshots
        ]
        ax.plot(hand_nums, values, marker=".", markersize=4, label=player)

    ax.set_title("对手技术水平评估变化")
    ax.set_xlabel("Hand #")
    ax.set_ylabel("Skill Estimate")
    ax.set_ylim(-0.05, 1.05)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _plot_convergence(convergence_path: Path, out_path: Path) -> None:
    """Plot learning convergence: overall score + per-stat error over time."""
    with open(convergence_path, encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        return

    n_players = len(data)
    fig, axes = plt.subplots(n_players, 2, figsize=(14, 5 * n_players), squeeze=False)

    for row, player_data in enumerate(data):
        name = player_data["player_name"]
        label = player_data["true_label"]
        snapshots = player_data["snapshots"]
        if not snapshots:
            continue

        hand_nums = [s["hand_number"] for s in snapshots]
        scores = [s["overall_score"] for s in snapshots]

        ax_score = axes[row][0]
        ax_score.plot(hand_nums, scores, "b-", linewidth=2, label="收敛分数")
        ax_score.axhline(0.8, color="green", linestyle="--", alpha=0.5, label="收敛阈值")
        wrong_hands = [s["hand_number"] for s in snapshots if s["wrong_learning_count"] > 0]
        wrong_scores = [s["overall_score"] for s in snapshots if s["wrong_learning_count"] > 0]
        if wrong_hands:
            ax_score.scatter(wrong_hands, wrong_scores, color="red", s=30,
                           zorder=5, label="错误学习")
        ax_score.set_title(f"{name} ({label}) - 学习收敛")
        ax_score.set_xlabel("Hand #")
        ax_score.set_ylabel("收敛分数")
        ax_score.set_ylim(-0.05, 1.05)
        ax_score.legend(fontsize=8)
        ax_score.grid(True, alpha=0.3)

        ax_err = axes[row][1]
        stat_names = list(snapshots[0]["stats"].keys())
        for stat in stat_names:
            errors = [s["stats"][stat]["error"] for s in snapshots]
            ax_err.plot(hand_nums, errors, marker=".", markersize=3, label=stat)
        ax_err.set_title(f"{name} - 各指标误差")
        ax_err.set_xlabel("Hand #")
        ax_err.set_ylabel("绝对误差")
        ax_err.legend(fontsize=8)
        ax_err.grid(True, alpha=0.3)

    fig.suptitle("学习收敛分析", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def generate_session_charts(session_dir: Path) -> list[Path]:
    """Generate all charts for a session. Returns list of saved image paths."""
    snapshots = _load_snapshots(session_dir)
    hands = _load_hand_jsons(session_dir)
    saved: list[Path] = []

    if snapshots:
        p1 = session_dir / "chart_profile_learning.png"
        _plot_profile_learning(snapshots, p1)
        saved.append(p1)

        p3 = session_dir / "chart_skill_estimate.png"
        _plot_skill_estimate(snapshots, p3)
        saved.append(p3)

    convergence_path = session_dir / "convergence_data.json"
    if convergence_path.exists():
        p4 = session_dir / "chart_convergence.png"
        _plot_convergence(convergence_path, p4)
        saved.append(p4)

    if hands:
        p2 = session_dir / "chart_advisor_quality.png"
        _plot_advisor_quality(hands, p2)
        saved.append(p2)

    return saved
