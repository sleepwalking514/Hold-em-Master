## Problems V5 — 当前Agent待修复问题

**数据来源**：6个新session（session_20260421_002249/002512/002549/002607/002635/002654），共约228手。其中session_002635（21手）和session_002549（26手）快速输光，session_002654仅1手即出局。

**V4修复状态总结**：
- 问题1（Effective stack误算→深筹码push）：**已修复**，`eff_bb = max(opp_effs[0], min(hero_bb, 100))`
- 问题2（面对raise时equity无折扣）：**已修复**，`_action_based_equity_discount`按street/size施加0.55-0.82x折扣
- 问题3（薄价值bet对底对无限制）：**已修复**，`_is_bottom_pair`守卫在BET和CHECK分支
- 问题4（Cold-start discount覆盖不完整）：**部分修复**，postflop已覆盖，preflop仍跳过
- 问题5（Hand Strength分类过粗）：**已修复**，`_classify_two_pair`区分strong/medium/weak
- 问题7（对手画像未参与决策）：**已修复**，style labels + exploit priorities已集成
- 问题8（SPR≤1时sizing不合理）：**已修复**，SPR≤1时WEAK_MADE以上all_in
- 问题6（对手行动序列不缩窄range）：**已修复**，`_action_sequence_discount`累积折扣

---

### 问题1：TRASH牌力时equity仍>min_eq导致call——CALL分支缺少hand_strength守卫

**严重度：P0**

**证据**：
- Hand#1 (session_002654): Hero持AQs(BTN)，board 2c-4s-9h-Kd-4h。AI_3 4bet到315后flop bet 533(overbet)。Advisor基线建议fold（牌力TRASH），但eff_equity=42.6%（raw=55.7%，cold-start discount后）> flop min_eq(~30%)，所以CALL分支直接返回call
  - 注意：0手时`classify_style()`返回"未知"，exploit并未激活。显示的"[疯子Maniac]"是`style_label`属性的显示bug（无置信度检查），不影响决策
  - 真正的问题：AQ在249 board上完全miss（TRASH），raw equity 55.7%是对随机range计算的。但对手4bet+flop overbet的range极强（AA/KK/AK为主），AQ的实际equity应<20%
  - CALL分支（advisor.py line 411-422）只检查`discounted_eq > min_eq`，不检查hand_strength。当equity被高估时，TRASH牌也会被建议call
- Hand#26 (session_002549): Hero持A8o(BTN,680)，board Qc-3h-9d。Flop牌力TRASH（A8 on Q93），eff_equity=43.7% > min_eq → call 128。Turn board配对9后牌力升为WEAK_MADE，equity=43.3% → call 287。River equity=37% → all_in 145。全程跟注到出局
  - 问题：Flop时A8 on Q93是纯空气，43.7%的equity完全不反映面对3bet+cbet的实际range
- Hand#1 (session_002607): Hero持86o(BTN)，flop 7c-4s-9h。被分类为STRONG_DRAW（open-ended straight draw 5-8），equity=34.8% > min_eq → call 63。最终输216 chips
  - 这手draw分类合理，但34.8%的equity面对对手bet仍偏高

**分析**：
当前CALL分支的决策逻辑是：
```
if discounted_eq > min_eq → CALL
if discounted_eq < min_eq → FOLD
```
这个逻辑完全依赖equity准确性。但equity是对随机range计算的，面对4bet/3bet/overbet时严重高估。`_action_based_equity_discount`只在hero_bet+opp_raised时触发，对手直接bet时不折扣（见问题2）。

结果：基线说fold（因为牌力TRASH），但equity说call（因为42%>30%），equity覆盖了基线判断。

**修复建议**：
1. CALL分支增加hand_strength守卫：当牌力为TRASH且无draw时，即使equity > min_eq也应fold（或将min_eq提高到50%）
2. 当基线建议fold但equity建议call时，引入"冲突解决"机制：如果牌力≤TRASH，优先采纳基线的fold
3. 面对overbet（>pot）时，无论是bet还是raise，都应触发equity discount

---

### 问题2：对手直接bet/overbet时equity discount未触发——仅hero_bet+opp_raised才折扣

**严重度：P0**

**证据**：
- Hand#26 (session_002549): AI_3 3bet preflop后flop直接bet 128、turn直接bet 287。这些是对手主动bet而非raise Hero的bet。`_action_based_equity_discount`要求`hero_bet AND opp_raised`，对手直接bet时完全不触发折扣
  - Turn equity=43.3%（raw=54.1%），action_sequence_discount仅折扣了约10%，但对手连续两条街大额bet代表的range强度远不止10%折扣
