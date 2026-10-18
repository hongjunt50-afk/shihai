# -*- coding: utf-8 -*-
"""PersonalityGraph —— 性格图谱: 性格是网, 不是七个数。

设计定稿(2026-10-18, 用户口径):
    性格往往是复杂的, 性格图谱往往是复杂的网状结构。
    每一个核心记忆节点作为一个支点(fulcrum), 带来一种性格倾向(tendency),
    倾向与倾向之间互相编织(braid)—— 冲突的对冲, 同向的加强。

        核心记忆#3 ──────┐
        (被骂要被换掉)    ├──▶ 支点: 谨慎 0.72 ──┐
                          │                      ├──▶ 编织: 谨慎×坚韧
        核心记忆#7 ───────┘        支点: 坚韧 0.65 ──┘   = "小心但压不垮"

    traits 七维与九型分数不再凭空平均, 而是从图上"读"出来:
    - 支点(fulcrum): 核心记忆 → (维度, 方向, 强度)。一条记忆可以同时
      撑起多个维度(被骂既增加谨慎也增加自责);
    - 编织(braid): 两条支点指向同向 → 强化(权重相乘取根);
      指向反向 → 对冲(弱者被削, 留下张力记录 —— 内在矛盾本身就是性格);
    - 演化: 新核心记忆升格时增量接线, 旧支点随记忆强度衰减而减弱,
      图是活的, 随经历重排。

    图的存储直接复用识海已有的 edges 表(src=persona:*), 不引入新依赖。
"""

import json
import math
from dataclasses import dataclass, field

from .store import utcnow

# 支点类型: 核心记忆的哪类情绪结构 → 撑起哪个维度、什么方向
# (方向 +1 强化该维度的"高"端, -1 压向"低"端)
FULCRUM_RULES = [
    # (条件函数(row)->强度0~1, 维度, 方向, 倾向描述)
    (lambda r: min(1.0, r["pain"] + r["avoidance"]), "caution", +1, "被伤害过, 先确认再动手"),
    (lambda r: r["pain"] * r["self_relevance"], "self_blame", +1, "出问题先看自己"),
    (lambda r: max(0.0, r["valence"]) * (1 + r["arousal"]), "warmth", +1, "被善待过, 愿意先信人"),
    (lambda r: max(0.0, -r["valence"]) * r["arousal"] * (0.5 if r["division"] != "self" else 1.0),
     "assertiveness", +1, "冲突里站住过, 敢表态"),
    (lambda r: r["arousal"] * max(0.0, r["valence"]) * 0.9, "curiosity", +1, "新东西点亮过自己"),
    (lambda r: min(1.0, r["access_count"] / 5.0) * (0.5 + 0.5 * max(0.0, r["valence"])),
     "persistence", +1, "反复召回仍愿再试"),
    (lambda r: r["avoidance"] * 1.2 + r["impact"], "guardedness", +1, "有些地方不再主动碰"),
    # 反向支点(方向 -1): 性格被往回拉的经历 —— 张力的另一半
    (lambda r: max(0.0, -r["valence"]) * r["self_relevance"] * 0.9,
     "warmth", -1, "被冷落过, 先存三分疑"),
    (lambda r: r["pain"] * r["avoidance"] * 0.8 if r["arousal"] < 0.3 else 0.0,
     "assertiveness", -1, "被压住过, 表态前先掂量"),
    (lambda r: r["impact"] * r["avoidance"] if r["arousal"] < 0.4 else 0.0,
     "curiosity", -1, "被泼过冷水, 好奇心收着"),
]

BRAID_REINFORCE = 1.25   # 同向编织: 加强系数
BRAID_TENSION = 0.7      # 反向编织: 弱者被削比例


@dataclass
class Fulcrum:
    event_id: int
    trait: str          # 七维之一
    direction: int      # +1 / -1
    strength: float     # 0~1, 随核心记忆强度浮动
    note: str           # 倾向描述(人话)


@dataclass
class Braid:
    a: str              # trait a
    b: str              # trait b
    kind: str           # reinforce / tension
    weight: float


@dataclass
class PersonaGraph:
    fulcrums: list = field(default_factory=list)
    braids: list = field(default_factory=list)
    traits: dict = field(default_factory=dict)          # 从图上读出的七维
    tensions: list = field(default_factory=list)        # 内在矛盾(未消解的对冲)
    summary: str = ""

    def to_dict(self):
        return {"fulcrums": [f.__dict__ for f in self.fulcrums],
                "braids": [b.__dict__ for b in self.braids],
                "traits": self.traits,
                "tensions": self.tensions,
                "summary": self.summary}


