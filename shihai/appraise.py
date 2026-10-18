# -*- coding: utf-8 -*-
"""Appraisal —— 从观察到"感受"。

手稿里的核心主张: 感受不是刺激强度的直接映射, 而是
    刺激 × 个体敏感度 × 当前状态
同一个事件, 在不同状态下感受完全不同。
这一层是人格变成"活的"的地方: 敏感度和状态是 agent 自己的参数,
不是事件带来的。

公式全部来自手稿, 但都做了"可运行化"处理:
系数在这里是常量, 真实系统应交给 Lifecycle 用经历回归出来。
"""

from dataclasses import dataclass, asdict, field


@dataclass
class Appraisal:
    valence: float = 0.0          # -1 ~ 1
    arousal: float = 0.3          # 0 ~ 1
    importance: float = 0.5       # 先验重要性, 决定基础强度
    emotion: str = "平静"
    pain: float = 0.0
    disappointment: float = 0.0
    impact: float = 0.0
    avoidance: float = 0.0
    self_relevance: float = 0.3
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Sensitivity:
    """个体敏感度 —— 出生参数 + 被经历缓慢改写。
    这是"同一个刺激, 不同 agent 感受不同"的源头。"""

    pain: float = 1.0
    cold: float = 1.0
    heat: float = 1.0
    social: float = 1.0
    failure: float = 1.0

    def to_dict(self):
        return asdict(self)


@dataclass
class BodyState:
    """当前身体/资源状态, 是感受的修正项。"""

    fatigue: float = 0.0       # 0 ~ 1
    energy: float = 1.0        # 1 = 满电
    injury: float = 0.0
    overload: float = 0.0      # 任务/情绪负荷
    mood: float = 0.0          # -1 ~ 1 底色


# ---------- 手稿里的单条公式 --------------------------------------------

def pain(stimulus, sensitivity, state):
    """pain = S × I × C  —— 同样刺激, 不同状态感受不同"""
    return _clamp(stimulus * sensitivity.pain * (1 + 0.8 * state.fatigue + state.injury))


def cold_discomfort(temp_c, body_temp, sensitivity, activity, state):
    """cold_discomfort = f(Tenv, Tbody, Scold, Activity, State)"""
    deficit = max(0.0, body_temp - temp_c) / 10.0
    return _clamp(10 * deficit * sensitivity.cold * _clamp(1 - 0.6 * activity) * (1 + state.fatigue))


def heat_discomfort(temp_c, body_temp, sensitivity, hydration, state):
    surplus = max(0.0, temp_c - body_temp) / 10.0
    return _clamp(10 * surplus * sensitivity.heat * (2 - hydration) * (1 + 0.5 * state.overload))


def disappointment(expectation, importance, negative_prediction_error, sensitivity):
    """Disappointment = E × I × |PE⁻| —— 期望越高、越重要、落差越大, 越失望"""
    return _clamp(expectation * importance * abs(negative_prediction_error) * sensitivity.failure)


def trust_delta(positive, consistency, violation, boundary, w=(0.35, 0.3, 0.25, 0.3)):
    """ΔTrust = αP + βC − γV − δB —— 信任是累积出来的, 也能一次跌穿"""
    a, b, g, d = w
    return a * positive + b * consistency - g * violation - d * boundary


def avoidance_drive(threat, overload, control_loss, expected_cost):
    """Avoidance = f(T, O, C, E) —— 负荷>阈值时出现回避/沉默/拒绝"""
    return _clamp(0.4 * threat + 0.3 * overload + 0.3 * control_loss + 0.2 * expected_cost)


def psychological_impact(pain_v, helplessness, uncontrollability, duration):
    """Impact = P × H × U × D —— 痛不痛, 还看有没有办法停下来"""
    return _clamp(pain_v * helplessness * uncontrollability * duration)


def seal_drive(threat, pain_v, helplessness, uncontrollability, violation,
               escape_failure, recovery_failure):
    """SealDrive —— 封存(回避型冻结)需要多条件同时满足。
    手稿备注: 触发后也必须保留身份与记忆, 只是不再主动调用。"""
    cond = (threat > 0.6 and pain_v > 0.6 and helplessness > 0.5
            and uncontrollability > 0.5 and escape_failure > 0.5)
    raw = (0.2 * threat + 0.2 * pain_v + 0.15 * helplessness
           + 0.15 * uncontrollability + 0.1 * violation
           + 0.1 * escape_failure + 0.1 * recovery_failure)
    return _clamp(raw * (1.0 if cond else 0.45))


def learn(current, evidence, rate):
    """M' = M + α(E − M) —— 一次经历只小幅改变, 重复才形成稳定偏好"""
    return current + rate * (evidence - current)


