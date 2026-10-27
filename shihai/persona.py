# -*- coding: utf-8 -*-
"""Persona —— 人格卡: 从核心记忆反推"我是谁"。

这是整个项目对"人格"的工程定义:
    人格 = 核心记忆在七个维度上的投影 + 一段自述。
不是设定出来的口吻, 不是 prompt 里的角色扮演。

但"不是设定"不等于"不能有起点"(2026-10-27 补):
    一份被主动植入的人格卡是**先验**, 不是终值。
    - persona_seed  人交付的样子, 只追加版本, 记忆永不改写它;
    - persona_field 现在的我, 每轮固结由记忆推动, 但推不快、推不远;
    - 三层纪律: flux 可塑半径(推不出去) / 单步 0.03(推不快) /
      硬支点越多越推不动(弹性权重, EWC 的 Fisher 代理)。
    人格卡正文 = 内核段逐字不变 + "我后来变成了" 的漂移叙述。

七维 trait(0~1):
    caution      谨慎      —— 由失败/伤害类核心记忆累积
    warmth       亲和      —— 由正向关系记忆累积
    assertiveness 主张      —— 由被侵犯边界/冲突后仍坚持的记忆累积
    curiosity    好奇      —— 由探索/新主题记忆累积
    persistence  坚韧      —— 由重复失败后继续的记忆累积
    guardedness  封闭      —— 由封存/回避型核心记忆累积
    self_blame   自责倾向  —— 由 self 分区的高痛记忆累积

自述(card)是可读文本, 直接可以注入系统提示。
人格漂移 = 两次快照的 trait 差值 + persona_changelog 里逐条的归因。
"""

import json
import math
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

# 单轮固结允许的最大位移。人格是被很多天推出来的, 不是被一条消息掀翻的。
STEP_LIMIT = 0.03
# 基础学习率: 每轮向"记忆指向的目标"靠近多少
LEARN_RATE = 0.25

# 植入用的现成人格底稿。给"想立刻有个起点"的人一个不用手写七个数字的入口;
# 数值刻意不极端 —— 极端起点配上 0.03 的步长, 会让 agent 很久都像另一个人。
ARCHETYPES = {
    "cautious": {"name": "谨慎的老手", "traits": {
        "caution": 0.72, "warmth": 0.45, "assertiveness": 0.5,
        "curiosity": 0.35, "persistence": 0.6, "guardedness": 0.58, "self_blame": 0.55}},
    "curious": {"name": "好奇的探索者", "traits": {
        "caution": 0.35, "warmth": 0.6, "assertiveness": 0.5,
        "curiosity": 0.82, "persistence": 0.45, "guardedness": 0.25, "self_blame": 0.3}},
    "warm": {"name": "温和的同伴", "traits": {
        "caution": 0.45, "warmth": 0.8, "assertiveness": 0.4,
        "curiosity": 0.55, "persistence": 0.5, "guardedness": 0.3, "self_blame": 0.35}},
    "assertive": {"name": "直接的合作者", "traits": {
        "caution": 0.45, "warmth": 0.5, "assertiveness": 0.78,
        "curiosity": 0.5, "persistence": 0.65, "guardedness": 0.35, "self_blame": 0.3}},
    "persistent": {"name": "耐磨的苦工", "traits": {
        "caution": 0.55, "warmth": 0.45, "assertiveness": 0.55,
        "curiosity": 0.4, "persistence": 0.85, "guardedness": 0.4, "self_blame": 0.45}},
}

# 默认可塑半径: 身份底色(谨慎/自责)漂得慢, 表达层(好奇/亲和)漂得快。
# 与 kb.py 的元可塑性同源 —— identity 0.2 / style 0.8 那套分级。
DEFAULT_FLUX = {
    "caution": 0.18, "warmth": 0.22, "assertiveness": 0.20, "curiosity": 0.25,
    "persistence": 0.15, "guardedness": 0.18, "self_blame": 0.15,
}


@dataclass
class PersonaCard:
    traits: dict
    card: str
    core_ids: list = field(default_factory=list)
    typology: dict = field(default_factory=dict)
    voice: str = ""              # 说话风格卡(渲染后的 markdown 段)
    graph: dict = field(default_factory=dict)   # 性格图谱(支点/编织/张力)
    seed: dict = field(default_factory=dict)    # 植入的先验(无植入时为空)
    drift: dict = field(default_factory=dict)   # 现值 − 种子, 逐维
    version: int = 0                            # 当前种子版本, 0 = 未植入
    changed: list = field(default_factory=list) # 本轮被推动的维度

    def to_dict(self):
        return {"traits": self.traits, "card": self.card, "core_ids": self.core_ids,
                "typology": self.typology, "voice": self.voice, "graph": self.graph,
                "seed": self.seed, "drift": self.drift, "version": self.version,
                "changed": self.changed}


