## Problems V2 — 当前Agent待修复问题

**数据来源**：8个session（共387手），重点分析session_210935（14手速败）和session_210824（24手速败）

---

### 问题1：Hand Strength分类与Equity严重脱节——导致低equity bluff

**严重度：P0**

**证据**：
- Hand#4 (session_210935): Hero持86s，board为5h-2s-Jh-Js-Jc。River时equity仅12.19%，但hand_strength被分类为MEDIUM_MADE(5)，strength_ratio=0.75。Advisor建议bet 218（接近全部剩余筹码）。结果输掉981。
  - 问题核心：board上三条J，Hero的86s只有trip J with 8 kicker，但hand_strength系统认为这是"中等成牌"并建议value bet
  - 实际上对手持有AT（trip J with A kicker），Hero被dominated
- Hand#10 (session_210824): Hero持A6o，board为Jd-Qd-9d-Jh-Jc。River时equity=53.78%，hand_strength=MEDIUM_MADE(5)。Advisor建议bet 416（全部剩余筹码）。对手持Q6s hit full house，Hero输掉全部。
  - 问题核心：board上三条J+两张高牌，Hero只有trip J with A kicker。equity 53%看似合理但这是对随机range的equity，面对call range实际equity远低于50%

**分析**：
1. `hand_strength`分类只看"Hero手牌绝对强度"，不考虑board texture的危险性。当board配对/三条时，kicker战争极其常见，MEDIUM_MADE的分类会导致错误的value bet
2. Advisor在river用equity>50%+hand_strength>=MEDIUM_MADE就建议bet，但没有考虑"对手call我的range中我的equity是多少"（即implied equity vs calling range）
3. 这是速败session的最大亏损来源——单手亏损接近100bb

**修复建议**：
- 当board有三条（trips on board）时，hand_strength应该基于kicker排名而非绝对牌力
- River bet决策应加入"vs calling range equity"估算：如果对手只会用更好的牌call，则不应bet
- 或者更简单：当board已经有trips且Hero kicker不在top 3时，降级hand_strength

---

### 问题2：Preflop 3bet/4bet后call逻辑过于宽松——用边缘牌call大额加注

**严重度：P0**

**证据**：
- Hand#4 (session_210935): Hero持86s在BB位，面对AI_1的4bet(270)，baseline建议fold，但advisor override为call(confidence=0.65, equity=46.68%)
  - 问题：86s面对4bet的equity不可能是46%。对手4bet range通常是AA-TT/AK-AQ，86s对此range的equity约30%
  - 结果：Hero call 270后进入flop完全miss，最终输掉全部筹码
- Hand#1 (session_210935): Hero持44在BTN位，3bet到105后面对多人5bet(945)，advisor建议fold → 这次正确
- Hand#14 (session_210935): Hero持A6o在SB位，面对AI_1的3bet(150)，baseline建议fold，advisor override为call(confidence=0.85, equity=38.89%)
  - 问题：A6o面对3bet在多人底池中call，equity 38%在3人底池中不够（需要>33%但还要考虑position disadvantage和reverse implied odds）
  - multiway_note写着"控池，避免膨胀底池"但action却是call进入膨胀的底池

**分析**：
1. `_resolve_preflop()`中line 209-211：当tier<=8且equity>pot_odds*1.2时override fold为call。这个条件太宽松——86s的tier可能<=8，而equity计算对随机range给出了虚高的46%
2. Equity计算在面对3bet/4bet时仍然用`monte_carlo_equity()`对随机range模拟，没有缩窄对手range
3. `_adjust_equity_vs_tight_allin()`方法似乎只在all-in场景触发，对3bet/4bet场景不生效

**修复建议**：
- 面对3bet时，equity计算应将对手range缩窄到top 10-15%
- 面对4bet时，缩窄到top 5%
- 或者直接用tier作为硬性门槛：面对4bet时只有tier<=2的手牌才能call

---

### 问题3：Exploit Note方向显示错误——被动对手触发"激进→多call down"

**严重度：P1**

