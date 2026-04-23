# Hold-em Master

`Hold-em Master` 是一个面向德州扑克实战记录、策略建议与复盘分析的命令行工具。它不是一个完整的线上扑克平台，而是一个偏训练与辅助决策的本地项目：你可以在终端中录入牌局、让 AI 给出建议、与模拟对手对战、批量跑自动对局，并把每一手牌和每次建议保存下来，供后续分析和自我学习使用。

整个项目围绕三件事展开：

1. **打牌时给建议**：基于翻前基线、翻后规则、蒙特卡洛胜率、底池赔率、对手画像和剥削规则给出建议动作。
2. **打完后能复盘**：按 session 保存手牌文本、JSON、画像快照和分析报告。
3. **对手会被建模**：系统会为每个对手维护画像，并在建议中逐步从“通用策略”过渡到“针对性剥削”。

## 适用场景

- 本地手动录入一桌德扑局面，边打边看建议
- 复盘自己在某一局中的动作、建议采纳情况和结果
- 用 AI 对手快速模拟大量手牌，观察策略、画像和分析报告是否合理
- 为后续策略调优、规则修正、自我学习工作流积累数据

## 核心特性

- 命令行交互式德扑牌局流程
- 支持实战模式、测试模式、AI 对战模式、全自动模拟模式
- AI 顾问会结合以下信息给出建议：
  - 翻前范围与规则基线
  - 翻后牌力判断
  - 蒙特卡洛 equity 估算
  - 范围 equity 与冷启动折扣
  - 底池赔率与 EV 校准
  - 对手画像与风格标签
  - exploit 调整与多人底池修正
- 可选对手先验类型，如 `极紧Nit`、`紧凶TAG`、`松凶LAG`、`跟注站`
- 自动记录手牌历史、建议内容、建议是否被采纳、输赢结果
- 自动保存 session 数据，支持后续生成分析报告
- 提供多组测试与模拟脚本，便于验证规则与行为

## 项目结构

```text
Hold-em-Master/
├─ main.py                     # CLI 入口与主流程
├─ requirements.txt            # Python 依赖
├─ env/                        # 游戏状态、动作空间、街道推进、规则基础
├─ engine/                     # AI 顾问、胜率、底池赔率、下注尺度、剥削逻辑
├─ data/                       # 翻前范围、翻后规则、手牌导出、复盘工作流
├─ profiler/                   # 对手画像、贝叶斯统计、风格识别、行为分析
├─ ui/                         # 终端交互、牌面解析、开局设置
├─ testing/                    # AI 对手、仿真流程、回放与分析脚本
├─ tests/                      # pytest 测试
└─ profiles/                   # 运行时生成，对手画像 JSON 存档
```

## 环境要求

- Windows、macOS、Linux 均可运行
- 推荐 Python `3.10+`
  - 项目代码使用了 `X | None` 这类 Python 3.10+ 语法
- 建议使用虚拟环境

## 安装

### 1. 克隆项目

```bash
git clone https://github.com/sleepwalking514/Hold-em-Master.git
cd Hold-em-Master
```

### 2. 创建虚拟环境

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

当前依赖包括：

- `numpy`
- `treys`
- `rich`
- `prompt-toolkit`
- `click`
- `pytest`
- `matplotlib`

说明：`requirements.txt` 中预留了 Web 版相关依赖，但目前默认未启用。

## 快速开始

最常用的启动方式：

```bash
python main.py
```

程序会引导你完成：

1. 输入玩家人数
2. 输入每位玩家名称与初始筹码
3. 选择你是哪个玩家
4. 设置小盲与大盲
5. 开始逐手进行牌局

按`ENTER`键接受默认设置。

如果启用了 AI 顾问（默认启用），轮到 Hero 行动时，系统会显示建议。

## 启动参数

`main.py` 提供以下命令行参数：

