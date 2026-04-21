## Problems V6 — 当前Agent待修复问题

**数据来源**：3个新session（session_20260421_150614/150707/150748），各60手，共180手。6人桌5/10盲注。

**V5修复状态总结**：
- 问题1（CALL分支缺少hand_strength守卫）：**已修复**，TRASH+无draw时强制fold（advisor.py line 462-466）
- 问题2（对手直接bet时equity无折扣）：**已修复**，`opp_bet and not hero_bet and pot_ratio > 0.5`分支已添加（line 681-696），按street/size施加0.70-0.88x折扣
- 问题3（Preflop open range过宽）：**未验证**，本轮3个session中BTN VPIP仍为75-83%，远超GTO基线
- 问题4（HU被3bet压制）：**未验证**，本轮session均为6人桌，HU场景较少
- 问题5（对手画像误分类LAG→Maniac）：**部分改善**，Session 1中AI_3(TAG)被误判为Maniac(收敛1%)，但Session 2中AI_1(CallStation)正确识别为松鱼
- 问题6（style_label显示不检查置信度）：**未修复**，Hand#28仍显示"疯子Maniac"标签（置信度71%但PFR学习值82%远超真实45%）
- 问题7（River低equity主动bet）：**部分改善**，Session 1 Hand#28 river fold正确（equity 30%），但turn仍bet 138（equity 37%）
- 问题8（Multiway 3bet pot call过宽）：**未验证**
- 残留1（Cold-start discount不覆盖preflop）：**未修复**

---

### 问题1：系统性Equity过度自信——3个session平均校准误差-28%~-33%

**严重度：P0**

**证据**：
- Session 1 (150614): 平均校准误差-33%，4个区间过度自信（<0.50区间偏差-32%，≥0.80区间偏差-27%）
- Session 2 (150707): 平均校准误差-30%，4个区间过度自信（≥0.80区间偏差-42%最严重）
- Session 3 (150748): 平均校准误差-28%，5个区间全部过度自信（≥0.80区间偏差-34%）
- 具体案例：Session 1 Hand#28，Hero持88在QAKTs board上，flop equity=49.6%（实际面对T4的pair T，但board上有3张overcard+顺子可能），turn equity=37.1%但仍建议bet 138
- ≥0.80 confidence区间的实际胜率仅44-59%，意味着advisor最有信心的决策中有一半以上是错的

**分析**：
Equity是对随机range的Monte Carlo模拟，不考虑对手的行动所暗示的range缩窄。虽然v5已添加`_action_based_equity_discount`和`_action_sequence_discount`，但折扣幅度不足：
1. 对手bet 0.5-1.0x pot时仅折扣12-18%，但实际range缩窄应导致equity下降25-40%
2. 对手连续多街bet时，折扣是线性累加而非指数递增
3. Confidence直接使用equity值，没有独立的校准机制——equity高估直接导致confidence高估

**修复建议**：
1. 增大`_action_based_equity_discount`的折扣幅度：对手直接bet时flop 0.75x→0.65x，turn 0.80x→0.70x，river 0.75x→0.60x
2. 引入confidence校准层：confidence不应直接等于equity，而应基于历史校准数据进行修正（如≥0.80区间实际胜率50%，则将confidence乘以0.6）
3. 对手连续bet时折扣应递增：第二条街额外-10%，第三条街额外-15%

---

### 问题2：VPIP系统性高估——多个session中对手VPIP学习值偏高15-25pp

**严重度：P0**

**证据**：
- Session 2: AI_1(CallStation, 真实VPIP=50%) 学习值65.3%，误差+15.3pp，置信度81%（高置信+高误差=学偏）
- Session 2: AI_3(Nit, 真实VPIP=12%) 学习值24.2%，误差+12.2pp，置信度64%
- Session 2: AI_4(CallStation, 真实VPIP=50%) 学习值65.3%，误差+15.3pp
- Session 3: AI_1(Nit, 真实VPIP=12%) 学习值24.2%，误差+12.2pp，置信度64%
- Session 3: AI_3(Fish, 真实VPIP=55%) 学习值73.3%，误差+18.3pp
- Session 1: AI_3(TAG, 真实VPIP=22%) 学习值44.2%，误差+22.2pp（收敛分数仅1%）
- 跨3个session，VPIP误差方向一致为正（高估），不是随机方差

