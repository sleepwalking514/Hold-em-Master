"""量化 Hero 对对手画像学习效果的收敛分析。

核心思路：
- 真实参数来自 AIOpponentConfig（对手的行为生成参数）
- 学习参数来自 PlayerProfile 的贝叶斯统计量
- 由于扑克信息不完全（弃牌不亮牌、随机性），学习必然有噪声和偏差
- 本模块量化：收敛速度、当前误差、错误学习检测、信息受限分析
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from profiler.player_profile import PlayerProfile
from testing.simulation.label_presets import AIOpponentConfig


# 真实参数与 profile stat 的映射
STAT_MAPPING: list[tuple[str, str]] = [
    ("vpip_target", "vpip"),
    ("pfr_target", "pfr"),
    ("aggression_freq_target", "aggression_freq"),
    ("fold_to_cbet", "fold_to_cbet"),
]

# 各 stat 的可接受误差阈值（考虑扑克随机性）
ACCEPTABLE_ERROR: dict[str, float] = {
    "vpip": 0.08,
    "pfr": 0.08,
    "aggression_freq": 0.10,
    "fold_to_cbet": 0.12,
}

# 信息可观测性权重：某些 stat 在不摊牌时几乎无法学习
OBSERVABILITY: dict[str, float] = {
    "vpip": 1.0,       # 每手都能观测（是否入池）
    "pfr": 0.9,        # 翻前行动基本可见
    "aggression_freq": 0.7,  # 需要翻后多次交手
    "fold_to_cbet": 0.5,     # 需要 hero cbet 且对手有机会 fold
}


@dataclass
class StatConvergence:
    """单个统计量的收敛状态。"""
    stat_name: str
    true_value: float
    learned_value: float
    error: float
    observations: int
    confidence: float
    is_converged: bool
    is_wrong_learning: bool
    observability: float

    @property
    def weighted_error(self) -> float:
        return self.error * self.observability


@dataclass
class ConvergenceSnapshot:
    """某一时刻的整体收敛状态。"""
    hand_number: int
    player_name: str
    stats: list[StatConvergence]
    overall_score: float        # 0~1, 1=完美收敛
    convergence_rate: float     # 相对上一次的改善速度
    wrong_learning_count: int   # 错误学习的 stat 数量
    info_limited_stats: list[str]  # 信息受限导致无法收敛的 stat


@dataclass
class ConvergenceHistory:
    """一个对手的完整学习收敛历史。"""
    player_name: str
    true_config: AIOpponentConfig
    snapshots: list[ConvergenceSnapshot] = field(default_factory=list)

    @property
    def final_score(self) -> float:
        return self.snapshots[-1].overall_score if self.snapshots else 0.0

    @property
    def convergence_hand(self) -> int | None:
        """首次达到 overall_score >= 0.8 的手数，None 表示未收敛。"""
        for s in self.snapshots:
            if s.overall_score >= 0.8:
                return s.hand_number
        return None

    @property
    def wrong_learning_episodes(self) -> list[tuple[int, list[str]]]:
        """返回 (hand_number, [stat_names]) 的错误学习事件列表。"""
        episodes = []
        for s in self.snapshots:
            wrong = [st.stat_name for st in s.stats if st.is_wrong_learning]
            if wrong:
                episodes.append((s.hand_number, wrong))
        return episodes


def analyze_stat_convergence(
    profile: PlayerProfile,
    config: AIOpponentConfig,
) -> list[StatConvergence]:
    """分析当前 profile 对真实参数的收敛状态。"""
    results = []
    for config_attr, stat_name in STAT_MAPPING:
        true_val = getattr(config, config_attr)
        learned_val = profile.get_stat(stat_name)
        obs = profile.stats[stat_name].observations if stat_name in profile.stats else 0
        conf = profile.get_confidence(stat_name)
        error = abs(learned_val - true_val)
        threshold = ACCEPTABLE_ERROR.get(stat_name, 0.10)
        observability = OBSERVABILITY.get(stat_name, 0.5)

        is_converged = error <= threshold and conf > 0.3
        # 错误学习：置信度高但误差大，说明学偏了
        is_wrong = conf > 0.4 and error > threshold * 1.5

        results.append(StatConvergence(
            stat_name=stat_name,
            true_value=true_val,
            learned_value=learned_val,
            error=error,
            observations=obs,
            confidence=conf,
            is_converged=is_converged,
            is_wrong_learning=is_wrong,
            observability=observability,
        ))
    return results


def compute_overall_score(stats: list[StatConvergence]) -> float:
    """加权计算整体收敛分数。0=完全不准，1=完美收敛。"""
    if not stats:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for s in stats:
        w = s.observability
        threshold = ACCEPTABLE_ERROR.get(s.stat_name, 0.10)
        # 用 sigmoid 风格的评分：误差越小分越高
        raw_score = max(0.0, 1.0 - s.error / (threshold * 2))
        # 置信度低时打折（还没学够）
        conf_factor = min(1.0, s.confidence / 0.5)
        weighted_score += w * raw_score * conf_factor
        total_weight += w
    return weighted_score / total_weight if total_weight > 0 else 0.0


def detect_info_limited(stats: list[StatConvergence]) -> list[str]:
    """检测哪些 stat 因信息不足而无法收敛。"""
    limited = []
    for s in stats:
        # 观测次数少且可观测性低 → 信息受限
        if s.observations < 10 and s.observability < 0.7:
            limited.append(s.stat_name)
        # 观测次数极少
        elif s.observations < 5:
            limited.append(s.stat_name)
    return limited


class LearningConvergenceTracker:
    """跟踪多个对手的学习收敛过程。"""

    def __init__(self):
        self._histories: dict[str, ConvergenceHistory] = {}
        self._configs: dict[str, AIOpponentConfig] = {}

    def register(self, name: str, config: AIOpponentConfig) -> None:
        self._configs[name] = config
        self._histories[name] = ConvergenceHistory(
            player_name=name, true_config=config,
        )

    def record(
        self, hand_number: int, profiles: dict[str, PlayerProfile],
    ) -> dict[str, ConvergenceSnapshot]:
        """记录当前时刻所有对手的收敛状态。"""
        results = {}
        for name, config in self._configs.items():
            profile = profiles.get(name)
            if profile is None:
                continue

            stats = analyze_stat_convergence(profile, config)
            score = compute_overall_score(stats)
            info_limited = detect_info_limited(stats)
            wrong_count = sum(1 for s in stats if s.is_wrong_learning)

            history = self._histories[name]
            prev_score = history.snapshots[-1].overall_score if history.snapshots else 0.0
            rate = score - prev_score

            snapshot = ConvergenceSnapshot(
                hand_number=hand_number,
                player_name=name,
                stats=stats,
                overall_score=score,
                convergence_rate=rate,
                wrong_learning_count=wrong_count,
                info_limited_stats=info_limited,
            )
            history.snapshots.append(snapshot)
            results[name] = snapshot
        return results

    def get_history(self, name: str) -> ConvergenceHistory | None:
        return self._histories.get(name)

    def summary_report(self) -> str:
        """生成简短的终端摘要。"""
        lines = ["=== 学习收敛摘要 ==="]
        for name, history in self._histories.items():
            config = self._configs[name]
            if not history.snapshots:
                lines.append(f"  {name} ({config.label}): 无数据")
                continue
            final = history.snapshots[-1]
            conv_hand = history.convergence_hand
            status = f"第{conv_hand}手收敛" if conv_hand else "未收敛"
            lines.append(f"  {name} ({config.label}): {final.overall_score:.0%} [{status}]")
        return "\n".join(lines)

    def detailed_report(self, profiles: dict[str, "PlayerProfile"] | None = None) -> str:
        """生成完整的学习收敛分析报告，包含所有可用信息。"""
        lines = []
        lines.append("=" * 70)
        lines.append("           学习收敛深度分析报告")
        lines.append("=" * 70)
        lines.append("")

        # 总览
        total_players = len(self._histories)
        converged_count = sum(
            1 for h in self._histories.values() if h.convergence_hand is not None
        )
        lines.append(f"对手总数: {total_players}")
        lines.append(f"已收敛: {converged_count}/{total_players}")
        if self._histories:
            avg_score = sum(
                h.final_score for h in self._histories.values()
            ) / total_players
            lines.append(f"平均收敛分数: {avg_score:.1%}")
        lines.append("")

        for name, history in self._histories.items():
            config = self._configs[name]
            lines.append("─" * 70)
            lines.append(f"  对手: {name}")
            lines.append(f"  真实类型: {config.label}")
            lines.append(f"  真实参数: VPIP={config.vpip_target:.0%} PFR={config.pfr_target:.0%} "
                         f"AF={config.aggression_freq_target:.0%} FoldCbet={config.fold_to_cbet:.0%} "
                         f"Bluff={config.bluff_frequency:.0%} Tilt={config.tilt_variance:.2f}")
            lines.append("─" * 70)

            if not history.snapshots:
                lines.append("  [无快照数据]")
                lines.append("")
                continue

            final = history.snapshots[-1]
            conv_hand = history.convergence_hand

            # 收敛状态
            lines.append("")
            lines.append("  【收敛状态】")
            lines.append(f"    最终收敛分数: {final.overall_score:.1%}")
            lines.append(f"    总观测手数: {final.hand_number}")
            if conv_hand:
                lines.append(f"    首次收敛手数: 第{conv_hand}手 (阈值0.8)")
                efficiency = conv_hand / final.hand_number if final.hand_number > 0 else 0
                lines.append(f"    收敛效率: 用了{efficiency:.0%}的总手数达到收敛")
            else:
                lines.append(f"    状态: 尚未收敛 (需要更多样本)")

            # 收敛速度分析
            lines.append("")
            lines.append("  【收敛速度】")
            if len(history.snapshots) >= 2:
                early_scores = [s.overall_score for s in history.snapshots[:len(history.snapshots)//3+1]]
                mid_scores = [s.overall_score for s in history.snapshots[len(history.snapshots)//3:2*len(history.snapshots)//3+1]]
                late_scores = [s.overall_score for s in history.snapshots[2*len(history.snapshots)//3:]]
                lines.append(f"    前期平均分: {sum(early_scores)/len(early_scores):.1%} "
                             f"(前{len(early_scores)}个快照)")
                if mid_scores:
                    lines.append(f"    中期平均分: {sum(mid_scores)/len(mid_scores):.1%} "
                                 f"(中{len(mid_scores)}个快照)")
                if late_scores:
                    lines.append(f"    后期平均分: {sum(late_scores)/len(late_scores):.1%} "
                                 f"(后{len(late_scores)}个快照)")
                rates = [s.convergence_rate for s in history.snapshots[1:]]
                if rates:
                    avg_rate = sum(rates) / len(rates)
                    max_rate = max(rates)
                    min_rate = min(rates)
                    lines.append(f"    平均改善速率: {avg_rate:+.4f}/快照")
                    lines.append(f"    最大改善: {max_rate:+.4f}  最大退步: {min_rate:+.4f}")
                    negative_count = sum(1 for r in rates if r < 0)
                    lines.append(f"    退步次数: {negative_count}/{len(rates)} "
                                 f"({negative_count/len(rates):.0%})")
            else:
                lines.append("    快照不足，无法分析速度")

            # 各指标详细分析
            lines.append("")
            lines.append("  【各指标收敛详情】")
            lines.append(f"    {'指标':<18} {'学习值':>7} {'真实值':>7} {'误差':>7} "
                         f"{'观测数':>6} {'置信度':>6} {'可观测性':>8} {'状态'}")
            lines.append(f"    {'─'*18} {'─'*7} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*8} {'─'*10}")
            for s in final.stats:
                if s.is_converged:
                    status = "✓ 已收敛"
                elif s.is_wrong_learning:
                    status = "✗ 错误学习"
                elif s.observations < 5:
                    status = "… 数据不足"
                else:
                    status = "… 学习中"
                lines.append(
                    f"    {s.stat_name:<18} {s.learned_value:>7.1%} {s.true_value:>7.1%} "
                    f"{s.error:>7.1%} {s.observations:>6} {s.confidence:>6.0%} "
                    f"{s.observability:>8.0%} {status}"
                )

            # 错误学习分析
            wrong_stats = [s for s in final.stats if s.is_wrong_learning]
            if wrong_stats:
                lines.append("")
                lines.append("  【错误学习诊断】")
                for s in wrong_stats:
                    threshold = ACCEPTABLE_ERROR.get(s.stat_name, 0.10)
                    lines.append(f"    ⚠ {s.stat_name}:")
                    lines.append(f"      学习值 {s.learned_value:.1%} vs 真实值 {s.true_value:.1%}")
                    lines.append(f"      误差 {s.error:.1%} 超过阈值 {threshold:.1%} 的 {s.error/threshold:.1f}x")
                    lines.append(f"      置信度 {s.confidence:.0%} (高置信+高误差=学偏)")
                    if s.observability < 0.7:
                        lines.append(f"      可能原因: 可观测性低({s.observability:.0%})，样本有偏")
                    else:
                        lines.append(f"      可能原因: 对手行为方差大或tilt_variance影响")

            # 错误学习历史
            wrong_episodes = history.wrong_learning_episodes
            if wrong_episodes:
                lines.append("")
                lines.append("  【错误学习时间线】")
                for hand_num, stats in wrong_episodes[-10:]:
                    lines.append(f"    第{hand_num}手: {', '.join(stats)}")

            # 信息受限分析
            if final.info_limited_stats:
                lines.append("")
                lines.append("  【信息受限指标】")
                for stat_name in final.info_limited_stats:
                    obs_weight = OBSERVABILITY.get(stat_name, 0.5)
                    stat_obj = next((s for s in final.stats if s.stat_name == stat_name), None)
                    obs_count = stat_obj.observations if stat_obj else 0
                    lines.append(f"    {stat_name}: 可观测性={obs_weight:.0%}, 观测次数={obs_count}")
                    if obs_weight < 0.7:
                        lines.append(f"      → 需要特定场景(如hero cbet)才能观测，建议增加样本")
                    else:
                        lines.append(f"      → 观测次数过少，建议继续模拟")

            # 收敛轨迹（每个快照的分数变化）
            lines.append("")
            lines.append("  【收敛轨迹】")
            step = max(1, len(history.snapshots) // 10)
            for i in range(0, len(history.snapshots), step):
                snap = history.snapshots[i]
                wrong_mark = f" ⚠x{snap.wrong_learning_count}" if snap.wrong_learning_count > 0 else ""
                info_mark = f" ℹ受限:{','.join(snap.info_limited_stats)}" if snap.info_limited_stats else ""
                lines.append(f"    第{snap.hand_number:>4}手: {snap.overall_score:.1%} "
                             f"(Δ{snap.convergence_rate:+.3f}){wrong_mark}{info_mark}")
            if len(history.snapshots) % step != 0:
                snap = history.snapshots[-1]
                wrong_mark = f" ⚠x{snap.wrong_learning_count}" if snap.wrong_learning_count > 0 else ""
                lines.append(f"    第{snap.hand_number:>4}手: {snap.overall_score:.1%} "
                             f"(Δ{snap.convergence_rate:+.3f}){wrong_mark} [最终]")

            # 额外 profile 信息（如果传入了 profiles）
            if profiles and name in profiles:
                profile = profiles[name]
                lines.append("")
                lines.append("  【完整画像快照】")
                lines.append(f"    风格判定: {profile.style_label}")
                lines.append(f"    总手数: {profile.total_hands}")
                lines.append(f"    先验类型: {profile.prior_type}")

                lines.append("    所有统计量:")
                for stat_name, stat_obj in profile.stats.items():
                    data_mean = stat_obj.data_mean
                    dm_str = f"{data_mean:.1%}" if data_mean is not None else "N/A"
                    lines.append(
                        f"      {stat_name:<20} 后验={stat_obj.mean:.1%} "
                        f"纯数据={dm_str} 观测={stat_obj.observations} "
                        f"置信={stat_obj.confidence:.0%} "
                        f"(α={stat_obj.alpha:.1f} β={stat_obj.beta:.1f})"
                    )

                lines.append("    街道倾向:")
                st = profile.street_tendencies
                for attr_name in ["flop_aggression", "turn_aggression", "river_aggression",
                                  "gives_up_turn", "double_barrel_freq", "triple_barrel_freq"]:
                    s = getattr(st, attr_name)
                    lines.append(f"      {attr_name:<22} {s.mean:.1%} (观测{s.observations})")

                lines.append("    高级动作:")
                aa = profile.advanced_actions
                for attr_name in ["check_raise_freq", "donk_bet_freq", "limp_freq",
                                  "limp_raise_freq", "probe_bet_freq", "raise_cbet_freq"]:
                    s = getattr(aa, attr_name)
                    lines.append(f"      {attr_name:<22} {s.mean:.1%} (观测{s.observations})")

                lines.append("    下注尺度:")
                bs = profile.bet_sizing
                lines.append(f"      平均价值下注: {bs.avg_value_sizing:.2f}x pot")
                lines.append(f"      平均诈唬下注: {bs.avg_bluff_sizing:.2f}x pot")
                lines.append(f"      超池频率: {bs.overbet_frequency:.0%} ({bs.overbet_count}/{bs.total_bets})")

                lines.append("    技术评估:")
                sk = profile.skill_estimate
                lines.append(f"      综合技术: {sk.overall_skill:.2f}")
                lines.append(f"      位置意识: {sk.positional_awareness:.2f}")
                lines.append(f"      尺度精细度: {sk.sizing_sophistication:.2f}")
                lines.append(f"      读牌能力: {sk.hand_reading_ability:.2f}")

            lines.append("")

        # 总结建议
        lines.append("=" * 70)
        lines.append("  总结与建议")
        lines.append("=" * 70)
        for name, history in self._histories.items():
            config = self._configs[name]
            if not history.snapshots:
                continue
            final = history.snapshots[-1]
            lines.append(f"  {name} ({config.label}):")
            if history.convergence_hand:
                lines.append(f"    ✓ 已在第{history.convergence_hand}手收敛，画像可信")
            elif final.overall_score >= 0.6:
                lines.append(f"    … 接近收敛({final.overall_score:.0%})，再观测20-30手可能收敛")
            else:
                lines.append(f"    ✗ 收敛不足({final.overall_score:.0%})，需要更多样本")
            wrong = [s.stat_name for s in final.stats if s.is_wrong_learning]
            if wrong:
                lines.append(f"    ⚠ 注意: {', '.join(wrong)} 存在错误学习，建议检查样本偏差")
        lines.append("")

        return "\n".join(lines)

    def to_json(self) -> list[dict[str, Any]]:
        """导出为 JSON 格式，可存入 session 目录。"""
        data = []
        for name, history in self._histories.items():
            config = self._configs[name]
            player_data: dict[str, Any] = {
                "player_name": name,
                "true_label": config.label,
                "true_params": {
                    attr: round(getattr(config, attr), 3)
                    for attr, _ in STAT_MAPPING
                },
                "convergence_hand": history.convergence_hand,
                "final_score": round(history.final_score, 3),
                "snapshots": [],
            }
            for snap in history.snapshots:
                snap_data: dict[str, Any] = {
                    "hand_number": snap.hand_number,
                    "overall_score": round(snap.overall_score, 3),
                    "convergence_rate": round(snap.convergence_rate, 4),
                    "wrong_learning_count": snap.wrong_learning_count,
                    "info_limited": snap.info_limited_stats,
                    "stats": {},
                }
                for s in snap.stats:
                    snap_data["stats"][s.stat_name] = {
                        "learned": round(s.learned_value, 3),
                        "true": round(s.true_value, 3),
                        "error": round(s.error, 3),
                        "observations": s.observations,
                        "confidence": round(s.confidence, 3),
                        "converged": s.is_converged,
                        "wrong_learning": s.is_wrong_learning,
                    }
                player_data["snapshots"].append(snap_data)
            data.append(player_data)
        return data