| 参数 | 作用 |
|---|---|
| `--skip-setup` | 跳过开局设置，使用默认 6 人桌 |
| `--test` | 测试模式，便于完整查看信息 |
| `--no-advisor` | 禁用 AI 顾问，只保留牌局记录与流程 |
| `--sim` | AI 对战模式，Hero 与 AI 对手进行牌局 |
| `--sim-auto` | 全自动模拟，多人桌批量生成数据 |
| `--sim-auto-solo` | 全自动 1v1 模拟，Hero 对单个随机 AI |
| `--max-hands N` | 全自动模式最大手数，默认 `60` |

### 常见用法示例

#### 1. 正常交互式使用

```bash
python main.py
```

#### 2. 用默认参数快速开局

```bash
python main.py --skip-setup
```

#### 3. 关闭顾问，只做手动录牌

```bash
python main.py --no-advisor
```

#### 4. 与 AI 对手对战

```bash
python main.py --sim
```

#### 5. 自动跑 200 手模拟

```bash
python main.py --sim-auto --max-hands 200
```

#### 6. 自动跑 1v1 压测

```bash
python main.py --sim-auto-solo --max-hands 500
```

## 使用说明

### 一、开局阶段

交互式启动后，程序会询问：

- 玩家人数
- 每位玩家名字
- 每位玩家起始筹码
- 你扮演哪位玩家
- 小盲、大盲大小

如果系统发现某个对手没有既有画像，且你启用了 AI 顾问，还会允许你给这个对手选择一个先验类型，例如：

- `极紧Nit`
- `岩石`
- `紧凶TAG`
- `松凶LAG`
- `疯子Maniac`
- `跟注站`
- `紧弱`
- `未知`

这一步的目的是让系统在样本很少的时候，也能先用一个比较合理的风格假设来辅助建议。

### 二、录入手牌与公共牌

项目支持手动输入牌，也支持直接回车随机发牌。

示例：

- 手牌：`Ah Kd`
- 翻牌：`Qs Jh 3c`
- 也支持紧凑形式：`AhKd`

如果直接按回车，系统会自动从剩余牌中随机抽取。

### 三、行动输入

轮到玩家行动时，常用输入如下：

| 输入 | 含义 |
|---|---|
| `F` | 弃牌 |
| `C` | 过牌 / 跟注 |
| `A` | 全下 |
| 数字 | 下注或加注到该金额 |
| `S` | 查看当前桌面信息 |
| `H` | 查看当前手牌行动历史 |
| `P` | 查看对手画像摘要 |
| `Enter` | 当存在 AI 建议时，直接采纳建议 |

说明：

- 当场上没人下注时，`C` 表示 `check`
- 当场上已有下注时，`C` 表示 `call`
- 输入数字时，程序会校验最小加注额
- 如果金额超过剩余筹码，会自动处理为 `all-in`

### 四、结束一手与继续游戏

每一手结束后，系统会：

- 结算本手输赢
- 记录手牌与动作
- 在有顾问的情况下保存当时的建议与采纳情况
- 必要时更新对手画像

你可以继续下一手，也可以输入 `Q` 退出 session。

## 运行模式详解

### 1. 实战模式

默认模式，适合边录边打。

特点：

- 以真人局面录入为主
- 你可以选择是否使用 AI 顾问
- 会维护对手画像与 session 数据

### 2. 测试模式

```bash
python main.py --test
```

适合验证牌局逻辑、调试和观察完整信息流。

### 3. AI 对战模式

```bash
python main.py --sim
```

在这个模式中，Hero 仍然可以手动操作，但对手由 `testing/simulation/ai_opponent.py` 中的 `AIOpponent` 控制。

适合：

- 检查牌局流程是否顺畅
- 验证 AI 对手风格是否符合预期
- 观察顾问在模拟对局中的建议表现

### 4. 全自动模拟模式

```bash
python main.py --sim-auto --max-hands 100
```

适合：

- 批量产出手牌数据
- 检验画像收敛速度
- 评估 exploit 规则是否有效
- 跑分析报告，做自我学习闭环

### 5. 全自动 1v1 模式

```bash
python main.py --sim-auto-solo --max-hands 100
```

适合更聚焦地分析：

- heads-up 决策
- 单一风格对手的适应过程
- exploit 与 confidence 校准

## 模块介绍

### `main.py`

