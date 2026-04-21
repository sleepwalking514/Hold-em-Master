## Problems V4 — 当前Agent待修复问题

**数据来源**：5个新session（session_20260420_231051/231114/231139/231155/231217），共约185手。其中2个session在22-29手内输光（session_231139/231155），说明存在致命级问题。

---

### 问题1：Effective stack计算使用players_in_hand——深筹码Hero被迫进入push/fold模式

**严重度：P0**

**证据**：
- Hand#32 (session_231051): Hero持T7o在SB位，stack=3135(313.5bb)。AI_4(2775)已fold，剩余对手AI_3(5)和AI_5(85)。Advisor建议all_in 3135，equity=27.35%，baseline="Solid基线: T7o 在SB位 → push"
  - 根因：`effective_stack_bb = min(3135, 85)/10 = 8.5bb` → 进入push_fold模式
  - 实际：Hero有313.5bb，这绝不是push/fold场景。T7o在SB位313bb深度应该open raise或fold
- Hand#28 (session_231051): Hero持QTo在SB位，stack=2190(219bb)。同样被建议push，equity=56.72%
  - 虽然这手赢了，但219bb深度push QTo是极端错误的策略

**分析**：
`gto_baseline.py` line 49-59: `effective_stack_bb`使用`players_in_hand`中对手的stack计算。当深筹码对手fold后，只剩短筹码对手，effective stack变得极小，触发push/fold逻辑。

V3修复了`num_players`参数（line 73改用`game_state.players`），但**没有修复effective_stack的计算**（line 49仍用`players_in_hand`）。这是V3问题2的残留——修了一半。

```python
# gto_baseline.py line 49-59 当前代码
opponents = [p for p in game_state.players_in_hand if p.name != hero.name]
...
opp_effs = sorted(
    [effective_stack_bb(hero, v, game_state.big_blind) for v in opponents],
    reverse=True,
)
eff_bb = opp_effs[0]  # 取最大的effective stack
```

当所有深筹码对手fold后，`opp_effs[0]`可能只有8.5bb，Hero被迫进入push/fold。

**修复建议**：
effective_bb应取Hero自身stack和对手effective stack中的较大值，或者设置下限为Hero自身stack的bb数：

```python
hero_bb = hero.stack / game_state.big_blind
if not opponents:
    eff_bb = hero_bb
else:
    opp_effs = sorted(
        [effective_stack_bb(hero, v, game_state.big_blind) for v in opponents],
        reverse=True,
    )
    eff_bb = max(opp_effs[0], min(hero_bb, 100))  # 至少按hero自身深度的策略打
```

或更简单：当Hero stack > 40bb时，永远不进入push_fold模式：
```python
if stack_cat == "push_fold" and hero.stack / big_blind > 40:
    stack_cat = "short"  # 降级为short stack策略
```

---

### 问题2：Equity不考虑对手行动强度——面对raise/all-in时无折扣

**严重度：P0**

**证据**：
- Hand#26 (session_231217): Hero持A8o，board 8c-7c-Qd-7h-Kh。Hero bet 920，对手raise to 2461(all-in)。Advisor equity=64.45%，建议call。实际对手持Q7s（trips 7），Hero输掉3961 chips
  - 问题：对手在river raise all-in，其range极强（至少trips/full house/straight），Hero的two pair(8+7 from board)几乎drawing dead。64%equity是对随机range计算的，完全不考虑对手raise代表的牌力
- Hand#21 (session_231139): Hero持AQo，board Qs-9c-As-Ks-2h。Hero bet 412(all-in)，对手raise to 1280。Advisor equity=91.94%。实际对手持99（set of 9s），Hero输掉662 chips
  - 问题：91.94%的equity意味着系统认为Hero几乎必赢，但对手在river raise代表极强牌力

**分析**：
当前advisor在面对raise时（line 378-388），只检查`equity > pot_odds`就建议call，完全不考虑对手raise这个行为本身传递的信息。在river上，对手raise几乎总是代表value（尤其是大额raise），此时raw equity严重高估Hero的实际胜率。

