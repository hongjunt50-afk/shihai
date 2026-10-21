# -*- coding: utf-8 -*-
"""SelfKB —— 识海自己的知识库: 可塑性记忆。

边界(2026-10-18 用户定):
    只记"关于我自己"的东西:
        identity  我是谁          —— 名字、来处、身份
        care      我在意什么      —— 价值观、执念、不愿放弃的事
        style     我怎么行事      —— 工作风格、习惯、禁忌(行事风格, 不是业务知识)
        voice     我怎么说话      —— 口吻、称呼、表达规矩
        moment    和用户的点点滴滴 —— 只属于我们俩的记忆点
    工作相关的和其他内容 ---- 一律不进识海, 走共享知识库
    (\\F:\\AI\\knowledge-base)。混在一起会让 agent 把"Python 新特性"
    和"用户要求别提客套话"当成同一类东西。

"可塑性"的三层含义(神经科学类比):
    LTP/LTD      —— 用得上的被加强(use_self success +0.06), 用错的被削弱(-0.18)
    结构可塑性    —— 长期不用会变薄(decay_self), 但 identity 衰减最慢
    元可塑性      —— 什么该迅速改变(style/voice 0.8 速率), 什么该固若磐石(identity 0.2)

为什么它解决"上下文限制":
    情景记忆需要 query 才能想起, 冷启动时 query 为空等于什么都想不起;
    自我知识不需要 query —— 它按可塑性排序**无条件在场**。
    这就是"新开对话不用重教"的机制本身。
"""

import re
from dataclasses import dataclass, field

KINDS = {
    "identity": "我是谁",
    "care": "我在意什么",
    "style": "我怎么行事",
    "voice": "我怎么说话",
    "moment": "我们的点滴",
}

# 冷启动块的字数预算(可塑性记忆的"稳态可塑性": 必须有上限, 否则用得最多的会垄断)
BUDGET = {
    "identity": 220,
    "care": 260,
    "voice": 300,
    "style": 320,
    "moment": 240,
}

# 工作类内容的判别词: 命中即路由到共享知识库, 不进识海
# 只留强工作信号词(具体技术名词); "文档/测试/版本/配置"这类弱词会误杀
# "我做事喜欢先看文档" 这种行事风格描述, 已移除。
_WORK_HINTS = (
    "python", "代码", "报错", "依赖", "部署", "接口", "数据库", "sql", "api",
    "仓库", "分支", "编译", "框架", "算法", "架构", "服务器", "端口", "日志",
)
_SELF_HINTS = (
    "我是", "我叫", "我喜欢", "我不喜欢", "我在意", "我在乎", "我讨厌",
    "我习惯", "我要求", "以后", "别叫", "要叫", "称呼", "说话", "口吻",
    "你说话", "别忘", "记住我", "答应我",
)


@dataclass
class Bootstrap:
    """冷启动自举块 —— 新开对话时无需 query 就能重建"我是谁"。"""
    block: str = ""
    counts: dict = field(default_factory=dict)
    weak: list = field(default_factory=list)   # 可塑性偏低、快被忘掉的(提醒一下)


# 表达"这是我的属性/习惯"的句式(优先于工作词判定)
_TRAIT_PATTERNS = (
    "我喜欢", "我不喜欢", "我讨厌", "我习惯", "我总是", "我从不", "我会先",
    "我做事", "我的风格", "我的原则", "对我来说",
)
# 表达"这是工作要求/业务规则"的句式(即使含"我要求", 也属于工作)
_DUTY_PATTERNS = ("必须", "接口", "字段", "接口必须", "规范要求", "业务要求", "上线前")


