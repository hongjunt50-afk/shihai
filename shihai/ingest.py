# -*- coding: utf-8 -*-
"""Ingest —— 一条经历怎么被拆开。

手稿的核心反对意见: 整句话直接存起来是错的。
正确做法是拆成节点, 再建立节点之间的关系;
一次经历可以有多个入口, 才能从多个维度被召回。

    E214 ──涉及人物──▶ P001 你
         ──产生任务──▶ T012 准备直播
         ──当时状态──▶ A019 担心
         ──提取主题──▶ S087 AI意识问题
         ──影响关系──▶ R033 协助直播准备

拆分器在这里是规则基线(可被 LLM 输出替换), 但产物结构就是最终结构。
"""

import re
from dataclasses import dataclass, field

from .appraise import appraise
from .store import utcnow


@dataclass
class Observation:
    """现实输入 → 一个观察。多模态输入先收敛成观察, 再进事件理解。"""
    text: str
    modality: str = "text"       # text/vision/location/touch/audio
    session: str = "default"
    ts: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class SplitEvent:
    event_id: int
    summary: str
    nodes: list = field(default_factory=list)   # [(kind, label)]
    task: str = ""
    semantic: list = field(default_factory=list)
    edges: list = field(default_factory=list)


# ---- 线索抽取 -----------------------------------------------------------

_PERSON = re.compile(r"(?:@|\bP)?([\u4e00-\u9fa5]{2,3})\s*(?:说|问|让我|要求|提醒|告诉)")
_DEADLINE = re.compile(r"(下?周[一二三四五六日天]|今天|明天|后天|本周[一二三四五六日天]|\d{1,2}月\d{1,2}[日号])")
_TASK = re.compile(r"(准备|完成|整理|修复|写|做|提交|测试|上线|发布|复盘|跟进|部署)([\u4e00-\u9fa5A-Za-z0-9]{0,12})")
_TASKOBJ = re.compile(r"(?:准备|完成|整理|修复|写|做|提交|测试|上线|发布|复盘|跟进|部署)([\u4e00-\u9fa5A-Za-z0-9]{1,12})")
_TOPIC = re.compile(r"(?:关于|有关|问题|讨论|主题)[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9]{2,16})")
_FACT = re.compile(r"(?:我喜欢|我不喜欢|我习惯|我喜欢用|我用|我要求|我的项目|每天|每周|总是|从不|我负责)([^。;；\n]{2,30})")
_PROMISE = re.compile(r"(?:承诺|答应|保证|一定|以后不|再也不会)([^。;；\n]{0,30})")
_LOCATION = re.compile(r"(?:在|去|位于)([\u4e00-\u9fa5A-Za-z0-9]{2,10})(?:市|区|路|街|楼|号|公司|家)") 


