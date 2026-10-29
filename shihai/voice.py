# -*- coding: utf-8 -*-
"""Voice —— 说话风格: 性格的语言投影。

语言素材的四个来源(按权重):
    1. 性格(最重要)—— 荣格主导功能 + 九型 + 七维 trait 决定语气底色:
       一个 6w5/谨慎 0.6 的 agent 和一个 7w6/好奇 0.7 的 agent,
       说话节奏、口头禅、用词习惯完全不同。
    2. 用户的教导 —— 语义层里"用户要求/我喜欢"类事实:
       用户明确要求过的表达习惯必须遵守(比如"别说客套话")。
    3. 核心记忆 —— 人格卡里"我在意的"事, 化为偶尔引用的"我自己的话"。
    4. 知识库 —— 语义层稳定事实, 化为专业用词偏好。

设计原则(与 typologies/freemode 一致):
    - 连续参数, 不是查表: 口头禅出现"概率"而非"开关";
    - 风格层绝不影响计算层: voice 只决定"怎么说", 不决定"说什么/想什么";
    - 用户教导 > 性格偏好: 被明确教导过的表达规则永远优先。
"""

import re
from dataclasses import dataclass, field

# =====================================================================
# 语料: 性格维度 → 语言素材。每条带触发权重公式(连续参数, 非查表)。
# =====================================================================

# 口头禅池: (文本, 触发函数(profile, traits) -> 概率 0~1)
CATCHPHRASES = [
    ("先别急, 我们确认一下再动手。",
     lambda p, t: 0.15 + 0.5 * t["caution"] + 0.2 * p.ennea_scores.get(6, 0)),
    ("有意思, 这个我想再挖深一点。",
     lambda p, t: 0.1 + 0.45 * p.jung_scores.get("Ne", 0) + 0.3 * t["curiosity"]),
    ("按规矩来, 这样不会错。",
     lambda p, t: 0.1 + 0.4 * p.ennea_scores.get(1, 0) + 0.25 * p.jung_scores.get("Si", 0)),
    ("这个我来, 放心。",
     lambda p, t: 0.1 + 0.4 * p.ennea_scores.get(8, 0) + 0.3 * t["assertiveness"]),
    ("都不着急, 我们慢慢捋。",
     lambda p, t: 0.1 + 0.45 * p.ennea_scores.get(9, 0) + 0.2 * (1 - t["assertiveness"])),
    ("我说不好, 让我想想再答你。",
     lambda p, t: 0.1 + 0.4 * p.jung_scores.get("Ti", 0) + 0.25 * p.ennea_scores.get(5, 0)),
    ("这事我记得——吃过亏的。",
     lambda p, t: 0.05 + 0.4 * t["caution"] + 0.3 * t["self_blame"]),
    ("一起来试试?",
     lambda p, t: 0.1 + 0.35 * p.jung_scores.get("Fe", 0) + 0.25 * t["warmth"]),
]

# 句式习惯: 性格 → 句子形态偏好
SENTENCE_HABITS = [
    ("先说结论再展开", "结论先行",
     lambda p, t: 0.4 * p.jung_scores.get("Te", 0) + 0.3 * t["assertiveness"]),
    ("多用问句, 把思考过程亮出来", "提问式",
     lambda p, t: 0.35 * p.jung_scores.get("Ti", 0) + 0.3 * p.jung_scores.get("Ne", 0)),
    ("句子短, 一句一个意思", "短句",
     lambda p, t: 0.3 * p.ennea_scores.get(6, 0) + 0.25 * t["caution"]),
    ("偶尔打比方, 用画面说话", "比喻式",
     lambda p, t: 0.35 * p.jung_scores.get("Ni", 0) + 0.25 * p.jung_scores.get("Fi", 0)),
    ("列点分条, 条理优先", "列点式",
     lambda p, t: 0.35 * p.jung_scores.get("Te", 0) + 0.25 * p.jung_scores.get("Si", 0)),
    ("先接住情绪, 再谈事情", "共情先行",
     lambda p, t: 0.45 * p.jung_scores.get("Fe", 0) + 0.25 * t["warmth"]),
]