项目总入口，负责：

- 解析命令行参数
- 创建游戏模式
- 进入每手牌、每条街的主循环
- 调用 `Advisor` 获取建议
- 处理玩家输入并转换为合法动作
- 调用记录器导出手牌与 session 数据

如果你想快速理解整个项目，建议优先看这个文件。

### `env/`

游戏规则层，核心模块包括：

- `action_space.py`
  - 定义 `GameMode`、`Street`、`ActionType`、`PlayerAction`
- `game_state.py`
  - 定义 `Player` 与 `GameState`
  - 负责位置分配、下盲、动作应用、街道推进、边池、结算
- `board_texture.py`
  - 分析公共牌面的湿润度、结构等特征
- `run_it_twice.py`
  - 支持 all-in 后发两次公共牌的流程

这一层回答的是：**当前桌面状态是什么、哪些动作合法、牌局如何推进。**

### `engine/`

策略与建议引擎，核心模块包括：

- `advisor.py`
  - AI 顾问总装配器
  - 把 baseline、equity、赔率、画像、exploit、多路池分析整合成最终建议
- `gto_baseline.py`
  - 规则基线
  - 为翻前和翻后提供默认策略骨架
- `equity_calculator.py`
  - 蒙特卡洛胜率估算
- `range_equity.py`
  - 手牌对范围的 equity 估算
- `pot_odds.py`
  - 底池赔率与 EV 辅助计算
- `bet_sizing.py`
  - 下注和加注尺度建议
- `street_planner.py`
  - 分街计划与后续路线
- `exploit_rules.py`
  - 根据对手画像做针对性调整
- `multiway_strategy.py`
  - 多人底池中的收紧、控池、诈唬抑制逻辑
- `reasoning.py`
  - 将建议组织成人类可读的解释文本

这一层回答的是：**在这个局面下，系统认为你更应该怎么打。**

### `profiler/`

对手建模与行为分析层，核心模块包括：

- `profile_manager.py`
  - 加载、创建、保存对手画像
  - 维护先验模板
- `player_profile.py`
  - 对手画像对象本体
- `bayesian_tracker.py`
  - 用贝叶斯方式更新 VPIP、PFR 等统计
- `style_labeler.py`
  - 将画像映射为 `Nit`、`TAG`、`LAG` 等风格标签
- `hand_range_estimator.py`
  - 依据行动推断对手范围
- `action_analyzer.py`
  - 评估动作质量与偏差类型
- `anti_misjudgment.py`
  - 防止过早、过度 exploit

这一层回答的是：**这个对手像什么类型的人、我们是否应该调整打法。**

### `data/`

静态策略数据和持久化输出层，主要包括：

- `preflop_ranges.py`
  - 翻前范围相关基线
- `postflop_rules.py`
  - 翻后牌力分类与规则建议
- `exploit_config.py`
  - exploit 相关配置与混合权重
- `hand_history.py`
  - 导出每手牌文本与 JSON
- `session_charts.py`
  - session 图表
- `self-learning-workflow.md`
  - 面向 session 报告的复盘流程说明

这一层回答的是：**基础策略数据从哪里来、结果最终保存到哪里去。**

### `ui/`

终端展示与交互层，核心模块包括：

- `terminal_ui.py`
  - 负责在终端中展示桌面、提示、结算
- `card_parser.py`
  - 解析牌面输入与随机发牌
- `session_manager.py`
  - 启动时的玩家配置与补码提示

这一层回答的是：**用户怎么和这个项目交互。**

### `testing/`

仿真与分析工具层，核心模块包括：

- `simulation/ai_opponent.py`
  - AI 对手行为模型
- `simulation/sim_game_loop.py`
  - 模拟流程
- 各类分析脚本
  - `decision_quality.py`
  - `exploit_effectiveness.py`
  - `bleed_pattern.py`
  - `equity_trajectory.py`
  - `catastrophic_hands.py`
  - `learning_convergence.py`
  - `positional_leak.py`
- `replay_engine.py`
  - 回放历史手牌

这一层回答的是：**如何用自动化方式检验系统行为是否健康。**