这是当前最大的单手亏损来源。Top 3亏损手牌（3961/662/449 chips）中有2手是因为面对raise时equity未折扣。

**修复建议**：
面对raise时对equity施加"action-based discount"：

```python
# 在 advisor.py 的 CALL 分支前加入
if action == ActionType.CALL and gs.current_bet > hero.current_bet:
    raise_size = gs.current_bet - hero.current_bet
    pot_ratio = raise_size / gs.pot if gs.pot > 0 else 1.0
    if gs.street == Street.RIVER:
        # River raise几乎总是value，大额raise更是如此
        if pot_ratio > 1.0:  # overbet raise
            equity *= 0.55
        elif pot_ratio > 0.5:
            equity *= 0.65
        else:
            equity *= 0.75
    elif gs.street == Street.TURN:
        if pot_ratio > 1.0:
            equity *= 0.65
        else:
            equity *= 0.75
```

---

### 问题3："薄价值下注"exploit驱动三条街bet底对——exploit反噬

**严重度：P0**

**证据**：
- Hand#20 (session_231155): Hero持33在BTN位，board 2s-9c-8d-5d-Ac。对手AI_5 aggression=16%（被动）。Exploit note="被动玩家→薄价值下注"。Advisor建议flop bet 57(equity 50.6%), turn bet 114(equity 49.6%), river bet 228(equity 46.1%)
  - Hero有底对3，board上有9/8/A三张overcards。对手持87（pair of 8s）
  - 结果：三条街共输449 chips
  - 问题：底对3在这个board上不是"薄价值"，而是"几乎没有价值"。对手call三条街说明至少有pair of 8+，Hero的33几乎drawing dead
- Hand#04 (session_231139): Hero持A6o在BB位，board Kd-6h-Kh-Qc-Th。Advisor建议三条街bet（equity从65%降到50%）。对手持K4s（trips K），Hero输341 chips
  - 问题：Hero有bottom pair(6)，board有paired K。Equity 65%对随机range，但对手call了preflop且call了flop raise，range中K/Q/T占比极高

**分析**：
"被动玩家→薄价值下注"这个exploit规则的问题不在于方向（V3已修复），而在于**没有牌力下限**。当前逻辑：
1. 对手被动 → exploit建议"薄价值下注"
2. Advisor看到hand_strength >= WEAK_MADE(4) → 认为可以bet
3. 底对(pair of 3s on 9-8-A board)被分类为WEAK_MADE → 满足条件 → bet

但底对在多overcards board上不是"薄价值"，而是"几乎没有价值"。薄价值下注应该至少是top pair weak kicker或middle pair on dry board。

**修复建议**：
对"薄价值下注"exploit加入board texture和相对牌力检查：

```python
# 在exploit驱动bet时，检查hand是否真的有"薄价值"
if exploit.get("thin_value"):
    # 底对(pair rank < any board card rank)不算薄价值
    if strength.value <= HandStrength.WEAK_MADE.value:
        hero_pair_rank = get_pair_rank(hero.hole_cards, board)
        board_ranks = sorted([Card.get_rank_int(c) for c in board], reverse=True)
        if hero_pair_rank is not None and hero_pair_rank < board_ranks[1]:
            # 底对或次底对，不执行薄价值bet
            return ActionType.CHECK, 0, 0.60
```

---

### 问题4：Cold-start discount覆盖不完整——range_equity存在但置信度低时折扣被绕过

**严重度：P1**

**证据**：
- advisor.py line 64: `if effective_equity is not None and range_equity_val is None:` — 仅在range_equity完全不可用时才触发cold-start discount
- 5个session的前10手几乎全部使用raw_equity（对手profile不足），equity系统性偏高10-20个百分点
- Hand#04 (session_231139): A6o flop equity=75.42%(raw)，实际对手持K4s(trips)，真实equity<15%

**分析**：
当HandRangeEstimator过早返回非None的range_matrix（即使只基于3-5手数据），`range_equity_val`不为None，cold-start discount被跳过。blend中75%的raw_equity完全未折扣。