**分析**：
VPIP的计算方式可能存在系统性偏差：
1. 6人桌中，Hero参与的手牌中对手更可能是主动入池的（选择偏差）——Hero fold时看不到对手是否fold
2. 贝叶斯先验可能偏高：如CallStation先验VPIP=50%，但实际观测到65%时先验无法有效拉回
3. 观测样本偏差：只有Hero参与的手牌才能观测对手行为，而Hero open时对手call的概率更高（条件概率偏差）

**修复建议**：
1. 检查VPIP统计是否包含了所有手牌（包括Hero fold后对手的行为），如果只统计Hero参与的手牌则存在选择偏差
2. 对VPIP的先验权重降低：当观测数>30时，先验权重应<10%（当前贝叶斯α+β初始值可能过大）
3. 引入"全桌观测"机制：即使Hero fold，也记录其他玩家是否入池，用于修正VPIP

---

### 问题3：WEAK_MADE在恐怖board上继续投入——turn bet逻辑缺少board texture守卫

**严重度：P1**

**证据**：
- Session 1 Hand#28: Hero持88(BTN)，board QcAcKsTs。Flop时88是underpair（WEAK_MADE），面对AI_2 bet 60，advisor建议call（equity 49.6%）。Turn出Ts形成QAKT四张broadway，88几乎没有胜率，但advisor建议bet 138（equity 37.1%，confidence 0.45）
  - Board上有4张broadway牌（Q/A/K/T），任何对手持有一张broadway牌就beat 88
  - 88在这个board上的真实equity应<15%，但系统给出37%
  - Advisor基线建议bet_small（WEAK_MADE+有位置+SPR=3.1），没有考虑board texture
- 这手最终亏损238 chips（23.8BB），是Session 1唯一的巨亏手

**分析**：
当前hand_strength分类只看Hero手牌与board的关系（pair/two pair/etc），不考虑board texture的危险程度。88在2-7-3 rainbow上是WEAK_MADE但相对安全，88在Q-A-K-T上也是WEAK_MADE但极度危险。基线对WEAK_MADE的处理是统一的bet_small/call，没有区分board texture。

**修复建议**：
1. 引入board_danger评分：统计board上broadway牌数量、连续性、花色集中度
2. 当board_danger≥3（如3+张broadway或3连张）且hand_strength≤WEAK_MADE时，降级为TRASH或强制check/fold
3. 在bet决策前检查：如果equity<40%且board_danger高，不应主动bet

---

### 问题4：BTN/SB位VPIP远超GTO基线——open range仍然过宽

**严重度：P1**

**证据**：
- Session 1: BTN VPIP=83%（GTO基线~42%，偏差+41pp），SB VPIP=73%（GTO基线~36%，偏差+37pp）
- Session 2: CO VPIP=100%（GTO基线~28%，偏差+72pp），SB VPIP=56%（偏差+20pp）
- Session 3: BTN VPIP=75%（偏差+33pp），SB VPIP=78%（偏差+42pp），UTG VPIP=60%（偏差+40pp）
- 3个session的BTN/SB VPIP均远超GTO基线，且偷盲成功率低：Session 1偷盲20%，Session 3偷盲0%
- Session 3偷盲净收益+245但成功率0%，说明盈利来自postflop而非偷盲本身

**分析**：
V5问题3（Preflop open range过宽）仍未修复。BTN/SB位open过多垃圾牌导致：
1. Postflop频繁miss，依赖equity继续（与问题1叠加）
2. 偷盲成功率低时，每次open-fold损失20-40 chips
3. 面对对手3bet时被迫fold，白送筹码

