# -*- coding: utf-8 -*-
"""识海 (Shihai) — 会遗忘、会沉淀、会长出人格的 agent 记忆层。

设计前提: 人格不是被"设定"的, 是被"记住"的。
普通记忆随时间和不召回而衰减消失; 少数记忆因为情绪强度、
反复召回、自我相关或被标记为转折点而升格为核心记忆;
核心记忆不参与遗忘, 并且是人格卡( trait 向量 + 自述)的唯一来源。

分层:
    raw_log    原始日志   —— 永不删除, 用于回溯/纠错/重放
    events     情景记忆   —— 一条条具体经历, 会衰减
    semantic   语义记忆   —— 从重复情景里蒸馏出的稳定事实
    relation   关系记忆   —— 对每个人的信任/边界/承诺
    task       任务记忆   —— 目标、进度、未完成事项
    working    工作状态   —— 当前会话的临时上下文
    persona    人格快照   —— 由核心记忆推导, 可 diff 看人格漂移
"""

from .store import Store, connect
from .appraise import Appraisal, appraise
from .ingest import Ingestor, Observation, SplitEvent
from .recall import RecallEngine, Cue, Spotlight
from .lifecycle import Lifecycle, LifecycleReport
from .persona import PersonaEngine, PersonaCard
from .typologies import TypologyEngine, TypologyProfile, JUNG_PATHWAYS, ENNEA
from .pgraph import PersonalityGraphEngine, PersonaGraph
from .voice import VoiceEngine, VoiceCard
from .freemode import FreeMode
from .kb import SelfKB, Bootstrap, KINDS as SELF_KINDS
from .diary import DiaryEngine
from .wiki import Wiki
from .viz import render as render_viz

__all__ = [
    "Store", "connect",
    "Appraisal", "appraise",
    "Ingestor", "Observation", "SplitEvent",
    "RecallEngine", "Cue", "Spotlight",
    "Lifecycle", "LifecycleReport",
    "PersonaEngine", "PersonaCard",
    "TypologyEngine", "TypologyProfile", "JUNG_PATHWAYS", "ENNEA",
    "PersonalityGraphEngine", "PersonaGraph",
    "VoiceEngine", "VoiceCard",
    "FreeMode",
    "SelfKB", "Bootstrap", "SELF_KINDS",
    "DiaryEngine", "Wiki", "render_viz",
]
__version__ = "0.7.1"