**修复建议**：
将触发条件改为基于对手样本量：

```python
opponents_list = [p for p in game_state.players_in_hand if p.name != hero.name]
min_hands = min(
    (self.profiles[o.name].total_hands if o.name in self.profiles else 0)
    for o in opponents_list
) if opponents_list else 999
if effective_equity is not None and min_hands < 20:
    effective_equity = self._cold_start_discount(game_state, hero, effective_equity)
```

---

### 问题5：Hand Strength分类过粗——Two Pair与Flush/Straight同级(MEDIUM_MADE)

**严重度：P1**

**证据**：
- Hand#21 (session_231139): Hero AQ on Qs-9c-As-Ks-2h，hand_rank=2479(Two Pair)，hand_strength=MEDIUM_MADE(5)
  - Two Pair AQ在这个board上是很强的牌，应该是STRONG_MADE
- Hand#26 (session_231217): Hero A8 on 8c-7c-Qd-7h-Kh，hand_rank=?(Two Pair)，hand_strength=MEDIUM_MADE(5)
  - 但这里的two pair是8+7(board pair)，实际很弱

**分析**：
`_classify_made_hand()`的分类：rank 1601-3500 → MEDIUM_MADE。这个范围包含了flush、straight、和two pair，但它们的实际强度差异很大：
- Flush/Straight: 通常是强牌
- Top two pair: 强牌
- Bottom pair + board pair: 弱牌

当前分类把它们全部归为MEDIUM_MADE，导致：
1. 强two pair(AQ on AQ board)只得到MEDIUM_MADE的bet sizing（bet_small），错失价值
2. 弱two pair(8+board pair)也得到MEDIUM_MADE，被鼓励继续bet

**修复建议**：
较大幅度地细化_classify_made_hand范围的分类，且根据two pair的具体组成（是否用到两张hole cards）来区分强弱。

---

### 问题6：SPR=0时仍建议bet_small——短筹码场景sizing不合理

**严重度：P2**

**证据**：
- Hand#25 (session_231217): Hero K8d，flop/turn时SPR=0.0，baseline建议"bet_small"和"bet_medium"
  - SPR=0意味着pot已经很大或stack很小，此时应该push或check，不应该用小尺寸bet
- 多手牌中出现SPR<1时advisor仍建议bet_small，没有自动转为push逻辑

**分析**：
当SPR≤1时，任何bet都会commit大部分stack。此时正确策略是：
- 有牌力 → push all-in（最大化fold equity + value）
- 没牌力 → check/fold

当前系统在SPR<1时仍按正常sizing逻辑出bet_small，导致：
1. 有价值时bet太小，给对手正确odds
2. 作为bluff时bet太小，对手永远不fold

**修复建议**：
```python
# 在bet sizing逻辑中加入SPR检查
if spr <= 1.0 and strength.value >= HandStrength.WEAK_MADE.value:
    return ActionType.ALL_IN, hero.stack, confidence
elif spr <= 1.0:
    return ActionType.CHECK, 0, 0.60
```

---

## 因果链总结

```
当前主要亏损链（按损失金额排序）：

1. 面对raise时equity无折扣（问题2）
   → 对手river raise all-in代表极强range
   → Advisor仍用raw equity(64-92%)建议call
   → 单手亏损662-3961 chips
   → 占总亏损的70%

2. Effective stack误算导致深筹码push（问题1）
   → 深筹码对手fold后，eff_bb降到8-15bb
   → Hero 200-300bb深度被迫进入push/fold
   → 用T7o/QTo push 2000-3000 chips
   → 虽然有时靠fold equity赢，但长期-EV

3. "薄价值下注"exploit对底对无限制（问题3）
   → 对手被动 → exploit建议薄value bet
   → 底对在overcards board上三条街bet
   → 对手call说明至少有better pair
   → 每次亏损200-450 chips

4. Cold-start equity高估（问题4）
   → 前20手raw equity偏高10-20pp
   → 边缘牌被错误bet/call
   → 稳定小额亏损累积
```