**证据**：
- Hand#10 (session_210824): exploit_note="AI_3: 对手激进→多call down (aggression_freq=16% vs基线40%)"
  - aggression=16% < 基线40%，对手明显是被动的，不是激进的
- Hand#14 (session_210935): exploit_note="AI_3: 对手激进→多call down (aggression_freq=19% vs基线40%)"
  - 同样的问题：19% < 40%，方向完全反了
- Hand#20 (session_210824): exploit_note="AI_3: 对手激进→多call down (aggression_freq=14% vs基线40%)"
- Hand#24 (session_210824): exploit_note="AI_3: 对手激进→多call down (aggression_freq=10% vs基线40%)"

**分析**：
`continuous_exploit()`在stat < baseline时返回负值。`high_aggression_defense`规则的description固定为"对手激进→多call down"，但当magnitude为负时，实际含义应该是"对手被动→少call down"。`top_exploits()`按`abs(magnitude)`排序，导致负方向的大偏差也被选为"最重要的exploit"并显示了正方向的description。

**修复建议**：
- 当magnitude为负时，显示反向description（如"对手被动→少call down / 多bluff"）
- 或者：只显示magnitude>0的exploit规则（即只显示"应该做什么"而非"不应该做什么"）
- `_compute_exploit()`中line 492已经过滤了DEFENSE类在not facing_bet时不显示，但没有过滤方向错误的情况

---

### 问题4：Equity系统性高估——对随机range计算而非对手实际range

**严重度：P1**

**证据**：
- Hand#5 (session_210935): Hero持86s，flop为Ac-8h-4s。Advisor显示equity=68.36%（底对8）
  - 问题：对手BTN open后cbet，其range中有大量Ax和overpair，Hero底对8的实际equity应在35-45%
  - 结果：Hero call到river输掉（对手持QTo hit pair of T on turn）
- Hand#4 (session_210935): 86s面对4bet，equity显示46.68%
  - 实际：面对4bet range(AA-TT,AK-AQ)，86s equity约28-32%
- Hand#10 (session_210824): A6o在flop Jd-Qd-9d上equity=54.6%
  - 实际：对手call了preflop open，其range中有大量Jx/Qx/flush draw，A6o无花无顺的equity应在30-40%

**分析**：
`monte_carlo_equity()`用5000次模拟对随机手牌计算equity。`_compute_range_equity()`存在但只在postflop且有board时才触发，且依赖`HandRangeEstimator`的range_matrix。在早期手牌（对手profile不足）时，range estimation不可用，fallback到raw equity。

这导致了一个系统性偏差：所有equity都偏高，因为实际对手的range比随机range强（他们选择了参与这手牌）。

**修复建议**：
- Preflop面对raise/3bet/4bet时，应用一个简单的range缩窄：对手raise→top 20%，3bet→top 10%，4bet→top 5%
- Postflop在没有range_matrix时，至少根据对手preflop action缩窄range（如：对手preflop raise过，则排除bottom 60%的手牌）
- 或者对raw_equity施加一个"action-based discount"：面对bet时equity *= 0.8，面对raise时 *= 0.7

---

### 问题5：低Equity时仍建议Bet——River Bluff决策缺乏合理性检查

**严重度：P1**

**证据**：
- Hand#4 (session_210935): River时equity=12.19%，advisor建议bet 218。hand_strength=MEDIUM_MADE
  - 问题：equity 12%意味着Hero几乎肯定输，此时bet只有在对手会fold时才有意义（即bluff）。但advisor的reasoning是"MEDIUM_MADE → bet_small"，这是value bet逻辑而非bluff逻辑
  - 如果是bluff：需要评估对手fold frequency。如果是value bet：equity 12%不支持value bet
  - 两种逻辑都不支持这个bet，但advisor仍然建议了

**分析**：
Advisor的postflop决策流程是：先看hand_strength分类→决定action模板→再用equity调整confidence。但当hand_strength与equity严重矛盾时（如hand_strength=5但equity=12%），系统没有硬性拦截机制。

