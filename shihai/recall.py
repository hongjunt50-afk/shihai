# -*- coding: utf-8 -*-
"""Recall —— 记忆怎么被想起。

手稿的第二张图: 只按关键词找是错的。
当前线索(人物/时间/主题/状态)先拆开, 多路并行召回候选,
候选再进"心光竞争"(灯塔): 相关度、重要性、情绪权重、
关系权重、置信度一起打分, 最高分进入意识。

关键点: 召回本身会强化记忆(access_count, last_access)。
被想起来的记忆活得更久 —— 这是遗忘机制有意义的前提。
"""

import math
import time
from dataclasses import dataclass, field

from .store import utcnow


@dataclass
class Cue:
    """当前线索。不必填满, 有什么用什么。"""
    text: str = ""
    person: str = ""
    theme: str = ""
    state: str = ""
    task: str = ""
    time_hint: str = ""
    mood: float = 0.0


@dataclass
class Spotlight:
    """一条赢得心光的记忆。"""
    event_id: int
    summary: str
    score: float
    parts: dict
    strength: float
    core: bool
    emotion: str
    via: list = field(default_factory=list)   # 从哪几个入口被照亮


# 心光竞争权重 —— 手稿里的六个维度
W = {
    "relevance": 0.28,     # 相关度
    "importance": 0.22,    # 重要性
    "emotion": 0.18,       # 情绪权重
    "relation": 0.12,      # 关系权重
    "recency": 0.10,       # 时间
    "confidence": 0.10,    # 置信度(未被证伪/未被重复)
}