---

### ***重点问题7：对手画像（Style Label）未参与实际决策——classify_style仅用于展示

**严重度：P0**

**证据**：
- `classify_style(profile)`在advisor.py中仅在`_opponent_summary()`(line 457)被调用，生成展示用的文字摘要
- `get_exploit_priority(label)`定义了每种风格的exploit优先级映射（如CallStation→value_heavy 0.9, no_bluff 0.8），但**从未在生产代码中被调用**（仅在注释掉的测试中出现）
- 实际决策完全依赖单个stat的exploit规则（如aggression_freq > baseline → "薄价值下注"），不考虑对手整体风格

**影响**：
1. 面对CallStation（跟注站）：系统只看到"aggression低→被动→薄价值下注"，但不知道CallStation的核心特征是"几乎不fold"。正确策略是"纯value bet，永不bluff"，但当前系统可能在其他规则触发时仍建议bluff
2. 面对Nit（极紧玩家）：系统只看到单个stat，不知道Nit的raise几乎总是代表nuts。面对Nit的raise应该大幅fold，但当前系统没有这个逻辑
3. 面对LAG（松凶）：系统看到"aggression高→对手激进→多call down"，但不区分"有纪律的LAG"和"无脑Maniac"。对有纪律的LAG call down是亏损的
4. 对手水平（skill_estimate）：`_get_secondary_trait`中有"高水平/低水平"标签，但从未影响决策。面对高水平对手应该更保守，面对低水平对手可以更exploit

**分析**：
当前系统的exploit决策是"stat-driven"（基于单个统计数据），而非"style-driven"（基于对手整体画像）。这导致：
- 对手画像系统做了大量工作（style_labeler、skill_estimate、secondary_trait），但产出仅用于展示
- 决策只看"aggression_freq vs baseline"这类单维度比较，缺乏对手整体行为模式的理解
- 无法区分"对手被动因为是CallStation（会call到底）"和"对手被动因为是TightPassive（会fold）"——两者的exploit策略完全相反

**修复建议**：
将`get_exploit_priority`接入决策流程，根据对手风格调整exploit权重：

```python
# 在 _get_exploit_adjustments 中加入style-based调整
label = classify_style(profile)
style_priorities = get_exploit_priority(label)

# 根据风格抑制不合适的exploit
if "no_bluff" in style_priorities and style_priorities["no_bluff"] > 0.5:
    adjustments["increase_bluff"] = False  # 对CallStation不bluff
if "value_heavy" in style_priorities and style_priorities["value_heavy"] > 0.5:
    adjustments["widen_value"] = True  # 对CallStation/Fish加宽value range

# 根据对手水平调整
skill = profile.skill_estimate.overall_skill
if skill > 0.7:
    # 高水平对手：减少exploit幅度，更接近GTO
    modifier *= 0.5
```

同时，面对不同风格的对手，preflop range也应调整：
- 面对CallStation在后位：加宽open range（他们会用弱牌call）
- 面对Nit的raise：收紧call range（他们的raise range极强）
- 面对Fish：isolate raise更宽（单挑对弱手有优势）

---

### 问题8：Postflop对手行动序列未影响equity——对手call/raise不缩窄range

**严重度：P1**

**证据**：
- Hand#20 (session_231155): 对手AI_5 call了preflop raise，call了flop bet，call了turn bet。三次call说明对手至少有pair+。但advisor在river仍给Hero底对33 equity=46%
  - 如果对手range已缩窄到"至少pair of 8+"，Hero的33 equity应<10%
- Hand#04 (session_231139): 对手AI_3 call了preflop limp，raise了flop bet，call了turn bet。Flop raise说明对手至少有top pair+。但advisor在turn仍给Hero bottom pair equity=62%
  - 对手flop raise后range极强，Hero的pair of 6 equity应<20%

