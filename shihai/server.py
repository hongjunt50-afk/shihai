# -*- coding: utf-8 -*-
r"""识海服务 —— agent 本体的存续层。

架构定稿(2026-10-18):
    记忆文档 = 投影(物化视图), 识海 = 库本体, 本服务 = 固结循环的宿主。

两种运行形态:
    1. 长驻服务:   python -m shihai.server --serve
       stdin/stdout 每行一个 JSON 请求, 返回一行 JSON 响应。
       适合被 agent 框架当作子进程长期持有。
    2. 单发调用:   python -m shihai.server call <method> [json-args]
       适合钩子脚本一次性调用(Stop hook / cron), 调完即退。

API(全部幂等, 无隐式状态):
    tell    {text, self?, importance?, session?}   -> 一段经历入库
    ask     {query, person?, limit?}               -> 心光竞争召回
    tick    {days?, free_cycles?}                  -> 固结 + 可选自由行为环
    context {query?, limit?}                       -> 投影: 注入用记忆文档块
    persona {}                                     -> 人格卡 + 类型档案
    freemode {action: on/off/status/run, cycles?}  -> 自由模式控制
    stats    {}                                    -> 库况

服务端不联网、不发布、不删库; 所有状态在 SHIHAI_HOME(默认 F:\MyDeck\shihai)。
"""

import json
import os
import sys

from .store import Store
from .ingest import Ingestor, Observation
from .recall import RecallEngine, Cue
from .lifecycle import Lifecycle
from .persona import PersonaEngine
from .typologies import TypologyEngine
from .freemode import FreeMode
from .kb import SelfKB
from .diary import DiaryEngine
from .wiki import Wiki
from . import home as H


