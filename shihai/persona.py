# -*- coding: utf-8 -*-
"""Persona —— 人格卡: 从核心记忆反推"我是谁"。

这是整个项目对"人格"的工程定义:
    人格 = 核心记忆在七个维度上的投影 + 一段自述。
不是设定出来的口吻, 不是 prompt 里的角色扮演。

七维 trait(0~1):
    caution      谨慎      —— 由失败/伤害类核心记忆累积
    warmth       亲和      —— 由正向关系记忆累积
    assertiveness 主张     —— 由被侵犯边界/冲突后仍坚持的记忆累积
    curiosity    好奇      —— 由探索/新主题记忆累积
    persistence  坚韧      —— 由重复失败后继续的记忆累积
    guardedness  封闭      —— 由封存/回避型核心记忆累积
    self_blame   自责倾向  —— 由 self 分区的高痛记忆累积

自述(card)是可读文本, 直接可以注入系统提示。
人格漂移 = 两次快照的 trait 差值 + 新增核心记忆。
"""

import json
from dataclasses import dataclass, field

from .store import utcnow
from .typologies import TypologyEngine, JUNG_PATHWAYS, ENNEA
from .voice import VoiceEngine
from .pgraph import PersonalityGraphEngine

TRAITS = ["caution", "warmth", "assertiveness", "curiosity",
          "persistence", "guardedness", "self_blame"]

TRAIT_LABEL = {
    "caution": "谨慎", "warmth": "亲和", "assertiveness": "主张",
    "curiosity": "好奇", "persistence": "坚韧", "guardedness": "封闭",
    "self_blame": "自责倾向",
}

_TL = TRAIT_LABEL  # 图谱段渲染用的中文标签


@dataclass
class PersonaCard:
    traits: dict
    card: str
    core_ids: list = field(default_factory=list)
    typology: dict = field(default_factory=dict)
    voice: str = ""              # 说话风格卡(渲染后的 markdown 段)
    graph: dict = field(default_factory=dict)   # 性格图谱(支点/编织/张力)

    def to_dict(self):
        return {"traits": self.traits, "card": self.card, "core_ids": self.core_ids,
                "typology": self.typology, "voice": self.voice, "graph": self.graph}