- Hand#13 (session_002635): AI_2(CallStation) flop check-call后turn突然bet 98、river all_in 32。被动对手突然主动bet是极强信号，但equity仍显示51%/49.6%，无任何折扣
- Hand#40 (session_002249): AI_2 turn直接bet 104（Hero flop bet后AI_2 call，turn AI_2主动bet）。这个"check-call转bet"的行动模式暗示对手在turn改善了牌力，但系统未识别

**分析**：
`_action_based_equity_discount`（advisor.py line 591）的条件`if not (hero_bet and opp_raised): return equity`过于严格。实际上对手的直接bet（尤其是overbet和连续bet）同样传递了range信息：
1. 对手flop bet + turn bet = 连续施压，range至少是中等牌力以上
2. 被动对手突然bet = 极强信号（CallStation/Fish几乎只在有强牌时主动bet）
3. Overbet（>pot）= 极化range（要么nuts要么bluff），但在低级别对手中通常是value

**修复建议**：
1. 扩展discount触发条件：当对手在当前street直接bet且`bet_size > 0.5 * pot`时，也应施加折扣（比raise折扣略轻，如0.85x/0.80x/0.75x for flop/turn/river）
2. 对手连续两条街以上bet时，`_action_sequence_discount`的折扣应递增（第一条街-5%，第二条街-10%，第三条街-15%）
3. 引入"被动对手突然激进"检测：当对手AF<25%但在当前street bet/raise时，额外折扣10-15%

---

### 问题3：Preflop open range过宽——BTN位open 86o/76o/K5o/43o导致postflop被动亏损

**严重度：P1**

**证据**：
- Hand#1 (session_002607): Hero持86o(BTN)，open raise 40。Flop 7c-4s-9h，AI_1 bet 63，advisor建议call（STRONG_DRAW，equity=34.8%）。Turn 7h，check through。River 2d，check through。AI_1持T8(pair T)赢，Hero输216 chips
- Hand#5 (session_002635): Hero持K5o(BTN)，open raise 50。Flop Jc-3s-Td完全miss，check。Turn 9h，AI_2 bet 71，Hero fold。净亏50 chips
- Hand#13 (session_002635): Hero持67o(BTN)，open raise 50。最终在A-high board上用底对6 call到river，输掉240 chips
- Hand#20 (session_002607): Hero持43o(BTN)，open raise。Flop 6h-8h-Js完全miss，check through到river勉强赢（对手更差）。这种"赢了也是运气"的hand不应该open

**分析**：
BTN位base open tier=9，这意味着86o(tier 7)、76o(tier 7)、K5o(tier 9)、43o(tier 9)都在open range内。在6人桌中，BTN open tier 9过于宽松——这些手牌在postflop几乎总是处于劣势，需要依赖bluff或运气赢pot。

统计：6个session中，Hero在BTN位open tier 8-10的手牌（垃圾牌），postflop进入的约15手中，仅3手盈利（多为对手fold），其余12手要么fold亏损open raise，要么call到后面亏损更多。

**修复建议**：
1. BTN位base open tier从9降到8，排除43o/K5o/Q2o等tier 9手牌
2. 或者：当有3+个对手还未行动时（即前面无人fold），BTN open tier降低1级
3. 对tier 8-10的手牌，postflop miss时应更积极fold而非依赖equity继续

---

### 问题4：HU（单挑）场景下Hero被持续3bet压制——open-fold循环消耗筹码

**严重度：P1**

**证据**：
- Session_002249后期（hand 30-60）：Hero与AI_2进入HU。AI_2被标记为Maniac（实际是LAG，VPIP=35% PFR=28%）。Hero的模式变成：
  - SB open raise 40 → AI_2 3bet 120 → Hero fold（hand#42 A4o, hand#48 42s, hand#56 86s, hand#60 J5o）
  - 每次fold损失40 chips，10手中有4手被3bet fold = -160 chips
  - Hero在60手后stack从3000降到1863，净亏约1137 chips
- 具体：Hand#60 Hero持J5o(SB)，open 40，AI_2 3bet 120，advisor建议fold（equity=42.8%）。这个fold本身合理，但问题是Hero不断open→被3bet→fold的循环
- Hand#42: A4o open→3bet→fold（equity=50.7%，但advisor建议fold）
  - 问题：A4o在HU SB位equity 50.7%面对3bet，pot odds 33%，按数学应该call或4bet。但advisor建议fold

**分析**：
1. **对手画像误分类**：AI_2实际是LAG（VPIP=35% PFR=28%），但被标记为Maniac（VPIP:50% PFR:70%）。观测PFR=70%远高于实际28%，说明小样本下PFR统计严重偏差。这导致系统高估对手的3bet频率
2. **面对频繁3bet无调整策略**：当对手3bet频率>40%时，Hero应该扩大4bet range或扩大call range，而非每次都fold。当前系统没有"anti-3bet"策略
3. **HU open range虽宽但无配套的3bet defense**：HU boost +4让Hero open几乎所有牌，但面对3bet时大部分都fold，等于白送40 chips