class ShihaiService:
    """一个进程一个 agent 一份识海。所有 handler 返回 (ok, payload)。"""

    def __init__(self, *, db_path=None, typo_path=None, agent_name="agent"):
        H.ensure_home()
        self.db_path = db_path or H.DB_PATH
        self.typo_path = typo_path or H.TYPOLOGY_PATH
        self.store = Store(self.db_path)
        self.lifecycle = Lifecycle(self.store, reflect_trigger=6.0)
        self.ingestor = Ingestor(self.store, lifecycle=self.lifecycle)
        self.recall = RecallEngine(self.store)
        name = agent_name
        ident = H.identity_card()
        if ident:
            name = ident.get("name", name)
        self.persona = PersonaEngine(self.store, name=name, typology_path=self.typo_path)
        self.typology = self.persona.typology_engine
        self.kb = SelfKB(self.store)
        self.diary = DiaryEngine(self.store)
        self.wiki = Wiki(self.store, root=os.path.join(H.SHIHAI_HOME, 'wiki'))
        self.freemode = FreeMode(self.store, self.ingestor, self.recall,
                                 self.lifecycle, typology_engine=self.typology)

    # -- handlers --------------------------------------------------------
    def h_tell(self, a):
        obs = Observation(
            text=a.get("text", ""),
            modality="self" if a.get("self") else a.get("modality", "text"),
            session=a.get("session", "hook"),
        )
        ev = self.ingestor.ingest(obs, importance_hint=a.get("importance"))
        return {"event_id": ev.event_id,
                "nodes": [(n["kind"], n["label"]) for n in ev.nodes],
                "task": ev.task,
                "semantic": [s[0] if isinstance(s, tuple) else s for s in ev.semantic]}

    def h_ask(self, a):
        cue = Cue(text=a.get("query", ""), person=a.get("person", ""),
                  theme=a.get("theme", ""), state=a.get("state", ""),
                  task=a.get("task", ""))
        hits = self.recall.recall(cue, limit=int(a.get("limit", 5)))
        return {"hits": [{"id": h.event_id, "score": h.score, "core": h.core,
                          "emotion": h.emotion, "summary": h.summary,
                          "via": h.via} for h in hits]}

    def h_tick(self, a):
        days = a.get("days")
        rep = self.lifecycle.tick(days=days)
        out = {"decayed": rep.decayed, "dormant": rep.dormant,
               "promoted": rep.promoted, "reflected": rep.reflected}
        # 自我知识随 tick 一并衰减/回收 —— 不要求人记得单独跑 selfmaint
        out["selfkb"] = self.kb.maintain(decay=True)
        # tick 顺带刷人格快照 —— 固结与投影保持同步
        self.persona.refresh()
        # 自由模式: 常驻服务默认每天跑几个行为环(cron 触发 tick 时自然发生)
        cycles = int(a.get("free_cycles", 0))
        fm_out = []
        if cycles > 0 and self.freemode.state.active:
            for _ in range(cycles):
                fm_out.append(self.freemode.run_cycle(log=None))
        out["freemode"] = fm_out
        return out

    def h_context(self, a):
        """投影: 给记忆文档用的注入块。这是识海对 agent 的唯一日常输出。"""
        snap = self.store.last_persona()
        if snap is None:
            refreshed = self.persona.refresh()
            card, voice = refreshed.card, refreshed.voice
        else:
            card = snap["card"]
            # voice 与快照同源: 用快照当天的 typology 状态文件(与快照同期生成)
            voice = self.persona.voice_engine.build(
                self.typology.infer(persist=True),
                json.loads(snap["traits"])).render()
        hits = self.recall.recall(
            Cue(text=a.get("query", "")), limit=int(a.get("limit", 4)))
        tasks = self.store.open_tasks()
        profile = self.typology.infer(persist=True)
        boot = self.kb.bootstrap()
        return {
            "persona": card,
            "voice": voice,
            "selfkb": boot.block,
            "diary": self.diary.bootstrap_block(n=2),
            "typology": {"dominant": profile.jung_dominant,
                         "ennea": "%dw%d" % (profile.ennea_type, profile.ennea_wing),
                         "health": profile.health, "drift": profile.drift_direction},
            "recalled": [{"core": h.core, "summary": h.summary} for h in hits],
            "tasks": [{"title": t["title"], "due": t["due"]} for t in tasks],
            "freemode": self.freemode.state.active,
        }

    def h_persona(self, a):
        card = self.persona.refresh()
        profile = self.typology.infer(persist=True)
        return {"card": card.card, "traits": card.traits,
                "core_ids": card.core_ids, "voice": card.voice,
                "typology": profile.to_dict()}

    def h_freemode(self, a):
        act = a.get("action", "status")
        if act == "on":
            self.freemode.handle_command("开启自由模式")
            return {"active": True}
        if act == "off":
            self.freemode.handle_command("关闭自由模式")
            return {"active": False}
        if act == "run":
            n = int(a.get("cycles", 1))
            out = []
            for _ in range(n):
                out.append(self.freemode.run_cycle(log=None))
            return {"ran": len(out), "cycles": out,
                    "energy": self.freemode.state.energy}
        return {"active": self.freemode.state.active,
                "cycle": self.freemode.state.cycle,
                "energy": round(self.freemode.state.energy, 2)}

    def h_stats(self, a):
        c = self.store.conn
        return {
            "events": c.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "core": c.execute("SELECT COUNT(*) FROM events WHERE core=1").fetchone()[0],
            "dormant": c.execute("SELECT COUNT(*) FROM events WHERE dormant=1").fetchone()[0],
            "nodes": c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "semantic": c.execute("SELECT COUNT(*) FROM semantic").fetchone()[0],
            "recalls": c.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0],
            "db": self.db_path,
        }

    # -- dispatch --------------------------------------------------------
    def h_selflearn(self, a):
        """学一条关于自己的事。工作类内容会被拒收并提示走共享知识库。"""
        kid, status, note = self.kb.learn(
            a.get("text", ""), kind=a.get("kind"), trigger=a.get("trigger"),
            source=a.get("source", "user"))
        return {"id": kid, "status": status, "note": note}

    def h_selfkb(self, a):
        rows = self.store.self_knowledge(kind=a.get("kind"),
                                         min_plasticity=float(a.get("min", 0.0)))
        return {"items": [{"id": r["id"], "kind": r["kind"], "text": r["text"],
                           "plasticity": round(r["plasticity"], 3),
                           "uses": r["uses"], "wins": r["wins"], "losses": r["losses"]}
                          for r in rows]}

    def h_selfconfirm(self, a):
        p = self.kb.confirm(int(a["id"]), success=bool(a.get("success", True)))
        return {"id": a["id"], "plasticity": p}

    def h_bootstrap(self, a):
        """冷启动自举: 新开对话不需要 query, 也不需要重教。
        自我知识(我是谁) + 最近日记(我经历过什么) 两层。"""
        b = self.kb.bootstrap(min_plasticity=float(a.get("min", 0.12)))
        block = b.block
        if block.startswith("(还没有"):
            block = ""   # 没有自我知识时不要占位, 让日记层直接出场
        diaries = self.diary.bootstrap_block(n=int(a.get("diary_days", 2)))
        if diaries:
            block = block + "\n\n" + diaries
        return {"block": block, "counts": b.counts,
                "weak": [{"kind": k, "text": t, "plasticity": p} for k, t, p in b.weak]}

    def h_selfmaint(self, a):
        return self.kb.maintain(decay=bool(a.get("decay", True)))

    def h_diary(self, a):
        action = a.get("action", "recent")
        if action == "close":
            r = self.diary.close_day(a.get("day"))
            return r or {"status": "no-events"}
        if action == "compose":
            d = self.diary.compose(a.get("day"), style=a.get("style", "voice"))
            return {"draft": None} if d is None else {
                "day": d.day, "text": d.text, "felt": d.felt,
                "details": d.details, "mood": d.mood, "warmth": d.warmth}
        if action == "recall":
            rows = self.diary.recall(a.get("query", ""), int(a.get("limit", 3)))
            return {"days": [{"day": r["day"], "mood": r["mood"], "text": r["text"],
                              "felt": r["felt"], "warmth": r["warmth"]} for r in rows]}
        if action == "edit":
            return {"edited": self.store.edit_diary(a.get("day"), text=a.get("text"),
                                                    felt=a.get("felt"))}
        if action == "export":
            path = a.get("path")
            text = self.diary.export_markdown(path)
            return {"path": path, "chars": len(text)}
        if action == "import":
            return {"imported": self.diary.import_markdown(a["path"])}
        if action == "warmth":
            return {"total": self.store.warmth_total(),
                    "note": "好感由人手工录入(agent 只读)"}
        rows = self.diary.recent(int(a.get("limit", 5)))
        return {"days": [{"day": r["day"], "mood": r["mood"], "text": r["text"],
                          "felt": r["felt"]} for r in rows]}

    def h_warmth(self, a):
        """好感条: 只允许人写入 —— agent 不能给自己加分。"""
        if a.get("action") == "add":
            self.store.add_warmth(a.get("day"), float(a.get("delta", 0)),
                                  a.get("reason", ""))
        return {"total": self.store.warmth_total()}

    def h_wiki(self, a):
        action = a.get("action", "sync")
        if action == "sync":
            return self.wiki.sync()
        if action == "lint":
            return {"report": self.wiki.lint_report()}
        if action == "index":
            path = os.path.join(self.wiki.root, "wiki", "index.md")
            return {"path": path,
                    "content": open(path, encoding="utf-8").read() if os.path.exists(path) else ""}
        return {"root": self.wiki.root}

    HANDLERS = {
        "tell": h_tell, "ask": h_ask, "tick": h_tick, "context": h_context,
        "persona": h_persona, "freemode": h_freemode, "stats": h_stats,
        "selflearn": h_selflearn, "selfkb": h_selfkb, "selfconfirm": h_selfconfirm,
        "bootstrap": h_bootstrap, "selfmaint": h_selfmaint,
        "diary": h_diary, "warmth": h_warmth, "wiki": h_wiki,
    }

    def dispatch(self, method, args=None):
        h = self.HANDLERS.get(method)
        if h is None:
            return False, {"error": "unknown method: %s" % method}
        try:
            return True, h(self, args or {})
        except Exception as e:
            return False, {"error": "%s: %s" % (type(e).__name__, e)}