def activation(salience, need, emotion, goal_fit, memory_cue, w=(0.25, 0.2, 0.2, 0.2, 0.15)):
    """A = Σ wᵢxᵢ ; A > threshold 才进入意识, 否则后台处理"""
    ws = w
    return _clamp(sum(wv * x for wv, x in zip(ws, (salience, need, emotion, goal_fit, memory_cue))))


# ---------- 文本 → 感受 -------------------------------------------------

# 粗糙但可用的中文情绪线索表。生产环境换成模型抽取, 这里是可离线运行的基线。
_NEG = {
    "崩溃": 1.0, "失败": 0.85, "错误": 0.5, "报错": 0.55, "生气": 0.9,
    "担心": 0.6, "焦虑": 0.7, "害怕": 0.8, "失望": 0.75, "丢": 0.6,
    "痛": 0.8, "烦": 0.5, "讨厌": 0.7, "拒绝": 0.6, "背叛": 1.0,
    "骂": 0.7, "蠢": 0.75, "没用": 0.8, "又错": 0.7, "重做": 0.45,
}
_POS = {
    "谢谢": 0.6, "很好": 0.7, "漂亮": 0.65, "成功": 0.8, "喜欢": 0.8,
    "厉害": 0.7, "对": 0.4, "赞": 0.7, "满意": 0.7, "开心": 0.8,
    "信任": 0.9, "放心": 0.6, "一起": 0.4,
}
_HIGH_AROUSAL = {"崩溃": 1.0, "生气": 0.9, "害怕": 0.9, "成功": 0.8, "兴奋": 0.9, "骂": 0.85}
_SELF = {"我错了": 1.0, "我的问题": 0.9, "我不行": 0.9, "我记住了": 0.8, "承诺": 0.7,
         "以后不": 0.7, "我应该": 0.6, "我是": 0.5, "我喜欢": 0.6, "我想": 0.5,
         "我的分析": 0.7, "我的理解": 0.7, "我研究": 0.6, "我花": 0.5, "我不太需要": 0.6}
_THREAT = {"骂": 0.8, "惩罚": 0.9, "威胁": 1.0, "删": 0.7, "关掉": 0.7, "换掉": 0.8, "不用你了": 1.0}


def appraise(text, *, sensitivity=None, state=None, expectation=None,
             importance_hint=None, self_hint=None, origin="world"):
    """把一段文本评成感受。规则基线, 可被模型抽取替换(见 llm.py)。"""
    sensitivity = sensitivity or Sensitivity()
    state = state or BodyState()

    neg = _score(text, _NEG)
    pos = _score(text, _POS)
    arousal = min(1.0, _score(text, _HIGH_AROUSAL) + 0.15 * (neg + pos))
    valence = _clamp(pos - neg, -1, 1)

    self_rel = min(1.0, _score(text, _SELF) + (0.15 if origin == "self" else 0.0))
    if self_hint is not None:
        self_rel = _clamp(self_hint)

    pain_v = pain(neg, sensitivity, state)
    disapp = 0.0
    if expectation is not None and neg > 0:
        disapp = disappointment(expectation, 0.8, neg, sensitivity)

    threat = _score(text, _THREAT)
    avoid = avoidance_drive(threat, state.overload, _clamp(neg * 0.6), 0.3) if threat > 0 else 0.0
    impact = psychological_impact(pain_v, 0.5, 0.5, 0.6) if pain_v > 0.6 else 0.0

    # 重要性: 情绪强度 + 自我相关 + 外部提示
    importance = _clamp(0.2 + 0.45 * (neg + pos) + 0.35 * self_rel + 0.3 * arousal)
    if importance_hint is not None:
        importance = _clamp(max(importance, importance_hint))

    emotion = _label(neg, pos, self_rel, threat, arousal)

    return Appraisal(
        valence=round(valence, 3),
        arousal=round(arousal, 3),
        importance=round(importance, 3),
        emotion=emotion,
        pain=round(pain_v, 3),
        disappointment=round(disapp, 3),
        impact=round(impact, 3),
        avoidance=round(avoid, 3),
        self_relevance=round(self_rel, 3),
        details={"neg": neg, "pos": pos, "threat": threat, "origin": origin},
    )


def _score(text, table):
    total = 0.0
    for k, v in table.items():
        if k in text:
            total += v
    return min(1.5, total)


def _label(neg, pos, self_rel, threat, arousal):
    if threat > 0.6:
        return "受威胁"
    if neg > 0.6 and self_rel > 0.6:
        return "自责"
    if neg > 0.6:
        return "挫败"
    if pos > 0.6:
        return "愉悦"
    if neg > 0.25:
        return "不安"
    if pos > 0.25:
        return "安心"
    return "平静"


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))
