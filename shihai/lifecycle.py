# -*- coding: utf-8 -*-
"""Lifecycle —— 遗忘、巩固、升格、蒸馏。

这是全项目最核心的一层, 因为"人格"就诞生在这里:
    1. 所有记忆每轮按 Ebbinghaus 曲线衰减
    2. 被频繁召回的记忆衰减更慢(加固), 从普通记忆变成稳定记忆
    3. 少数记忆因核心分数越过阈值而升格为核心记忆, 从此豁免遗忘
    4. 重复出现的情景蒸馏成语义记忆
    5. 核心记忆驱动人格卡的更新

核心记忆的判定不只看"重要", 而看四件事同时成立:
    情绪强度高 / 反复被召回 / 与自我相关 / 改变了之后的行为
第四条需要一个外部信号: 之后的记忆是否与它关联(behavior_shift)。
"""

from bisect import bisect_right
from dataclasses import dataclass, field

from .store import utcnow

# 核心记忆升格阈值
CORE_THRESHOLD = 0.62


class _GraphIndex:
    """一次 tick 内的图快照: 事件挂哪些节点、状态节点上挂着哪些事件。
    tick 期间图不变(升格只改 events 的 core/dormant, 不动边), 所以摊平一次就够。"""

    def __init__(self, store):
        self._ev_nodes = {}
        self._state_ev = {}
        states = {r["id"] for r in store.conn.execute(
            "SELECT id FROM nodes WHERE kind='state'")}
        dormant = {r["id"] for r in store.conn.execute(
            "SELECT id FROM events WHERE dormant=1")}
        for r in store.conn.execute("SELECT src, dst FROM edges WHERE dst LIKE 'node:%'"):
            if not r["src"].startswith("event:"):
                continue
            eid = int(r["src"].split(":")[1])
            self._ev_nodes.setdefault(eid, set()).add(r["dst"])
            if int(r["dst"].split(":")[1]) in states and eid not in dormant:
                self._state_ev.setdefault(r["dst"], set()).add(eid)
        self._live = [r["id"] for r in store.conn.execute(
            "SELECT id FROM events WHERE dormant=0 ORDER BY id")]

    def pattern_recurrence(self, event_id):
        siblings = set()
        for nref in self._ev_nodes.get(event_id, ()):
            siblings |= self._state_ev.get(nref, set())
        siblings.discard(event_id)
        return min(1.0, len(siblings) / 3.0)

    def behavior_shift(self, event_id):
        src = self._ev_nodes.get(event_id)
        if not src:
            return 0.0
        # 慢路径的口径是 "id 之后 60 条非休眠事件", 休眠事件本身也照样往后看
        i = bisect_right(self._live, event_id) - 1
        overlap = 0
        for rid in self._live[i + 1:i + 61]:
            if self._ev_nodes.get(rid, set()) & src:
                overlap += 1
        return min(1.0, overlap / 3.0)


@dataclass
class LifecycleReport:
    decayed: int = 0
    dormant: int = 0
    promoted: list = field(default_factory=list)     # [(event_id, score)]
    distilled: list = field(default_factory=list)    # [claim]
    reflected: bool = False                          # 本轮是否触发了反思
    persona_changed: bool = False
    trait_delta: dict = field(default_factory=dict)