**修复建议**：
1. 收紧preflop open range：BTN目标VPIP 40-50%，SB目标35-45%，UTG目标15-20%
2. 根据对手fold_to_steal调整：如果对手fold_to_steal<30%，进一步收紧open range
3. 引入preflop hand ranking表，低于阈值的手牌直接fold不进入equity计算

---

### 问题5：BB弃牌率过高——3个session均超过60%红线

**严重度：P1**

**证据**：
- Session 1: BB弃牌率=64%（红线60%）
- Session 2: BB弃牌率=75%
- Session 3: BB弃牌率=86%（最严重）
- BB位GTO基线VPIP约40%，即弃牌率约60%。当前系统BB弃牌率持续偏高
- Session 3中BB VPIP仅14%，意味着86%的时候直接放弃BB，被偷盲严重

**分析**：
BB位已经投入1BB，面对open raise有更好的底池赔率（通常需要call 2-3BB看flop），应该defend更宽的range。当前系统在BB位过于保守，可能原因：
1. Preflop equity计算对BB位没有考虑底池赔率优势
2. BB位的open range表过紧
3. 面对min-raise时BB应defend 50-60%的手牌，但当前只defend 14-36%

**修复建议**：
1. BB位面对单次raise时，降低fold阈值：当pot odds > 30%时，equity > 28%即可call（当前可能要求>35%）
2. 增加BB位的defend range：面对BTN/SB open时，BB应defend至少40%的手牌
3. 引入BB special defense逻辑：面对min-raise时几乎不fold（除非手牌极差如72o/83o等）

---

### 问题6：Exploit后期效果不稳定——Session 2后期平均亏损，Session 3 GTO偏离盈利率仅33%

**严重度：P1**

**证据**：
- Session 2 (150707): 前期exploit平均+2.7BB/次，后期+6.4BB/次，胜率从21%升至100%（正常改善）
- Session 2 (150707): exploit总盈亏+255.1BB，表现良好
- Session 3 (150748): 前期exploit平均-0.8BB/次，后期-1.5BB/次（后期反而更差）
  - "对手被动→多bluff/少call down"规则：37次触发，低置信度时平均-43BB/次
  - "被动玩家→薄价值下注"规则：25次触发，低置信度时平均-127BB/次（极端亏损）
- Session 3 GTO偏离18次，仅6次盈利（33%），远低于Session 2的80%
- Session 2 (150707): "对手常摊牌→少bluff"规则2次触发，平均-6.4BB，画像正确但执行亏损

**分析**：
1. 低置信度exploit亏损严重：当画像置信度<50%时，exploit方向可能正确但执行过于激进
2. "对手被动→多bluff"规则在面对多个被动对手时过度触发（Session 3有3个CallStation/Fish），导致bluff频率过高
3. 后期反而更差说明：对手可能在调整（不太可能，AI对手是固定策略），或者exploit规则在特定board/situation下不适用
4. GTO偏离盈利率33%说明exploit整体在亏损，应收紧exploit触发条件

**修复建议**：
1. 低置信度(<50%)时禁止exploit，回退到GTO基线
2. "对手被动→多bluff"规则增加频率限制：每10手最多bluff 2次，避免过度bluff
3. 当exploit后期效果差于前期时，自动降低exploit频率（动态调节机制）
4. "对手常摊牌→少bluff"规则需要检查执行逻辑：画像正确但亏损说明规则本身有问题

---

### 问题7：画像收敛速度慢且存在系统性错误学习——60手后平均收敛仅29%

**严重度：P1**

**证据**：
- Session 1: 平均收敛30.9%，0/5收敛。AI_3(TAG)收敛仅1%，vpip/pfr/AF全部错误学习
- Session 2: 平均收敛28.8%，0/5收敛。AI_1(CallStation) vpip错误学习（65.3% vs 50%），AI_3(Nit) vpip/pfr错误学习
- Session 3: 平均收敛28.8%，0/5收敛。AI_1(Nit) vpip错误学习（24.2% vs 12%），AI_2(Fish)收敛仅4%
- 跨3个session共15个对手画像，0个收敛，平均收敛29.5%
- VPIP是最常见的错误学习指标，方向一致为高估（见问题2）
- fold_to_cbet在所有session中观测次数极低（0-7次），可观测性仅50%

