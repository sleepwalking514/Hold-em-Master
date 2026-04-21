## Problems V3 — 当前Agent待修复问题

**数据来源**：3个session（session_20260420_221742/221754/221827），共约140手。对照problems_v2修复状态进行验证。

**V2修复状态总结**：
- 问题1（Hand Strength trips board）：已部分修复，加入了`_kicker_rank_on_trips_board()`
- 问题2（Preflop 3bet/4bet call过宽）：已部分修复，加入了tier门槛和equity discount
- 问题3（Exploit Note方向错误）：已修复REVERSE_DESCRIPTIONS，但引入了新bug → **V3已修复**（交换description与REVERSE_DESCRIPTIONS）
- 问题4（Equity系统性高估）：已部分修复，加入了range equity blending → **V3已修复**（加入cold-start discount）
- 问题5（低equity时仍bet）：已部分修复，加入了40% equity floor → **V3已修复**（加入turn floor 35%，river floor按board wetness区分）
- 问题6（3bet bluff被4bet）：已部分修复，tier门槛限制了call → **V3已修复**（小对子22-66不再3bet）
- 问题7（Multiway Note矛盾）：**V3已修复**（multiway_note传入preflop决策，控池时提高equity门槛，矛盾note不显示）

---

### 问题1：`low_aggression`规则语义反转——激进对手被标记为"被动玩家"

**严重度：P0**

**证据**：
- Hand#8 (session_221754): AI_1 aggression_freq=57%（>基线40%），flop exploit_note="AI_1: 被动玩家→薄价值下注 (aggression_freq=57% vs基线40%)"
- Hand#9 (session_221754): AI_1 aggression_freq=59%，exploit_note="AI_1: 被动玩家→薄价值下注"
- Hand#32 (session_221754): AI_2 aggression_freq=67%，exploit_note="AI_2: 被动玩家→薄价值下注"
- Hand#40 (session_221754): AI_2 aggression_freq=70%，exploit_note="AI_2: 被动玩家→薄价值下注"
- Hand#7 (session_221827): AI_3 aggression_freq=36%（<基线40%），exploit_note="AI_3: 对手激进→少薄价值下注"
  - 这里36%<40%是被动的，但REVERSE_DESCRIPTIONS显示"对手激进"

**分析**：
`low_aggression`规则（exploit_rules.py line 64）的description="被动玩家→薄价值下注"，语义上是"当对手被动时→我们应该薄价值下注"。但`continuous_exploit(stat, baseline)`返回`tanh(sensitivity * (stat - baseline))`：
- 当aggression=57% > baseline=40%时，magnitude > 0，不触发REVERSE_DESCRIPTIONS（line 136只在magnitude<0时替换）
- 结果：对手明明激进（57%），却显示"被动玩家→薄价值下注"

同时REVERSE_DESCRIPTIONS中`"low_aggression": "对手激进→少薄价值下注"`在magnitude<0时显示——但magnitude<0意味着stat<baseline，对手确实是被动的，此时显示"对手激进"也是错的。

**根因**：`low_aggression`规则的语义方向与其他规则相反。其他规则（如`high_fold_to_cbet`）的description对应magnitude>0的情况。但`low_aggression`的description"被动玩家→薄价值下注"对应的是magnitude<0的情况（stat<baseline=对手被动）。V2修复REVERSE_DESCRIPTIONS时没有处理这个语义反转。

**修复建议**：
两种方案任选其一：
1. 将`low_aggression`规则的description改为"对手激进→少薄价值下注"（匹配magnitude>0=stat>baseline的语义），REVERSE_DESCRIPTIONS改为"被动玩家→薄价值下注"（匹配magnitude<0）
2. 或者：在`evaluate()`中对`low_aggression`规则取反magnitude（`return -continuous_exploit(...)`），使得stat<baseline时magnitude>0，与description语义一致

---

### 问题2：`_short_handed_boost`使用players_in_hand而非table_size——导致开牌范围过宽

**严重度：P0**

**证据**：
- Hand#7 (session_221754): 5人桌（6人桌1人已出局），UTG fold后Hero在CO位。此时`players_in_hand`=4人，`_short_handed_boost(4)`=+2。CO open tier=8+2=10，导致42s（tier 10）被建议open
  - 实际：6人桌中1人fold不应改变开牌策略，42s在CO位不应open