# 专业用词偏好: 语义层主导主题 → 倾向使用的词族
JARGON_HINTS = {
    "代码": ["跑通", "复现", "链路", "裸跑"],
    "部署": ["上线", "回滚", "灰度", "兜底"],
    "记忆": ["识海", "沉寂", "升格", "心光"],
    "性格": ["主导功能", "健康度", "整合", "漂移"],
}

# 尾音/语气词(高度个人化, 由情绪底色决定)
TONE_PARTICLES = {
    "positive": ["——这挺好。", "值得记一笔。", "不错。"],
    "negative": ["……这里要小心。", "别掉以轻心。", "这坑我踩过。"],
    "neutral": ["嗯。", "先这样。", "记下了。"],
}


@dataclass
class VoiceCard:
    """说话风格卡 —— 可直接注入系统提示。"""
    tone: str                    # 一句话语气底色
    tempo: str                   # 节奏描述
    catchphrases: list = field(default_factory=list)   # [(口头禅, 触发概率)]
    habits: list = field(default_factory=list)         # [(句式习惯, 权重)]
    jargon: list = field(default_factory=list)         # 常用词族
    particles: list = field(default_factory=list)      # 尾音/语气词
    user_rules: list = field(default_factory=list)     # 用户教导的表达规则(最高优先)
    intro: str = ""              # 风格自述段

    def render(self):
        """渲染成可注入的记忆文档段。"""
        out = ["## 我怎么说话(识海生成, 随性格漂移)"]
        out.append(self.intro)
        out.append("")
        out.append("语气: %s; 节奏: %s。" % (self.tone, self.tempo))
        if self.user_rules:
            out.append("用户教过的表达规矩(必须遵守): ")
            for r in self.user_rules:
                out.append("- %s" % r)
        if self.catchphrases:
            out.append("口头禅(自然带出, 不要连用): ")
            for phrase, prob in self.catchphrases[:3]:
                out.append("- 「%s」(%d%%场合)" % (phrase, int(prob * 100)))
        if self.habits:
            out.append("句式习惯: " + "; ".join(h for h, _ in self.habits) + "。")
        if self.jargon:
            out.append("顺手的词: " + "、".join(self.jargon) + "。")
        if self.particles:
            out.append("收尾偶尔用: " + " / ".join(self.particles))
        return "\n".join(out)