class RecallEngine:
    def __init__(self, store, *, half_life_days=7.0, threshold=0.34):
        self.store = store
        self.half_life_days = half_life_days
        self.threshold = threshold

    # -- 主入口 ---------------------------------------------------------
    def recall(self, cue, limit=5, *, reinforce=True, log=True):
        cue = cue if isinstance(cue, Cue) else Cue(text=str(cue))
        candidates = {}

        # 多线索召回: 每一路都往候选池里投票, 并记录入口
        for cid, via in self._gather(cue):
            candidates.setdefault(cid, []).append(via)

        scored = []
        now = time.time()
        for eid, via in candidates.items():
            row = self.store.get_event(eid)
            if row is None or row["dormant"]:
                continue
            parts = self._score(row, cue, now, via)
            total = sum(W[k] * v for k, v in parts.items())
            # 强度直接参与: 快消失的记忆更难点亮
            total *= (0.45 + 0.55 * row["strength"])
            if total < self.threshold:
                continue
            scored.append((total, row, parts, via))

        scored.sort(key=lambda x: -x[0])
        out = []
        for total, row, parts, via in scored[:limit]:
            out.append(Spotlight(
                event_id=row["id"], summary=row["summary"], score=round(total, 4),
                parts={k: round(v, 3) for k, v in parts.items()},
                strength=round(row["strength"], 3), core=bool(row["core"]),
                emotion=row["emotion"], via=sorted(set(via)),
            ))
            if reinforce:
                self._reinforce(row["id"])

        if log:
            self.store.log_recall(
                cue.text or cue.person or cue.theme,
                {"person": cue.person, "theme": cue.theme, "state": cue.state,
                 "task": cue.task, "time": cue.time_hint},
                [{"event": s.event_id, "score": s.score, "via": s.via} for s in out],
            )
        # 语义与自我知识不参与心光竞争(它们不是"经历"), 但对齐后一起返回;
        # 调用方按需取用: 经历用于共情, 语义用于事实, 自我知识用于"我是怎样的人"。
        self.last_semantic = [{"id": i, "claim": c} for i, c in self.semantic_hits[:3]]
        self.last_self = [{"id": i, "kind": k, "text": t}
                          for i, k, t in self.self_hits[:3]]
        return out

    def recall_all(self, cue, limit=5):
        """一次拿全三层: 经历 + 语义事实 + 自我知识。
        这是"被问起时该想起什么"的完整答案。"""
        hits = self.recall(cue, limit=limit)
        return {"events": [{"id": h.event_id, "summary": h.summary,
                            "score": h.score, "core": h.core} for h in hits],
                "semantic": getattr(self, "last_semantic", []),
                "self": getattr(self, "last_self", [])}

    # -- 多路召回 -------------------------------------------------------
    def _gather(self, cue):
        votes = []

        # 路 1: 文本相似 —— 走倒排索引(O(命中) 而非 O(全表))。
        # 命中的事件按"命中 token 占 query 的比例"过滤, 与旧的 overlap 语义一致。
        self.semantic_hits = []
        self.self_hits = []
        if cue.text:
            qtokens = _tokens(cue.text)
            if qtokens:
                for eid, hits in self.store.search_tokens(qtokens, min_hits=1):
                    if hits / float(len(qtokens)) >= 0.22:
                        votes.append((eid, "text"))
                # 路 8: 语义层 —— 世界事实也该被想起(答案常在这里, 不在事件里)
                for r in self.store.conn.execute(
                        "SELECT id, claim FROM semantic WHERE confidence>=0.45"):
                    if _overlap(qtokens, _tokens(r["claim"])) >= 0.28:
                        self.semantic_hits.append((r["id"], r["claim"]))
                # 路 9: 自我知识 —— 问"我平时怎么说/我怎么做事"时该被点亮
                for r in self.store.conn.execute(
                        "SELECT id, kind, text FROM self_knowledge"):
                    if _overlap(qtokens, _tokens(r["text"])) >= 0.28:
                        self.self_hits.append((r["id"], r["kind"], r["text"]))

        # 路 2~5: 通过节点走网络
        for kind, value, tag in (
            ("person", cue.person, "person"),
            ("theme", cue.theme, "theme"),
            ("state", cue.state, "state"),
            ("task", cue.task, "task"),
        ):
            if not value:
                continue
            nid = self._find_node(kind, value)
            if nid is None:
                continue
            for e in self.store.edges_to("node:%d" % nid):
                if e["src"].startswith("event:"):
                    votes.append((int(e["src"].split(":")[1]), tag))
            for e in self.store.edges_from("node:%d" % nid):
                if e["dst"].startswith("event:"):
                    votes.append((int(e["dst"].split(":")[1]), tag))

        # 路 6: 时间线索
        if cue.time_hint:
            for row in self.store.conn.execute("SELECT id, ts, summary FROM events"):
                if cue.time_hint in (row["ts"] or "") or cue.time_hint in row["summary"]:
                    votes.append((row["id"], "time"))

        # 路 7: 核心记忆默认参与竞争 —— 人格不会被"想不起来"。
        # 但只取核心分最高的几条: 核心记忆多起来以后, 全部参战会稀释注意力。
        for row in self.store.conn.execute(
                "SELECT id FROM events WHERE core=1 AND dormant=0 "
                "ORDER BY core_score DESC LIMIT 5"):
            votes.append((row["id"], "core"))

        return votes

    def _find_node(self, kind, value):
        key = value.strip().lower()
        row = self.store.conn.execute(
            "SELECT id FROM nodes WHERE kind=? AND (key=? OR label=?)", (kind, key, value)
        ).fetchone()
        return row["id"] if row else None

    # -- 心光竞争的六项 -------------------------------------------------
    def _score(self, row, cue, now, via):
        relevance = min(1.0, 0.25 * len(set(via)))
        if cue.text:
            relevance = max(relevance, _overlap(_tokens(cue.text), _tokens(row["summary"])) * 2.6)
        relevance = min(1.0, relevance)

        importance = float(row["importance"])
        emotion = min(1.0, abs(float(row["valence"])) * 0.6 + float(row["arousal"]) * 0.7
                      + float(row["pain"]) * 0.5)
        relation = min(1.0, 0.4 + 0.6 * float(row["self_relevance"]))

        age_days = _age_days(row["ts"], now)
        # 指数衰减(generative_agents 的 recency_decay=0.99^步数 思路):
        # 老记忆按固定速率指数失去时间优势, 而不是线性半衰期 ——
        # 每过 half_life_days 打一次对折, 与遗忘曲线一致
        recency = 0.5 ** (age_days / self.half_life_days)

        # 置信度: 被证伪或反复冲突的记忆会掉分 —— 这里用情绪极值做代理
        confidence = 1.0 - 0.35 * (1.0 if row["core"] else 0.0) * 0.0  # 占位: 核心不因自洽降分
        confidence = 0.95 if row["core"] else 0.8
        if cue.mood and float(row["valence"]) * cue.mood < 0:
            emotion *= 0.6  # 心境不一致时, 反向情绪记忆更难被点亮

        return {
            "relevance": relevance, "importance": importance, "emotion": emotion,
            "relation": relation, "recency": recency, "confidence": confidence,
        }

    def _reinforce(self, event_id):
        self.store.conn.execute(
            """UPDATE events SET access_count = access_count + 1,
                                 last_access = ?,
                                 strength = MIN(base_strength * 1.4, strength + 0.06)
               WHERE id = ?""",
            (utcnow(), event_id),
        )
        self.store.conn.commit()


# ---- 工具 ---------------------------------------------------------------

_STOP = set("的了是我你他她它在和与就都也还又很太把被让给对说要做个这那有没不吗呢吧啊哦嗯")


def _tokens(text):
    """中文没有空格, 用二字组做基线; 生产环境换 embedding。"""
    s = "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    s = "".join(ch for ch in s if ch not in _STOP)
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _overlap(a, b):
    """重叠系数: 交集/较短集合。短 query 召回长记忆时比 jaccard 更合理,
    否则 3 个字的 query 几乎永远打不中 20 个字的记忆。"""
    if not a or not b:
        return 0.0
    return len(a & b) / float(min(len(a), len(b)))


def _age_days(ts, now):
    try:
        from datetime import datetime, timezone
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (now - t.timestamp()) / 86400.0)
    except Exception:
        return 0.0