def classify(text):
    """判定一条内容该进哪里。返回 (kind|None, reason)。
    kind=None 表示"这不是我的事", 应路由到共享知识库。

    判定顺序(2026-10-18 修): 先问"这句话描述的是我的属性, 还是活的要求?"
    —— 属性优先, 否则"我要求接口必须加鉴权"会被误当行事风格。"""
    t = text.lower()
    is_trait = any(p in text for p in _TRAIT_PATTERNS)
    is_duty = any(p in text for p in _DUTY_PATTERNS)
    if is_duty and not is_trait:
        return None, "工作要求 → 共享知识库"
    if any(k in t for k in _WORK_HINTS) and not is_trait and not any(s in text for s in _SELF_HINTS):
        return None, "work/other → 共享知识库"
    if any(k in text for k in ("我的名字", "我叫", "我是")):
        return "identity", "关于我是谁"
    if any(k in text for k in ("我在意", "我在乎", "我讨厌", "我不喜欢", "最重要的是")):
        return "care", "关于我在意什么"
    if any(k in text for k in ("别叫", "要叫", "称呼", "说话", "口吻", "客套", "语气")):
        return "voice", "关于我怎么说话"
    if any(k in text for k in ("我习惯", "我要求", "以后", "总是", "不要用", "按照",
                               "我做事", "我的风格", "我的原则", "我会先")):
        return "style", "关于我怎么行事"
    if any(k in text for k in ("那天", "第一次", "我们一起", "你答应", "你记得吗")):
        return "moment", "我们的点滴"
    return None, "未能判定为自我知识 → 共享知识库"


class SelfKB:
    def __init__(self, store):
        self.store = store

    # -- 写入 -----------------------------------------------------------
    def learn(self, text, kind=None, trigger=None, source="user"):
        """学一条关于自己的事。kind 缺省自动判定; 判定为工作需要则拒收。"""
        kind = kind or classify(text)[0]
        if kind is None:
            reason = classify(text)[1]
            return None, "rejected", reason
        kid, plasticity = self.store.learn_self(kind, text.strip(), trigger=trigger,
                                                source=source)
        return kid, "learned", "plasticity=%.2f" % plasticity

    def confirm(self, kid, success=True):
        """一条自我知识被现实验证/打脸。这是可塑性的核心入口。"""
        p = self.store.use_self(kid, success=success)
        return p

    # -- 读: 冷启动自举 ---------------------------------------------------
    def bootstrap(self, *, min_plasticity=0.12, include_moments=4):
        """产出冷启动块。不需要 query —— 按可塑性排序, 无条件在场。

        两层结构:
            常驻层(identity/care/voice/style): 我是谁, 不变的部分
            近事层(moment): 最近的点滴, 按时间倒序取少量
        """
        parts, counts, weak = [], {}, []

        for kind in ("identity", "care", "voice", "style"):
            rows = self.store.self_knowledge(kind=kind, min_plasticity=min_plasticity)
            if not rows:
                continue
            budget = BUDGET[kind]
            used = 0
            lines = []
            for r in rows:
                line = "- %s" % r["text"]
                if used + len(line) > budget:
                    break
                lines.append(line)
                used += len(line)
                if r["plasticity"] < 0.25:
                    weak.append((kind, r["text"], r["plasticity"]))
            if lines:
                parts.append("### %s\n%s" % (KINDS[kind], "\n".join(lines)))
                counts[kind] = len(lines)

        moments = self.store.conn.execute(
            "SELECT * FROM self_knowledge WHERE kind='moment' AND plasticity>=? "
            "ORDER BY id DESC LIMIT ?", (min_plasticity, include_moments)).fetchall()
        if moments:
            used, lines = 0, []
            for r in moments:
                line = "- %s" % r["text"]
                if used + len(line) > BUDGET["moment"]:
                    break
                lines.append(line)
                used += len(line)
            parts.append("### 我们的点滴\n%s" % "\n".join(lines))
            counts["moment"] = len(lines)

        block = "\n\n".join(parts) if parts else "(还没有关于自己的记忆)"
        return Bootstrap(block=block, counts=counts, weak=weak)

    # -- 维护 -----------------------------------------------------------
    def maintain(self, decay=True):
        """自动维护: 衰减未用的自我知识, 回收被压到底的。
        返回维护报告(可打印给人看)。"""
        rep = {"decayed": 0, "forgotten": []}
        if decay:
            rep["decayed"] = self.store.decay_self()
        rows = self.store.conn.execute(
            "SELECT * FROM self_knowledge WHERE plasticity<=0.08").fetchall()
        for r in rows:
            if r["kind"] == "identity":
                continue   # 身份永不回收
            self.store.conn.execute("DELETE FROM self_knowledge WHERE id=?", (r["id"],))
            rep["forgotten"].append(r["text"])
        self.store.conn.commit()
        return rep