def serve(agent_name="agent"):
    """长驻: 每行一个 {"method": ..., "args": {...}}, 回一行 {"ok":..., ...}。"""
    svc = ShihaiService(agent_name=agent_name)
    _emit(None, {"ready": True, "db": H.DB_PATH})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            _emit(None, {"ok": False, "error": "bad json"})
            continue
        if req.get("method") == "shutdown":
            _emit(req.get("id"), {"ok": True, "result": {"bye": True}})
            break
        ok, payload = svc.dispatch(req.get("method", ""), req.get("args") or {})
        _emit(req.get("id"), {"ok": ok, "result": payload})


def _emit(req_id, obj):
    if req_id is not None and "id" not in obj:
        obj["id"] = req_id
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cli(argv):
    """python -m shihai.server call <method> '<json-args>'"""
    if argv and argv[0] == "call":
        method = argv[1]
        args = json.loads(argv[2]) if len(argv) > 2 else {}
        svc = ShihaiService()
        ok, payload = svc.dispatch(method, args)
        print(json.dumps({"ok": ok, "result": payload}, ensure_ascii=False, indent=1))
        return 0
    agent_name = "agent"
    if argv and argv[0] == "--serve":
        if len(argv) > 1:
            agent_name = argv[1]
        serve(agent_name)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]))