## 决策行为说明

这一部分是本项目最重要的逻辑，也是 README 中最值得理解的部分。

### 总体决策链路

Hero 轮到行动时，AI 顾问大致按下面的顺序做判断：

```text
牌局状态
  -> 生成基线建议
  -> 计算原始 equity
  -> 估算 range equity
  -> 根据样本量做冷启动/置信修正
  -> 结合底池赔率与 EV 调整
  -> 读取对手画像，做 exploit 修正
  -> 如果是多人底池，再做 multiway 修正
  -> 生成动作、尺度、置信度、解释文本
```

### 1. 基线策略

第一层并不是完全自由推理，而是先生成一个“基线动作”。

- 翻前主要看：
  - 位置
  - 当前是否面临 open / 3bet / 4bet
  - 手牌所属范围
- 翻后主要看：
  - 当前牌力类别
  - 牌面结构
  - 是否有听牌、是否成牌
  - 下注/加注所处的局面

你可以把它理解为：**先给出一个比较稳妥的默认打法，再决定是否偏离。**

### 2. 胜率估算

项目会在 Hero 有明确手牌时，进行蒙特卡洛胜率计算。

主要用途：

- 评估当前手牌在当前公共牌面下的大致获胜概率
- 在跟注、全下、边缘下注等局面中辅助判断

项目还会结合范围 equity，而不是只看“裸牌面对随机手牌”的胜率。

### 3. 冷启动与可信度修正

如果对手样本量很少，画像并不稳定。

因此系统不会立刻激进地依赖画像，而是会：

- 降低范围信息的权重
- 对有效 equity 做折扣
- 限制 exploit 幅度

这能避免“只看了几手牌就把对手当成绝对跟注站或绝对 Nit”。

### 4. 底池赔率与 EV

当 Hero 面临下注时，系统会计算：

- 当前 call amount
- pot odds
- 不同行动的大致 EV 依据

这部分主要影响：

- 跟注是否划算
- 边缘牌是否该放弃
- 置信度是否应该上调或下调

### 5. 对手画像与 exploit

这是项目区别于纯规则脚本的重要部分。

系统会持续跟踪对手常见统计项，例如：

- `VPIP`
- `PFR`
- `3bet`
- `aggression_freq`
- `WTSD`
- `cbet_flop`
- `fold_to_cbet`
- `fold_to_3bet`
- `steal`

然后把这些统计映射成风格标签，并据此调整建议，例如：

- 面对 `Nit`：
  - 更愿意在合适场景诈唬
  - 更愿意对其强行动进行弃牌
- 面对 `跟注站`：
  - value bet 更宽
  - 更少纯诈唬
  - value 尺寸可以更大
- 面对 `LAG` / `Maniac`：
  - 更倾向以中强牌跟注
  - 少做边缘弃牌

### 6. 多人底池修正

多人底池不是单挑的简单叠加，项目会专门做一些保守处理：

- 诈唬频率下降
- 更强调成牌与坚果优势
- 更倾向控池
- 对边缘价值下注更谨慎

这可以避免把 heads-up 的激进打法直接照搬到 multiway 场景。

### 7. 输出解释文本

最终系统不仅给你动作，还会给出解释文本，通常会包含：

- 推荐动作
- 推荐尺度
- 置信度
- equity / range equity
- exploit 理由
- 多人底池提示

所以这个项目不是“偷偷在后台算”，而是尽量让建议具备可解释性。

## AI 对手行为

当你使用 `--sim` 或全自动模式时，对手由 `AIOpponent` 控制。

它的行为并不是完全随机，而是基于一组风格参数：

- `vpip_target`
- `pfr_target`
- `aggression_freq_target`
- `fold_to_cbet`
- `bluff_frequency`
- `tilt_variance`
- `passivity`

其大致行为特点如下：

- 翻前：
  - 先评估手牌强度
  - 叠加位置修正和随机扰动
  - 依据目标 VPIP / PFR 阈值决定弃牌、跟注或加注
- 翻后：
  - 基于牌力、听牌加成、位置、赔率和风格参数决策
  - 强牌更偏向下注或加注
  - 弱牌在某些风格下会保留一定诈唬频率

