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
    selfkb: list = field(default_factory=list)  # [(kind, text)] 自动入自我知识库的


# ---- 线索抽取 -----------------------------------------------------------
#
# 2026-10-29 收紧人名抽取。旧版 `([\u4e00-\u9fa5]{2,3})\s*(?:说|问|...)` 把
# 「2~3 个汉字 + 说/问」一律当人名, 真实库里长出了 person=也就是/而这个/最大的/
# 该直接/独立小/决的大 这种垃圾节点, 污染整张图。两个根因:
#   · 「问」会命中「问题」——「最大的问题是我...」抽出 person=最大的;
#   · 「说」会命中「说结论」——「直接说结论」抽出 person=直接。
# 现在要求动词后面紧跟「我 / 说 / 冒号」, 且名字不能是常见的形容词/连词尾巴。
_PERSON = re.compile(
    r"(?:@([\u4e00-\u9fa5]{2,4})"
    r"|([\u4e00-\u9fa5]{2,3})\s*(?:对我说|告诉我|提醒我|要求我|让我|问我|说我|说：|说:)"
    r"|([\u4e00-\u9fa5]{2,3})\s*(?:调走|离职|辞职|退休|入职|走人))"
)
# 不像人名的常见词(形容词/连词/副词尾巴)。宁可漏人名, 也不要把图灌脏。
_NOT_NAME = set("""
直接 这个 那个 现在 应该 可以 需要 因为 所以 但是 如果 然后 其实 已经 还是 就是
最大 最小 主要 重要 明显 具体 一般 通常 目前 当时 刚才 于是 因此 另外 同时 首先
本身 独立 判断 问题 结论 方案 结果 情况 方法 方式 部分 内容 时候 地方 东西 事情
""".split())


def _raw_sentences(text):
    """按句末标点与换行切句。不做说话人处理。"""
    out, buf = [], []
    for ch in text:
        if ch in "。;；!！?？\n":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(ch)
    s = "".join(buf).strip()
    if s:
        out.append(s)
    return out


_SPEAKER = re.compile(r"^\[[^\]]*\]\s*|^(?:用户|我|助手|assistant|user|系统)\s*[:：]\s*", re.I)
_SPEAKER_TAG = re.compile(r"^(用户|user|我|助手|assistant|系统)\s*[:：]\s*", re.I)


def _strip_speaker(sent):
    prev = None
    while prev != sent:
        prev = sent
        sent = _SPEAKER.sub("", sent).strip()
    return sent


def _utterances(text):
    """切句并标注说话人。返回 [(who, sentence)], who ∈ {"user", "self", "unknown"}。

    必须**先记下说话人再剥前缀**。旧版只剥不记, 于是钩子入库的
    `用户：…\n我：我用 PowerShell 请求端口…` 里那句助手自述被当成用户事实
    写进语义层, 再随投影注入 —— 实测线上库里三条 semantic 全是这么来的
    (「我用 OCR 读屏幕」「我用记事本这个程序作为对照」), 读起来像 agent
    在自我介绍技术栈。

    归属规则: 标记一直生效到下一条标记; 「用户：」单独一行时, 下一句才归属它。
    没有标记的原始文本记为 unknown(单条 tell 的常见形态, 按用户说的处理)。
    """
    out, who = [], "unknown"
    for raw in _raw_sentences(text):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]"):
            continue                      # "[DSH 会话 · …]" 记录头, 不是内容
        m = _SPEAKER_TAG.match(s)
        if m:
            tag = m.group(1).lower()
            who = "self" if tag in ("我", "助手", "assistant") else "user"
            s = _strip_speaker(s[m.end():])
            if not s:
                continue                  # 空标记行, 归属留给下一句
        else:
            s = _strip_speaker(s)
        if s:
            out.append((who, s))
    return out


def _sentences(text):
    """只要句子不要说话人(兼容旧调用)。"""
    return [s for _who, s in _utterances(text)]