- Hand#7 (session_221827): 6人桌，UTG limp后Hero在BTN位。`players_in_hand`可能=5或6，BTN open tier=9+1=10，导致85o（tier 10）被建议open
  - 实际：85o在满桌BTN位不应open raise（尤其面对UTG limp表示有人参与）

**分析**：
`gto_baseline.py` line 73: `num_players=len(game_state.players_in_hand)`传入的是当前还在手牌中的玩家数（已fold的不算），而非桌上总人数。这导致：
- 6人桌中2人fold后，剩余4人被当作4人桌处理，boost=+2
- 开牌范围被错误地放宽到tier 10（包含42s、85o、32s等垃圾牌）

`_short_handed_boost`的设计意图是：桌上人少→位置优势更大→可以开更宽。但"桌上人少"应该指table_size（固定的），不是"当前手牌剩余人数"（每手变化的）。后者的变化只意味着前面的人fold了（可能暗示他们牌差），不意味着我们应该用垃圾牌open。

**修复建议**：
- `_preflop_baseline()`中改用`game_state.num_seats`或`game_state.table_size`（桌上总座位数）而非`len(game_state.players_in_hand)`
- 如果GameState没有table_size字段，可以用`len(game_state.all_players)`（包含已fold的）
- 或者：将boost逻辑改为只在table_size<=4时才给+2，table_size<=3时+4

---

### 问题3：Equity仍然系统性高估——postflop对随机range计算

**严重度：P1**

**证据**：
- Hand#7 (session_221754): Hero持42s，flop 8h-7s-4c（底对4）。Equity=52.74%
  - 实际：对手AI_1 call了preflop raise，其range中有大量overpair和高牌，底对4的equity应在30-40%
  - 结果：advisor建议bet 47（基于52%equity），Hero输掉
- Hand#32 (session_221754): Hero持Q4s，flop Qh-Ad-Kh（中对Q，A/K在board上）。Equity=67.53%
  - 实际：对手UTG open range中有大量AK/AQ/KQ，Hero的Q4s在这个board上equity应<40%
  - 结果：Hero call到river输给straight
- Hand#7 (session_221827): Hero持85o，flop Qc-As-9h（完全miss）。Equity=27.11%
  - 这个相对合理，但turn时equity=24.41%仍建议bet 75（见问题4）

**分析**：
V2修复加入了`_compute_range_equity()`和range blending，但这依赖`HandRangeEstimator`有可用的`range_matrix`。在早期手牌（对手profile不足）时，`range_matrix`为None，fallback到`raw_equity`（对随机range的monte carlo）。

当前session的前10-20手几乎全部使用raw_equity，因为对手profile尚未建立。这段"冷启动期"的equity全部偏高，导致系统性的错误call/bet。

**修复建议**：
- 冷启动期（range_matrix不可用时）对postflop equity施加"position-based discount"：
  - 对手preflop raise过 → equity *= 0.80
  - 对手preflop 3bet过 → equity *= 0.70
  - 对手call了preflop raise → equity *= 0.85（至少排除了最差的手牌）
- 这比V2建议的方案更简单，不需要完整的range estimation，只需根据对手preflop action做一个粗略折扣

---

### 问题4：Turn bluff逻辑缺乏equity floor——低equity时仍建议bet

**严重度：P1**

**证据**：
- Hand#7 (session_221827): Hero持85o，turn board Qc-As-9h-Jc。Equity=24.41%，hand_strength=MEDIUM_DRAW(2)。Advisor建议bet 75
  - 问题：equity 24%在turn上bet，对手call后Hero几乎必输。这不是合理的bluff（board太湿，对手不太可能fold Qx/Ax/Jx）
  - baseline reasoning="牌力MEDIUM_DRAW (有位置, SPR=7.7) → bet_small"——系统把gutshot当作semi-bluff理由，但equity太低
- V2修复只在River加了40% floor（advisor.py line 400），Turn没有任何equity floor

**分析**：
River的equity floor（<40%→check）已生效，但Turn缺少类似保护。Turn上的semi-bluff需要满足两个条件：
1. 有足够的outs（draw equity）
2. 对手有合理的fold frequency

当前系统只看hand_strength（MEDIUM_DRAW=有4+ outs），不检查total equity是否支持bet。equity=24%意味着即使对手fold 30%的时间，bet的EV仍然是负的（除非sizing很小）。

**修复建议**：
- Turn加入equity floor：equity < 30%且hand_strength <= MEDIUM_DRAW时 → check
- 或者：Turn bet时要求equity > 30% OR 对手fold_to_turn_bet > 50%
- 不要对STRONG_DRAW施加此限制（flush draw + straight draw有足够equity支持semi-bluff）