这让模拟对手至少具备“风格差异”和“统计可学习性”，而不是纯随机出手。

## 数据输出与文件说明

### 手牌历史

每个 session 会在 `data/hands/` 下创建独立目录，目录名类似：

```text
session_时间戳_人数_SB_BB
```

内部常见文件包括：

- `session_info.txt`
- `hand_001.txt`
- `hand_001.json`
- `profile_snapshots.json`
- `analysis/` 下的分析报告

### 每手牌记录内容

导出的手牌文件通常会包含：

- 玩家与位置
- 手牌与公共牌
- 各街行动历史
- AI 顾问建议文本
- 当时的 equity / confidence 等信息
- 摊牌结果
- 本手输赢
- 建议是否被采纳

### 对手画像

画像文件保存在项目根目录下的 `profiles/` 中，以 JSON 存储。

你可以：

- 保留画像，让系统跨 session 持续学习
- 删除某个画像文件，让系统重新开始学习该玩家

## 复盘与自我学习

项目内置了一套围绕 session 报告的复盘思路，说明文档位于：

```text
data/self-learning-workflow.md
```

这套流程的核心思路是：

- 不必逐手人工复盘所有牌
- 先看 session 汇总报告，找到 1 到 3 个最重要的问题
- 再针对异常去抽查具体 hand JSON

当前工作流重点关注的报告包括：

1. 收敛分析
2. 决策质量与置信度校准
3. exploit 效果
4. 慢性失血模式
5. equity 轨迹
6. 巨亏手分析
7. 位置漏洞

如果你后续要继续迭代策略系统，这一部分非常值得保留。

## 测试

### 运行 pytest

```bash
pytest
```

### 运行单个测试文件

```bash
pytest tests/test_phase1.py
pytest tests/test_phase2.py
pytest tests/test_phase3.py
pytest tests/test_comprehensive_track.py
```

这些测试主要覆盖：

- 位置分配
- 盲注处理
- 动作应用
- 发牌与牌面解析
- 手牌历史导出
- 牌局推进与边界情况

## 开发建议

如果你准备继续开发这个项目，建议按下面的顺序阅读代码：

1. `main.py`
2. `env/game_state.py`
3. `engine/advisor.py`
4. `profiler/profile_manager.py`
5. `data/hand_history.py`
6. `testing/simulation/ai_opponent.py`

这样能最快理解：

- 牌局如何推进
- 建议是怎样算出来的
- 对手画像如何影响建议
- 数据是如何落盘并进入复盘流程的

## 已知定位与限制

- 这是一个**本地 CLI 顾问/训练工具**，不是完整的联网扑克平台
- 当前建议系统包含大量规则与启发式逻辑，不能等同于严格求解器输出
- 对手画像在样本很少时主要依赖先验，因此前期 exploit 应谨慎理解
- Web 版依赖仍处于预留状态，当前主入口是 `main.py`
- 项目更适合做训练、研究、模拟与复盘，不建议把它理解为线上实战自动化工具

## 常见问题

### 1. 可以不输入具体牌吗？

可以。很多输入步骤支持直接回车随机发牌。

### 2. 为什么建议会随着对局进行而变化？

因为系统会逐步更新对手画像，建议不只依赖当前牌力，也会依赖对手风格和历史统计。

### 3. 为什么同样的牌在多人底池里建议更保守？

因为多人底池下 bluff 成功率通常更低，且被多家继续的概率更高，所以系统会主动收紧。

### 4. 为什么全自动模式更适合调参？

因为它可以快速生成大量样本，便于验证画像收敛、置信度校准和 exploit 规则是否真的带来收益。

## 后续可扩展方向

- 增加更完善的图表与 session 仪表盘
- 补充更细的日志筛选、回放和对局检索
- 引入更强的范围推断与线路建模
- 将当前 CLI 能力封装为 Web 界面
- 增加配置文件，支持自定义盲注、默认玩家、分析阈值

## License

项目包含 `LICENSE` 文件，请按仓库中的许可协议使用。