class Ingestor:
    def __init__(self, store, lifecycle=None):
        self.store = store
        self.lifecycle = lifecycle   # 可选: 传入则每条经历扣反思预算

    def ingest(self, obs, *, session=None, expectation=None, importance_hint=None):
        """完整链路: 原始日志 → 评估 → 事件 → 拆节点 → 建边 → 派生语义/任务/关系。"""
        session = session or obs.session
        ts = obs.ts or utcnow()

        # 1. 原始日志先落盘, 永不丢。即使后面拆错了也能回溯重放。
        raw_id = self.store.log_raw(
            obs.text, ts=ts, session=session, modality=obs.modality, meta=obs.meta
        )

        # 2. Appraisal
        ap = appraise(
            obs.text,
            expectation=expectation,
            importance_hint=importance_hint,
            origin="self" if obs.modality == "self" else "world",
        )

        # 3. 基础强度: 重要性 × (1 + 情绪唤醒) + 情绪惩罚项
        base = _clamp01(0.25 + 0.75 * ap.importance + 0.5 * ap.arousal
                        + 0.4 * ap.pain + 0.3 * ap.disappointment)

        # 4. 事件
        division = _division(obs.text, ap)
        event_id = self.store.add_event(raw_id, obs.text.strip(), ap, base,
                                        ts=ts, division=division)
        ref = "event:%d" % event_id

        # 5. 拆节点 + 建边
        nodes, edges = self._split_nodes(event_id, obs.text, ap)
        task_title = self._attach_task(event_id, obs.text, nodes, edges)
        sem = self._attach_semantic(event_id, obs.text, nodes, edges)
        self._attach_person_promise(event_id, obs.text, nodes, edges)

        # 5b. 倒排索引: 让以后的召回走 O(命中) 而不是 O(全表)
        self.store.index_tokens(event_id, obs.text.strip())

        # 6. 反思预算(generative_agents): 有分量的经历积累到阈值 -> 该反思了
        if self.lifecycle is not None:
            self.lifecycle.charge_importance(ap.importance)

        # 7. 更新工作状态
        self.store.set_working(session, "last_event", event_id)
        self.store.set_working(session, "mood", round(ap.valence, 3))

        return SplitEvent(event_id=event_id, summary=obs.text.strip(),
                          nodes=nodes, task=task_title, semantic=sem, edges=edges)

    # -- 内部 -----------------------------------------------------------
    def _split_nodes(self, event_id, text, ap):
        ref = "event:%d" % event_id
        nodes, edges = [], []

        def add_node(kind, label, rel):
            if not label or len(label) < 2:
                return None
            nid = self.store.upsert_node(kind, label)
            nodes.append({"id": nid, "kind": kind, "label": label})
            self.store.add_edge(ref, "node:%d" % nid, rel)
            edges.append((ref, "node:%d" % nid, rel))
            return nid

        for m in _PERSON.finditer(text):
            add_node("person", m.group(1), "involved")
        for m in _LOCATION.finditer(text):
            add_node("location", m.group(1), "about")
        for m in _TOPIC.finditer(text):
            add_node("theme", m.group(1), "about")
        # 情绪状态也做成节点: "担心"能成为一个召回入口
        if ap.emotion not in ("平静",):
            add_node("state", ap.emotion, "state")
        return nodes, edges

    def _attach_task(self, event_id, text, nodes, edges):
        ms = list(_TASKOBJ.finditer(text))
        if not ms:
            return ""
        obj = ms[0].group(1).lstrip("的了")
        if len(obj) < 2:
            return ""
        due = None
        dm = _DEADLINE.search(text)
        if dm:
            due = dm.group(1)
        nid = self.store.upsert_node("task", obj)
        nodes.append({"id": nid, "kind": "task", "label": obj})
        self.store.add_edge("event:%d" % event_id, "node:%d" % nid, "produced")
        edges.append(("event:%d" % event_id, "node:%d" % nid, "produced"))
        self.store.add_task(obj, due=due, event_id=event_id, node_id=nid)
        return obj

    def _attach_semantic(self, event_id, text, nodes, edges):
        """稳定事实: 只有自述/偏好/要求类的句子才蒸馏, 避免噪音。
        走 resolve_semantic 做冲突决策(mem0 式 ADD/UPDATE/NOOP/SUPERSEDE)。"""
        out = []
        for m in _FACT.finditer(text):
            claim = (m.group(0)).strip()
            if len(claim) < 4:
                continue
            sid, action = self.store.resolve_semantic(claim, subject=None,
                                                      confidence=0.7, sources=[event_id])
            if action in ("ADD", "UPDATE", "SUPERSEDE"):
                self.store.add_edge("event:%d" % event_id, "semantic:%d" % sid, "supports")
                nodes.append({"id": sid, "kind": "semantic", "label": claim})
            out.append((claim, action))
        return out

    def _attach_person_promise(self, event_id, text, nodes, edges):
        """承诺 → 关系记忆。被记下的承诺, 是信任账本里的应收款。"""
        if not _PROMISE.search(text):
            return
        for n in nodes:
            if n["kind"] != "person":
                continue
            nid = n["id"]
            self.store.update_relation(nid, promise_up=1, trust=0.05)
            pn = self.store.upsert_node("commitment", text.strip()[:40])
            self.store.add_edge("event:%d" % event_id, "node:%d" % pn, "promised")
            self.store.add_edge("node:%d" % pn, "node:%d" % nid, "to_person")
            return


def _division(text, ap):
    if ap.self_relevance > 0.55:
        return "self"
    if any(k in text for k in ("你", "他", "她", "用户", "同事", "老板")):
        return "other"
    return "world"


def _clamp01(x):
    return max(0.0, min(1.0, x))
