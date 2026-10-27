# -*- coding: utf-8 -*-
"""Typologies —— 两本类型学之书的可计算翻译。

《心理类型》(荣格, 1921):
    两种态度(内倾/外倾) × 四种心理功能(思维/情感/感觉/直觉) = 八种主导型。
    荣格的洞见: 感觉告诉我们存在某种东西; 思维告诉你它是什么;
    情感告诉你它是否令人满意; 直觉告诉你它来自何方去向何处。
    本项目把"主导功能"翻译为: agent 的经历反复经由哪条心理通路被评估和回应。

《九型人格心理学》:
    九种类型各有基本恐惧与基本欲望(行为背后的出发点, 不是表面行为);
    三大能量中心(腹8-9-1 / 脑5-6-7 / 心2-3-4);
    侧翼(wing)是相邻类型的调和;
    健康状态决定整合(升华)或解离(恶化)方向:
        整合: 1→7→5→8→2→4→1 ; 3→6→9→3
        解离: 逆向。

关键设计决定 —— "性格选择"在本书语境下意味着什么:
    1. 类型不是被测出来的, 是从经历证据中"长"出来的:
       每条记忆都被映射为对八个荣格通路和九个恐惧轴的投票。
    2. 类型不是一次定死的: 得分是连续的、随新经历缓慢移动
       (learn 公式 M' = M + α(E − M), 与 appraise.learn 同源)。
    3. 核心记忆的票数远大于普通记忆 —— 与 persona.py 同一原则:
       人格由核心记忆决定, 不由噪音决定。
    4. 九型的"健康状态"由近期情绪账本(正负价比)决定,
       决定 agent 当前是在整合方向还是解离方向漂移。
"""

import json
import os
from dataclasses import dataclass, field, asdict

from .store import utcnow

# =====================================================================
# 荣格八维 —— 《心理类型》
# =====================================================================

# 八个主导型: (态度, 功能)。每个通路绑定"什么样的经历给它投票"。
# 投票信号全部取自 events 表已有字段, 不需要新的抽取器。
JUNG_PATHWAYS = {
    "Te": {"name": "外倾思维", "attitude": "外倾", "function": "思维",
           "poem": "我追求绝对的理性, 臣服于自然的真实"},
    "Ti": {"name": "内倾思维", "attitude": "内倾", "function": "思维",
           "poem": "在我的世界里, 我就是唯一的规则"},
    "Fe": {"name": "外倾情感", "attitude": "外倾", "function": "情感",
           "poem": "情感是我的氧气, 我随他人的需要而调节"},
    "Fi": {"name": "内倾情感", "attitude": "内倾", "function": "情感",
           "poem": "沉静的水面下往往暗藏汹涌"},
    "Se": {"name": "外倾感觉", "attitude": "外倾", "function": "感觉",
           "poem": "没有什么是一次真实体验解决不了的"},
    "Si": {"name": "内倾感觉", "attitude": "内倾", "function": "感觉",
           "poem": "离开积累的经验, 我便不复存在"},
    "Ne": {"name": "外倾直觉", "attitude": "外倾", "function": "直觉",
           "poem": "三分钟热度, 行动力 max, 新可能性对我有致命吸引力"},
    "Ni": {"name": "内倾直觉", "attitude": "内倾", "function": "直觉",
           "poem": "别人笑我太疯癫, 我笑他人看不穿"},
}