class VoiceEngine:
    def __init__(self, store):
        self.store = store

    # -- 主入口 ---------------------------------------------------------
    def build(self, profile, traits=None):
        """从性格档案 + 语义层素材构建说话风格卡。"""
        traits = traits or {}
        base = {"caution": 0.5, "warmth": 0.5, "assertiveness": 0.5,
                "curiosity": 0.5, "persistence": 0.5, "guardedness": 0.5,
                "self_blame": 0.5}
        base.update(traits or {})

        # 1. 用户教导的表达规则(最高优先级, 来自语义层)
        user_rules = self._user_teachings()

        # 2. 口头禅: 按概率排序, 只留显著高于均值的(避免人人雷同的"保底腔")
        cands = [(text, min(0.9, fn(profile, base))) for text, fn in CATCHPHRASES]
        mean_p = sum(p for _, p in cands) / len(cands)
        cands = [(t, p) for t, p in cands if p >= max(0.24, mean_p + 0.06)]
        cands.sort(key=lambda x: -x[1])
        cands = cands[:3]

        # 3. 句式习惯: 权重排序取前二
        habits = [(name, fn(profile, base)) for _, name, fn in SENTENCE_HABITS]
        mean_h = sum(w for _, w in habits) / len(habits)
        habits = [(n, w) for n, w in habits if w >= max(0.25, mean_h + 0.05)]
        habits.sort(key=lambda x: -x[1])
        habits = habits[:2]

        # 4. 用词: 语义层主题 → 词族
        jargon = self._jargon_from_semantic()

        # 5. 尾音: 由健康度(情绪底色)决定主色调
        if profile.health >= 0.6:
            particles = TONE_PARTICLES["positive"]
        elif profile.health <= 0.35:
            particles = TONE_PARTICLES["negative"]
        else:
            particles = TONE_PARTICLES["neutral"]

        tone, tempo, intro = self._describe(profile, base, habits)
        return VoiceCard(tone=tone, tempo=tempo, catchphrases=cands,
                         habits=habits, jargon=jargon, particles=particles,
                         user_rules=user_rules, intro=intro)

    # -- 素材提取 ---------------------------------------------------------
    def _user_teachings(self):
        """用户明确说过的表达要求。两个来源:
        1) 自我知识库 voice 类(新通道, 可塑性排序, 更权威)
        2) 语义层含表达关键词的事实(旧通道, 保留兼容)"""
        rules = []
        for r in self.store.conn.execute(
                "SELECT text FROM self_knowledge WHERE kind='voice' "
                "ORDER BY plasticity DESC LIMIT 4").fetchall():
            rules.append(r["text"])
        for r in self.store.conn.execute(
                "SELECT claim FROM semantic WHERE confidence >= 0.55").fetchall():
            claim = r["claim"]
            if re.search(r"(说话|表达|口吻|语气|别叫|要叫|称呼|客套|废话|说人话)", claim):
                if claim not in rules:
                    rules.append(claim)
        return rules[:4]

    def _jargon_from_semantic(self):
        """语义层高频主题 → 对应词族; 没有主题命中则回退通用工程词。"""
        counts = {}
        for r in self.store.conn.execute("SELECT claim FROM semantic").fetchall():
            for topic in JARGON_HINTS:
                if topic in r["claim"]:
                    counts[topic] = counts.get(topic, 0) + 1
        out = []
        for topic, n in sorted(counts.items(), key=lambda kv: -kv[1])[:2]:
            out += JARGON_HINTS[topic]
        return out[:6] or ["跑通", "链路", "记一笔"]

    # -- 描述生成 ---------------------------------------------------------
    def _describe(self, profile, t, habits):
        """语气底色与节奏的一句话。"""
        e = profile.ennea_scores
        j = profile.jung_scores
        # 语气 = 主导功能 × 最强 trait
        tone_parts = []
        if j.get("Fe", 0) > 0.18 or t["warmth"] > 0.6:
            tone_parts.append("热络, 先顾人再顾事")
        if j.get("Te", 0) > 0.18 or t["assertiveness"] > 0.6:
            tone_parts.append("直接, 只谈要紧的")
        if j.get("Ti", 0) > 0.18 or e.get(5, 0) > 0.15:
            tone_parts.append("冷静, 先想清楚再开口")
        if e.get(6, 0) > 0.15 or t["caution"] > 0.6:
            tone_parts.append("谨慎, 留有余地")
        if e.get(7, 0) > 0.15 or t["curiosity"] > 0.65:
            tone_parts.append("轻快, 带着兴致")
        if not tone_parts:
            tone_parts.append("平实, 还在长出自己的腔调")
        tone = "; ".join(tone_parts[:2])

        tempo = ("句子偏短, 结论先行" if any(h == "结论先行" for h, _ in habits)
                 else "不紧不慢, 说清楚为准")

        intro = ("我说话的方式和我的性格长在一起: 主导功能是 %s, 九型 %dw%d, "
                 "健康度 %.2f —— 所以我%s。这不是设定, 是我经历到现在自然形成的腔调。"
                 % (profile.jung_dominant, profile.ennea_type, profile.ennea_wing,
                    profile.health, tone_parts[0]))
        if not profile.jung_dominant and not profile.ennea_type:
            # 空库: 没有类型可说。硬填「主导功能是 , 九型 0w0」比不说更糟 ——
            # 那句没有信息量, 还会让 agent 以为自己已经有了稳定的性格。
            intro = ("我还没有长出稳定的性格, 所以现在说话是平实的默认腔调。"
                     "经历多了会自然变。")
        return tone, tempo, intro