**修复建议**：
1. 当对手3bet频率>35%时，自动扩大面对3bet的call range（降低fold阈值）
2. 引入4bet bluff逻辑：当对手3bet频率>40%且Hero有blocker（Ax/Kx）时，考虑4bet
3. 如果连续3+手被3bet fold，降低open sizing（从40降到25-30）以减少fold损失
4. 修复PFR统计偏差：小样本时PFR应向先验值回归，避免10手数据就得出PFR=70%的结论

---

### 问题5：对手画像误分类——LAG被标记为Maniac，导致exploit方向偏差

**严重度：P1**

**证据**：
- Session_002249: AI_2 ground truth是LAG（VPIP=35% PFR=28% AF=50%），但从第10手起就被标记为Maniac（VPIP:60.9% PFR:57.9% AF:55.6%），一直持续到第60手（VPIP:50.6% PFR:70.5% AF:54.1%）
  - 观测VPIP=50.6% vs 实际35%：偏差+15.6pp
  - 观测PFR=70.5% vs 实际28%：偏差+42.5pp（！）
  - 这个PFR偏差极其离谱，60手后仍未收敛
- Session_002654: AI_3 ground truth是Maniac（VPIP=65% PFR=45%），但在0手时先验值就是VPIP:70% PFR:50% AF:75%，与实际偏差不大。问题是0手时就以高置信度激活exploit
- Session_002635: AI_2 ground truth是CallStation（VPIP=50% PFR=8% AF=18%），观测为松鱼（VPIP:58% PFR:9% AF:16%）。标签基本正确但VPIP偏高8pp

**分析**：
PFR统计偏差的根因可能是：
1. **样本选择偏差**：PFR只在preflop有意义，但如果统计时分母不是"所有preflop机会"而是"参与的手牌"，会严重高估
2. **先验值影响过大**：AI_2的先验PFR可能就很高，小样本时先验权重过大导致观测值被拉高
3. **HU场景下PFR自然偏高**：HU时几乎每手都要raise，导致PFR统计值膨胀。但这不代表对手是Maniac——HU的"正常"PFR就应该在50-70%

**修复建议**：
1. HU场景下的PFR/VPIP统计应使用HU专用基线（HU正常VPIP=60-80%，PFR=40-60%），而非6人桌基线
2. 标签分类时应考虑当前桌上人数：HU时VPIP=50%+PFR=70%不是Maniac，而是正常的LAG/TAG
3. 先验值的衰减速度应加快：20手后先验权重应<20%，当前可能仍>40%

---

### 问题6：style_label显示不检查置信度——0手时显示"疯子Maniac"误导分析

**严重度：P2**

**证据**：
- Hand#1 (session_002654): 所有对手0手数据，但advisor显示"AI_3 [疯子Maniac] VPIP:70% PFR:50% AF:75% (0手)"。实际`classify_style()`在0手时返回"未知"，exploit未激活。但显示层的`style_label`属性（player_profile.py line 221-233）直接用先验均值分类，无置信度检查
- 这不影响决策（advisor用的是`classify_style()`），但会误导人工复盘分析，让人以为exploit在0手时就激活了

**分析**：
存在两套风格分类系统：
1. `classify_style()`（advisor决策用）：有`avg_conf < 0.30`守卫，0手时返回"未知" ✓
2. `PlayerProfile.style_label`（显示用）：无置信度检查，直接用prior mean分类 ✗

**修复建议**：
统一使用`classify_style()`，或在`style_label`属性中加入置信度检查：当`total_hands < 5`或平均置信度<30%时返回"未知"

---

### 问题7：River低equity主动bet/all-in——equity<40%时不应主动下注

**严重度：P1**

**证据**：
- Hand#26 (session_002549): River board Qc-3h-9d-9s-2c，Hero持A8o（pair 9 from board，实际只有A high kicker）。Equity=37%，advisor建议all_in 145。37%的equity主动push是明确的-EV
- Hand#40 (session_002249): River board Qs-7s-9h-Kc-6s，Hero持Q4h（top pair weak kicker）。Equity=57.9%，advisor建议bet 242。对手raise后equity降到50.9%仍建议call。虽然57.9%看似够bet，但Q4在QKXX board上是很弱的top pair，river bet 242是过度薄价值

**分析**：
当前river bet的equity floor似乎不够严格。V3修复了river equity floor按board wetness区分（wet board 40%，dry board 35%），但：
1. 37% equity仍然通过了某些条件触发all_in（可能是SPR≤1的逻辑：SPR=0.1时WEAK_MADE以上all_in）
2. 弱top pair（Q4 on Q-K board）在river bet时，应考虑"被call时的equity"而非"对随机range的equity"——被call时对手range更强，实际equity会大幅下降