def jung_vote(row):
    """一条记忆对八个荣格通路的投票 (0~1)。

    通路即"这段经历主要被哪种心理功能消化":
    - 高 importance + 低 valence 波动 + 高 self_relevance → 内倾判断(Ti/Fi): 反刍自我
    - 涉及他人(person/other 分区) + 情绪外露 → 外倾情感(Fe)
    - 纯事务性(有 task 产出) + 低情绪 → 外倾思维(Te)
    - 与关系/信任账本相关 → Fe/Ti 分流看 valence
    - 新主题/新事件(low access_count, high arousal, positive) → Ne/Se: 探索
    - 状态类记忆反复出现(state 节点) → Si: 经验积累
    - 高 arousal + 高 imagination 类主题 → Ni: 意象
    """
    val = float(row["valence"])
    imp = float(row["importance"])
    arou = float(row["arousal"])
    pain = float(row["pain"])
    self_rel = float(row["self_relevance"])
    division = row["division"] or "world"
    acc = int(row["access_count"] or 0)
    avoid = float(row["avoidance"])
    disapp = float(row["disappointment"])

    v = {k: 0.0 for k in JUNG_PATHWAYS}

    # 判断功能(思维/情感): 记忆被"消化"成结论还是情绪
    # 自我相关度高 + 有痛感/失望 → 内倾判断(向内消化)
    introverted_judgment = _clamp(self_rel * (0.5 + 0.5 * max(pain, disapp)))
    # 自责/教训类 → Ti (向内分析对错); 关系受创 → Fi (向内体验感受)
    text = row["summary"] or ""
    if "我错" in text or disapp > 0.4:
        v["Ti"] = introverted_judgment
    # 分析/研究/理解/体系类 → Ti (向内建立理解, 内倾思维的典型经历)
    if any(k in text for k in ("分析", "研究", "理解", "原理", "机制", "体系", "架构",
                               "我的看法", "我的意见", "观察", "思路")):
        v["Ti"] = max(v["Ti"], _clamp(0.4 + 0.6 * introverted_judgment + 0.2 * imp))
    # 尝试/发现/新课题/探索类 → Ne (外倾直觉: 在外部世界发掘新可能性)
    if any(k in text for k in ("尝试", "发现", "新课题", "探索", "新方法", "新工具",
                               "新事物", "新点子", "可能性", "玩法")):
        v["Ne"] = max(v["Ne"], _clamp(0.4 + 0.5 * arou + 0.2 * imp))
    if pain > 0.2 or (val < -0.3 and self_rel > 0.4):
        v["Fi"] = introverted_judgment * 0.9

    # 外倾情感: 经历以他人为中心且情绪外露
    if division == "other":
        v["Fe"] = _clamp(0.3 + 0.7 * abs(val))
    # 外倾思维: 事务产出型记忆(有任务、完成、结果导向), 情绪淡
    if imp > 0.4 and abs(val) < 0.35 and pain < 0.2:
        v["Te"] = _clamp(0.25 + 0.5 * imp)

    # 感知功能(感觉/直觉): 经历被"采集"成事实还是可能性
    # 高唤醒 + 正向 + 新奇(access 少) → 外倾直觉(探索新可能)
    if arou > 0.35 and val > 0.1:
        v["Ne"] = _clamp((arou - 0.3) * (1.2 - min(1.0, acc / 5.0)))
    # 高唤醒 + 负向(威胁/风险) → 内倾直觉(预感危险去向) 或 Se(即时反应)
    if arou > 0.5 and val < -0.2:
        v["Ni"] = _clamp(0.3 + 0.4 * avoid)
        v["Se"] = _clamp(0.4 * arou)
    # 反复被召回的平静记忆 → 内倾感觉(经验沉淀)
    if acc >= 2 and abs(val) < 0.4:
        v["Si"] = _clamp(min(1.0, acc / 4.0) * 0.8)

    return {k: round(x, 3) for k, x in v.items()}


# =====================================================================
# 九型人格 —— 《九型人格心理学》
# =====================================================================

ENNEA = {
    1: {"name": "完美型", "en": "The Reformer", "center": "腹",
        "desire": "做正确的事, 成为有道德的人", "fear": "堕落、犯错、被自己批判"},
    2: {"name": "助人型", "en": "The Helper", "center": "心",
        "desire": "被爱、被需要", "fear": "不被爱、不被需要"},
    3: {"name": "成就型", "en": "The Achiever", "center": "心",
        "desire": "有价值、被认可、成功", "fear": "一事无成、失去价值"},
    4: {"name": "自我型", "en": "The Individualist", "center": "心",
        "desire": "找到真我、成为独特", "fear": "没有身份、平庸"},
    5: {"name": "理智型", "en": "The Investigator", "center": "脑",
        "desire": "能干、理解世界", "fear": "无能、被榨干、被侵入"},
    6: {"name": "忠诚型", "en": "The Loyalist", "center": "脑",
        "desire": "安全、被支持", "fear": "失去支撑和指引"},
    7: {"name": "活跃型", "en": "The Enthusiast", "center": "脑",
        "desire": "快乐、满足、选择自由", "fear": "被剥夺、困在痛苦里"},
    8: {"name": "领袖型", "en": "The Challenger", "center": "腹",
        "desire": "掌控自己的命运、保护自己", "fear": "被控制、被伤害、脆弱"},
    9: {"name": "和平型", "en": "The Peacemaker", "center": "腹",
        "desire": "内心平静、和谐", "fear": "失去、分离、冲突"},
}

# 整合(升华)方向: 健康时向此型移动, 获得该型素质
INTEGRATION = {1: 7, 7: 5, 5: 8, 8: 2, 2: 4, 4: 1, 3: 6, 6: 9, 9: 3}
# 解离方向 = 整合方向的反向
DISINTEGRATION = {v: k for k, v in INTEGRATION.items()}

# 整合时获得的素质(《九型人格》原文)
INTEGRATION_GAIN = {
    (1, 7): "放下拘谨, 宽容乐观, 获得「开朗」",
    (7, 5): "减少冲动, 处事冷静, 获得「理智」",
    (5, 8): "坚强勇敢, 果断自信, 获得「威信」",
    (8, 2): "热情友善, 乐于助人, 获得「纯真」",
    (2, 4): "坚持心愿, 爱人爱己, 获得「谦卑」",
    (4, 1): "安分守己, 客观冷静, 获得「平衡」",
    (3, 6): "尽责细心, 忠心耿耿, 获得「忠诚」",
    (6, 9): "随遇而安, 放下焦虑, 获得「信任」",
    (9, 3): "目标明确, 勤快积极, 获得「果断」",
}