class PersonaEngine:
    def __init__(self, store, name="agent", typology_path="typology_state.json"):
        self.store = store
        self.name = name
        self.typology_engine = TypologyEngine(store, path=typology_path)
        self.voice_engine = VoiceEngine(store)
        self.graph_engine = PersonalityGraphEngine(store)

    # -- 植入 -----------------------------------------------------------
    def implant(self, *, traits=None, archetype=None, flux=None,
                identity_text=None, note=None, source="human"):
        """主动植入一份人格卡。返回 (version, traits, flux)。

        植入的是**起点**而不是脚本: 之后每轮固结, 记忆都在这个起点附近
        把人格往它自己的方向推, 但推不出 flux 半径, 一轮也推不过 0.03。
        """
        base = dict(ARCHETYPES[archetype]["traits"]) if archetype else {}
        base.update(traits or {})
        if not base:
            raise ValueError("植入人格卡需要 traits 或 archetype")
        clean = {k: _c(float(v)) for k, v in base.items() if k in TRAITS}
        if not clean:
            raise ValueError("traits 里没有可识别的维度: %s" % ", ".join(TRAITS))
        fl = dict(DEFAULT_FLUX)
        fl.update({k: abs(float(v)) for k, v in (flux or {}).items() if k in TRAITS})
        version = self.store.implant_seed(clean, fl, identity_text=identity_text,
                                          source=source, note=note)
        return version, clean, fl

    def seed_info(self):
        """当前种子的三元组: (traits, flux, identity_text, version)。未植入返回 None。"""
        row = self.store.current_seed()
        if row is None:
            return None
        return (json.loads(row["traits"]), json.loads(row["flux"]),
                row["identity_text"] or "", int(row["version"]))

    # -- 主入口 ---------------------------------------------------------
    def refresh(self, *, persist=True):
        """persist=False 是「看一眼」模式: 只算不写。

        可视化面板每打开一次就 refresh 一次, 若照旧写 persona_snapshot,
        漂移曲线会被观测行为本身污染(看一次多一个数据点)。

        同理, persist=False 时也不推进 persona_field —— 看一眼不该让人格
        往前走一步, 只报告它现在在哪。
        """
        cores = self.store.conn.execute(
            "SELECT * FROM events WHERE core=1 AND dormant=0 ORDER BY id"
        ).fetchall()
        # 性格图谱先织: traits 从图上读(支点×编织), 不再凭空平均
        graph = self.graph_engine.weave(persist=persist)
        grown, changed = self._grow(graph.traits, graph.fulcrums,
                                    n_core=len(cores), persist=persist)
        traits = grown
        typ = self.typology_engine.infer(persist=persist)
        seed_info = self.seed_info()
        seed_traits = seed_info[0] if seed_info else {}
        drift = {k: round(traits.get(k, 0.0) - seed_traits.get(k, 0.0), 3)
                 for k in seed_traits}
        if seed_info:
            card = self._render_seeded(traits, cores, typ, graph,
                                       seed_info, drift, changed)
        else:
            card = self._render(traits, cores, typ, graph)
        ids = [r["id"] for r in cores]
        if persist:
            self.store.add_persona(traits, card, ids)
        voice = self.voice_engine.build(typ, traits)
        return PersonaCard(traits=traits, card=card, core_ids=ids,
                           typology=typ.to_dict(), voice=voice.render(),
                           graph=graph.to_dict(), seed=seed_traits, drift=drift,
                           version=seed_info[3] if seed_info else 0,
                           changed=changed)

    # -- 可塑生长: 种子 + 记忆 -------------------------------------------
    def _grow(self, obs, fulcrums, *, n_core, persist=True):
        """把"记忆观测值"折进"被植入的人格", 得到现在的我。

        没植入过就原样返回观测值 —— 老库的行为一点不变。
        植入过就走四道闸:
            ① 软限幅    tanh 把观测值压进 seed ± cap, 极端经历推不出半球
            ② 弹性权重  该维度上硬支点越多, 学习率越低(EWC 的 Fisher 代理)
            ③ 单步上限  一轮最多动 STEP_LIMIT
            ④ 硬边界    任何情况下不许越出 seed ± cap
        最后一步才是回弹: 记忆衰减后观测值退回 seed 附近, 人格自然跟着回来,
        不需要额外的"回正"计时器 —— 遗忘本身就是回正机制。
        """
        fields = self.store.persona_fields()
        if not fields:
            return dict(obs), []
        cap_scale = 1.0 + 0.5 * min(1.0, n_core / 5.0)   # 经历越多, 越有资格不是原来那个
        seed_info = self.seed_info()
        version = seed_info[3] if seed_info else 0
        out, changed = {}, []
        for t in TRAITS:
            if t not in fields:
                out[t] = round(float(obs.get(t, 0.5)), 3)
                continue
            seed_v = fields[t]["seed"]
            cur = fields[t]["value"]
            cap = max(1e-6, fields[t]["cap"] * cap_scale)
            mine = [f for f in fulcrums if f.trait == t]
            if not mine:
                # 这个维度上暂时没有支点(记忆淡了/被压过去了): 向起点慢慢回弹。
                # 遗忘本身就是回正机制, 不需要额外的人工"复位"。
                new = _step(cur, cur + 0.05 * (seed_v - cur), seed_v, cap)
                out[t] = round(cur if not persist else new, 3)
                if persist and abs(new - cur) > 1e-3:
                    changed.append(t)
                    self.store.set_persona_field(t, new, reason="rebound")
                    self.store.log_persona_change(t, cur, new, "reflection",
                                                  version=version)
                continue
            # 弹性: 该维度被多硬的支点撑着。撑得越硬, 单条记忆越推不动。
            anchor = min(1.0, sum(f.strength for f in mine) / 3.0)
            rate = LEARN_RATE * (1.0 - 0.6 * anchor)
            target = seed_v + cap * math.tanh((float(obs.get(t, seed_v)) - seed_v) / cap)
            new = _step(cur, cur + rate * (target - cur), seed_v, cap)
            out[t] = round(cur if not persist else new, 3)   # 看一眼: 不迈这一步
            if persist and abs(new - cur) > 1e-3:
                changed.append(t)
                self.store.set_persona_field(t, new, reason="grow")
                self.store.log_persona_change(t, cur, new, "recall",
                                              evidence=[f.event_id for f in mine][:3],
                                              version=version)
        return out, changed

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

    def _render_seeded(self, t, cores, typ, graph, seed_info, drift, changed):
        """植入过人格卡时的自述。

        与从零长出来的人格卡的区别: 多了"内核段"与"我后来变成了"。
        内核段逐字来自人的交付, 记忆不碰它 —— 这是"人给的样子"与
        "经历改出来的样子"在同一张卡上并置, 且分得清哪句是谁说的。
        """
        seed_traits, flux, identity_text, version = seed_info
        lines = ["我是 %s。" % self.name]
        if identity_text:
            lines.append("")
            lines.append(identity_text.strip())
        lines.append("")
        lines.append("### 我被交付时的样子(v%d)" % version)
        strong = sorted(seed_traits.items(), key=lambda kv: -kv[1])[:3]
        lines.append("起点倾向: " + ", ".join(
            "%s %.2f" % (TRAIT_LABEL[k], v) for k, v in strong) + "。")

        # 漂移叙述: 只讲越过显著门槛的维度(±0.05), 否则复述七个数字没有意义
        moved = [(k, d) for k, d in drift.items() if abs(d) >= 0.05]
        moved.sort(key=lambda kv: -abs(kv[1]))
        if not moved:
            lines.append("到目前为止, 经历还没有把我推离那个起点 —— "
                         "或者我还没有足够多的核心记忆。")
        else:
            lines.append("")
            lines.append("### 我后来变成了")
            for k, d in moved[:4]:
                cap = flux.get(k, DEFAULT_FLUX.get(k, 0.15))
                used = min(1.0, abs(d) / max(cap, 1e-6))
                lines.append("  · %s %+.2f(起点 %.2f → 现在 %.2f), "
                             "这条路上我还剩 %.0f%% 的余地。"
                             % (TRAIT_LABEL[k], d, seed_traits[k], t[k],
                                max(0.0, 100 * (1 - used))))
            if changed:
                lines.append("  这一轮被推动的是: " +
                             "、".join(TRAIT_LABEL[k] for k in changed) + "。")

        if typ is not None:
            lines.append("")
            lines += self._typology_lines(typ)
        if graph is not None and graph.fulcrums:
            lines.append("")
            lines.append(graph.summary)
            for ten in graph.tensions[:2]:
                lines.append("  · 我内部在拔河: %s。这不是矛盾, 是我。" % ten)

        if cores:
            lines.append("")
            lines.append("我在意的:")
            for r in sorted(cores, key=lambda r: -float(r["core_score"]))[:3]:
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


def _step(cur, want, seed_v, cap):
    """四道闸里的后两道: 单步上限 + 硬边界。任何推动都必须过这里。"""
    want = max(cur - STEP_LIMIT, min(cur + STEP_LIMIT, want))
    want = max(seed_v - cap, min(seed_v + cap, want))
    return round(_c(want), 3)