`_ev_based_confidence()`会降低confidence（从0.5降到0.45），但不会改变action本身。需要一个"equity floor"：当equity < 某个阈值时，无论hand_strength如何，都不应该bet for value。

**修复建议**：
- 加入硬性规则：River时equity < 25%且不是纯bluff场景（对手fold_to_river_bet < 50%）→ 不bet
- 或者：当equity与hand_strength矛盾超过2级时（如equity<30%但strength>=MEDIUM_MADE），强制重新评估hand_strength

---

### 问题6：3bet Bluff范围过宽——用垃圾牌3bet后被4bet陷入困境

**严重度：P2**

**证据**：
- Hand#4 (session_210935): 86s在BB位面对UTG open，advisor建议3bet(90)。baseline reasoning="Solid基线: 86s 在BB位 → 3bet"
  - 问题：86s在BB位对UTG open做3bet是极其激进的线路。UTG open range通常是top 15%，86s对此range的equity很差
  - 后续：被4bet后advisor又建议call，导致全部筹码投入一个dominated的spot
- Hand#1 (session_210935): 44在BTN位面对CO raise做3bet(105)，被4bet后正确fold
  - 但初始3bet本身就有问题：44在BTN位对CO raise应该flat call而非3bet（set mining value）

**分析**：
`_short_handed_boost()`给5人桌+1 tier boost，加上BB位facing raise的3bet tier本身就比较宽，导致86s这种手牌进入了3bet range。问题不在于3bet本身（作为bluff有时合理），而在于被4bet后的应对——系统没有"3bet bluff被4bet后必须fold"的逻辑。

**修复建议**：
- 3bet range分为"value 3bet"和"bluff 3bet"两类
- Bluff 3bet（tier>5的手牌）被4bet后必须fold，不应该用equity override
- 或者：面对4bet时，只有原始3bet是value range内的手牌才能继续

---

### 问题7：Multiway Note与实际Action矛盾

**严重度：P2**

**证据**：
- Hand#14 (session_210935): multiway_note="多人底池(3人): 牌力不足且弃牌收益低→倾向过牌/弃牌"，但advisor action=call(150)
- Hand#24 (session_210824): multiway_note="多人底池(3人): 中等牌力多人底池→控池，避免膨胀底池"，但advisor action=call(945) all-in
- Hand#1 (session_210753): multiway_note="控池，避免膨胀底池"，但advisor建议call 945 all-in

**分析**：
`_analyze_multiway()`生成的note是纯信息性的，不影响实际action决策。`_resolve_preflop()`中的equity override逻辑完全独立于multiway分析。这导致系统一边说"应该控池"一边做着膨胀底池的action。

**修复建议**：
- Multiway note应该作为action modifier：当note建议"控池"时，应该提高call/raise的equity门槛（如从35%提高到45%）
- 或者：当multiway_note与action矛盾时，不显示note（避免信息混乱）

---

## 因果链总结

```
速败根因链：
1. Equity高估（对随机range计算）
   → 边缘牌被override为call/raise
   → 进入dominated的spot
   → 单手大额亏损（50-100bb）

2. Hand Strength与Board Texture脱节
   → Board trips时仍认为是"中等成牌"
   → River用低equity做value bet
   → 被更好的kicker/full house call掉

3. 3bet bluff无退出机制
   → 垃圾牌3bet后被4bet
   → Equity override建议call
   → 全部筹码投入-EV spot
```

---

## 改进优先级

| 优先级 | 问题 | 预期收益 |
|--------|------|---------|
| P0 | Hand Strength在board trips时分类错误 | 避免单手100bb级bluff亏损 |
| P0 | 面对3bet/4bet时equity未缩窄对手range | 避免dominated call，每session节省50-200bb |
| P1 | Exploit Note方向显示错误 | 消除信息混乱 |
| P1 | Equity系统性高估（全局） | 减少所有街的错误call/bet |
| P1 | 低equity时仍bet（缺乏equity floor） | 避免river bluff亏损 |
| P2 | 3bet bluff被4bet后无fold机制 | 避免preflop大额亏损 |
| P2 | Multiway Note与Action矛盾 | 提升决策一致性 |