class PersonalityGraphEngine:
    """从核心记忆织性格图。每次 persona.refresh 时重织 —— 图随经历演化。"""

    def __init__(self, store):
        self.store = store

    def weave(self):
        rows = self.store.conn.execute(
            "SELECT * FROM events WHERE core=1 AND dormant=0 ORDER BY id"
        ).fetchall()
        fulcrums = []
        for r in rows:
            w = float(r["strength"]) * (0.6 + 0.4 * float(r["core_score"]))
            for cond, trait, direction, note in FULCRUM_RULES:
                s = cond(r)
                if s >= 0.25:   # 太弱的支点不成支点
                    fulcrums.append(Fulcrum(r["id"], trait, direction,
                                            round(min(1.0, s * w), 3), note))
        braids, tensions = self._braid(fulcrums)
        traits = self._read_traits(fulcrums, braids)
        g = PersonaGraph(fulcrums=fulcrums, braids=braids, traits=traits,
                         tensions=tensions, summary=self._summarize(fulcrums, braids))
        self._persist(g)
        return g

    # -- 编织 ------------------------------------------------------------
    def _braid(self, fulcrums):
        """同向加强, 反向对冲。对冲未消解的记为'内在张力' —— 那也是性格。"""
        by_trait = {}
        for f in fulcrums:
            by_trait.setdefault(f.trait, []).append(f)

        braids, tensions = [], []
        traits_seen = sorted(by_trait)
        for i, ta in enumerate(traits_seen):
            for tb in traits_seen[i + 1:]:
                a_strength = sum(f.strength * f.direction for f in by_trait[ta])
                b_strength = sum(f.strength * f.direction for f in by_trait[tb])
                if abs(a_strength) < 0.1 or abs(b_strength) < 0.1:
                    continue
                same = (a_strength > 0) == (b_strength > 0)
                w = min(abs(a_strength), abs(b_strength))
                if same:
                    braids.append(Braid(ta, tb, "reinforce", round(w * BRAID_REINFORCE, 3)))
                elif w > 0.2:   # 明显的对冲才叫张力
                    tensions.append("%s 与 %s 在拔河(%.2f vs %.2f)"
                                    % (ta, tb, abs(a_strength), abs(b_strength)))
                    braids.append(Braid(ta, tb, "tension", round(w, 3)))
        return braids, tensions

    # -- 从图读 traits -----------------------------------------------------
    def _read_traits(self, fulcrums, braids):
        """七维分数 = 支点强度和 × 编织系数。无支点 → 0.5 中性。"""
        out = {k: 0.5 for k in ("caution", "warmth", "assertiveness", "curiosity",
                                "persistence", "guardedness", "self_blame")}
        if not fulcrums:
            return out
        # 编织奖励: 对数压缩 —— 同向加固有上限, 防止全部维度顶格
        braid_bonus = {}
        for b in braids:
            if b.kind == "reinforce":
                add = 0.05 * math.log1p(b.weight)
                braid_bonus[b.a] = braid_bonus.get(b.a, 0) + add
                braid_bonus[b.b] = braid_bonus.get(b.b, 0) + add
        acc = {k: 0.0 for k in out}
        wsum = 0.0
        for f in fulcrums:
            acc[f.trait] += f.strength * f.direction
            wsum += f.strength
        n = max(1, len(fulcrums))
        for k in out:
            if wsum <= 0:
                continue
            # 支点强度均值(0~1) × 方向净和, 善待支点(亲和方向)能把受伤维度拉回来
            raw = acc[k] / wsum
            observed = _c(0.5 + 0.7 * raw + braid_bonus.get(k, 0.0))
            # 收缩: 支点少时不要过分偏激
            shrink = min(1.0, len(fulcrums) / 4.0)
            out[k] = round(_c(0.5 + (observed - 0.5) * shrink), 3)
        return out

    def _summarize(self, fulcrums, braids):
        if not fulcrums:
            return "性格图谱还是白纸: 没有核心记忆, 也就没有支点。"
        n_re = sum(1 for b in braids if b.kind == "reinforce")
        n_te = sum(1 for b in braids if b.kind == "tension")
        return ("性格图谱: %d 个支点(来自核心记忆), 编织出 %d 条同向加固、%d 处内在张力。"
                % (len(fulcrums), n_re, n_te))

    # -- 持久化: 复用 edges 表, 不建新存储 ---------------------------------
    def _persist(self, g):
        now = utcnow()
        # 清旧 persona 边, 重写(图小, 全量重建成本可忽略)
        self.store.conn.execute("DELETE FROM edges WHERE src LIKE 'persona:%'")
        for f in g.fulcrums:
            self.store.add_edge("persona:graph", "event:%d" % f.event_id,
                                "fulcrum:%s:%+d" % (f.trait, f.direction),
                                weight=f.strength, note=f.note)
        for b in g.braids:
            self.store.add_edge("persona:graph", "braid:%s|%s|%s" % (b.a, b.b, b.kind),
                                "braid", weight=b.weight)
        self.store.conn.commit()


def _c(x, lo=0.05, hi=0.95):
    return max(lo, min(hi, x))
