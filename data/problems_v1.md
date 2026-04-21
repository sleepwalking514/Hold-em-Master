## 当前数据观察到的核心问题

基于已有的10个session（共588手）的抽样分析：

### 问题1：Solid基线在短桌/HU场景下严重过紧

**证据**：
- Hand#140 (session_202337): K4o在SB位，equity 51.4%，对手AI_1的VPIP仅14%，advisor建议fold
- Hand#120 (session_202337): J2s在SB位，equity 48.1%，advisor建议fold
- Hand#100 (session_202337): 83s在SB位，equity 41.8%，advisor建议fold（这个合理）
- Hand#40 (session_202132): 76o在SB位 vs 单个对手，equity 42.6%，advisor建议fold

**分析**：当桌上只剩2-3人时，SB vs BB的open范围应该极宽（top 60-70%）。但advisor仍然使用6人桌的范围表。K4o在HU中是标准open，equity 51%远超所需阈值。

**影响**：每次不合理fold损失约0.5-1bb（放弃了正EV的偷盲机会）。在151手的session中，如果有50手是HU/3人桌，保守估计损失25-50bb。

### 问题2：Exploit规则"对手激进→多call down"是最大的亏损来源

**证据**：
- Hand#12 (session_202448): Q6s在flop上牌力为TRASH（board 4c-2s-7h），equity仅39.9%，但因为AI_4被标记为"疯子"，advisor建议call。这次碰巧赢了（对手纯bluff），但逻辑有问题。
- Hand#89 (session_202448): 84o hit底对，全程check-check到showdown输了。advisor的exploit note写着"对手激进→多call down"但对手根本没bet，这条规则完全没有触发场景却一直显示。
- Hand#10 (session_202337): ATo面对AI_1的all-in，advisor建议call（equity 62%）。AI_1被标记为"紧凶TAG VPIP:6%"——一个VPIP 6%的玩家all-in时range极强，62%的equity估计严重高估。

**分析**：exploit规则的问题不仅是"无条件触发"，更深层的是：
1. 对"紧凶"玩家的all-in range估计不足——VPIP 6%的玩家push时几乎只有AA-QQ/AK
2. "对手激进→多call down"这条规则在对手没有bet时也显示在建议中，造成信息噪音
3. 规则没有区分"对手在bluff"和"对手在value bet"——激进玩家也会有value

### 问题3：画像标签在早期样本下不可靠但已被用于决策

**证据**：
- Hand#1 (session_202337): 所有对手都是"0手"样本，但已经有了风格标签（AI_2标记为"疯子Maniac VPIP:70%"）。这些是初始先验，不是观察结果。
- Hand#5 (session_202448): AI_3在仅4手样本下被标记为"疯子Maniac VPIP:53%"，AI_4也是4手就被标记为"疯子Maniac VPIP:67%"。4手的样本量完全不足以判断风格。
- Hand#50 (session_202337): 49手后AI_1被标记为"紧凶TAG VPIP:14% PFR:50%"——PFR 50%的玩家不应该被归类为TAG（TAG的PFR通常在20-35%之间）。

**分析**：
1. 初始先验过于极端——0手就给出"疯子"标签会误导早期决策
2. 置信度公式`1-1/(1+sqrt(n))`在n=4时已经给出67%置信度，远超合理水平
3. 标签分类只看VPIP和aggression_freq两个维度，但PFR与VPIP的比值才是区分TAG/LAG/Maniac的关键

**追加修改要求**：
在sim-auto模式下，可以给对手ai设定初始化标签，但是这个标签不暴露给主视角ai，主视角ai看到的是一个初始的平均状态。我们先排除先验标签的影响，确保模型能在普通路人对局中发挥能力

### 问题4：Advisor的confidence值与实际决策质量不相关

**证据**：
- 大量fold决策的confidence=80%（高置信度），但其中很多是错误的fold（如K4o HU fold）
- 大量call决策的confidence=55%或45%（低置信度），但这些才是真正影响盈亏的关键决策
- Hand#5 (session_202448): 3bet KQo confidence=75%，面对4bet call confidence=55%。最终赢了+1432，但低confidence的决策反而是正确的。

**分析**：confidence值似乎只反映"是否符合基线"，而不是"这个决策的EV有多高"。符合基线的fold永远是高confidence，偏离基线的exploit play永远是低confidence。这导致系统在需要exploit时犹豫，在应该exploit时反而不敢。

### 问题5：多人底池判断逻辑有误

**证据**：
- Hand#1 (session_202337): 实际是4人底池（AI_4 call, AI_5 raise, Hero待决策, AI_1/AI_2还没行动），advisor写"多人底池(4人)"。但Hero fold后实际只有2人进入翻后。
- Hand#50 (session_202337): 3人桌（Hero, AI_1, AI_5），advisor写"多人底池(2人)"——2人不是"多人"。
- 多处出现"多人底池→牌力不足且弃牌收益低→倾向过牌/弃牌"的模板化建议，即使实际只有2人。

**分析**：多人底池的判断似乎是基于"当前还在底池中的人数"而非"预期会进入翻后的人数"。而且"多人底池→保守"的逻辑过于简单——在多人底池中有位置优势时，反而应该更积极地隔离。

---

## 改进优先级（基于本次观察更新）

| 优先级 | 问题 | 具体修复 | 预期收益 |
|--------|------|---------|---------|
| P0 | 短桌范围过紧 | 按实际人数动态调整open range，HU时SB open top 60% | +30-50bb/session |
| P0 | exploit call_down无条件触发 | 加入hand_strength>=WEAK_MADE前置条件 | 避免单次100-500bb亏损 |
| P1 | 置信度公式过激 | 将公式改为`1-1/(1+sqrt(n/4))`，使25手才达到70% | 减少早期误判 |
| P1 | 对紧玩家all-in range估计不足 | 当VPIP<15%的玩家all-in时，将其range缩窄到top 5% | 避免dominated call |
| P2 | 多人底池判断逻辑 | 基于"已投入筹码的玩家数"而非"座位数"判断 | 减少误导性建议 |
| P2 | confidence值无意义 | 重新定义confidence为EV-based而非baseline-deviation-based | 提升决策信号质量 |
| P3 | exploit规则信息噪音 | 只在规则实际触发时显示，对手未bet时不显示"多call down" | 减少认知负担 |