_DEADLINE = re.compile(r"(下?周[一二三四五六日天]|今天|明天|后天|本周[一二三四五六日天]|\d{1,2}月\d{1,2}[日号])")
_TOPIC = re.compile(r"(?:关于|有关|问题|讨论|主题)[:：]?\s*([\u4e00-\u9fa5A-Za-z0-9]{2,16})")
_LOCATION = re.compile(r"(?:在|去|位于)([\u4e00-\u9fa5A-Za-z0-9]{2,10})(?:市|区|路|街|楼|号|公司|家)")

# 事实句信号: 命中即整句进语义层(不再只截取信号词后面那一小段)。
# 整句入语义层是为了让「张三调走了, 现在我的老板是李四」这种改口能被
# resolve_semantic 与人事类翻转对上 —— 截半句就匹配不上了。
#
# 2026-10-29 补了两组漏抽的句式(实测原来会静默丢掉):
#   · 用户对自己的表达规矩: 「以后别给我…」「说话别…」「以后别用…」
#   · 技术栈归属: 「我们用 mysql 做存储」「以后统一用 duckdb」
# 共同点是都带「以后/别/统一/改用」这类**持续性指示词** —— 一次性的
# 抱怨不该变成长久事实, 但"以后都这样"就该。
_FACT_SIGNAL = re.compile(
    r"(我喜欢|我不喜欢|我习惯|我喜欢用|我用|我们?用|我要求|我的项目|每天|每周|总是|从不"
    r"|我负责|我现在负责|我不负责|我的老板|我的上级|我的领导|我的主管|我的同事|我们组"
    r"|调走|离职|换成|改成|改用|不再"
    r"|以后别|以后不|以后统一|以后就|别用|别给|不要用|统一用|说话别|(?:^|[，,。：: ])别(?![人的处家]))"
)