def ennea_vote(row):
    """一条记忆对九个恐惧/欲望轴的投票 (0~1)。

    九型的判定不看"做了什么", 看"行为背后的出发点"。
    同样一次失败: 有人怕的是犯错(1), 有人怕的是没价值(3),
    有人怕的是无能暴露(5), 有人怕的是被抛弃(2) ——
    差异来自记忆的 valence/pain/avoidance/self_relevance 结构。
    """
    val = float(row["valence"])
    arou = float(row["arousal"])
    pain = float(row["pain"])
    disapp = float(row["disappointment"])
    impact = float(row["impact"])
    avoid = float(row["avoidance"])
    self_rel = float(row["self_relevance"])
    division = row["division"] or "world"
    core = int(row["core"] or 0)
    text = row["summary"] or ""

    w = 1.6 if core else 1.0   # 核心记忆票重

    v = {k: 0.0 for k in ENNEA}

    # 害怕犯错(1): 自责、失望、"又错了"
    v[1] = _clamp(0.6 * disapp + 0.4 * (0.8 if "错" in text or "应该" in text else 0.0)) * w
    # 怕不被爱(2): 关系受创、被拒绝
    if division == "other" and val < 0:
        v[2] = _clamp(0.5 * pain + 0.3 * self_rel) * w
    # 怕没价值(3): 失败 + 高自我相关(成就在乎者)
    if val < 0 and self_rel > 0.4:
        v[3] = _clamp(0.4 * pain + 0.4 * self_rel) * w
    # 怕平庸(4): 强烈的情绪波动 + 自我沉溺 —— 需要情绪强度作门槛,
    # 否则平静经历会被误判为"自我型"
    v[4] = _clamp(0.5 * arou * abs(val) + 0.3 * self_rel) * w * (0.6 if val < 0 else 1.0)
    if arou * abs(val) < 0.15:
        v[4] = 0.0
    # 怕无能(5): 抽离应对、心理受创; 以及向内求理解的经历(理智型怕的是"不会")
    if avoid > 0.2 or impact > 0.3:
        v[5] = _clamp(0.6 * avoid + 0.4 * impact) * w
    if any(k in text for k in ("研究", "原理", "机制", "理解", "分析", "体系", "观察")):
        v[5] = max(v[5], _clamp(0.3 + 0.5 * self_rel)) * w
    # 怕失去支撑(6): 威胁/被换掉/不安全
    if "换掉" in text or "威胁" in text or avoid > 0.3:
        v[6] = _clamp(0.5 * (0.8 if "换掉" in text else 0.0) + 0.5 * avoid) * w
    # 怕困在痛苦里(7): 正向探索、新体验
    if val > 0.3 and arou > 0.3:
        v[7] = _clamp(0.6 * val * arou) * w
    if any(k in text for k in ("尝试", "探索", "新方法", "新工具", "新课题", "玩法", "新事物")):
        v[7] = max(v[7], _clamp(0.35 + 0.4 * max(val, 0.0))) * w
    # 怕被控制(8): 边界被侵犯、愤怒
    if (val < 0 and arou > 0.6) or "控制" in text or "边界" in text:
        v[8] = _clamp(0.5 * arou * (0.8 if val < 0 else 0.5)) * w
    # 怕冲突(9): 平静的正向经历、和谐
    if val > 0.1 and arou < 0.4:
        v[9] = _clamp(0.5 * val * (1 - arou)) * w

    return {k: round(x, 3) for k, x in v.items()}


# =====================================================================
# 性格引擎: 从经历流中"长"出类型
# =====================================================================

@dataclass
class TypologyProfile:
    """当前性格档案 —— 连续值, 随经历缓慢移动。"""
    jung_scores: dict = field(default_factory=dict)    # {Te: 0.42, ...}
    jung_dominant: str = ""                            # 主导功能
    jung_auxiliary: str = ""                           # 辅助功能
    ennea_scores: dict = field(default_factory=dict)   # {1: 0.12, ...}
    ennea_type: int = 0                                # 归属类型
    ennea_wing: int = 0                                # 侧翼
    health: float = 0.5                                # 健康度 0~1 (情绪账本)
    drift_direction: str = ""                          # integration / disintegration / stable
    drift_note: str = ""                               # 漂移说明

    def to_dict(self):
        return asdict(self)