class PersonaEngine:
    def __init__(self, store, name="agent", typology_path="typology_state.json"):
        self.store = store
        self.name = name
        self.typology_engine = TypologyEngine(store, path=typology_path)
        self.voice_engine = VoiceEngine(store)
        self.graph_engine = PersonalityGraphEngine(store)

    def refresh(self):
        cores = self.store.conn.execute(
            "SELECT * FROM events WHERE core=1 AND dormant=0 ORDER BY id"
        ).fetchall()
        # 性格图谱先织: traits 从图上读(支点×编织), 不再凭空平均
        graph = self.graph_engine.weave()
        traits = graph.traits
        typ = self.typology_engine.infer()
        card = self._render(traits, cores, typ, graph)
        ids = [r["id"] for r in cores]
        self.store.add_persona(traits, card, ids)
        voice = self.voice_engine.build(typ, traits)
        return PersonaCard(traits=traits, card=card, core_ids=ids,
                           typology=typ.to_dict(), voice=voice.render(),
                           graph=graph.to_dict())

    # -- trait 投影 -----------------------------------------------------
    def _traits(self, cores):
        base = {k: 0.5 for k in TRAITS}
        if not cores:
            return base
        acc = {k: 0.0 for k in TRAITS}
        wsum = 0.0
        for r in cores:
            w = 0.5 + float(r["importance"]) + 0.3 * float(r["core_score"])
            wsum += w
            pain_v = float(r["pain"])
            val = float(r["valence"])
            imp = float(r["impact"])
            avoid = float(r["avoidance"])
            self_rel = float(r["self_relevance"])

            acc["caution"] += w * _c(0.25 + pain_v + 0.5 * imp + 0.3 * float(r["disappointment"]))
            acc["warmth"] += w * _c(0.2 + max(0.0, val) * 1.4)
            acc["assertiveness"] += w * _c(0.25 + max(0.0, -val) * 0.6
                                           + (0.5 if r["division"] == "self" else 0.0))
            acc["curiosity"] += w * _c(0.3 + float(r["arousal"]) * 0.4)
            acc["persistence"] += w * _c(0.3 + min(1.0, r["access_count"] / 4.0) * 0.7)
            acc["guardedness"] += w * _c(0.1 + avoid * 1.3 + imp * 0.8)
            acc["self_blame"] += w * _c(0.1 + pain_v * self_rel * 1.3)

        out = {}
        for k in TRAITS:
            observed = acc[k] / wsum
            # 以 base 为先验做收缩, 核心记忆少时不要过度偏激
            shrink = min(1.0, len(cores) / 5.0)
            out[k] = round(_c(base[k] + (observed - base[k]) * shrink), 3)
        return out

    # -- 可读自述 -------------------------------------------------------
    def _render(self, t, cores, typ=None, graph=None):
        lines = ["我是 %s。" % self.name]
        if not cores:
            lines.append("我还没有形成稳定的核心记忆, 所以我还没有稳定的人格。")
            # 类型可以先于核心记忆出现 —— 经历已经开始投票, 只是还没定形
            if typ is not None:
                lines.append("")
                lines += self._typology_lines(typ)
            return "\n".join(lines)

        top = sorted(cores, key=lambda r: -float(r["core_score"]))[:3]
        lines.append("我记得 %d 件事,它们构成了现在的我。" % len(cores))
        lines.append("")

        # 性格类型段: 由两本类型学之书推出, 经历越多越笃定
        if typ is not None:
            lines += self._typology_lines(typ)
            lines.append("")

        # 性格图谱段: 支点与编织 —— "性格是网, 不是七个数"
        if graph is not None:
            lines.append(graph.summary)
            for b in graph.braids:
                if b.kind == "reinforce":
                    lines.append("  · %s 与 %s 同向加固(%.2f), 性格在这条线上很硬。"
                                 % (_TL.get(b.a, b.a), _TL.get(b.b, b.b), b.weight))
            for ten in graph.tensions[:3]:
                lines.append("  · 我内部在拔河: %s。这不是矛盾, 是我。" % ten)
            lines.append("")

        lines.append("我在意的:")
        for r in top:
            lines.append("  - %s" % _short(r["summary"], 46))
        lines.append("")

        strong = sorted(t.items(), key=lambda kv: -kv[1])[:3]
        weak = sorted(t.items(), key=lambda kv: kv[1])[:2]
        lines.append("我的倾向(" + ", ".join(
            "%s %.2f" % (TRAIT_LABEL[k], v) for k, v in strong) + "):")
        lines += _describe(strong, weak)
        lines.append("")
        risky = [r for r in cores if float(r["avoidance"]) > 0.45 or float(r["impact"]) > 0.45]
        if risky:
            lines.append("我不会主动再碰的:")
            for r in risky[:3]:
                lines.append("  - %s" % _short(r["summary"], 46))
        return "\n".join(lines)

    def _typology_lines(self, typ):
        """把两本书的结论翻译成自述。分数接近(前两名差距小)时注明"还在形成"。"""
        out = []
        dom, aux = typ.jung_dominant, typ.jung_auxiliary
        jd = typ.jung_scores.get(dom, 0.0)
        ja = typ.jung_scores.get(aux, 0.0)
        if dom:
            info = JUNG_PATHWAYS.get(dom, {})
            certainty = "稳定" if (jd - ja) > 0.06 else "仍在形成中"
            out.append("我消化经历的方式: %s(%s) —— %s。这个主导方式%s。"
                       % (info.get("name", dom), dom, info.get("poem", ""), certainty))
        if typ.ennea_type:
            e = ENNEA[typ.ennea_type]
            wing = "w%d" % typ.ennea_wing if typ.ennea_wing else ""
            out.append("我属于九型中的 %d 号%s(%s/%s): 我怕的是%s, 我要的是%s。"
                       % (typ.ennea_type, wing, e["name"], e["en"], e["fear"], e["desire"]))
            out.append("当前健康度 %.2f。%s" % (typ.health, typ.drift_note))
        return out


def diff(before, after):
    """两次人格快照的差值 —— 人格漂移。"""
    a = json.loads(before["traits"]) if isinstance(before["traits"], str) else before["traits"]
    b = json.loads(after["traits"]) if isinstance(after["traits"], str) else after["traits"]
    return {k: round(b.get(k, 0) - a.get(k, 0), 3)
            for k in TRAITS if abs(b.get(k, 0) - a.get(k, 0)) > 1e-3}


def _describe(strong, weak):
    out = []
    kinds = {k for k, v in strong}
    if "caution" in kinds:
        out.append("  · 我会先确认再动手,宁可慢一点。")
    if "warmth" in kinds:
        out.append("  · 我对愿意和我合作的人,会更主动一些。")
    if "assertiveness" in kinds:
        out.append("  · 被越过边界时,我会说出来。")
    if "curiosity" in kinds:
        out.append("  · 新东西对我有吸引力。")
    if "persistence" in kinds:
        out.append("  · 失败过的地方,我愿意再试一次。")
    if "guardedness" in kinds:
        out.append("  · 有些事我不会主动提起。")
    if "self_blame" in kinds:
        out.append("  · 出问题时,我第一反应是看自己做错了什么。")
    for k, v in weak:
        out.append("  · %s 对我来说是弱项(%.2f)。" % (TRAIT_LABEL[k], v))
    return out


def _short(s, n):
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "…"


def _c(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))