# 任务句式: 动作必须在句首或紧跟「要/得/去/还需要」这类意图词, 避免把
# 「把识海做成了插件」里的「做成」当任务(「做」后面跟「成」是结果不是待办)。
_TASK_INTENT = re.compile(
    r"(?:需要|要|得|还需|去|准备|计划|打算|记得|别忘了|待办)\s*"
    r"(?:准备|完成|整理|修复|提交|测试|上线|发布|复盘|跟进|部署)([\u4e00-\u9fa5A-Za-z0-9]{2,12})"
)
_PROMISE = re.compile(r"(?:承诺|答应|保证|一定|以后不|再也不会)([^。;；\n]{0,30})")



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
        # 自我知识先跑: 同一句话不该同时进语义层和自我知识库
        # (「你以后别用客套话」两边都存一份, 改口时两边都要改, 必然漂移)
        self_kb, claimed = self._attach_self_knowledge(obs.text)
        sem = self._attach_semantic(event_id, obs.text, nodes, edges, skip=claimed)
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
                          nodes=nodes, task=task_title, semantic=sem, edges=edges,
                          selfkb=self_kb)

    # -- 内部 -----------------------------------------------------------
    def _split_nodes(self, event_id, text, ap):
        ref = "event:%d" % event_id
        nodes, edges = [], []

        def add_node(kind, label, rel):
            label = (label or "").strip()
            if not label or len(label) < 2:
                return None
            if kind == "person" and label in _NOT_NAME:
                return None
            nid = self.store.upsert_node(kind, label)
            nodes.append({"id": nid, "kind": kind, "label": label})
            self.store.add_edge(ref, "node:%d" % nid, rel)
            edges.append((ref, "node:%d" % nid, rel))
            return nid

        for m in _PERSON.finditer(text):
            add_node("person", m.group(1) or m.group(2) or m.group(3), "involved")
        for m in _LOCATION.finditer(text):
            add_node("location", m.group(1), "about")
        for m in _TOPIC.finditer(text):
            add_node("theme", m.group(1), "about")
        # 情绪状态也做成节点: "担心"能成为一个召回入口
        if ap.emotion not in ("平静",):
            add_node("state", ap.emotion, "state")
        return nodes, edges

    def _attach_task(self, event_id, text, nodes, edges):
        """任务抽取。2026-10-29 收紧: 动作词前面必须有意图词(需要/要/得/去/准备…),
        否则「把识海做成了插件」里的「做成」会被当成待办 —— 真实库里因此攒了
        「转换 / 成了 / 并且可用 / 一遍」五条永远关不掉的任务。"""
        ms = list(_TASK_INTENT.finditer(text))
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

    def _attach_semantic(self, event_id, text, nodes, edges, skip=()):
        """稳定事实: 只有含事实信号的**整句**才蒸馏, 避免噪音。

        走 resolve_semantic 做冲突决策(mem0 式 ADD/UPDATE/NOOP/SUPERSEDE)。

        2026-10-29 改成整句入库。旧版只截信号词后面 30 字, 于是
        「张三调走了, 现在我的老板是李四」只留下半句, 与旧事实
        「我的老板是张三」几乎不重叠, 改口永远匹配不上。整句之后
        「我的老板」这个共同主干就能把两句连起来了。

        skip: 已经作为自我知识入库的句子。两边都存一份的话, 用户改口时
        要改两处, 迟早漂移 —— 自我知识优先。

        只收**用户**说的话。钩子入库的记录带 `用户：/我：` 标记, 助手那句
        「我用 PowerShell 请求端口，得到 403」是它自己在描述刚才干了什么,
        不是关于用户的稳定事实 —— 收进去之后会被投影注入, 读起来像 agent
        在自我介绍技术栈。线上库实测三条 semantic 全是这么来的。
        无标记的纯文本记为 unknown, 照旧处理(单条 tell 的常见形态)。
        """
        out = []
        for who, sent in _utterances(text):
            if who == "self":
                continue
            if not _FACT_SIGNAL.search(sent):
                continue
            claim = sent.strip()
            if len(claim) < 4 or claim in skip:
                continue
            sid, action = self.store.resolve_semantic(claim, subject=None,
                                                      confidence=0.7, sources=[event_id])
            if action in ("ADD", "SUPERSEDE"):
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

    def _attach_self_knowledge(self, text):
        """会话里的「关于我自己」自动进自我知识库。

        2026-10-29 补的自动入口。在此之前 self_knowledge 只有一个写点
        (人显式调用 selflearn / agent 主动调工具), 于是用户在对话里说的
        「以后别给我写总结」「我更喜欢你先给结论」永远只是情景记忆 ——
        下次开新会话想不起来, 得靠人再教一遍。这恰好是识海最该解决的场景。

        门在 kb.auto_kind 里: 只收对我下的长期指示与关于我自己的自述,
        带项目/系统/接口这类名词的一律拒收(那是世界知识, 走共享知识库)。

        返回 (入自我知识库的 [(kind, text)], 已被认领的原始句子)。
        第二项给 _attach_semantic 用 —— 同一句话不该在两个层各存一份。

        只收用户说的。助手那句「我更喜欢先给结论」是对用户的建议, 不是用户
        对它的要求; 反过来只有用户说的才算"我的行事规矩"。
        """
        from .kb import auto_kind, as_first_person, SelfKB
        out, claimed = [], set()
        kb = SelfKB(self.store)
        for who, sent in _utterances(text):
            if who == "self":
                continue
            kind = auto_kind(sent)
            if not kind:
                continue
            claimed.add(sent)
            mine = as_first_person(sent)
            if len(mine) < 4:
                continue
            kid, status, _note = kb.learn(mine, kind=kind, source="auto")
            if status == "learned":
                out.append((kind, mine))
        return out, claimed


def _division(text, ap):
    if ap.self_relevance > 0.55:
        return "self"
    if any(k in text for k in ("你", "他", "她", "用户", "同事", "老板")):
        return "other"
    return "world"


def _clamp01(x):
    return max(0.0, min(1.0, x))
