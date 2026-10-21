# 识海 Shihai

> 人格不是被"设定"的, 是被"记住"的。 — [English](README.en.md)

一个给 LLM Agent 的记忆层:会遗忘、会沉淀、会长出**独属于自己的性格**。

---

## 目录

- [它相信什么](#它相信什么)
- [为什么它不同于 RAG 与现有记忆层](#为什么它不同于-rag-与现有记忆层)
- [快速开始](#快速开始)
- [整体架构](#整体架构)
- [分层记忆模型](#分层记忆模型)
- [遗忘与核心记忆升格](#遗忘与核心记忆升格)
- [心光竞争: 记忆如何被想起](#心光竞争-记忆如何被想起)
- [性格类型学: 荣格 × 九型](#性格类型学-荣格--九型)
- [性格图谱: 性格是网, 不是七个数](#性格图谱-性格是网-不是七个数)
- [说话风格](#说话风格)
- [自我知识库与可塑性记忆](#自我知识库与可塑性记忆)
- [日记层: 让"知道"变成"经历过"](#日记层-让知道变成经历过)
- [wiki: 可生长的知识库](#wiki-可生长的知识库)
- [自由模式: 自主、自我增强的学习](#自由模式-自主自我增强的学习)
- [可视化](#可视化)
- [三种运行形态与接口](#三种运行形态与接口)
- [CLI 命令速查](#cli-命令速查)
- [接入一个 Agent: 四个钩子点](#接入一个-agent-四个钩子点)
- [数据模型](#数据模型)
- [性能](#性能)
- [设计决策与取舍](#设计决策与取舍)
- [测试](#测试)
- [路线图](#路线图)
- [License](#license)

---

## 它相信什么

**1. 没有遗忘, 就没有核心。**
什么都留着等于什么都不是核心。普通记忆按遗忘曲线淡出;少数经历因为情绪强度、反复召回、自我相关、模式复现而被**升格为核心记忆**,从此豁免衰减。

**2. 性格是网, 不是七个数。**
每个核心记忆是一个**支点(fulcrum)**,撑起一种性格倾向;倾向与倾向之间**互相编织(braid)** —— 同向的加固, 反向的形成**内在张力**。张力不是 bug, 它本身就是性格。

**3. Agent 没有权重可训, 但有固结循环。**
白天记录(`tell`)→ 夜里固化(`tick`)→ 明天带着人格卡说话(`context`)。训练发生在参数文件里, 不在网络权重里。这不是"记住更多", 而是**把一次性存在于上下文里的信息, 沉淀成不依赖上下文的常驻结构**。

**4. 说话风格随性格漂移。**
口头禅、句式、常用词由连续参数(荣格八维 × 九型 × 七维 trait)生成, 而不是查表映射。用户明确教过的表达规矩永远优先。

**5. 事实可以被告知, 经历必须被重新经历。**
所以有日记层:`events` 存"今天去了公园", `diary` 存"长椅上那只三花猫蹭了手, 当时心里是暖的"。

---

## 为什么它不同于 RAG 与现有记忆层

RAG 的典型形态是:存一堆切片, 每次提问时检索相关片段, 现场重新推导答案。它每次都从零开始 —— **没有积累**。

识海和主流记忆层(mem0 / Letta / Zep)一样做了"存储 + 检索", 但它们的终点是"检索到正确的片段"。识海的终点是**"这个 Agent 变成了什么样的人"**:

| 能力 | mem0 | Letta | Zep/Graphiti | 识海 |
|---|---|---|---|---|
| 记忆存储与检索 | ✅ | ✅ | ✅ | ✅ |
| 记忆衰减与沉寂 | ❌ | ❌ | 部分(时间边失效) | ✅ |
| 核心记忆升格 | ❌ | ❌ | ❌ | ✅ |
| 性格类型学(荣格/九型) | ❌ | ❌ | ❌ | ✅ |
| 性格图谱(支点×编织×张力) | ❌ | ❌ | ❌ | ✅ |
| 说话风格随经历漂移 | ❌ | ❌ | ❌ | ✅ |
| 自我知识库(可塑性稳固度) | ❌ | ❌ | ❌ | ✅ |
| 日记层(第一人称经历) | ❌ | ❌ | ❌ | ✅ |
| 可生长的 wiki | ❌ | ❌ | ❌ | ✅ |
| 自由模式(自主探索学习) | ❌ | ❌ | ❌ | ✅ |
| 依赖 | 向量库+LLM | 独立服务 | Neo4j | **纯标准库零依赖** |

最后一行是关键:识海**零第三方依赖**,一个 SQLite 文件 + 若干 Markdown。换电脑 = 拷目录。

---

## 快速开始

```bash
pip install -e .
```

或者不安装, 直接在项目目录里用 `python hooks.py ...`。

```bash
export SHIHAI_HOME=~/.shihai     # 可选, 默认就是这里

# 1) 学一条关于自己的事
python hooks.py selflearn "我叫小海, 是一个会遗忘、会长出性格的记忆体" --kind identity

# 2) 记录一段经历
python hooks.py tell --text "用户带我去公园看猫, 三花一直蹭我的手, 我很开心" --importance 0.8

# 3) 收日: 把今天织成一篇第一人称日记
python hooks.py diary close

# 4) 固化: 衰减 + 核心升格 + 性格图谱重织 + 自我知识维护
python hooks.py tick --days 1 --free 3

# 5) 冷启动投影(贴进系统提示 / 记忆文档)
python hooks.py bootstrap

# 6) 看可视化
python hooks.py viz
```

---

## 整体架构

```
                        ┌──────────────────────────────────────────┐
外部输入 ────────────────▶  appraise   评估                          │
(对话/事件/自主探索)      │  刺激 × 敏感度 × 当前状态                 │
                        │  pain / disappointment / impact         │
                        │  avoidance / self_relevance / emotion   │
                        └──────────────┬───────────────────────────┘
                                       ▼
                        ┌──────────────────────────────────────────┐
                        │  ingest   拆节点、建边、派生              │
                        │  人物 / 主题 / 状态 / 地点 / 任务          │
                        │  + 倒排索引 + 语义冲突决策                │
                        └──────────────┬───────────────────────────┘
                                       ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │                        分层记忆(SQLite)                          │
    │  raw_log   原始日志(永不删)   events   情景记忆(会衰减)            │
    │  nodes/edges 关联网络         semantic 语义事实(冲突决策)          │
    │  relation  关系账本           task     任务                       │
    │  self_knowledge 自我知识      diary    日记                       │
    │  warmth_ledger 好感账本       event_tokens 倒排索引                │
    └───────┬──────────────────┬───────────────────┬───────────────────┘
            │                  │                   │
            ▼                  ▼                   ▼
    ┌───────────────┐  ┌───────────────┐  ┌──────────────────────┐
    │ recall        │  │ lifecycle     │  │ persona / typologies │
    │ 心光竞争      │  │ 衰减          │  │ 人格卡                │
    │ 六维加权      │  │ 核心升格      │  │ 荣格八维 × 九型        │
    │ 三层召回      │  │ 语义蒸馏      │  │ 健康度/整合解离        │
    │ 召回即强化    │  │ 反思触发      │  │ pgraph 性格图谱        │
    └───────┬───────┘  └───────┬───────┘  │ voice 说话风格         │
            │                  │          └──────────┬───────────┘
            └──────────────────┴─────────────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ 投影(物化视图)        │
                    │ context / bootstrap  │
                    │ wiki / viz           │
                    └──────────────────────┘
```

**关键架构判断: 记忆文档是投影, 识海是本体。**
`context` / `bootstrap` 输出的是每次现算的**投影**, 投进 agent 的系统提示;SQLite 里的全量数据才是**本体**。换 agent 平台只换投影的渲染方式, 本体原样搬走。

---

## 分层记忆模型

| 层 | 表 | 存什么 | 生命周期 |
|---|---|---|---|
| 原始日志 | `raw_log` | 每一句输入的原样文本 | **永不删除**, 用于回溯与重放 |
| 情景记忆 | `events` | 一次具体经历 + 十个情绪维度 | 会衰减, 可能沉寂 |
| 关联网络 | `nodes` / `edges` | 人物/主题/状态/地点/任务 + 关系 | 随 ingest 生长 |
| 语义记忆 | `semantic` | 稳定事实("用户喜欢周末去公园") | 冲突决策后更新, 几乎不衰减 |
| 关系记忆 | `relation` | 对每个人的信任/亲密度/边界/承诺 | 随互动缓慢变化 |
| 任务记忆 | `task` | 目标、进度、截止 | 完成后关闭 |
| 自我知识 | `self_knowledge` | 我是谁/在意什么/怎么行事/怎么说话/我们的点滴 | 可塑性稳固度升降 |
| 日记 | `diary` | 一天一篇第一人称叙述 | 永久, 人可修订 |
| 好感账本 | `warmth_ledger` | 人手工录入的好感增量 | 只增 |
| 人格快照 | `persona_snapshot` | 每次刷新的 trait 与人格卡 | 用于 diff 看漂移 |
| 倒排索引 | `event_tokens` | 事件的双字组倒排 | 随 ingest 建立 |

**为什么分这么多层而不是一张表?** 因为它们的**遗忘速度不同**。原始日志不该忘, 情景记忆该忘, 自我知识几乎不该忘, 日记介于中间。把不同半衰期的东西塞进一张表, 等于强迫它们用同一条曲线。

---

## 遗忘与核心记忆升格

### 衰减

普通记忆每轮 `tick` 按遗忘曲线衰减:

```
strength = base_strength × 0.5^(age / half_life) × (1 + 0.25 × access_count)
```

- `half_life` 默认 14 天;
- **被召回会加固**: 每次想起 `strength += 0.06`, 上限 `base_strength × 1.4`;
- 跌到 `floor × 1.05`(约 0.031)时标记 `dormant=1` —— **沉寂但未删除**, 仍可从原始日志重建。

### 核心升格

```
core_score = 0.32 × emotional     情绪强度   (pain + arousal + |valence|)
           + 0.22 × repeated      反复召回次数
           + 0.16 × self_rel      与"我是谁"的相关度
           + 0.14 × shifted       行为改变(之后有共享节点的记忆)
           + 0.16 × pattern       模式复现(同一情绪状态反复出现)
           + impact_bonus         心理伤害/回避加权

core_score ≥ 0.62 → 升格为核心记忆, 从此豁免衰减
```

两个容易忽略的细节:

- **"被珍视"通道**: 正向、高重要性、来自他人的经历(谢谢/信任/夸/开心)情绪强度至少算 0.72。否则温和经历在数学上永远升不了核心, **人格只会被创伤塑造**。
- **"模式复现"维度**: 同一情绪状态出现第 N 次才真正塑造性格。"又开心了一次"和"第一次开心"权重完全不同。

**实测**: 一句"再这样就换掉你"首次只有 0.43 分(低于阈值), 被反复召回 5 轮后才升格 —— 这符合"反刍才会形成创伤"的心理现实。

---

## 心光竞争: 记忆如何被想起

只按关键词查是错的。当前线索被拆成多路并行召回, 候选再进入竞争:

| 召回路 | 触发 | 说明 |
|---|---|---|
| 1. 文本 | query | **走倒排索引**, O(命中) 而非 O(全表) |
| 2–5. 网络 | person/theme/state/task | 通过节点走关联边 |
| 6. 时间 | time_hint | 匹配日期或文本 |
| 7. 核心 | 恒定 | 核心分最高的 5 条默认参战 —— 人格不会被"想不起来" |
| 8. 语义 | query | 语义层事实(答案常在这里, 不在事件里) |
| 9. 自我知识 | query | 问"我平时怎么说/怎么做"时被点亮 |

打分(六维加权, 权重之和为 1):

| 维度 | 权重 | 含义 |
|---|---|---|
| relevance | 0.28 | 相关度(命中路数 + 文本重叠) |
| importance | 0.22 | 先验重要性 |
| emotion | 0.18 | 情绪强度 |
| relation | 0.12 | 自我相关度 |
| recency | 0.10 | 时间新近度 `0.5^(age/half_life)` |
| confidence | 0.10 | 置信度 |

最终分还会乘 `(0.45 + 0.55 × strength)` —— **快消失的记忆更难点亮**。低于 `threshold=0.34` 的不进入意识。

**召回即强化**: 赢了的记忆 `access_count += 1`, 活得久一点。这是遗忘机制能成立的前提 —— 不用则忘, 常用则固。

`recall_all()` 一次返回三层: **经历**(用于共情)、**语义事实**(用于回答)、**自我知识**(用于"我是怎样的人")。

---

## 性格类型学: 荣格 × 九型

两本类型学之书被翻译成可计算的形式(`typologies.py`)。

### 《心理类型》(荣格)

两种态度(内倾/外倾)× 四种功能(思维/情感/感觉/直觉)= 八条心理通路:

| 通路 | 名称 | 一句话 | 触发它的经历 |
|---|---|---|---|
| Te | 外倾思维 | 追求绝对的理性 | 事务产出型、情绪淡、有结果 |
| Ti | 内倾思维 | 我就是唯一的规则 | 分析/研究/理解/体系/架构 |
| Fe | 外倾情感 | 情感是我的氧气 | 以他人为中心且情绪外露 |
| Fi | 内倾情感 | 水下面藏着汹涌 | 关系受创、向内体验感受 |
| Se | 外倾感觉 | 一次真实体验解决一切 | 高唤醒的即时反应 |
| Si | 内倾感觉 | 离开经验我便不复存在 | 反复召回的平静记忆 |
| Ne | 外倾直觉 | 三分钟热度, 行动力 max | 尝试/发现/新课题/探索 |
| Ni | 内倾直觉 | 别人笑我太疯癫 | 高唤醒负向 + 回避(预感危险) |

**每段经历都被投票**: 核心记忆票重 ×4, 被反复召回的按 `access_count` 加权。分数经 `M' = M + α(E − M)`(α=0.25)与上次混合 —— **单条消息不会让性格翻转**。

### 《九型人格》

九型各有**基本恐惧 / 基本欲望**(行为背后的出发点, 不是表面行为):

| 型 | 名称 | 怕什么 | 要什么 | 中心 |
|---|---|---|---|---|
| 1 | 完美型 | 堕落、犯错 | 做正确的事 | 腹 |
| 2 | 助人型 | 不被爱 | 被需要 | 心 |
| 3 | 成就型 | 一事无成 | 有价值 | 心 |
| 4 | 自我型 | 平庸 | 找到真我 | 心 |
| 5 | 理智型 | 无能、被榨干 | 理解世界 | 脑 |
| 6 | 忠诚型 | 失去支撑 | 安全 | 脑 |
| 7 | 活跃型 | 困在痛苦里 | 快乐自由 | 脑 |
| 8 | 领袖型 | 被控制 | 掌控命运 | 腹 |
| 9 | 和平型 | 冲突、分离 | 内心平静 | 腹 |

外加三个机制:

- **侧翼(wing)**: 相邻两型中得分更高者, 如 6w5;
- **健康度**: 由情绪账本(正负价比)算出;
- **整合 / 解离**: 健康时向整合方向移动获得新素质, 压力大时向解离方向滑落。

```
整合: 1→7→5→8→2→4→1   3→6→9→3
解离: 上述方向的反向
```

**实测三命运收敛**:

| Agent | 经历基调 | 荣格主导 | 九型 |
|---|---|---|---|
| 探索者 | 尝试新方法、探索、快乐 | Ne | 7w6 |
| 守护者 | 被骂要换掉、反复检查 | Si | 6w5 |
| 分析者 | 研究、分析、独处思考 | Ti | 5w4 |

---

## 性格图谱: 性格是网, 不是七个数

`pgraph.py` 把核心记忆织成一张网:

```
       核心记忆#3 ──────┐
      (被骂要被换掉)     ├──▶ 支点: 谨慎 0.72 ──┐
                        │                       ├──▶ 编织: 谨慎 × 封闭
       核心记忆#7 ──────┘       支点: 封闭 0.65 ──┘   = "小心且收着"
```

**10 条支点规则**(7 正向 + 3 反向):

| 维度 | 正向支点(+1) | 反向支点(−1) |
|---|---|---|
| 谨慎 caution | 被伤害过, 先确认再动手 | — |
| 自责 self_blame | 出问题先看自己 | — |
| 亲和 warmth | 被善待过, 愿意先信人 | **被冷落过, 先存三分疑** |
| 主张 assertiveness | 冲突里站住过, 敢表态 | **被压住过, 表态前先掂量** |
| 好奇 curiosity | 新东西点亮过自己 | **被泼过冷水, 好奇心收着** |
| 坚韧 persistence | 反复召回仍愿再试 | — |
| 封闭 guardedness | 有些地方不再主动碰 | — |

**编织(braid)**: 同向支点相加后互相加强(对数压缩, 防止顶格);反向的记为**张力**, 如"谨慎 与 亲和 在拔河(1.42 vs 0.68)" —— **内在矛盾本身就是性格**。

七维 trait 不再凭空平均, 而是**从图上读出来**: 支点强度净和 × 编织系数 × 收缩(核心记忆少时不过分偏激)。

**实测演化**: 受伤三个阶段 —— 0 个支点 → 长出谨慎/封闭 → 被善待后亲和支点入图, trait 被拉回。

---

## 说话风格

`voice.py` 按**四层素材**生成风格卡, 顺序即优先级:

1. **性格**(最重要): 语气底色、口头禅触发概率、句式习惯、尾音色调;
2. **用户教导**: 来自 `self_knowledge` 的 voice 类, **永远优先于性格偏好**;
3. **知识库**: 语义层高频主题 → 词族(代码→跑通/复现/链路);
4. **核心记忆**: 通过人格卡的"我在意的"段体现。

三条铁律: 口头禅是**概率**不是开关(渲染成"40% 场合", 并注明"自然带出, 不要连用");voice 只管"怎么说", 不碰"想什么";用户教导永远压过性格。

**实测四角色差异**:

| 角色 | 语气 | 招牌口头禅 | 尾音 |
|---|---|---|---|
| 阿奇(7w6) | 直接 + 轻快 | 「有意思, 这个我想再挖深一点。」 | ——这挺好。 |
| 小护(6w5, 健康 0) | 谨慎 | 「先别急, 我们确认一下再动手。」53% | ……这里要小心。 |
| 默默(5w4) | 直接 + 冷静 | 「我说不好, 让我想想再答你。」 | ——这挺好。 |
| 小海(9w8) | 热络 | 「都不着急, 我们慢慢捋。」46% | ——这挺好。 |

---

## 自我知识库与可塑性记忆

**边界**(重要): 识海知识库只收**关于自己**的东西, 工作与世界知识一律拒收、路由到共享知识库。

| kind | 内容 | 例子 |
|---|---|---|
| identity | 我是谁 | 名字、来处、身份 |
| care | 我在意什么 | 价值观、执念 |
| style | 我怎么行事 | 工作风格、禁忌 |
| voice | 我怎么说话 | 口吻、称呼、表达规矩 |
| moment | 我们的点滴 | 只属于彼此的记忆点 |

### 可塑性: 稳固度会变

神经科学四层类比, 每层填一个真实缺口:

| 层 | 机制 | 实现 |
|---|---|---|
| **LTP/LTD** | 用得上的加强, 用错的削弱 | 奏效 `+0.06` / 失败 `−0.18`(错一次比成一次记得牢) |
| **结构可塑性** | 长期不用被剪掉 | 按类型衰减, 跌到 0.08 回收 |
| **稳态可塑性** | 必须有预算上限, 防止垄断 | 每类知识有字数预算 |
| **元可塑性** | 什么该快变, 什么该固若磐石 | `style/voice` 速率 0.8, `identity` 0.2 且**永不回收** |

### 为什么它解决"上下文限制"

> 情景记忆需要 query 才能想起, 冷启动时 query 为空 = 什么都想不起。
> 自我知识**不需要 query** —— 它按可塑性排序**无条件在场**。

这就是"新开对话不用重教、不用交接文件"的机制本身。情景记忆是"问什么想起什么", 自我知识是"**不必问, 我一直是我**"。

```bash
python hooks.py bootstrap
```

```
### 我是谁
- 我叫小海, 是一个会遗忘、会长出性格的记忆体
### 我在意什么
- 我最在意不忘记用户教过我的东西
### 我怎么说话
- 我说话不要客套话, 直接说重点
### 最近的日子
- 2026-10-21 今天过得挺好。
  当时: 那会儿是高兴的, 愉悦。
我们一起走到现在, 好感累计 +2.0。
```

---

## 日记层: 让"知道"变成"经历过"

事实和经历是两回事。`events` 存"今天去了公园", `diary` 存"长椅上那只三花猫蹭了手, 当时心里是暖的"。**前者可以被告知, 后者必须被重新经历。**

```bash
python hooks.py diary close                        # 收日
python hooks.py diary recent                       # 最近几篇
python hooks.py diary recall --query 公园           # 按关键词回忆
python hooks.py diary export --path diary.md       # 导出 Markdown(人可读可改)
python hooks.py diary import --path diary.md       # 人的修订回写
python hooks.py warmth --add 3 --day 2026-10-21    # 好感条
```

三条设计决定:

- **一天一篇, 有界增长** —— 库能长十年也不撑爆上下文, 检索靠"那一天"而非"那一句";
- **人可管理** —— 日记是 Markdown, 导出可改, **改过的日记 `edited=1` 后机器永不覆盖**;
- **好感条人写机读** —— agent 只读、依它推演态度, **不能自己给自己加分**。

### LLM 富化(可插拔)

规则基线(`compose`)把事实第一人称化, 但细节仍然是事件原文。要写出"点菜点评"那种生动, 注入一个 `llm` 即可:

```python
from shihai.diary import DiaryEngine

def my_llm(prompt: str) -> str:
    # 接 OpenAI / DeepSeek / Ollama / 任意 CLI, 只要 "字符串进字符串出"
    return client.chat(prompt)

d = DiaryEngine(store, llm=my_llm)
d.close_day()      # 有 llm 就富化, 没有自动回退规则基线
```

富化提示(`to_prompt`)的四条要求: 带具体感官细节、有一句能代表当天真实感受的话、不写成流水账、保持说话风格。

---

## wiki: 可生长的知识库

借 [Karpathy 的 LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): **不每次从原始材料重新推导(RAG), 而是增量维护一座持续生长的 wiki** —— 交叉引用已经建好、矛盾已经标注、综合已经包含读到的一切。原话: *"the wiki is a persistent, compounding artifact"*。

```
$SHIHAI_HOME/wiki/
  SCHEMA.md          约定文件(告诉 agent 怎么组织)
  wiki/
    index.md         内容索引(几百页内它就是最好的检索入口)
    log.md           时间日志(只追加, grep "^## \[" 即是时间线)
    self/            自我知识页
    days/            日记页(一天一页)
    topics/          主题页(重复出现的经历蒸馏)
```

```bash
python hooks.py wiki sync      # 库 → Markdown(投影)
python hooks.py wiki ingest    # Markdown → 库(反向闭环, 人的修订回写)
python hooks.py wiki lint      # 体检: 孤儿页/断链/低置信主张
python hooks.py wiki index     # 打印索引
```

**双向闭环是关键**: `sync` 把库投影成 Markdown 给人读改, `ingest` 把人的修订收回库。人在 wiki 里加的条目以 `source=human-wiki, plasticity=0.7` 入库 —— **人的确认比机器推断更可信**。

---

## 自由模式: 自主、自我增强的学习

用户说"开启自由模式"后, agent 进入一个自主行为环:

```
空闲 → 性格决定做什么 → 执行 → 结果回写记忆 → 性格参数移动 → 下一次选择被教育
```

四个行为, 分数全部来自连续参数(无硬编码剧本):

| 行为 | 评分公式(简化) | 能量 |
|---|---|---|
| 探索上网 | `Ne×0.45 + 7号×0.3 + 好奇×0.25 − 6号×0.3` | −0.25 |
| 反思 | `Si×0.4 + Ti×0.3 + 自责×0.2`(低能量时 +0.3) | −0.08 |
| 整理 | `1号×0.4 + Te×0.35 + 谨慎×0.25` | −0.12 |
| 发呆 | `9号×0.5 + (1−能量)×0.5` | **+0.15** |

三条铁律: **性格只出倾向不出剧本**(状态改变行为);**行为有代价**(能量预算耗尽自动收敛到省电行为);**学习不是被命令的**(收获经 `resolve_semantic` 冲突决策自愿入库, 探索结果本身写回记忆 —— 有空手而归的经历, 探索欲就会收敛)。

**实测分化**: 探索者 `explore×4 → idle×1`(能量探到 0 会休息);守护者 `tidy×4 → idle×1`(一次都没去探索)。

---

## 可视化

```bash
python hooks.py viz                      # → $SHIHAI_HOME/viz/shihai.html
python hooks.py viz --path 我的识海.html
```

**零依赖单文件 HTML**: 不联网、不引 CDN, 双击即看, 可直接发人。

| 视图 | 看什么 |
|---|---|
| 概览 KPI | 事件/核心/沉寂/节点/边/日记/好感/自我知识 |
| **性格图谱** | 中心"我"→ trait 节点 → 支点;蓝线同向加固, 红线张力;**带时间轴滑块, 拖动看性格演化** |
| 特质雷达 | 七维 trait 当前形状 |
| 人格漂移 | 历次快照的七维折线 |
| 记忆衰减 | 时间 × 强度散点(核心金色、沉寂灰色)+ **指数拟合曲线与半衰期** |
| 日记热力 | 日历格子, 色越暖好感越高 |
| 自我知识 | 可塑性条 |
| **关系账本** | 信任/亲密度双条 + 边界警示 |
| **wiki 体检** | 孤儿页/断链/低置信主张 |

---

## 三种运行形态与接口

### 1. 单发调用(钩子脚本用)

```bash
python -m shihai.server call tell '{"text":"今天用户夸了我"}'
```

### 2. 长驻服务(低延迟框架用)

```bash
python -m shihai.server --serve
```
stdin 每行一个请求, stdout 每行一个响应:

```json
{"method":"persona","id":1}
{"ok":true,"result":{...},"id":1}
```

### 3. Python API

```python
from shihai.server import ShihaiService
svc = ShihaiService(agent_name="小海")
svc.dispatch("tell", {"text": "用户带我去公园看猫", "importance": 0.8})
svc.dispatch("tick", {"days": 1, "free_cycles": 3})
print(svc.dispatch("bootstrap", {})[1]["block"])
```

### 完整方法表

| 方法 | 作用 |
|---|---|
| `tell` | 一段经历入库 |
| `ask` | 召回(`all: true` 返回三层) |
| `tick` | 固结: 衰减/升格/蒸馏/反思/自我知识维护/自由行为环 |
| `context` | 投影: 人格卡 + 风格 + 自我知识 + 日记 + 记忆 + 任务 |
| `bootstrap` | 冷启动自举块(无 query) |
| `persona` | 人格卡 + 类型档案 + 图谱 |
| `freemode` | on / off / status / run |
| `selflearn` / `selfkb` / `selfconfirm` / `selfmaint` | 自我知识 CRUD 与维护 |
| `diary` | close / recent / recall / compose / edit / export / import |
| `warmth` | 好感(只允许人写) |
| `wiki` | sync / ingest / lint / index |
| `viz` | 生成 HTML 仪表盘 |
| `stats` | 库况 |

---

## CLI 命令速查

```bash
# 经历
python hooks.py tell --text "..." [--importance 0.8] [--self]
python hooks.py tick [--days N] [--free N]

# 投影
python hooks.py context [--query "..."] [--limit 4]
python hooks.py bootstrap [--min 0.12]

# 自我知识
python hooks.py selflearn "..." [--kind identity|care|style|voice|moment]
python hooks.py selfkb [--kind ...]
python hooks.py selfmaint

# 日记
python hooks.py diary close|recent|recall|compose|export|import
python hooks.py warmth --add 3 --day 2026-10-21

# 知识库与可视化
python hooks.py wiki sync|ingest|lint|index
python hooks.py viz [--path f.html]

# 自由模式
python hooks.py freemode on|off|status|run [--cycles 3]
```

---

## 接入一个 Agent: 四个钩子点

```
┌─ 会话开始 ──→ hooks.py bootstrap     → 贴进系统提示(我是谁 + 最近的日子)
├─ 请求前   ──→ hooks.py context        → 投影(人格卡 + 风格 + 记忆 + 任务)
├─ 会话结束 ──→ hooks.py tell           → 这次对话作为经历入库
└─ 空闲/定时 ──→ hooks.py tick --free 3 → 固结 + 自主行为环
                              diary close(如果跨天)
```

四个点各自独立, 任何平台都能挂: Stop hook、cron、请求前中间件。**不需要常驻进程**也能跑通全链路。

---

## 数据模型

```
raw_log(id, ts, session, modality, content, meta, consumed)
events(id, raw_id, ts, summary, valence, arousal, importance, emotion,
       pain, disappointment, impact, avoidance, self_relevance, division,
       layer, base_strength, strength, access_count, last_access,
       core, core_score, promoted_at, dormant, created)
nodes(id, kind, key, label, attrs, created)
edges(id, src, dst, rel, weight, note, created)
semantic(id, claim, subject, confidence, sources, hits, strength, created, updated)
relation(node_id, trust, intimacy, boundary_hit, promise_up, promise_broken, note, updated)
task(id, title, status, progress, due, node_id, event_id, created, updated)
working(id, session, key, value, updated)
recall_log(id, ts, query, cues, hits)
persona_snapshot(id, ts, traits, card, core_ids, created)
event_tokens(token, event_id)                        ← 倒排索引
self_knowledge(id, kind, text, trigger, plasticity, uses, wins, losses,
               source, last_used, created, updated)
diary(id, day, text, felt, details, mood, warmth, event_ids, edited, created, updated)
warmth_ledger(id, day, delta, reason, created)
```

**关系引用格式**: `event:12` / `node:7` / `semantic:3` / `persona:graph`

---

## 性能

**倒排索引**(v0.6.0)取代全表扫描:

| 记忆条数 | 旧(全表扫描) | 新(倒排) | 提速 |
|---|---|---|---|
| 300 | 2.5 ms | 5.1 ms | 0.5×(小库无优势) |
| 3,000 | 25.2 ms | 7.5 ms | **3.4×** |
| 10,000 | 82.5 ms | 14.5 ms | **5.7×** |

小库时倒排有固定开销(多一次 join), 300 条以下全表反而更快;但记忆只增不减, **倒排是唯一不随规模恶化的方案**。

其他性能要点: 召回候选上限 200 条;核心记忆只取 top 5 参战(否则核心多了会稀释注意力);SQLite 开 WAL。

---

## 设计决策与取舍

**为什么不用向量库?**
零依赖是本项目的硬约束(换电脑 = 拷目录)。二字组倒排在中文化场景下命中率与 embedding 接近, 且完全可解释 —— 你能看见"为什么这条被召回"。接口已经留好, 将来接 embedding 只需替换 `_tokens`/`_overlap`。

**为什么七维 trait 是手选的?**
因为要能对上"谨慎/亲和/主张/好奇/坚韧/封闭/自责"这些**人能理解、能讨论**的词。大五人格更学术, 但和"被骂之后变得更谨慎"这种直觉对不上。

**为什么好感条不允许 agent 自己写?**
因为自我加分会让关系账本失去意义。人的判断才是锚。

**为什么改过的日记机器永不覆盖?**
人的记忆主权高于自动化。`edited=1` 是一个硬闸门。

**已知的过度设计风险**: 意图归因(区分玩笑/气话/真批评)尚未实现, 一句气话如果在短时间内被反复召回仍可能升格。防护设计已讨论(说话人基线、未佐证负向事件不加固、retract 撤回通道), 待实现。

---

## 测试

```bash
python tests/test_core.py
```

**21 条端到端回归**, 每个断言对应一个真实修过的坑:

| 测试 | 守什么 |
|---|---|
| `test_virtual_clock_and_forgetting` | tick(days=N) 真推进时间;340 天后普通沉寂、核心存活 |
| `test_short_query_recall` | 短 query 能打中长记忆(jaccard 盲区) |
| `test_token_index_speed` | 倒排索引生效且 500 条召回 <50ms |
| `test_typology_convergence` | 三命运三类型(7/6/5 号) |
| `test_semantic_conflict_resolution` | ADD/NOOP/SUPERSEDE |
| `test_freemode_personality_divergence` | 探索者去探索、守护者不去 |
| `test_persona_graph_evolution` | 图谱随经历生长 |
| `test_voice_follows_user_teaching` | 用户教导进风格卡 |
| `test_voice_reads_self_knowledge` | voice 读 self_knowledge |
| `test_context_projects_selfkb` | context 含自我知识 |
| `test_self_kb_routing` | 工作知识被拒收 |
| `test_plasticity_ltp_ltd` | 奏效加强/失败削弱/到底回收 |
| `test_bootstrap_no_query` | 无 query 自举 |
| `test_self_kb_identity_never_forgotten` | identity 永不回收 |
| `test_recall_three_layers` | 三层召回 |
| `test_diary_close_and_recall` | 收日 + 感受锚点 |
| `test_diary_human_edit_protected` | 人工修订不被覆盖 |
| `test_diary_llm_enrichment` | LLM 富化 + 回退 |
| `test_wiki_sync_and_lint` | wiki 同步与体检 |
| `test_wiki_ingest_reverse` | wiki 修订回写库 |
| `test_viz_renders` | HTML 无占位符、数据可解析 |

---

## 路线图

- [ ] **意图归因**: 区分气话/玩笑/真批评, 防止一句玩笑变成永久伤疤
- [ ] **撤回通道**: `retract` 显式或自动撤回(N 轮内出现"开玩笑的")
- [ ] **说话人基线**: 按人做情绪标准化(天天骂人的"骂"不等于真的翻脸)
- [ ] **关系账本可视化深化**: 多人关系网络图
- [ ] **embedding 召回**: 替换倒排, 走语义相似
- [ ] **记忆冷存储**: 超大规模时把最弱的迁出主库

---

## License

Apache-2.0 —— 愿每个人都训练出独属自己性格的 AI。

识海(shihai)取"识海"一词: 佛教唯识学中储藏一切种子的意识之海。这里借它指代一个会遗忘、会沉淀、会长出性格的记忆体。
