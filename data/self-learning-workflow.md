# 自我学习流程设计（基于Session分析报告）

## 流程概述

学习目录在data/hands下

每个session结束后，利用 `analysis/` 目录下的7份分析报告进行系统性复盘。
不再逐手审查，而是以报告为入口，仅在发现问题时抽查具体hand.json验证。

**核心原则：**
- 报告驱动，非逐手驱动
- 效果优先 >> 实现难度
- 跨session对比追踪改善趋势

**分析报告清单（每session自动生成）：**
1. `convergence_analysis` — 画像收敛速度与准确度
2. `decision_quality_analysis` — 决策质量与confidence校准
3. `exploit_effectiveness_analysis` — 剥削策略效果
4. `bleed_pattern_analysis` — 慢性失血模式
5. `equity_trajectory_analysis` — equity轨迹与止损
6. `catastrophic_hands_analysis` — 巨亏手深度分析
7. `positional_leak_analysis` — 位置漏洞

---

## 第一步：快速健康检查（5分钟）

读取本session的7份分析报告摘要行，建立全局印象：

| 报告 | 关注指标 | 红线 |
|------|---------|------|
| convergence | 平均收敛分数、已收敛对手数 | <40%且60手后无改善 |
| decision_quality | 校准偏差、系统性过度自信 | 平均校准误差>25% |
| exploit | 胜率、高/低置信度盈亏差 | 低置信度exploit亏损 |
| bleed | 失血速率(bb/hand)、偷盲成功率 | >2bb/hand失血 |
| equity_trajectory | 下降模式手数占比 | 下降模式>40%且无止损 |
| catastrophic | 巨亏手数、总巨亏BB | 单session>50BB巨亏 |
| positional | 位置胜率异常、GTO偏离 | 任一位置偏离GTO>30% |

**输出：** 标记本session的1-3个重点问题领域，进入深入分析。

---

## 第二步：画像收敛审计

基于 `convergence_analysis` 报告：

### 2.1 收敛速度评估

```
检查每个对手的收敛轨迹：
- 前期(1-20手)→中期(21-40手)→后期(41-60手)的分数变化
- 改善速率是否>0？是否存在停滞（连续3个快照无变化）？
- 退步次数占比是否>20%？
```

### 2.2 信息受限指标识别

```
找出可观测性<70%的指标（如fold_to_cbet、fold_to_3bet）：
- 这些指标观测次数=0说明场景未触发
- 判断：是Hero打法导致（如从不cbet）还是对手行为导致？
- 如果是Hero打法导致 → 标记为"信息采集盲区"
```

### 2.3 先验偏差检查

```
对比"后验值"与"纯数据值"：
- 如果差异>15%且观测数>10，说明先验拉力过强
- 如果观测数<5但置信度>30%，说明先验权重过高
- 标记需要调整先验参数的对手类型
```

**抽查触发条件：** 如果某对手收敛分数<30%且已60手，抽查该对手参与的2-3手hand.json，验证ground truth与学习值的具体偏差来源。

---

## 第三步：决策质量与Confidence校准审计

基于 `decision_quality_analysis` 报告：

### 3.1 校准偏差诊断

```
按confidence区间检查：
- 过度自信区间（实际胜率 << confidence）：equity估算系统性高估
- 过度保守区间（实际胜率 >> confidence）：可能错过value机会
- 重点关注：≥0.80区间的实际胜率，这直接影响all-in决策
```

### 3.2 GTO偏离效果评估

```
从报告中提取：
- 偏离次数/总决策 → exploit频率是否合理
- 偏离后盈利比 → <50%说明exploit整体亏损，应收紧
- 结合exploit_effectiveness报告交叉验证
```

### 3.3 按街行动分布异常

```
检查各街的行动分布：
- preflop fold率是否过高（>50%说明范围过紧）
- flop/turn check率是否过高（错失value bet机会）
- river fold率是否过高（被bluff过多）
```

---

## 第四步：剥削策略效果审计

基于 `exploit_effectiveness_analysis` 报告：

### 4.1 规则级盈亏分析

```
对每条exploit规则：
- 触发次数、胜率、平均盈亏
- 胜率<40%的规则 → 标记为"待修正"
- 平均盈亏为负的规则 → 标记为"有害规则"
```

### 4.2 置信度门槛验证

```
对比高置信度(≥50%) vs 低置信度(<50%)的exploit效果：
- 如果低置信度exploit平均亏损 → 确认门槛设置合理或需提高
- 如果高置信度exploit也亏损 → 规则本身有问题，非置信度问题
```

