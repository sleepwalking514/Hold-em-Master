# 自我学习流程设计

## 流程概述

每积累10手进入翻后的对局（非preflop fold），触发一次批量复盘。复盘聚焦两个维度：
1. 对手画像调整是否合理
2. Advisor建议是否合理

---

## 第一步：筛选有效样本

从最近的手牌中筛选出"有信息量"的手牌：

**入选条件**（满足任一）：
- Hero进入了翻后（至少看到flop）
- Hero在preflop面对加注做了call/raise决策
- 手牌到了showdown（无论Hero是否参与）
- Hero损失超过50bb的手牌

**排除条件**：
- 纯preflop fold且无对手showdown信息
- 盲注轮转中无人加注的walk

每次复盘取10手有效样本。

---

## 第二步：画像合理性审计

对每手牌中出现的对手画像标签，检查以下问题：

### 2.1 标签稳定性检查

```
对每个对手，记录最近20手中的标签变化序列：
- 如果标签在5手内来回切换（如 LAG→Maniac→LAG），标记为"标签震荡"
- 震荡原因通常是：置信度公式过于激进 + 样本边界效应
```

### 2.2 画像→行为一致性检查

```
对每个被标记为特定风格的对手，验证：
- 标记为"紧凶TAG"的对手：实际VPIP是否<26%？PFR是否>38%？
- 标记为"疯子Maniac"的对手：实际VPIP是否>42%？
- 如果标签与实际统计数据矛盾，标记为"标签失真"
```

### 2.3 画像信息利用率检查

```
对每手牌的advisor建议，检查：
- 画像中识别出的exploit机会（如"fold_to_3bet高"）是否被实际利用？
- 如果advisor建议fold，但画像显示对手有明显可exploit的弱点，标记为"exploit未执行"
- 统计：exploit识别次数 vs exploit实际执行次数 → 计算利用率
```

---

## 第三步：Advisor建议合理性审计

### 3.1 翻前决策审计

对每个preflop决策点：

| 检查项 | 判定标准 | 问题标签 |
|--------|---------|---------|
| 位置利用 | BTN/CO位equity>35%却fold | "位置浪费" |
| 3bet机会 | 对手fold_to_3bet>50%却从不3bet | "3bet缺失" |
| 范围过紧 | SB vs BB单挑，equity>40%却fold | "HU范围过紧" |
| 多人底池误判 | 2人底池被标记为"多人底池" | "人数误判" |

### 3.2 翻后决策审计

对每个postflop决策点：

| 检查项 | 判定标准 | 问题标签 |
|--------|---------|---------|
| 低equity call | equity<30%在river call | "亏损call" |
| exploit误用 | "对手激进→多call down"但Hero牌力为TRASH | "exploit反噬" |
| 下注尺寸 | value bet时对手fold_to_cbet<30%却用大尺寸 | "尺寸不当" |
| 止损缺失 | equity从flop到river持续下降(>20pp)但全程call | "无止损" |
| SPR忽视 | SPR<1时还在check而非push | "SPR误用" |

### 3.3 Equity可靠性审计

对到showdown的手牌：

```
比较advisor声称的equity vs 实际结果：
- 如果声称equity>60%但输了，检查range estimation是否合理
- 如果声称equity<35%但建议call，标记为"阈值失效"
- 统计：高equity(>60%)手牌的实际胜率 → 如果<50%说明equity系统性高估
```

---

## 第四步：模式识别与问题聚类

将10手牌中发现的问题按类型聚类：

### 4.1 频率统计

```
问题类型          | 出现次数 | 涉及金额 | 严重度
----------------|---------|---------|-------
位置浪费          |         |         |
exploit未执行     |         |         |
exploit反噬      |         |         |
亏损call         |         |         |
HU范围过紧       |         |         |
标签震荡          |         |         |
```

### 4.2 因果链分析

对每个高频问题，追溯根因：

```
问题：HU范围过紧
→ 直接原因：Solid基线查表结果为fold
→ 根因：基线范围表未区分人数（6人桌范围 vs 3人桌 vs HU）
→ 影响：每手fold损失0.5bb盲注，100手累计-50bb

问题：exploit反噬
→ 直接原因：exploit规则"high_aggression_defense"无条件触发call_down
→ 根因：规则缺少hand_strength前置条件
→ 影响：单次大额亏损（100-500bb）
```

---

## 第五步：生成改进建议

### 5.1 参数调整建议

基于观察到的问题，输出具体的参数修改建议：

```python
# 示例输出格式
adjustments = {
    "preflop_range": {
        "issue": "HU范围过紧",
        "current": "SB vs BB: fold K4o (equity 51%)",
        "suggested": "SB vs BB: open所有equity>45%的手牌",
        "expected_impact": "+2bb/100hands"
    },
    "exploit_guard": {
        "issue": "exploit反噬",
        "current": "aggression>40% → call_down无条件",
        "suggested": "aggression>40% AND hand_strength>=WEAK_MADE → call_down",
        "expected_impact": "避免TRASH牌call down，减少大额亏损"
    }
}
```

### 5.2 画像系统建议

```python
profile_adjustments = {
    "confidence_threshold": {
        "issue": "标签震荡",
        "current": "10手=76%置信度",
        "suggested": "提高到25手才达到70%置信度",
    },
    "exploit_activation": {
        "issue": "过早exploit",
        "current": "confidence>40%即激活exploit",
        "suggested": "confidence>60%才激活，之前用GTO基线",
    }
}
```

---

## 第六步：验证与回归测试

每次生成改进建议后，用接下来的10手有效样本验证：

```
验证指标：
1. 同类问题是否减少？（频率对比）
2. 是否引入新问题？（回归检查）
3. 整体盈亏是否改善？（ROI对比）

如果改善 → 保留调整
如果恶化 → 回滚并分析原因
如果无变化 → 保留但降低优先级
```

---

## 执行节奏

```
每10手有效样本 → 执行一次完整复盘（步骤1-5）
每20手有效样本 → 执行一次验证（步骤6）
每50手有效样本 → 生成一份阶段性报告，更新self-review-report.md
```

---