class Lifecycle:
    def __init__(self, store, *, half_life_days=14.0, floor=0.03,
                 reflect_trigger=None):
        self.store = store
        self.half_life_days = half_life_days
        self.floor = floor
        self._clock_shift = 0.0   # 虚拟时钟偏移(天), 供 tick(days=N) 模拟时间流逝
        # 反思预算(generative_agents 的 importance_trigger 机制):
        # 每条新经历按其重要性扣预算, 预算耗尽 -> 强制反思一轮。
        # None = 关闭(手动 tick 模式不受影响)。
        self.reflect_budget = reflect_trigger
        self._budget_left = reflect_trigger if reflect_trigger else float("inf")

    # -- 一轮演化 -------------------------------------------------------
    def tick(self, *, days=None, persona=None, reflect=None):
        """固结一轮。reflect=None 跟随反思预算; False 显式跳过(纯时间推进);
        True 强制反思。时间推进与反思在此解耦(2026-10-18)。"""
        if days:
            self._clock_shift += float(days)
        rep = LifecycleReport()
        rows = self.store.all_events(include_dormant=True)
        for row in rows:
            if row["core"]:
                continue  # 核心记忆不衰减
            age = self._age(row)
            base_decay = 0.5 ** (age / self.half_life_days)
            # 加固: 每次召回都降低有效年龄感(相当于减缓衰减)
            access_bonus = 1.0 + min(1.5, 0.25 * row["access_count"])
            new = row["base_strength"] * base_decay * access_bonus
            new = max(self.floor * 0.99, min(1.0, new))

            if abs(new - row["strength"]) > 1e-6:
                rep.decayed += 1
                self.store.conn.execute(
                    "UPDATE events SET strength=? WHERE id=?", (new, row["id"])
                )
            if new <= self.floor * 1.05 and not row["dormant"]:
                rep.dormant += 1
                self.store.conn.execute(
                    "UPDATE events SET dormant=1 WHERE id=?", (row["id"],)
                )
        self.store.conn.commit()

        rep.promoted = self._promote()
        rep.distilled = self._distill()
        if reflect is False:
            rep.reflected = False
        elif reflect is True:
            rep.reflected = self._reflect_due(rep, force=True)
        else:
            rep.reflected = self._reflect_due(rep)

        if persona is not None:
            before = self.store.last_persona()
            card = persona.refresh()
            if before is not None:
                import json
                old = json.loads(before["traits"])
                rep.trait_delta = {
                    k: round(card.traits.get(k, 0) - old.get(k, 0), 3)
                    for k in card.traits
                    if abs(card.traits.get(k, 0) - old.get(k, 0)) > 1e-3
                }
                rep.persona_changed = bool(rep.trait_delta)
            else:
                rep.persona_changed = True
                rep.trait_delta = {"__first__": 0.0}  # 首次快照, 无漂移可比
        return rep

    # -- 反思触发器 -----------------------------------------------------
    def charge_importance(self, importance):
        """每条新经历按重要性扣反思预算。预算耗尽 -> 下次 tick 触发反思。
        借鉴 generative_agents: 反思不该按固定时间表, 该按"积累了多少
        有分量的经历"触发 —— 平淡的日子不需要反思。"""
        if self.reflect_budget is None:
            return False
        self._budget_left -= max(0.05, float(importance))
        return self._budget_left <= 0

    def _reflect_due(self, rep, force=False):
        if self.reflect_budget is None:
            return force
        if self._budget_left > 0 and not force:
            return False
        # 重置预算, 进入下一个反思周期
        self._budget_left = self.reflect_budget
        return True

    # -- 核心记忆升格 ---------------------------------------------------
    def _promote(self):
        promoted = []
        rows = self.store.conn.execute(
            "SELECT * FROM events WHERE core=0 AND dormant=0"
        ).fetchall()
        if not rows:
            return promoted
        # 升格要看"这条事件影响了之后哪些记忆"和"这种感受复现过几次",
        # 两条都靠图。原先每条事件各自去查一遍边和兄弟事件, 一万条要 80 秒;
        # 图在一次 tick 内不变, 所以先摊平成索引, 权当一次全表扫描。
        idx = _GraphIndex(self.store)
        for row in rows:
            s = self._core_score(row, idx)
            self.store.conn.execute(
                "UPDATE events SET core_score=? WHERE id=?", (s, row["id"])
            )
            if s >= CORE_THRESHOLD:
                self.store.conn.execute(
                    """UPDATE events SET core=1, promoted_at=?, strength=MAX(strength, base_strength),
                                        dormant=0 WHERE id=?""",
                    (utcnow(), row["id"]),
                )
                promoted.append((row["id"], round(s, 3)))
        self.store.conn.commit()
        return promoted

    def _core_score(self, row, idx=None):
        """五个维度: 情绪强度 / 反复召回 / 自我相关 / 行为改变 / 模式复现。
        创伤走前两条(一次重击即可核心), 性格塑造走最后一条(同种感受反复出现)。
        这也是"普通记忆会被遗忘, 核心记忆不会"的分界线。"""
        emotional = min(1.0, float(row["pain"]) * 1.1
                        + float(row["arousal"]) * 0.7
                        + abs(float(row["valence"])) * 0.5)
        # 被珍视通道: 正向 + 高重要性 + 他人赠与(谢谢/信任/夸) 的经历
        # 情绪不激烈但塑造性格(否则人格只会被创伤塑造, 修于 2026-10-18)
        if float(row["valence"]) > 0.6 and float(row["importance"]) > 0.6:
            text = row["summary"] or ""
            if any(k in text for k in ("谢谢", "信任", "夸", "放心", "开心", "喜欢")):
                emotional = max(emotional, 0.72)
        repeated = min(1.0, row["access_count"] / 5.0)
        self_rel = float(row["self_relevance"])
        # 行为改变: 之后出现与该事件共享节点的记忆 = 它确实影响了后续
        shifted = self._behavior_shift(row["id"], idx)
        # 模式复现: 与其他事件共享同一情绪状态节点 = 这种感受不是一次性的
        pattern = self._pattern_recurrence(row["id"], idx)
        # 心理伤害/回避型事件额外加权(手稿里的"封存"通道)
        impact_bonus = 0.15 * float(row["impact"]) + 0.1 * float(row["avoidance"])

        return min(1.0,
                   0.32 * emotional + 0.22 * repeated + 0.16 * self_rel
                   + 0.14 * shifted + 0.16 * pattern + impact_bonus)

    def _pattern_recurrence(self, event_id, idx=None):
        """同一情绪状态节点挂在多少个其他事件上。
        "又开心了一次"和"第一次开心"在性格塑造上完全不同。"""
        if idx is not None:
            return idx.pattern_recurrence(event_id)
        siblings = set()
        for e in self.store.edges_from("event:%d" % event_id):
            if not e["dst"].startswith("node:"):
                continue
            node_id = e["dst"]
            node = self.store.conn.execute(
                "SELECT kind FROM nodes WHERE id=?", (int(node_id.split(":")[1]),)
            ).fetchone()
            if node is None or node["kind"] != "state":
                continue
            for e2 in self.store.edges_to(node_id):
                if e2["src"].startswith("event:") and e2["src"] != "event:%d" % event_id:
                    other = int(e2["src"].split(":")[1])
                    row = self.store.conn.execute(
                        "SELECT dormant FROM events WHERE id=?", (other,)
                    ).fetchone()
                    if row and not row["dormant"]:
                        siblings.add(other)
        return min(1.0, len(siblings) / 3.0)

    def _behavior_shift(self, event_id, idx=None):
        if idx is not None:
            return idx.behavior_shift(event_id)
        later = self.store.conn.execute(
            "SELECT id FROM events WHERE id > ? AND dormant=0 LIMIT 60", (event_id,)
        ).fetchall()
        if not later:
            return 0.0
        src = set()
        for e in self.store.edges_from("event:%d" % event_id):
            if e["dst"].startswith("node:"):
                src.add(e["dst"])
        if not src:
            return 0.0
        overlap = 0
        for r in later:
            for e in self.store.edges_from("event:%d" % r["id"]):
                if e["dst"] in src:
                    overlap += 1
                    break
        return min(1.0, overlap / 3.0)

    # -- 语义蒸馏 -------------------------------------------------------
    def _distill(self):
        """同一主题下, 多条情景共享同一稳定事实 → 提升置信度并记入语义层。"""
        out = []
        rows = self.store.conn.execute(
            """SELECT n.id, n.label, COUNT(*) AS c
               FROM nodes n JOIN edges e ON e.dst = 'node:' || n.id
               WHERE n.kind = 'theme' AND e.src LIKE 'event:%'
               GROUP BY n.id HAVING c >= 2"""
        ).fetchall()
        for r in rows:
            ev_ids = [int(e["src"].split(":")[1])
                      for e in self.store.edges_to("node:%d" % r["id"])]
            claims = self.store.conn.execute(
                "SELECT claim FROM semantic WHERE sources LIKE ?",
                ("%" + str(ev_ids[0]) + "%",),
            ).fetchall()
            for c in claims:
                sid = self.store.add_semantic(c["claim"], subject=r["label"],
                                              confidence=min(0.95, 0.6 + 0.1 * r["c"]),
                                              sources=ev_ids)
                out.append((r["label"], c["claim"], sid))
        # 去重后返回
        seen, uniq = set(), []
        for t in out:
            if t[1] in seen:
                continue
            seen.add(t[1])
            uniq.append(t)
        return uniq

    # -- 工具 -----------------------------------------------------------
    def _age(self, row):
        from datetime import datetime, timezone
        try:
            t = datetime.fromisoformat(row["created"])
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
            return max(0.0, age + self._clock_shift)
        except Exception:
            return self._clock_shift