### 4.3 学习阶段对比

```
前1/3 session vs 后1/3 session：
- 后期胜率应>前期（画像更准确）
- 如果后期反而更差 → 可能存在对手调整或过拟合
```

---

## 第五步：失血与巨亏诊断

基于 `bleed_pattern_analysis` + `catastrophic_hands_analysis`：

### 5.1 慢性失血源定位

```
从bleed报告提取：
- 失血速率(bb/hand) → 目标<1.0
- 偷盲成功率 → <25%说明偷盲策略需调整
- 最长连亏段 → 分析主因（翻后亏损 vs 盲注消耗）
- 翻后弃牌平均已投入 → >5BB说明进入翻后太深才放弃
```

### 5.2 巨亏手根因分析

```
对每手巨亏手：
- 类型分类（overplay/cooler/tilt/bad_call）
- equity轨迹：在哪条街equity大幅下降？
- 关键决策点：equity<40%时是否继续投入？
- 是否可避免？（cooler不可避免，overplay可避免）
```

**抽查触发条件：** 对每手巨亏手，读取对应hand.json确认advisor当时的建议是否合理。

---

## 第六步：位置与Equity轨迹审计

基于 `positional_leak_analysis` + `equity_trajectory_analysis`：

### 6.1 位置漏洞

```
- 哪些位置bb/hand为负？
- VPIP/PFR与GTO偏离>20%的位置 → 需要调整该位置的范围
- BB弃牌率>60% → 面对偷盲过弱
- BTN/CO open但偷盲成功率<25% → 对手不fold，需收紧或调整sizing
```

### 6.2 Equity轨迹模式

```
- "下降"模式占比 → 高占比说明经常在不利局面继续投入
- "下降"模式的平均亏损 → 止损是否及时
- "稳定高位"和"上升"模式的盈利 → 确认value extraction正常
```

---

## 第七步：跨Session趋势对比

每完成一个session的分析后，与前几个session对比：

### 7.1 核心指标趋势表

```
指标                    Session N-2   Session N-1   Session N   趋势
─────────────────────────────────────────────────────────────────
平均收敛分数              xx%          xx%          xx%        ↑/↓/→
校准误差                  xx%          xx%          xx%        ↑/↓/→
Exploit胜率              xx%          xx%          xx%        ↑/↓/→
失血速率(bb/hand)         xx           xx           xx        ↑/↓/→
巨亏BB                   xx           xx           xx        ↑/↓/→
偷盲成功率               xx%          xx%          xx%        ↑/↓/→
```

### 7.2 改进验证

```
对上一session提出的改进建议，检查本session是否改善：
- 同类问题频率是否下降？
- 是否引入新问题？（回归检查）
- 如果连续2个session无改善 → 升级为"系统性问题"，需要代码层面修改
```

---

## 第八步：生成改进建议

### 8.1 按优先级排序

```
优先级判定：
P0（立即修复）：导致巨亏的规则缺陷、系统性equity高估
P1（本轮修复）：失血速率>1.5bb/hand的漏洞、exploit胜率<40%的规则
P2（观察中）：收敛速度慢但无直接亏损、位置偏离但盈利
```

### 8.2 建议格式

```python
improvement = {
    "priority": "P0/P1/P2",
    "source_report": "哪份分析报告发现的",
    "issue": "问题描述",
    "evidence": "报告中的具体数据",
    "root_cause": "根因分析",
    "suggested_fix": "具体修改建议",
    "expected_impact": "预期改善",
    "verify_in_next_session": "下个session如何验证"
}
```

### 8.3 修改范围控制

```
每个session最多输出：
- P0修复：不限（必须立即处理）
- P1修复：最多3个（避免同时改太多无法归因）
- P2观察：记录但不修改，等待更多数据
```

---

## 执行节奏

```
每个session结束 → 执行步骤1-6（单session分析）
每3个session → 执行步骤7（跨session趋势对比）
发现P0问题 → 立即修复，下个session验证
P1问题 → 下个session前修复
P2问题 → 累积3个session数据后决定是否修复
```

---

## 抽查hand.json的时机

不再常规逐手审查，仅在以下情况抽查：
1. 巨亏手 → 必查，验证advisor建议合理性
2. 收敛异常对手 → 抽2-3手，看ground truth与学习值偏差来源
3. exploit反噬 → 查触发该规则的具体手牌，确认规则逻辑
4. 校准严重偏差 → 查高confidence但输的手牌，验证equity计算

---