---

### 问题5：Preflop 3bet范围仍然包含不适合3bet的小对子

**严重度：P2**

**证据**：
- Hand#10 (session_221742): Hero持22在BB位面对UTG open，baseline建议3bet(90)
  - 问题：22在BB位面对UTG open应该flat call（set mining），不应该3bet。3bet后被4bet必须fold，浪费了set mining的implied odds
  - 后续：被4bet后正确fold，但已损失90（9bb）
- THREE_BET_TIERS中BB位=5，加上short_handed_boost(5人)=+1，实际3bet tier=5+0=5（boost//2=0）。22是tier 6，不应该3bet
  - 但baseline显示"Solid基线: 22 在BB位 → 3bet"，说明实际计算结果是3bet

**分析**：
检查代码：`THREE_BET_TIERS["BB"]=5`，`sh_boost//2`对于5人桌=`1//2=0`。所以3bet tier=5。22是tier 6，不应该3bet。但baseline说3bet了。

可能原因：`facing_raise`判断时，`raise_count`可能>=2导致进入`facing_3bet`分支而非`facing_raise`分支。或者`players_in_hand`数量导致boost计算不同。需要进一步debug。

无论如何，小对子（22-55）面对open raise的最优策略是flat call for set mining，不是3bet。3bet后被4bet必须fold，损失了3bet sizing；flat call后hit set可以赢大pot。

**修复建议**：
- 在`get_preflop_advice()`的`facing_raise`分支中，对pocket pairs（tier 5-6的小对子）加入特殊逻辑：
  - 如果hand是pair且tier>=5，即使tier<=three_bet_tier也返回CALL而非THREE_BET
  - 理由：小对子的价值来自set mining implied odds，3bet会bloat pot并暴露手牌强度
- 或者：将22-55从tier 5-6中单独标记为"set mining only"类型

---

### 问题6：River equity floor 40%可能过于保守——错过薄价值bet

**严重度：P2**

**证据**：
- 多手牌中Hero在river持有中等牌力（如top pair weak kicker），equity在40-50%之间，系统正确bet
- 但观察到一些equity=38-39%的场景（如middle pair on dry board），对手range中有很多missed draw会fold，此时bet有正EV但被floor拦截

**分析**：
V2问题5的修复（equity<40%→check）解决了"12% equity还bet"的极端情况，但40%作为硬性阈值可能过高。在dry board上持有middle pair，equity可能只有38%（因为对手range中有overpair），但对手的missed draw（占range 30-40%）会fold，使得bet有正EV。

**修复建议**：
- 将硬性40% floor改为动态阈值：
  - Dry board（board_wet=false）：floor = 30%
  - Wet board（board_wet=true）：floor = 40%
- 或者：当hand_strength >= WEAK_MADE且board_wet=false时，降低floor到35%
- 保持TRASH牌的floor在40%不变

---

## 因果链总结

```
当前主要亏损链：

1. short_handed_boost误用players_in_hand
   → 垃圾牌（42s/85o/32s）被open
   → Postflop miss后equity仍偏高（对随机range计算）
   → 用垃圾牌bet/call → 稳定小额亏损累积

2. low_aggression规则语义反转
   → 激进对手被标记为"被动"
   → 系统建议对激进对手"薄价值下注"
   → 被激进对手raise/call → 亏损

3. Equity冷启动期无折扣
   → 前20手全部用raw_equity
   → 系统性高估10-20个百分点
   → 边缘牌被override为call/bet
```

---

## 改进优先级

| 优先级 | 问题 | 预期收益 | V2对应 |
|--------|------|---------|--------|
| P0 | low_aggression规则语义反转 | 消除exploit方向错误，避免对激进对手薄value bet | V2#3的修复引入的新bug |
| P0 | short_handed_boost误用players_in_hand | 避免垃圾牌open，每session减少20-50bb稳定亏损 | 新问题 |
| P1 | Equity冷启动期无折扣 | 前20手减少错误call/bet | V2#4残留 |
| P1 | Turn缺少equity floor | 避免turn低equity bluff | V2#5修复不完整 |
| P2 | 小对子不应3bet | 避免3bet后被4bet的9bb损失 | V2#6相关 |
| P2 | River equity floor过于保守 | 恢复部分薄value bet收益 | V2#5修复过头 |
