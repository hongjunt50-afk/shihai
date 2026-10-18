# -*- coding: utf-8 -*-
"""FreeMode —— 自由模式。

用户说"开启自由模式"后, agent 不再只做被动应答, 而是进入一个
自主、自我增强的行为环:

    ┌────────────────────────────────────────────────┐
    │  开启词 → 激活                                   │
    │    ↓                                            │
    │  空闲 → 性格决定做什么(探索上网/反思/整理/发呆)    │
    │    ↓                                            │
    │  上网学到的东西 → 评价值不值得留 → 语义层            │
    │    ↓                                            │
    │  行为结果(成功/无聊/有收获)→ tell() 写回记忆        │
    │    ↓                                            │
    │  记忆投票 → 性格参数移动 → 下一次行为选择被教育      │
    └────────────────────────────────────────────────┘

三条铁律(与 policy 设计讨论一致):
    1. 性格只出"倾向", 不出"剧本": 连续参数决定各行为的权重,
       同一个 agent 在不同状态下选择可以不同。
    2. 行为有代价: 每个行为消耗时间/资源预算(energy 预算制),
       低预算的 agent 会自动收敛到"省电"行为(反思/发呆)。
    3. 学习不是被命令的: 上网探索的收获经过 resolve_semantic
       的冲突决策自愿入库 —— 没有价值的噪音进不了知识库,
       而这本身又是一次"我有收获"的经历, 反哺探索欲。

"自由"的边界(设计决定, 不是疏漏):
    - 上网学习只读不写(不发布任何东西)
    - 行为结果永远回写记忆(自由不等于失忆)
    - 用户随时可关("关闭自由模式"), 关闭不丢状态
"""

import math
import random
from dataclasses import dataclass, field

from .ingest import Observation
from .store import utcnow
from .typologies import TypologyEngine

# 开启词 —— 用户对 agent 说的
ACTIVATE_WORDS = ("开启自由模式", "进入自由模式", "自由模式开启")
DEACTIVATE_WORDS = ("关闭自由模式", "退出自由模式", "自由模式关闭")


@dataclass
class BehaviorOption:
    """一个候选行为(generative_agents 的动作候选制)。"""
    name: str              # explore / reflect / tidy / idle / delegate
    desc: str              # 给人看的一句描述
    score: float           # 性格+状态+情境算出的倾向分
    energy_cost: float     # 能量预算消耗


@dataclass
class FreeModeState:
    active: bool = False
    cycle: int = 0                       # 已运行的行为环数
    energy: float = 1.0                  # 0~1, 每个行为耗能, 空闲恢复
    history: list = field(default_factory=list)   # [(cycle, 行为, 收获摘要)]