**分析**：
当前equity计算是"静态"的——每条街独立计算raw equity（对随机range的monte carlo），不考虑对手在之前街的行动已经缩窄了其range。`HandRangeEstimator`理论上可以做这个工作，但：
1. 冷启动期range_matrix为None，完全用raw_equity
2. 即使有range_matrix，当前的likelihood函数（`likelihood_bet/call/check`）过于简单，没有充分缩窄range

对手的每次call/raise都是信息：
- Call flop bet → 至少有draw或weak pair
- Call turn bet → 至少有pair或strong draw
- Raise → 至少有strong pair或better
- Call all three streets → 几乎确定有made hand

这些信息应该逐街累积折扣equity，但当前系统没有这个机制。

**修复建议**：
加入"对手行动序列折扣"：

```python
def _action_sequence_discount(self, gs: GameState, hero: Player, equity: float) -> float:
    """Discount equity based on opponent's action sequence (calls/raises narrow their range)."""
    if gs.street == Street.PREFLOP:
        return equity
    
    opp_calls = 0
    opp_raises = 0
    for street in (Street.FLOP, Street.TURN, Street.RIVER):
        for action in gs.action_history.get(street, []):
            if action.player_name != hero.name:
                if action.action_type == ActionType.CALL:
                    opp_calls += 1
                elif action.action_type in (ActionType.RAISE, ActionType.BET):
                    opp_raises += 1
    
    # 每次call缩窄range约10%，每次raise缩窄约20%
    discount = 1.0 - (opp_calls * 0.05 + opp_raises * 0.10)
    discount = max(discount, 0.60)  # 最多折扣40%
    return equity * discount
```

---

## 因果链总结

```
当前主要亏损链（按损失金额排序）：

1. 面对raise时equity无折扣（问题2）
   → 对手river raise all-in代表极强range
   → Advisor仍用raw equity(64-92%)建议call
   → 单手亏损662-3961 chips
   → 占总亏损的70%

2. Effective stack误算导致深筹码push（问题1）
   → 深筹码对手fold后，eff_bb降到8-15bb
   → Hero 200-300bb深度被迫进入push/fold
   → 用T7o/QTo push 2000-3000 chips
   → 虽然有时靠fold equity赢，但长期-EV

3. "薄价值下注"exploit对底对无限制（问题3）
   → 对手被动 → exploit建议薄value bet
   → 底对在overcards board上三条街bet
   → 对手call说明至少有better pair
   → 每次亏损200-450 chips

4. 对手画像未参与决策 + 行动序列不缩窄range（问题7+8）
   → 对手风格信息（CallStation/Nit/LAG）被浪费
   → 对手连续call/raise不影响equity估算
   → 系统无法区分"对手被动会fold"和"对手被动会call到底"
   → exploit方向可能完全错误

5. Cold-start equity高估（问题4）
   → 前20手raw equity偏高10-20pp
   → 边缘牌被错误bet/call
   → 稳定小额亏损累积
```

---

## 改进优先级

| 优先级 | 问题 | 预期收益 | 关联 |
|--------|------|---------|------|
| P0 | Effective stack误算→深筹码push | 避免200-300bb深度用垃圾牌push，每session减少大额风险敞口 | V3#2残留 |
| P0 | 面对raise时equity无折扣 | 避免river call all-in的巨额亏损，预计每session减少50-200bb | 新问题 |
| P0 | 薄价值bet对底对无限制 | 避免三条街bet底对的稳定亏损，预计每session减少20-50bb | 新问题 |
| P1 | Cold-start discount覆盖不完整 | 冷启动期减少错误call/bet | V3#3残留 |
| P1 | Hand Strength分类过粗 | 强two pair获得更大sizing，弱two pair不被鼓励bet | 新问题 |
| P1 | 对手画像未参与决策 | 利用style信息调整exploit方向，避免对CallStation bluff | 新问题 |
| P1 | 对手行动序列不缩窄range | 对手连续call/raise后折扣equity，避免底对三条街bet | 新问题 |
| P2 | SPR≤1时sizing不合理 | 短筹码场景正确push或check | 新问题 |