**分析**：
1. 60手样本对于贝叶斯收敛来说确实偏少，但VPIP这种高频指标应该在30-40手就能收敛
2. VPIP系统性高估（问题2）直接导致画像分类错误：Nit被判为TAG，CallStation被判为松鱼
3. fold_to_cbet长期数据不足说明Hero的cbet频率过低，无法采集该指标
4. 收敛轨迹显示很多对手在10-15手后就停滞不前（如AI_1在Session 1从第10手起一直50%不变）

**修复建议**：
1. 优先修复VPIP统计偏差（问题2），这是画像收敛的根本障碍
2. 降低贝叶斯先验的初始权重（α+β初始值从当前水平减半），让数据更快主导
3. 增加Hero的cbet频率以采集fold_to_cbet数据
4. 当收敛分数连续5个快照无变化时，触发"重新评估"机制，检查是否存在系统性偏差

---

### 问题8：PFR学习值严重偏高——TAG/Nit对手PFR被高估20-40pp

**严重度：P1**

**证据**：
- Session 1: AI_3(TAG, 真实PFR=18%) 学习值73.9%，误差+55.9pp（极端偏差）
- Session 1: AI_2(Maniac, 真实PFR=45%) 学习值82.4%，误差+37.4pp
- Session 3: AI_1(Nit, 真实PFR=10%) 学习值38.5%，误差+28.5pp
- Session 2: AI_4(CallStation, 真实PFR=8%) 学习值14.3%，误差+6.3pp（相对较小）
- PFR偏差方向与VPIP一致，均为高估

**分析**：
PFR（Preflop Raise Frequency）的统计可能存在与VPIP相同的选择偏差问题。此外：
1. PFR的观测样本更少（只有对手主动raise时才计数），小样本下先验影响更大
2. 如果先验PFR设置偏高（如Maniac先验PFR=50%），少量观测无法修正
3. AI_3(TAG)的PFR学习值73.9%远超任何合理范围，说明统计逻辑可能有bug（如把call也计入了raise）

**修复建议**：
1. 检查PFR统计逻辑：确认只统计主动raise/3bet，不包含call或limp-raise
2. 降低PFR先验权重，特别是对紧型对手（Nit/TAG）的先验PFR应设为10-20%而非更高
3. 增加PFR合理性检查：如果PFR > VPIP，标记为异常（PFR不可能超过VPIP）

---

### 残留问题

**残留1：Cold-start discount不覆盖preflop（V4#4残留，V5残留1）**
- `_cold_start_discount`在preflop时直接return equity（line 637），冷启动期preflop决策无保护
- 本轮Session 1 Hand#28 preflop equity=50.8%（0手观测AI_2），无任何折扣

**残留2：Preflop open range过宽（V5#3）**
- BTN/SB VPIP仍远超GTO基线，本轮升级为问题4

---

## V5→V6修复验证

| V5问题 | 状态 | V6验证 |
|--------|------|--------|
| #1 CALL分支缺少hand_strength守卫 | ✅已修复 | TRASH+无draw时正确fold（line 462-466） |
| #2 对手直接bet时equity无折扣 | ✅已修复 | opp_bet分支已添加（line 681-696），但折扣幅度不足（升级为V6#1） |
| #3 Preflop open range过宽 | ❌未修复 | BTN VPIP仍75-83%（升级为V6#4） |
| #4 HU被3bet压制 | ⏸未验证 | 本轮无HU session |
| #5 对手画像误分类 | ⚠部分改善 | VPIP系统性高估导致分类仍有偏差（V6#2/7/8） |
| #6 style_label显示不检查置信度 | ❌未修复 | 低优先级 |
| #7 River低equity主动bet | ⚠部分改善 | River fold正确，但turn仍bet（V6#3） |
| #8 Multiway 3bet pot call过宽 | ⏸未验证 | 本轮无明显案例 |
| 残留1 Cold-start preflop | ❌未修复 | 仍然残留 |