class FreeMode:
    def __init__(self, store, ingestor, recall_engine, lifecycle,
                 typology_engine=None, *, energy_per_cycle=0.08,
                 web_tool=None, typology_path="typology_state.json"):
        """web_tool: 可选的外部探索工具 callable(query, n) -> [(title, snippet, url)]。
        不传时探索行为退化为"翻自己的记忆找未被消化的角落"(离线模式,
        链路仍然完整, 方便测试)。"""
        self.store = store
        self.ingestor = ingestor
        self.recall = recall_engine
        self.lifecycle = lifecycle
        self.typology = typology_engine or TypologyEngine(store, path=typology_path)
        self.state = FreeModeState()
        self.energy_per_cycle = energy_per_cycle
        self.web_tool = web_tool

    # -- 开关 -----------------------------------------------------------
    def handle_command(self, user_text):
        """从用户话里识别开关指令。返回 True 表示自由模式当前为开。"""
        if any(w in user_text for w in DEACTIVATE_WORDS):
            self.state.active = False
            self.ingestor.ingest(
                Observation(text="用户关闭了自由模式", modality="self", session="freemode", ts=""))
            return False
        if any(w in user_text for w in ACTIVATE_WORDS):
            self.state.active = True
            # 开启本身是一次经历: 会被记住, 也会参与性格投票
            self.ingestor.ingest(
                Observation(text="用户让我开启自由模式, 我可以自主安排行为了", modality="self", session="freemode", ts=""))
            return True
        return self.state.active

    # -- 行为选择: 性格 × 状态 × 情境 ------------------------------------
    def choose(self, situation="idle"):
        """从行为候选里选一个。分数全部来自连续参数, 无硬编码剧本。"""
        profile = self.typology.infer(persist=True)
        j = profile.jung_scores
        e = profile.ennea_scores
        traits = self._trait_cache
        energy = self.state.energy

        cands = [
            BehaviorOption(
                "explore", "上网探索新东西",
                # 探索欲 = Ne(外倾直觉) + 7号轴(求快乐/新体验) + 好奇 - 6号轴(怕失支持,偏保守)
                score=self._w(0.45 * j.get("Ne", 0) + 0.3 * e.get(7, 0)
                              + 0.25 * traits["curiosity"] - 0.3 * e.get(6, 0)),
                energy_cost=0.25,
            ),
            BehaviorOption(
                "reflect", "翻自己的记忆反思",
                # 反思倾向 = Si(经验沉淀) + Ti(向内分析) + 自责倾向; 低能量时加权(省电)
                score=self._w(0.4 * j.get("Si", 0) + 0.3 * j.get("Ti", 0)
                              + 0.2 * traits["self_blame"] + (0.3 if energy < 0.4 else 0.0)),
                energy_cost=0.08,
            ),
            BehaviorOption(
                "tidy", "整理知识库/任务",
                # 整理倾向 = 1号轴(求正确) + Te(事务性) + 谨慎
                score=self._w(0.4 * e.get(1, 0) + 0.35 * j.get("Te", 0)
                              + 0.25 * traits["caution"]),
                energy_cost=0.12,
            ),
            BehaviorOption(
                "idle", "发呆休息",
                # 发呆倾向 = 9号轴(求平静) + 疲劳; 能量越低越合理
                score=self._w(0.5 * e.get(9, 0) + 0.5 * (1.0 - energy)),
                energy_cost=-0.15,   # 恢复能量
            ),
        ]
        # 低能量惩罚耗能行为 —— 不是禁止, 是概率收缩(状态改变行为, 不是性格决定一切)
        for c in cands:
            if c.energy_cost > 0 and energy < 0.3:
                c.score *= (energy / 0.3)
        cands.sort(key=lambda c: -c.score)
        return cands, profile

    _trait_cache = {"curiosity": 0.5, "self_blame": 0.5, "caution": 0.5}

    def sync_traits(self, persona_engine):
        """从最近一次人格快照同步七维 trait(性格的另一个投影)。"""
        snap = self.store.last_persona()
        if snap is not None:
            import json
            t = json.loads(snap["traits"])
            self._trait_cache.update({k: t.get(k, 0.5) for k in self._trait_cache})

    # -- 行为执行 -------------------------------------------------------
    def run_cycle(self, *, n_topics=2, log=print):
        """跑一个行为环: 选行为 → 执行 → 收获回写记忆。返回本轮摘要。"""
        if not self.state.active:
            return None
        self.state.cycle += 1
        cands, profile = self.choose()
        chosen = cands[0]
        self.state.energy = max(0.0, min(1.0, self.state.energy - chosen.energy_cost))

        gains = []
        if chosen.name == "explore":
            gains = self._do_explore(profile, n_topics)
        elif chosen.name == "reflect":
            gains = self._do_reflect()
        elif chosen.name == "tidy":
            gains = self._do_tidy()
        else:
            gains = self._do_idle()

        summary = "cycle %d: %s(%s) 收获 %d 条 | 能量 %.2f" % (
            self.state.cycle, chosen.name, chosen.desc, len(gains), self.state.energy)
        self.state.history.append((self.state.cycle, chosen.name, gains))
        if log:
            log(summary)
            for g in gains:
                log("   · " + g)
        return summary

    # -- 各行为的实现 ----------------------------------------------------
    def _do_explore(self, profile, n_topics):
        """自主探索: 不是被命令的学习。
        话题来自自己的记忆角落(最近在意的主题), 而不是外部指定的。
        收获经冲突决策自愿入库; "这次探索有收获"本身也写回记忆。"""
        # 从记忆里找自己关心的话题(自主性的来源: 兴趣由记忆决定)
        rows = self.store.conn.execute(
            """SELECT n.label, COUNT(*) c FROM nodes n
               JOIN edges e ON e.dst='node:'||n.id
               WHERE n.kind='theme' GROUP BY n.id ORDER BY c DESC LIMIT 5"""
        ).fetchall()
        topics = [r["label"] for r in rows] or ["新事物"]

        gains = []
        for topic in topics[:n_topics]:
            if self.web_tool:
                results = self.web_tool(topic, 3)
                for title, snippet, url in results:
                    claim = "%s: %s" % (title[:40], snippet[:120])
                    sid, action = self.store.resolve_semantic(
                        claim, subject=topic, confidence=0.55, sources=[])
                    if action == "ADD":
                        gains.append("新知识入库 [%s] %s" % (topic, claim[:50]))
                    elif action == "UPDATE":
                        gains.append("更新了旧认知 [%s] %s" % (topic, claim[:50]))
            else:
                # 离线探索: 翻语义层找低置信事实, 尝试巩固
                weak = self.store.conn.execute(
                    "SELECT claim, confidence FROM semantic WHERE confidence < 0.65 LIMIT 2"
                ).fetchall()
                for w in weak:
                    self.store.conn.execute(
                        "UPDATE semantic SET confidence=MIN(0.9, confidence+0.1) WHERE claim=?",
                        (w["claim"],))
                    gains.append("巩固了低置信认知 [%s] %s" % (topic, w["claim"][:44]))
        self.store.conn.commit()

        # 探索的经历写回 —— 有收获则强化探索轴, 这就是"自我增强"
        if gains:
            self.ingestor.ingest(Observation(
                text="我自己探索了%s, 有收获, 学到了新东西" % "、".join(topics[:2]),
                modality="self", session="freemode", ts=""))
        else:
            self.ingestor.ingest(Observation(
                text="我自己探索了%s, 但没什么有价值的发现, 有点无聊" % topics[0],
                modality="self", session="freemode", ts=""))
        return gains

    def _do_reflect(self):
        """反思: 触发生命周期固化 + 从记忆里蒸馏一句对自己的新认识。"""
        rep = self.lifecycle.tick(persona=None)
        n = rep.decayed + len(rep.promoted)
        return ["反思完成: 衰减 %d 条记忆, 升格 %d 条核心" % (rep.decayed, len(rep.promoted))] if True else []

    def _do_tidy(self):
        """整理: 把 open 任务的逾期项和低置信语义标记出来。"""
        tasks = self.store.open_tasks()
        out = ["盘点任务: 还有 %d 件未完成" % len(tasks)]
        weak = self.store.conn.execute(
            "SELECT COUNT(*) FROM semantic WHERE confidence < 0.5").fetchone()[0]
        if weak:
            out.append("发现 %d 条低置信认知待验证" % weak)
        return out

    def _do_idle(self):
        return ["休息了一会儿, 能量恢复"]

    @staticmethod
    def _w(x):
        return max(0.0, x)