**修复建议**：
1. River主动bet时，equity门槛应提高到50%（而非当前的35-40%）
2. 引入"被call时equity估算"：river bet时，假设对手只会用top 50% range call，重新计算equity
3. SPR≤1时的all_in逻辑应增加equity下限：即使SPR≤1且WEAK_MADE，equity<45%时也不应all_in

---

### 问题8：Preflop 3bet call range在multiway pot中过宽——QJs/77面对3bet+cold call仍建议call

**严重度：P2**

**证据**：
- Hand#12 (session_002549): Hero持QJs(CO)，open 50。AI_2 3bet 150，AI_5 cold call 150。Advisor建议Hero call（equity=40%，raw=44.4%）。Flop miss后check-fold，净亏150 chips
  - 问题：面对3bet + cold call（3人底池），QJs的implied odds不够好。Cold caller的range通常很强（能cold call 3bet的牌），Hero的QJs在3人底池中equity被高估
- Hand#10 (session_002635): Hero持77(UTG)，open 40。AI_3 3bet 120，AI_4 cold call 120。Advisor建议call（equity=42%）。Flop Kd-8d-3d（全花面），Hero bet 180（equity=25.4%！），最终all_in输掉630 chips
  - 问题：77面对3bet+cold call进入3人底池，flop全花面只有25% equity却bet 180，这是灾难性的决策链

**分析**：
面对3bet时的call决策没有考虑"已有cold caller"这个因素。当已有人cold call 3bet时：
1. 底池变成multiway，implied odds下降
2. Cold caller的range通常很强
3. 中等牌力（QJs/77）在multiway 3bet pot中的实现率很低

**修复建议**：
1. 面对3bet时，如果已有1+个cold caller，equity门槛提高10pp（从当前的~40%提高到~50%）
2. 小对子（22-88）面对3bet+cold call应fold（除非SPR>15有足够set mining implied odds）
3. Multiway 3bet pot中，postflop的equity floor应提高到45%

---

## V4残留问题

### 残留1：Cold-start discount不覆盖preflop

**严重度：P1**

advisor.py line 621: `if gs.street == Street.PREFLOP: return equity` 显式跳过preflop。这意味着冷启动期（<20手）的preflop决策（open range、3bet call等）不受任何折扣保护。

---

## 因果链总结

```
当前主要亏损链：

1. Equity高估 + CALL分支无牌力守卫（问题1+2）
   → Raw equity对随机range计算，面对4bet/overbet时严重高估
   → 对手直接bet时无equity discount
   → 基线说fold（TRASH），但equity说call（42%>30%）
   → Equity覆盖基线判断，TRASH牌call overbet
   → 单手亏损680-1000 chips，session首手出局

2. HU被3bet压制 + 画像误分类（问题4+5）
   → LAG被误分类为Maniac（PFR偏差+42pp，60手未收敛）
   → Hero不断open→被3bet→fold
   → 每手损失40 chips，10手-160 chips
   → 筹码缓慢流失，从3000降到1863

3. Preflop open range过宽（问题3）
   → BTN open 86o/76o/K5o/43o
   → Postflop miss后依赖equity继续
   → 稳定小额亏损累积

4. River低equity主动bet（问题7）
   → Equity 37%仍建议all_in（SPR≤1逻辑）
   → 弱top pair river bet被raise
   → 单手大额亏损
```

---

## 改进优先级

| 优先级 | 问题 | 预期收益 | 关联 |
|--------|------|---------|------|
| P0 | 问题1: CALL分支缺少hand_strength守卫 | 避免TRASH牌call overbet，预计避免session首手出局 | 新问题 |
| P0 | 问题2: 对手直接bet时equity无折扣 | 避免对手连续bet时无折扣的大额call亏损，预计每session减少100-300bb | V4#2修复不完整 |
| P1 | 问题3: Preflop open range过宽 | 减少垃圾牌open后的postflop亏损，预计每session减少20-40bb | V3#2相关 |
| P1 | 问题4: HU被3bet压制 | 减少open-fold循环的筹码流失，预计每session减少30-50bb | 新问题 |
| P1 | 问题5: 对手画像误分类（LAG→Maniac） | 修正exploit方向，避免对LAG使用Maniac策略 | 新问题 |
| P2 | 问题6: style_label显示不检查置信度 | 修复显示误导，不影响决策 | 显示bug |
| P1 | 问题7: River低equity主动bet | 避免37% equity all_in和弱top pair river bet | 新问题 |
| P2 | 问题8: Multiway 3bet pot call过宽 | 避免QJs/77在3人3bet pot中的亏损 | 新问题 |
| P1 | 残留1: Cold-start discount不覆盖preflop | 冷启动期preflop决策无保护 | V4#4残留 |