---

## 跨Session趋势对比

```
指标                    Session 1     Session 2     Session 3     趋势
─────────────────────────────────────────────────────────────────
平均收敛分数              30.9%        28.8%        28.8%        → 停滞
校准误差(平均)            -33%         -30%         -28%         ↑ 微改善
Exploit总盈亏            +255.1BB     +124.8BB     +312.0BB     → 波动
Exploit胜率              48%          43%          34%          ↓ 下降
失血速率(bb/hand)         -1.41        -1.16        -1.26        ↑ 微改善
巨亏BB                   -23.8        0            -23.6        → 正常
偷盲成功率               20%          30%          0%           ↓ 不稳定
BB弃牌率                 64%          75%          86%          ↓ 恶化
GTO偏离盈利率             50%          80%          33%          ↓ 不稳定
```

**趋势分析**：
1. 校准误差从-33%改善到-28%，说明v5的equity discount修复有效果，但幅度不足
2. Exploit胜率持续下降（48%→43%→34%），exploit策略在当前参数下越来越不稳定
3. BB弃牌率持续恶化（64%→75%→86%），这是一个新发现的系统性问题
4. 失血速率稳定在1.2-1.4 bb/hand，低于2bb/hand红线但仍有改善空间
5. 画像收敛完全停滞在29%左右，VPIP系统性高估是根本原因

---

## 亏损链路分析

```
1. Equity系统性高估（问题1）
   → 所有confidence区间过度自信
   → 导致CALL/BET决策在不利局面继续投入
   → 叠加board texture不考虑（问题3）
   → 88在QAKT board上turn bet 138
   → 单手巨亏23.8BB

2. VPIP系统性高估（问题2）→ 画像错误（问题7/8）
   → Nit被判为TAG，CallStation被判为松鱼
   → Exploit方向偏差（对"松"的对手bluff更多，但对手实际更紧）
   → Exploit后期效果恶化（问题6）
   → Session 3 exploit后期平均-1.5BB/次

3. Open range过宽（问题4）+ BB过弱（问题5）
   → BTN/SB open垃圾牌 → postflop miss → 依赖高估的equity继续
   → BB面对偷盲过度fold → 被对手免费偷盲
   → 两端都在漏筹码
```

---

## 改进优先级

| 优先级 | 问题 | 预期收益 | 关联 |
|--------|------|---------|------|
| P0 | 问题1: Equity系统性过度自信 | 修正校准误差从-30%到-10%以内，预计每session减少50-100bb | V5#2修复不完整 |
| P0 | 问题2: VPIP系统性高估 | 修正画像准确度，预计收敛速度提升50% | 新问题（根因） |
| P1 | 问题3: WEAK_MADE缺少board texture守卫 | 避免恐怖board上继续投入，预计每session减少20-30bb | 新问题 |
| P1 | 问题4: BTN/SB open range过宽 | 减少垃圾牌open后的亏损，预计每session减少15-25bb | V5#3残留 |
| P1 | 问题5: BB弃牌率过高 | 减少被偷盲损失，预计每session减少10-20bb | 新问题 |
| P1 | 问题6: Exploit后期效果不稳定 | 避免低置信度exploit亏损，预计每session减少20-40bb | 新问题 |
| P1 | 问题7: 画像收敛速度慢 | 提升exploit准确度 | 问题2下游 |
| P1 | 问题8: PFR学习值严重偏高 | 修正画像分类 | 问题2相关 |
| P2 | 残留1: Cold-start preflop无折扣 | 冷启动期preflop保护 | V4残留 |
| P2 | 残留2: style_label显示不检查置信度 | 显示修复 | V5#6残留 |