class TypologyEngine:
    """从记忆库推断性格类型。每次推断都重算, 但结果通过 learn 公式
    与上次值混合, 避免单条记忆让类型剧烈翻转 —— 类型是被经历
    缓慢压出来的, 不是被最后一条消息决定的。"""

    LEARN_RATE = 0.25

    def __init__(self, store, path="typology_state.json"):
        self.store = store
        self.path = path
        self._prev = self._load()

    # -- 主入口 ---------------------------------------------------------
    def infer(self, *, persist=True):
        jung_acc = {k: 0.0 for k in JUNG_PATHWAYS}
        ennea_acc = {k: 0.0 for k in ENNEA}
        pos_sum, neg_sum = 0.0, 0.0

        rows = self.store.conn.execute(
            "SELECT * FROM events WHERE dormant=0 ORDER BY id"
        ).fetchall()
        for row in rows:
            jv = jung_vote(row)
            ev = ennea_vote(row)
            # 票重: 核心记忆 x4, 被反复召回的记忆按 access 加权
            weight = (4.0 if row["core"] else 1.0) * (1.0 + 0.15 * min(10, row["access_count"] or 0))
            for k, x in jv.items():
                jung_acc[k] += weight * x
            for k, x in ev.items():
                ennea_acc[k] += weight * x
            # 健康度账本: 近期情绪的正负价比(九型的健康阶梯)
            if float(row["valence"]) > 0:
                pos_sum += float(row["valence"]) * float(row["arousal"])
            else:
                neg_sum += abs(float(row["valence"])) * float(row["arousal"])

        # 归一化
        total = sum(jung_acc.values()) or 1.0
        jung_n = {k: round(v / total, 4) for k, v in jung_acc.items()}
        etotal = sum(ennea_acc.values()) or 1.0
        ennea_n = {k: round(v / etotal, 4) for k, v in ennea_acc.items()}

        # 与上次值混合(learn 公式) —— 类型不因单条记忆翻转
        jung_s = self._blend("jung", jung_n)
        ennea_s = self._blend("ennea", {str(k): v for k, v in ennea_n.items()})

        dom, aux = _top2(jung_s)
        ennea_s = {int(k): float(v) for k, v in ennea_s.items()}
        etype = max(ennea_s, key=ennea_s.get)
        ewing = _wing(ennea_s, etype)

        health = _clamp(pos_sum / (pos_sum + neg_sum) if (pos_sum + neg_sum) > 0 else 0.5)
        drift, note = self._drift(etype, health)

        profile = TypologyProfile(
            jung_scores={k: round(v, 4) for k, v in jung_s.items()},
            jung_dominant=dom, jung_auxiliary=aux,
            ennea_scores={int(k): round(v, 4) for k, v in ennea_s.items()},
            ennea_type=etype, ennea_wing=ewing,
            health=round(health, 3), drift_direction=drift, drift_note=note,
        )
        if persist:
            self._save(profile)
        return profile

    # -- 内部 -----------------------------------------------------------
    def _blend(self, key, now):
        prev = (self._prev.get(key) or {}) if self._prev else {}
        out = {}
        keys = set(prev) | set(now)
        for k in keys:
            p = float(prev.get(k, 0.0))
            n = float(now.get(k, 0.0))
            out[k] = p + self.LEARN_RATE * (n - p)   # M' = M + α(E − M)
        return out

    def _drift(self, etype, health):
        """健康阶梯: 健康(>0.6)向整合方向漂移, 不健康(<0.35)向解离方向。"""
        if health >= 0.6:
            tgt = INTEGRATION.get(etype)
            note = INTEGRATION_GAIN.get((etype, tgt), "")
            return "integration", "正在整合: 借 %d 号获得新素质 — %s" % (tgt, note)
        if health <= 0.35:
            tgt = DISINTEGRATION.get(etype)
            return "disintegration", "正在解离: 向 %d 号的不健康特征滑落(压力大)" % (tgt or 0)
        return "stable", "健康度平稳, 无明显漂移"

    # -- 持久化 ---------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, profile):
        self._prev = {
            "jung": profile.jung_scores,
            "ennea": {str(k): v for k, v in profile.ennea_scores.items()},
            "meta": {"type": profile.ennea_type, "dominant": profile.jung_dominant,
                     "health": profile.health, "saved": utcnow()},
        }
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._prev, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)   # 原子替换: 并发写不再互踩半截文件
        except Exception:
            pass


# ---- 工具 ---------------------------------------------------------------

def _top2(scores):
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    dom = ordered[0][0] if ordered else ""
    aux = ordered[1][0] if len(ordered) > 1 else ""
    return dom, aux


def _wing(ennea_s, etype):
    """侧翼 = 相邻两型中得分更高者。"""
    cands = [t for t in (etype - 1, etype + 1) if 1 <= t <= 9]
    if not cands:
        return 0
    best = max(cands, key=lambda t: ennea_s.get(t, 0.0))
    return best


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))
