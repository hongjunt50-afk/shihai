# -*- coding: utf-8 -*-
"""SQLite 持久层。单文件数据库, 纯标准库, 可直接拷走。"""

import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
PRAGMA journal_mode = WAL;

-- 原始日志: 只追加, 永不删除。所有派生记忆都能从它重建。
CREATE TABLE IF NOT EXISTS raw_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT NOT NULL,
    session   TEXT,
    modality  TEXT DEFAULT 'text',
    content   TEXT NOT NULL,
    meta      TEXT,
    consumed  INTEGER DEFAULT 0
);

-- 情景记忆: 一次具体经历。strength 会衰减, core=1 时豁免。
CREATE TABLE IF NOT EXISTS events (
    id             INTEGER PRIMARY KEY,
    raw_id         INTEGER NOT NULL REFERENCES raw_log(id),
    ts             TEXT NOT NULL,
    summary        TEXT NOT NULL,
    valence        REAL DEFAULT 0,      -- -1 负 ~ +1 正
    arousal        REAL DEFAULT 0.3,    -- 0 平静 ~ 1 激烈
    importance     REAL DEFAULT 0.5,    -- 0.05 ~ 1 先验重要性
    emotion        TEXT DEFAULT '平静',
    pain           REAL DEFAULT 0,
    disappointment REAL DEFAULT 0,
    impact         REAL DEFAULT 0,      -- 心理伤害 (可累积成创伤)
    avoidance      REAL DEFAULT 0,      -- 回避驱力
    self_relevance REAL DEFAULT 0.3,    -- 与"我是谁"的相关度
    division       TEXT DEFAULT 'self', -- self / world / other
    layer          TEXT DEFAULT 'scene',
    base_strength  REAL NOT NULL,
    strength       REAL NOT NULL,
    access_count   INTEGER DEFAULT 0,
    last_access    TEXT,
    core           INTEGER DEFAULT 0,
    core_score     REAL DEFAULT 0,
    promoted_at    TEXT,
    dormant        INTEGER DEFAULT 0,   -- 淡化到不可召回, 但未删除
    created        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_strength ON events(strength);
CREATE INDEX IF NOT EXISTS idx_events_core ON events(core);

-- 记忆节点: 人物/任务/主题/状态/地点/物件。事件是枢纽, 节点是入口。
CREATE TABLE IF NOT EXISTS nodes (
    id    INTEGER PRIMARY KEY,
    kind  TEXT NOT NULL,   -- person/task/theme/state/location/object/commitment
    key   TEXT NOT NULL,   -- 归一化 key
    label TEXT NOT NULL,   -- 展示名
    attrs TEXT,
    created TEXT NOT NULL,
    UNIQUE(kind, key)
);

-- 关联网络: 记忆不是孤岛, 是一张网。
CREATE TABLE IF NOT EXISTS edges (
    id     INTEGER PRIMARY KEY,
    src    TEXT NOT NULL,   -- "event:12" / "node:7" / "semantic:3"
    dst    TEXT NOT NULL,
    rel    TEXT NOT NULL,   -- involved/raised/produced/about/caused/by/promised_to...
    weight REAL DEFAULT 1.0,
    note   TEXT,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

-- 语义记忆: 从重复情景蒸馏出的稳定事实, 几乎不衰减。
CREATE TABLE IF NOT EXISTS semantic (
    id         INTEGER PRIMARY KEY,
    claim      TEXT NOT NULL,
    subject    TEXT,
    confidence REAL DEFAULT 0.6,
    sources    TEXT,         -- json [event_id...]
    hits       INTEGER DEFAULT 1,
    strength   REAL DEFAULT 0.9,
    created    TEXT NOT NULL,
    updated    TEXT NOT NULL
);

-- 关系记忆: 对每个人的信任账本。
CREATE TABLE IF NOT EXISTS relation (
    node_id      INTEGER PRIMARY KEY REFERENCES nodes(id),
    trust        REAL DEFAULT 0.5,
    intimacy     REAL DEFAULT 0.3,
    boundary_hit INTEGER DEFAULT 0,
    promise_up   INTEGER DEFAULT 0,
    promise_broken INTEGER DEFAULT 0,
    note         TEXT,
    updated      TEXT
);

-- 任务记忆
CREATE TABLE IF NOT EXISTS task (
    id      INTEGER PRIMARY KEY,
    title   TEXT NOT NULL,
    status  TEXT DEFAULT 'open',   -- open/done/abandoned
    progress REAL DEFAULT 0,
    due     TEXT,
    node_id INTEGER,
    event_id INTEGER,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);

-- 工作状态: 会话级临时上下文, 会话结束即归档。
CREATE TABLE IF NOT EXISTS working (
    id      INTEGER PRIMARY KEY,
    session TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT,
    updated TEXT NOT NULL,
    UNIQUE(session, key)
);

-- 召回日志: 谁在什么时候因为什么被想起。这是心光竞争的实证记录。
CREATE TABLE IF NOT EXISTS recall_log (
    id    INTEGER PRIMARY KEY,
    ts    TEXT NOT NULL,
    query TEXT NOT NULL,
    cues  TEXT,
    hits  TEXT
);

-- 人格快照: 只由核心记忆推导, diff 两次快照 = 人格漂移
CREATE TABLE IF NOT EXISTS persona_snapshot (
    id         INTEGER PRIMARY KEY,
    ts         TEXT NOT NULL,
    traits     TEXT NOT NULL,
    card       TEXT NOT NULL,
    core_ids   TEXT NOT NULL,
    created    TEXT NOT NULL
);

-- 检索索引: 事件的二字组倒排(2026-10-19 优化1)。
-- 不用 FTS5 是因为中文没有词边界, unicode61 只能切整段;
-- 二字组倒排更准, 且纯 SQL 就能做 O(命中) 而不是 O(n) 全表。
CREATE TABLE IF NOT EXISTS event_tokens (
    token   TEXT NOT NULL,
    event_id INTEGER NOT NULL,
    PRIMARY KEY(token, event_id)
);
CREATE INDEX IF NOT EXISTS idx_tok_event ON event_tokens(event_id);

-- 日记: 一天一篇第一人称叙述。这是"知道"变"经历过"的关键层。
-- events 存事实(去了公园), diary 存当时的感受与细节(长椅上的三花猫、笑到停不下来)。
-- 冷启动时读日记 = 以第一人称重新经历一次, 而不是被告知发生了什么。
CREATE TABLE IF NOT EXISTS diary (
    id        INTEGER PRIMARY KEY,
    day       TEXT NOT NULL,          -- YYYY-MM-DD
    text      TEXT NOT NULL,          -- 第一人称正文
    felt      TEXT,                   -- 感受锚点: 一句能被重新唤起的话
    details   TEXT,                   -- 感官细节(可被 LLM 富化)
    mood      TEXT,                   -- 当天底色
    warmth    REAL DEFAULT 0,         -- 当天好感增量(+/-)
    event_ids TEXT,                   -- 来源事件(可追溯)
    edited    INTEGER DEFAULT 0,      -- 人手工改过(回写时保护)
    created   TEXT NOT NULL,
    updated   TEXT NOT NULL,
    UNIQUE(day)
);
CREATE INDEX IF NOT EXISTS idx_diary_day ON diary(day);

-- 关系好感: 人可管理的长期账本(截图里的"好感条")
CREATE TABLE IF NOT EXISTS warmth_ledger (
    id     INTEGER PRIMARY KEY,
    day    TEXT NOT NULL,
    delta  REAL NOT NULL,
    reason TEXT,
    created TEXT NOT NULL
);

-- 自我知识库: 只存"关于我自己"的东西, 不存工作知识(那些去共享知识库)。
-- plasticity 就是可塑性记忆的核心: 稳固度随使用而变, 不是内容随使用而变。
CREATE TABLE IF NOT EXISTS self_knowledge (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,     -- identity/care/style/voice/moment
    text       TEXT NOT NULL,
    trigger    TEXT,              -- 何时该想起这条(关键词/情境)
    plasticity REAL DEFAULT 0.5,  -- 0.05 ~ 1.0 稳固度(LTP 涨 / LTD 落)
    uses       INTEGER DEFAULT 0,
    wins       INTEGER DEFAULT 0,
    losses     INTEGER DEFAULT 0,
    source     TEXT DEFAULT 'user',  -- user/self/reflection
    last_used  TEXT,
    created    TEXT NOT NULL,
    updated    TEXT NOT NULL,
    UNIQUE(kind, text)
);
CREATE INDEX IF NOT EXISTS idx_self_kind ON self_knowledge(kind);
CREATE INDEX IF NOT EXISTS idx_self_plasticity ON self_knowledge(plasticity);
"""


_STOP_TOK = set("的了是我你他她它在和与就都也还又很太把被让给对说要做个这那有没不吗呢吧啊哦嗯")


def _bigrams(text):
    """中文二字组(去停用字)。与 recall._tokens 保持完全一致的规则 ——
    索引和查询必须用同一套切分, 否则命中率会崩。"""
    s = "".join(ch for ch in (text or "") if ch.isalnum() or "一" <= ch <= "鿿")
    s = "".join(ch for ch in s if ch not in _STOP_TOK)
    if len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _claim_tokens(claim):
    """语义断言的粗粒度词组重叠(与 recall._tokens 同思路)。"""
    s = "".join(ch for ch in claim if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set()


def _claim_similar(a, b, threshold=0.55):
    ta, tb = _claim_tokens(a), _claim_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / float(min(len(ta), len(tb))) >= threshold


def _claim_conflict(a, b):
    """矛盾检测基线: 同主体且断言被否定词翻转("喜欢"vs"不喜欢", "用"vs"不用")。"""
    if not _claim_similar(a, b, 0.4):
        return False
    flips = [("喜欢", "不喜欢"), ("用", "不用"), ("是", "不是"), ("会", "不会"), ("要", "不要")]
    for pos, neg in flips:
        if ((pos in a and neg in b) or (neg in a and pos in b)):
            return True
    return False


def connect(path):
    """打开(必要时创建)识海数据库。"""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


class Store:
    """对连接的一层薄封装, 避免每个模块各自拼 SQL 连接到不同 conn。"""

    def __init__(self, path=":memory:"):
        self.path = path
        self.conn = connect(path)

    # -- 原始日志 -------------------------------------------------------
    def log_raw(self, content, ts=None, session=None, modality="text", meta=None):
        ts = ts or utcnow()
        cur = self.conn.execute(
            "INSERT INTO raw_log(ts, session, modality, content, meta) VALUES (?,?,?,?,?)",
            (ts, session, modality, content, json.dumps(meta, ensure_ascii=False) if meta else None),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_raw(self, raw_id):
        return self.conn.execute("SELECT * FROM raw_log WHERE id=?", (raw_id,)).fetchone()

    # -- 事件 -----------------------------------------------------------
    def add_event(self, raw_id, summary, appraisal, base_strength, ts=None, division="self"):
        ts = ts or utcnow()
        now = utcnow()
        cur = self.conn.execute(
            """INSERT INTO events(raw_id, ts, summary, valence, arousal, importance,
                                  emotion, pain, disappointment, impact, avoidance,
                                  self_relevance, division, base_strength, strength, created)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                raw_id, ts, summary,
                appraisal.valence, appraisal.arousal, appraisal.importance,
                appraisal.emotion, appraisal.pain, appraisal.disappointment,
                appraisal.impact, appraisal.avoidance, appraisal.self_relevance,
                division, base_strength, base_strength, now,
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_event(self, event_id):
        return self.conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    def all_events(self, include_dormant=False):
        q = "SELECT * FROM events"
        if not include_dormant:
            q += " WHERE dormant=0"
        q += " ORDER BY id"
        return self.conn.execute(q).fetchall()

    # -- 节点与边 -------------------------------------------------------
    def upsert_node(self, kind, label, key=None, attrs=None):
        key = key or label.strip().lower()
        row = self.conn.execute(
            "SELECT * FROM nodes WHERE kind=? AND key=?", (kind, key)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO nodes(kind, key, label, attrs, created) VALUES (?,?,?,?,?)",
            (kind, key, label, json.dumps(attrs, ensure_ascii=False) if attrs else None, utcnow()),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_edge(self, src, dst, rel, weight=1.0, note=None):
        cur = self.conn.execute(
            "INSERT INTO edges(src, dst, rel, weight, note, created) VALUES (?,?,?,?,?,?)",
            (src, dst, rel, weight, note, utcnow()),
        )
        self.conn.commit()
        return cur.lastrowid

    def edges_from(self, ref, rel=None):
        if rel:
            return self.conn.execute(
                "SELECT * FROM edges WHERE src=? AND rel=?", (ref, rel)
            ).fetchall()
        return self.conn.execute("SELECT * FROM edges WHERE src=?", (ref,)).fetchall()

    def edges_to(self, ref, rel=None):
        if rel:
            return self.conn.execute(
                "SELECT * FROM edges WHERE dst=? AND rel=?", (ref, rel)
            ).fetchall()
        return self.conn.execute("SELECT * FROM edges WHERE dst=?", (ref,)).fetchall()

    # -- 关系 -----------------------------------------------------------
    def relation_row(self, node_id):
        row = self.conn.execute("SELECT * FROM relation WHERE node_id=?", (node_id,)).fetchone()
        if row:
            return row
        self.conn.execute("INSERT INTO relation(node_id, updated) VALUES (?,?)", (node_id, utcnow()))
        self.conn.commit()
        return self.conn.execute("SELECT * FROM relation WHERE node_id=?", (node_id,)).fetchone()

    def update_relation(self, node_id, **deltas):
        self.relation_row(node_id)
        sets, vals = [], []
        for k, v in deltas.items():
            sets.append("%s = MIN(1.0, MAX(0.0, COALESCE(%s,0) + ?))" % (k, k))
            vals.append(v)
        sets.append("updated = ?")
        vals.append(utcnow())
        vals.append(node_id)
        self.conn.execute("UPDATE relation SET %s WHERE node_id=?" % ", ".join(sets), vals)
        self.conn.commit()

    # -- 语义 -----------------------------------------------------------
    def resolve_semantic(self, claim, subject=None, confidence=0.6, sources=None,
                         min_conf_to_keep=0.75):
        """mem0 式冲突决策: 新事实进语义层前, 先与既有事实对质。
        决策四值(借鉴 mem0 的 ADD/UPDATE/DELETE/NONE):
            ADD      —— 没有近似旧事实, 直接入库
            UPDATE   —— 新事实与旧事实矛盾且新事实置信更高, 覆盖(旧值留 history)
            NOOP     —— 近似重复, 只涨 hits
            SUPERSEDE—— 旧事实被显式否定("不再/换了/取消"), 降权但不删
        返回 (semantic_id, action)。
        """
        now = utcnow()
        # 1) 完全一致 → NOOP
        row = self.conn.execute("SELECT * FROM semantic WHERE claim=?", (claim,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE semantic SET hits=hits+1, confidence=?, sources=?, updated=? WHERE id=?",
                (min(1.0, confidence + 0.05), json.dumps(sources or []), now, row["id"]),
            )
            self.conn.commit()
            return row["id"], "NOOP"

        # 2) 显式否定 → 降权旧事实
        negations = ("不再", "不是了", "换了", "取消", "改用", "以后不用")
        if any(n in claim for n in negations):
            for old in self.conn.execute("SELECT * FROM semantic").fetchall():
                if _claim_similar(old["claim"], claim):
                    self.conn.execute(
                        "UPDATE semantic SET confidence=MAX(0.1, confidence-0.4), updated=? WHERE id=?",
                        (now, old["id"]),
                    )
            cur = self.conn.execute(
                "INSERT INTO semantic(claim, subject, confidence, sources, created, updated) VALUES (?,?,?,?,?,?)",
                (claim, subject, confidence, json.dumps(sources or []), now, now),
            )
            self.conn.commit()
            return cur.lastrowid, "SUPERSEDE"

        # 3) 近似重复 → NOOP + hits 合并
        for old in self.conn.execute("SELECT * FROM semantic").fetchall():
            if _claim_similar(old["claim"], claim):
                self.conn.execute(
                    "UPDATE semantic SET hits=hits+1, confidence=?, sources=?, updated=? WHERE id=?",
                    (min(1.0, confidence + 0.05), json.dumps(sources or []), now, old["id"]),
                )
                self.conn.commit()
                return old["id"], "NOOP"

        # 4) 矛盾冲突(同主体+反向断言) → 置信高者胜
        for old in self.conn.execute("SELECT * FROM semantic WHERE subject IS ?", (subject,)).fetchall():
            if _claim_conflict(old["claim"], claim):
                if confidence >= old["confidence"]:
                    self.conn.execute(
                        "UPDATE semantic SET claim=?, confidence=?, sources=?, updated=? WHERE id=?",
                        (claim, confidence, json.dumps(sources or []), now, old["id"]),
                    )
                    self.conn.commit()
                    return old["id"], "UPDATE"
                # 旧事实置信更高: 新事实以低置信并存, 等更多证据
                confidence = max(0.3, confidence * 0.5)

        cur = self.conn.execute(
            "INSERT INTO semantic(claim, subject, confidence, sources, created, updated) VALUES (?,?,?,?,?,?)",
            (claim, subject, confidence, json.dumps(sources or []), now, now),
        )
        self.conn.commit()
        return cur.lastrowid, "ADD"

    def add_semantic(self, claim, subject=None, confidence=0.6, sources=None):
        """兼容旧接口: 只落盘不做冲突决策。新代码请用 resolve_semantic。"""
        now = utcnow()
        row = self.conn.execute("SELECT * FROM semantic WHERE claim=?", (claim,)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE semantic SET hits=hits+1, confidence=?, sources=?, updated=? WHERE id=?",
                (min(1.0, confidence + 0.05), json.dumps(sources or []), now, row["id"]),
            )
            self.conn.commit()
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO semantic(claim, subject, confidence, sources, created, updated) VALUES (?,?,?,?,?,?)",
            (claim, subject, confidence, json.dumps(sources or []), now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    # -- 任务 -----------------------------------------------------------
    def add_task(self, title, due=None, event_id=None, node_id=None):
        now = utcnow()
        cur = self.conn.execute(
            "INSERT INTO task(title, due, event_id, node_id, created, updated) VALUES (?,?,?,?,?,?)",
            (title, due, event_id, node_id, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def open_tasks(self):
        return self.conn.execute(
            "SELECT * FROM task WHERE status='open' ORDER BY COALESCE(due,'9999')"
        ).fetchall()

    # -- 工作状态 -------------------------------------------------------
    def set_working(self, session, key, value):
        self.conn.execute(
            """INSERT INTO working(session, key, value, updated) VALUES (?,?,?,?)
               ON CONFLICT(session,key) DO UPDATE SET value=excluded.value, updated=excluded.updated""",
            (session, key, json.dumps(value, ensure_ascii=False), utcnow()),
        )
        self.conn.commit()

    def get_working(self, session):
        rows = self.conn.execute("SELECT key, value FROM working WHERE session=?", (session,)).fetchall()
        return {r["key"]: json.loads(r["value"]) if r["value"] else None for r in rows}

    # -- 召回日志 -------------------------------------------------------
    def log_recall(self, query, cues, hits):
        self.conn.execute(
            "INSERT INTO recall_log(ts, query, cues, hits) VALUES (?,?,?,?)",
            (utcnow(), query, json.dumps(cues, ensure_ascii=False), json.dumps(hits, ensure_ascii=False)),
        )
        self.conn.commit()

    # -- 自我知识库(可塑性记忆) ------------------------------------------
    def learn_self(self, kind, text, trigger=None, source="user", init=0.55):
        """学会一条关于自己的事(LTP 的写入端)。
        同 (kind, text) 重复学会 → 不是重复存储, 而是可塑性上涨(被验证了)。"""
        now = utcnow()
        row = self.conn.execute(
            "SELECT * FROM self_knowledge WHERE kind=? AND text=?", (kind, text)).fetchone()
        if row:
            p = min(1.0, float(row["plasticity"]) + 0.12)
            self.conn.execute(
                "UPDATE self_knowledge SET plasticity=?, wins=wins+1, updated=?, "
                "trigger=COALESCE(?, trigger) WHERE id=?",
                (p, now, trigger, row["id"]))
            self.conn.commit()
            return row["id"], p
        cur = self.conn.execute(
            """INSERT INTO self_knowledge(kind, text, trigger, plasticity, source, created, updated)
               VALUES (?,?,?,?,?,?,?)""",
            (kind, text, trigger, init, source, now, now))
        self.conn.commit()
        return cur.lastrowid, init

    def use_self(self, kid, success=True):
        """这条知识被用了一次: 奏效 → 加强; 失败 → 削弱(LTD)。"""
        row = self.conn.execute("SELECT * FROM self_knowledge WHERE id=?", (kid,)).fetchone()
        if row is None:
            return None
        delta = 0.06 if success else -0.18   # 负面证据权重更大: 错一次比成一次记得牢
        p = max(0.05, min(1.0, float(row["plasticity"]) + delta))
        self.conn.execute(
            "UPDATE self_knowledge SET plasticity=?, uses=uses+1, "
            "wins=wins+?, losses=losses+?, last_used=?, updated=? WHERE id=?",
            (p, 1 if success else 0, 0 if success else 1, utcnow(), utcnow(), kid))
        self.conn.commit()
        return p

    def decay_self(self, rate=0.03, floor=0.05):
        """长期不用的自我知识会变薄(结构可塑性: 不用则剪)。
        注意: identity 类衰减最慢 —— 身份不该因为三个月没提就消失。"""
        now = utcnow()
        rows = self.conn.execute("SELECT * FROM self_knowledge").fetchall()
        changed = 0
        for r in rows:
            k = {"identity": 0.2, "care": 0.6, "style": 0.8, "voice": 0.8}.get(r["kind"], 1.0)
            p = max(floor, float(r["plasticity"]) - rate * k)
            if abs(p - float(r["plasticity"])) > 1e-6:
                self.conn.execute(
                    "UPDATE self_knowledge SET plasticity=?, updated=? WHERE id=?",
                    (p, now, r["id"]))
                changed += 1
        self.conn.commit()
        return changed

    def self_knowledge(self, kind=None, min_plasticity=0.0, limit=100):
        q = "SELECT * FROM self_knowledge WHERE plasticity>=?"
        args = [min_plasticity]
        if kind:
            q += " AND kind=?"
            args.append(kind)
        q += " ORDER BY plasticity DESC, uses DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(q, args).fetchall()

    # -- 检索索引 -------------------------------------------------------
    def index_tokens(self, event_id, summary):
        """给一条事件建倒排(幂等: 先删后插)。"""
        toks = _bigrams(summary)
        if not toks:
            return 0
        self.conn.execute("DELETE FROM event_tokens WHERE event_id=?", (event_id,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO event_tokens(token, event_id) VALUES (?,?)",
            [(t, event_id) for t in toks])
        return len(toks)

    def search_tokens(self, tokens, min_hits=1, limit=200):
        """倒排查询: 只碰命中 token 的事件, 复杂度 O(命中数) 而非 O(全表)。
        返回 [(event_id, 命中token数)] 按命中降序。"""
        toks = list(set(tokens))
        if not toks:
            return []
        ph = ",".join("?" * len(toks))
        rows = self.conn.execute(
            "SELECT event_id, COUNT(*) c FROM event_tokens WHERE token IN (%s) "
            "GROUP BY event_id HAVING c>=? ORDER BY c DESC LIMIT ?" % ph,
            toks + [min_hits, limit]).fetchall()
        return [(r["event_id"], r["c"]) for r in rows]

    def reindex_all(self):
        """全量重建倒排(迁移/修复用)。"""
        self.conn.execute("DELETE FROM event_tokens")
        n = 0
        for r in self.conn.execute("SELECT id, summary FROM events"):
            n += self.index_tokens(r["id"], r["summary"] or "")
        self.conn.commit()
        return n

    # -- 日记 -----------------------------------------------------------
    def add_diary(self, day, text, felt=None, details=None, mood=None,
                  warmth=0.0, event_ids=None):
        now = utcnow()
        row = self.conn.execute("SELECT * FROM diary WHERE day=?", (day,)).fetchone()
        if row:
            if row["edited"]:
                # 人改过的日记: 只更新机器字段, 不覆盖正文
                self.conn.execute(
                    "UPDATE diary SET warmth=?, event_ids=?, updated=? WHERE id=?",
                    (warmth, json.dumps(event_ids or []), now, row["id"]))
                self.conn.commit()
                return row["id"], "kept-human-edit"
            self.conn.execute(
                """UPDATE diary SET text=?, felt=?, details=?, mood=?, warmth=?,
                   event_ids=?, updated=? WHERE id=?""",
                (text, felt, details, mood, warmth, json.dumps(event_ids or []),
                 now, row["id"]))
            self.conn.commit()
            return row["id"], "updated"
        cur = self.conn.execute(
            """INSERT INTO diary(day, text, felt, details, mood, warmth, event_ids,
                                 created, updated) VALUES (?,?,?,?,?,?,?,?,?)""",
            (day, text, felt, details, mood, warmth, json.dumps(event_ids or []),
             now, now))
        self.conn.commit()
        return cur.lastrowid, "created"

    def edit_diary(self, day, text=None, felt=None):
        """人手工修订日记(方便人来管理)。改过的日记不再被机器覆盖。"""
        row = self.conn.execute("SELECT id FROM diary WHERE day=?", (day,)).fetchone()
        if row is None:
            return False
        sets, vals = ["edited=1", "updated=?"], [utcnow()]
        if text is not None:
            sets.append("text=?"); vals.append(text)
        if felt is not None:
            sets.append("felt=?"); vals.append(felt)
        vals.append(row["id"])
        self.conn.execute("UPDATE diary SET %s WHERE id=?" % ", ".join(sets), vals)
        self.conn.commit()
        return True

    def diaries(self, limit=30, recent=True):
        q = "SELECT * FROM diary ORDER BY day %s LIMIT ?" % ("DESC" if recent else "ASC")
        return self.conn.execute(q, (limit,)).fetchall()

    def diary_of(self, day):
        return self.conn.execute("SELECT * FROM diary WHERE day=?", (day,)).fetchone()

    # -- 好感条 ---------------------------------------------------------
    def add_warmth(self, day, delta, reason=""):
        self.conn.execute(
            "INSERT INTO warmth_ledger(day, delta, reason, created) VALUES (?,?,?,?)",
            (day, delta, reason, utcnow()))
        self.conn.commit()

    def warmth_total(self):
        row = self.conn.execute("SELECT COALESCE(SUM(delta),0) FROM warmth_ledger").fetchone()
        return float(row[0])

    # -- 人格快照 -------------------------------------------------------
    def add_persona(self, traits, card, core_ids):
        cur = self.conn.execute(
            "INSERT INTO persona_snapshot(ts, traits, card, core_ids, created) VALUES (?,?,?,?,?)",
            (utcnow(), json.dumps(traits, ensure_ascii=False), card,
             json.dumps(core_ids), utcnow()),
        )
        self.conn.commit()
        return cur.lastrowid

    def last_persona(self):
        return self.conn.execute(
            "SELECT * FROM persona_snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def close(self):
        self.conn.close()
